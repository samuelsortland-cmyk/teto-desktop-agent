// Teto Link - lets the Teto desktop agent on this PC work in the tabs you already
// have open. It only ever talks to Teto at http://127.0.0.1:47823.
const BASE = "http://127.0.0.1:47823";
const HDR = {"X-Teto-Link": "1", "X-Teto-Link-Version": chrome.runtime.getManifest().version};
const sleep = ms => new Promise(r => setTimeout(r, ms));
let running = false;

async function loop() {
  if (running) return;
  running = true;
  let backoff = 1000;
  try {
    for (;;) {
      chrome.runtime.getPlatformInfo(() => {});          // keeps the service worker awake
      let r;
      try {
        r = await fetch(BASE + "/poll", {headers: HDR, cache: "no-store"});
      } catch (e) {                                       // Teto isn't running right now
        await sleep(backoff);
        backoff = Math.min(backoff * 2, 15000);
        continue;
      }
      backoff = 1000;
      if (r.status === 204) continue;
      if (r.status !== 200) { await sleep(3000); continue; }
      const cmd = await r.json();
      await handle(cmd);
    }
  } finally {
    running = false;
  }
}

async function handle(cmd) {
  let res;
  try {
    const fn = COMMANDS[cmd.cmd];
    if (!fn) throw new Error("unknown command " + cmd.cmd);
    res = {id: cmd.id, ok: true, result: await fn(cmd.args || {})};
  } catch (e) {
    res = {id: cmd.id, ok: false, error: String((e && e.message) || e)};
  }
  try {
    await fetch(BASE + "/result", {method: "POST", headers: {...HDR, "Content-Type": "application/json"},
                                   body: JSON.stringify(res)});
  } catch (e) { /* Teto went away */ }
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
    const tab = await chrome.tabs.get(tabId);
    if (tab.active) {
      try {
        const url = await chrome.tabs.captureVisibleTab(tab.windowId, {format: 'jpeg', quality: 60});
        return url.split(',')[1];
      } catch (e) { /* window hidden: fall through */ }
    }
    const shot = await Promise.race([cdp(tabId, 'Page.captureScreenshot', {format: 'jpeg', quality: 60}),
                                     sleep(4000).then(() => null)]);
    if (!shot) throw new Error('that tab could not be captured');
    return shot.data;
  },

  async open({url}) { const t = await chrome.tabs.create({url, active: false}); return {id: t.id}; },
};

chrome.runtime.onStartup.addListener(loop);
chrome.runtime.onInstalled.addListener(loop);
chrome.alarms.create('teto-link', {periodInMinutes: 0.5});
chrome.alarms.onAlarm.addListener(loop);
loop();
