// Teto for Chromebook - the extension half of Teto. It talks only to the Teto
// program in this Chromebook's Linux side (http://localhost:<port>), using the
// secret token the installer put in token.json.
const sleep = ms => new Promise(r => setTimeout(r, ms));
let CONF = null;          // {token, port}
let BASE = null;          // the address that answered
let running = false, eventsRunning = false;

async function conf() {
  if (!CONF) CONF = await (await fetch(chrome.runtime.getURL('token.json'))).json();
  return CONF;
}

function hdr(extra = {}) {
  return {"X-Teto-Token": CONF.token, "X-Teto-Ext": chrome.runtime.getManifest().version, ...extra};
}

async function base() {
  await conf();
  if (BASE) return BASE;
  for (const host of ['localhost', '127.0.0.1', 'penguin.linux.test']) {
    const b = `http://${host}:${CONF.port}`;
    try {
      const r = await fetch(b + '/ping', {headers: hdr(), cache: 'no-store'});
      if (r.ok) { BASE = b; return b; }
    } catch (e) {}
  }
  throw new Error('Teto is not running');
}

async function loop() {
  if (running) return;
  running = true;
  let backoff = 1000;
  try {
    for (;;) {
      chrome.runtime.getPlatformInfo(() => {});          // keeps the service worker awake
      let r;
      try {
        r = await fetch((await base()) + '/poll', {headers: hdr(), cache: 'no-store'});
      } catch (e) {                                       // Teto isn't running right now
        BASE = null;
        await setOnline(false);
        await sleep(backoff);
        backoff = Math.min(backoff * 2, 15000);
        continue;
      }
      backoff = 1000;
      await setOnline(true);
      const want = r.headers.get('X-Teto-Ext-Version');  // Teto updated the extension's files
      if (want && want !== chrome.runtime.getManifest().version) { chrome.runtime.reload(); return; }
      if (r.status === 204) continue;
      if (r.status !== 200) { await sleep(3000); continue; }
      handle(await r.json());                             // don't block the next command
    }
  } finally {
    running = false;
  }
}

async function handle(cmd) {
  let res;
  try {
    const fn = COMMANDS[cmd.cmd];
    if (!fn) throw new Error('unknown command ' + cmd.cmd);
    res = {id: cmd.id, ok: true, result: await fn(cmd.args || {})};
  } catch (e) {
    res = {id: cmd.id, ok: false, error: String((e && e.message) || e)};
  }
  try {
    await fetch((await base()) + '/result', {method: 'POST', headers: hdr({'Content-Type': 'application/json'}),
                                              body: JSON.stringify(res)});
  } catch (e) { /* Teto went away */ }
}

// ------------------------------------------------------------- events -> the pet on your pages
let lastSeq = 0;
async function setOnline(on) {
  const {online} = await chrome.storage.session.get('online');
  if (online !== on) {
    await chrome.storage.session.set({online: on});
    broadcast({type: 'teto', event: {type: 'online', online: on}});
  }
}

async function broadcast(msg) {
  const tabs = await chrome.tabs.query({active: true});
  for (const t of tabs) chrome.tabs.sendMessage(t.id, msg).catch(() => {});
}

async function eventsLoop() {
  if (eventsRunning) return;
  eventsRunning = true;
  try {
    for (;;) {
      let data;
      try {
        const r = await fetch(`${await base()}/events?after=${lastSeq}&wait=20`, {headers: hdr(), cache: 'no-store'});
        data = await r.json();
      } catch (e) { await sleep(3000); continue; }
      for (const ev of data.events || []) {
        lastSeq = Math.max(lastSeq, ev.seq);
        if (['status', 'log', 'ask', 'confirm', 'done', 'settings'].includes(ev.type)) {
          broadcast({type: 'teto', event: ev});
        }
        if (ev.type === 'settings') chrome.storage.local.set({pet: ev.settings.pet});
      }
    }
  } finally {
    eventsRunning = false;
  }
}

async function petVisible(tabId, on) {
  try { await chrome.tabs.sendMessage(tabId, {type: 'pet_visible', on}); } catch (e) {}
  if (!on) await sleep(40);            // let the page repaint without her
}

async function capture(tab) {
  let data = null;
  if (tab.active) {
    try {
      const url = await chrome.tabs.captureVisibleTab(tab.windowId, {format: 'jpeg', quality: 70});
      data = url.split(',')[1];
    } catch (e) { /* window hidden: fall through */ }
  }
  if (!data) {
    const shot = await Promise.race([cdp(tab.id, 'Page.captureScreenshot', {format: 'jpeg', quality: 70}),
                                     sleep(5000).then(() => null)]);
    if (!shot) throw new Error('that tab could not be captured');
    data = shot.data;
  }
  const size = await inPage(tab.id, () => ({w: innerWidth, h: innerHeight})).catch(() => null);
  return {data, cssWidth: size ? size.w : tab.width, cssHeight: size ? size.h : tab.height};
}

// ------------------------------------------------------------- page scripts
function pageSnapshot() {
  const sel = 'a[href],button,input:not([type=hidden]),select,textarea,summary,label,[role=button],[role=link],' +
    '[role=checkbox],[role=radio],[role=tab],[role=menuitem],[role=option],[role=switch],[role=combobox],' +
    '[role=textbox],[role=searchbox],[contenteditable=""],[contenteditable=true],[onclick],[tabindex]';
  document.querySelectorAll('[data-teto-ref]').forEach(e => e.removeAttribute('data-teto-ref'));
  const items = []; let n = 0;
  const clickable = el => { try { return getComputedStyle(el).cursor === 'pointer'; } catch (e) { return false; } };
  const cands = new Set(document.querySelectorAll(sel));
  // quiz answers etc. are often plain <div>s with a click handler: pointer cursor gives them away
  for (const el of [...document.querySelectorAll('div,li,span,p,td')].slice(0, 4000)) {
    if (clickable(el) && !(el.parentElement && clickable(el.parentElement))) cands.add(el);
  }
  const ordered = [...cands].sort((a, b) =>
    a === b ? 0 : (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1));
  for (const el of ordered) {
    const r = el.getBoundingClientRect(), st = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none') continue;
    if (r.bottom < -innerHeight || r.top > innerHeight * 3) continue;
    if (el.tagName === 'LABEL' && el.control && cands.has(el.control)) continue;
    n++; el.setAttribute('data-teto-ref', String(n));
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || (tag === 'input' ? 'input:' + (el.type || 'text') :
                 (['div', 'li', 'span', 'p', 'td'].includes(tag) ? 'clickable' : tag));
    let name = (el.getAttribute('aria-label') || el.innerText || el.placeholder || el.title || el.alt ||
                el.getAttribute('name') || '').trim().replace(/\s+/g, ' ').slice(0, 90);
    if (!name && tag === 'input' && (el.type === 'submit' || el.type === 'button')) name = el.value || '';
    if (!name && tag === 'input' && el.labels && el.labels[0]) name = el.labels[0].innerText.trim().slice(0, 90);
    let val = '';
    if ((tag === 'input' || tag === 'textarea') && !['submit', 'button', 'checkbox', 'radio'].includes(el.type))
      val = el.type === 'password' ? (el.value ? '****' : '') : (el.value || '').slice(0, 60);
    if (tag === 'select') val = (el.options[el.selectedIndex] || {}).text || '';
    const checked = (el.type === 'checkbox' || el.type === 'radio') ? (el.checked ? ' [x]' : ' [ ]') :
                    (el.getAttribute('aria-checked') === 'true' || el.getAttribute('aria-selected') === 'true' ? ' [x]' : '');
    const where = (r.top >= 0 && r.bottom <= innerHeight) ? '' : ' (scroll to see)';
    items.push(`[${n}] ${role} "${name}"` + (val ? ` value="${val}"` : '') + checked +
               (el.disabled ? ' (disabled)' : '') + where);
    if (n >= 250) break;
  }
  // the text the user would see on screen right now
  const parts = [];
  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  let total = 0;
  for (let t = walker.nextNode(); t && total < 5000; t = walker.nextNode()) {
    const s = t.nodeValue.replace(/\s+/g, ' ').trim();
    if (!s) continue;
    const p = t.parentElement;
    if (!p || ['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(p.tagName)) continue;
    range.selectNodeContents(t);
    const rr = range.getBoundingClientRect();
    if (rr.width === 0 || rr.bottom < 0 || rr.top > innerHeight) continue;
    parts.push(s); total += s.length + 1;
  }
  return {title: document.title, url: location.href, items, visible: parts.join('\n'),
          scroll: `${Math.round(scrollY)} of ${Math.max(0, document.documentElement.scrollHeight - innerHeight)}`};
}

function pageClick(ref) {
  const el = document.querySelector(`[data-teto-ref="${ref}"]`);
  if (!el) return 'missing';
  el.scrollIntoView({block: 'center', inline: 'nearest'});
  const r = el.getBoundingClientRect();
  const o = {bubbles: true, cancelable: true, composed: true, view: window, button: 0,
             clientX: r.left + r.width / 2, clientY: r.top + r.height / 2};
  for (const t of ['pointerover', 'pointerenter', 'mouseover', 'pointerdown', 'mousedown']) {
    el.dispatchEvent(t.startsWith('pointer') ? new PointerEvent(t, {...o, pointerType: 'mouse', isPrimary: true})
                                             : new MouseEvent(t, o));
  }
  if (el.focus) el.focus({preventScroll: true});
  el.dispatchEvent(new PointerEvent('pointerup', {...o, pointerType: 'mouse', isPrimary: true}));
  el.dispatchEvent(new MouseEvent('mouseup', o));
  el.click();
  return 'ok';
}

function pageType(ref, text, clear, submit) {
  const el = document.querySelector(`[data-teto-ref="${ref}"]`);
  if (!el) return 'missing';
  el.scrollIntoView({block: 'center'});
  el.focus();
  if (el.isContentEditable) {
    if (clear) document.execCommand('selectAll', false);
    document.execCommand('insertText', false, text);
  } else {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;   // React/Vue-friendly
    setter.call(el, clear ? text : (el.value || '') + text);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  }
  if (submit) {
    for (const t of ['keydown', 'keypress', 'keyup'])
      el.dispatchEvent(new KeyboardEvent(t, {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}));
    if (el.form && el.form.requestSubmit) el.form.requestSubmit();
  }
  return 'ok';
}

function pageSelect(ref, option) {
  const el = document.querySelector(`[data-teto-ref="${ref}"]`);
  if (!el || el.tagName !== 'SELECT') return 'missing';
  const o = [...el.options].find(o => o.text.trim() === option || o.value === option) ||
            [...el.options].find(o => o.text.toLowerCase().includes(option.toLowerCase()));
  if (!o) return 'nooption';
  el.value = o.value;
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  return 'ok';
}

async function inPage(tabId, func, args = []) {
  const [r] = await chrome.scripting.executeScript({target: {tabId}, func, args});
  return r ? r.result : undefined;
}

// ------------------------------------------------------------- debugger (trusted input)
const attached = new Map();      // tabId -> detach timer
async function cdp(tabId, method, params = {}) {
  if (!attached.has(tabId)) {
    await chrome.debugger.attach({tabId}, "1.3");
  } else {
    clearTimeout(attached.get(tabId));
  }
  attached.set(tabId, setTimeout(() => { chrome.debugger.detach({tabId}).catch(() => {}); attached.delete(tabId); },
                                 15000));
  return await chrome.debugger.sendCommand({tabId}, method, params);
}
chrome.debugger.onDetach.addListener(src => { if (src.tabId) attached.delete(src.tabId); });

const KEYS = {enter: ['Enter', 13, '\r'], return: ['Enter', 13, '\r'], tab: ['Tab', 9], escape: ['Escape', 27],
              esc: ['Escape', 27], backspace: ['Backspace', 8], delete: ['Delete', 46], space: [' ', 32, ' '],
              up: ['ArrowUp', 38], down: ['ArrowDown', 40], left: ['ArrowLeft', 37], right: ['ArrowRight', 39],
              home: ['Home', 36], end: ['End', 35], pageup: ['PageUp', 33], page_up: ['PageUp', 33],
              pagedown: ['PageDown', 34], page_down: ['PageDown', 34]};
const MODS = {alt: 1, ctrl: 2, control: 2, meta: 4, cmd: 4, win: 4, shift: 8};

async function pressKey(tabId, combo) {
  const parts = combo.split('+').map(s => s.trim()).filter(Boolean);
  let mods = 0;
  for (const p of parts.slice(0, -1)) mods |= MODS[p.toLowerCase()] || 0;
  const k = parts[parts.length - 1];
  let key, code, text;
  const named = KEYS[k.toLowerCase()];
  if (named) { [key, code, text] = named; }
  else if (/^f\d{1,2}$/i.test(k)) { key = k.toUpperCase(); code = 111 + parseInt(k.slice(1)); }
  else { key = k.length === 1 ? k : k; code = k.toUpperCase().charCodeAt(0); text = (mods & 7) ? undefined : k; }
  const base = {modifiers: mods, key, windowsVirtualKeyCode: code, code: key.length === 1 ? 'Key' + key.toUpperCase() : key};
  await cdp(tabId, 'Input.dispatchKeyEvent', {...base, type: text ? 'keyDown' : 'rawKeyDown', text});
  await cdp(tabId, 'Input.dispatchKeyEvent', {...base, type: 'keyUp'});
}

async function writeText(tabId, text) {
  for (const ch of text.replace(/\r\n/g, '\n')) {
    if (ch === '\n') { await pressKey(tabId, 'Enter'); continue; }
    await cdp(tabId, 'Input.dispatchKeyEvent', {type: 'keyDown', text: ch, key: ch, unmodifiedText: ch});
    await cdp(tabId, 'Input.dispatchKeyEvent', {type: 'keyUp', key: ch});
  }
}

// ------------------------------------------------------------- commands
const COMMANDS = {
  async ping() { return {version: chrome.runtime.getManifest().version}; },

  async tabs() {
    const wins = await chrome.windows.getAll({populate: true, windowTypes: ['normal']});
    let focused = null;
    try { focused = (await chrome.windows.getLastFocused()).id; } catch (e) {}
    wins.sort((a, b) => (b.id === focused) - (a.id === focused));
    const out = [];
    for (const w of wins) for (const t of w.tabs)
      out.push({id: t.id, windowId: w.id, active: t.active, frontWindow: w.id === focused,
                minimized: w.state === 'minimized', title: t.title || '', url: t.url || ''});
    return out;
  },

  async read({tabId}) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.discarded) throw new Error("that tab is asleep (Edge 'sleeping tabs') - clicking it once wakes it; " +
                                       "you can stop Edge from putting it to sleep in edge://settings/system");
    const snap = await inPage(tabId, pageSnapshot);
    return {...snap, active: tab.active, windowId: tab.windowId};
  },

  async click({tabId, ref, trusted}) {
    if (trusted) {
      const box = await inPage(tabId, (ref) => {
        const el = document.querySelector(`[data-teto-ref="${ref}"]`);
        if (!el) return null;
        el.scrollIntoView({block: 'center'});
        const r = el.getBoundingClientRect();
        return {x: r.left + r.width / 2, y: r.top + r.height / 2};
      }, [ref]);
      if (!box) return 'missing';
      for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased'])
        await cdp(tabId, 'Input.dispatchMouseEvent', {type, x: box.x, y: box.y, button: 'left', clickCount: 1});
      return 'ok';
    }
    return await inPage(tabId, pageClick, [ref]);
  },

  async type({tabId, ref, text, clear, submit}) { return await inPage(tabId, pageType, [ref, text, !!clear, !!submit]); },
  async select({tabId, ref, option}) { return await inPage(tabId, pageSelect, [ref, option]); },
  async key({tabId, keys}) { await pressKey(tabId, keys); return 'ok'; },
  async write({tabId, text}) { await writeText(tabId, text); return 'ok'; },

  async scroll({tabId, dy}) {
    return await inPage(tabId, (dy) => {
      // scroll the page, or the biggest scrollable box if the page itself doesn't scroll
      const before = scrollY;
      window.scrollBy({top: dy, behavior: 'instant'});
      if (scrollY !== before) return 'ok';
      let best = null, area = 0;
      for (const el of document.querySelectorAll('*')) {
        const s = getComputedStyle(el);
        if (!/(auto|scroll)/.test(s.overflowY) || el.scrollHeight <= el.clientHeight + 4) continue;
        const a = el.clientWidth * el.clientHeight;
        if (a > area) { area = a; best = el; }
      }
      if (best) best.scrollBy({top: dy, behavior: 'instant'});
      return 'ok';
    }, [dy]);
  },

  async navigate({tabId, url, action}) {
    if (url) await chrome.tabs.update(tabId, {url});
    else if (action === 'back') await chrome.tabs.goBack(tabId);
    else if (action === 'forward') await chrome.tabs.goForward(tabId);
    else await chrome.tabs.reload(tabId);
    for (let i = 0; i < 100; i++) {                    // until it's loaded (max ~10 s)
      const t = await chrome.tabs.get(tabId);
      if (t.status === 'complete') break;
      await sleep(100);
    }
    return 'ok';
  },

  async activate({tabId}) { await chrome.tabs.update(tabId, {active: true}); return 'ok'; },

  async screenshot({tabId}) {
    return (await COMMANDS.screenshot2({tabId})).data;
  },

  async screenshot2({tabId}) {
    const tab = await chrome.tabs.get(tabId);
    await petVisible(tabId, false);
    try { return await capture(tab); } finally { petVisible(tabId, true); }
  },

  async open({url}) { const t = await chrome.tabs.create({url, active: false}); return {id: t.id}; },
};


// ------------------------------------------------------------- Chromebook extras
Object.assign(COMMANDS, {
  async click_xy({tabId, x, y, button, double}) {
    const b = button === 'right' ? 'right' : 'left';
    await cdp(tabId, 'Input.dispatchMouseEvent', {type: 'mouseMoved', x, y});
    const n = double ? 2 : 1;
    for (let i = 1; i <= n; i++) {
      await cdp(tabId, 'Input.dispatchMouseEvent', {type: 'mousePressed', x, y, button: b, clickCount: i});
      await cdp(tabId, 'Input.dispatchMouseEvent', {type: 'mouseReleased', x, y, button: b, clickCount: i});
    }
    return 'ok';
  },

  async hold({tabId, key, seconds}) {
    const named = KEYS[key.toLowerCase()];
    const k = named ? named[0] : key;
    const code = named ? named[1] : key.toUpperCase().charCodeAt(0);
    const codeName = k.length === 1 ? 'Key' + k.toUpperCase() : k;
    const base = {key: k, code: codeName, windowsVirtualKeyCode: code};
    await cdp(tabId, 'Input.dispatchKeyEvent', {...base, type: 'rawKeyDown'});
    const end = Date.now() + seconds * 1000;
    while (Date.now() < end) {                 // auto-repeat like a held key
      await sleep(60);
      await cdp(tabId, 'Input.dispatchKeyEvent', {...base, type: 'rawKeyDown', autoRepeat: true});
    }
    await cdp(tabId, 'Input.dispatchKeyEvent', {...base, type: 'keyUp'});
    return 'ok';
  },
});

// the side panel opens from the toolbar icon, or when you click Teto on a page
chrome.sidePanel.setPanelBehavior({openPanelOnActionClick: true}).catch(() => {});
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg && msg.type === 'open_panel' && sender.tab) {
    chrome.sidePanel.open({windowId: sender.tab.windowId}).then(() => reply({ok: true}),
                                                               e => reply({ok: false, error: String(e)}));
    return true;
  }
  if (msg && msg.type === 'pet_state') {
    chrome.storage.session.get('online').then(s => reply({online: !!s.online}));
    return true;
  }
});

function wake() { loop(); eventsLoop(); }
chrome.runtime.onStartup.addListener(wake);
chrome.runtime.onInstalled.addListener(wake);
chrome.alarms.create('teto-cb', {periodInMinutes: 0.5});
chrome.alarms.onAlarm.addListener(wake);
wake();
