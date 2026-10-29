// Teto's chat in Chrome's side panel. Talks to the Teto program in Linux.
const $ = id => document.getElementById(id);
const sleep = ms => new Promise(r => setTimeout(r, ms));
let CONF = null, BASE = null, last = 0, pending = null, eagle = false, settings = {}, busy = false;
const shown = new Set();      // event seqs already drawn

async function conf() {
  if (!CONF) CONF = await (await fetch(chrome.runtime.getURL('token.json'))).json();
  return CONF;
}
const hdr = (x = {}) => ({'X-Teto-Token': CONF.token, ...x});

async function base() {
  await conf();
  if (BASE) return BASE;
  for (const host of ['localhost', '127.0.0.1', 'penguin.linux.test']) {
    const b = `http://${host}:${CONF.port}`;
    try { if ((await fetch(b + '/ping', {headers: hdr(), cache: 'no-store'})).ok) return (BASE = b); } catch (e) {}
  }
  throw new Error('offline');
}

async function api(name, body = {}) {
  const r = await fetch(`${await base()}/api/${name}`, {method: 'POST', headers: hdr({'Content-Type': 'application/json'}),
                                                         body: JSON.stringify(body)});
  return r.json();
}

// ------------------------------------------------------------- drawing
function scrollEnd(force) {
  const m = $('chatView');
  if (force || m.scrollHeight - m.scrollTop - m.clientHeight < 80) m.scrollTop = m.scrollHeight;
}

function intro() {
  $('log').innerHTML = '';
  const d = document.createElement('div');
  d.className = 'divider';
  d.textContent = new Date().toLocaleDateString(undefined, {month: 'long', day: 'numeric', year: 'numeric'});
  const o = document.createElement('div');
  o.className = 'online';
  o.textContent = 'Teto is online';
  $('log').append(d, o);
}

function add(kind, text) {
  if (!text) return;
  const el = document.createElement('div');
  if (['action', 'thought', 'system'].includes(kind)) el.className = 'note ' + kind;
  else el.className = 'msg ' + (kind === 'user' ? 'user' : kind === 'error' ? 'error' : kind === 'ask' ? 'ask' : 'teto');
  el.textContent = text;
  $('log').append(el);
  scrollEnd(kind === 'user');
}

function showReplies(id, choices, kind) {
  clearReplies();
  pending = {id, kind};
  const row = document.createElement('div');
  row.className = 'replies';
  row.id = 'replies';
  choices.forEach((c, i) => {
    const b = document.createElement('button');
    b.className = 'pill' + (i === 0 ? '' : ' outline');
    b.textContent = c.label;
    b.onclick = () => answer(c.value, c.label);
    row.append(b);
  });
  $('log').append(row);
  scrollEnd(true);
}

function clearReplies() {
  const r = $('replies');
  if (r) r.remove();
  pending = null;
}

async function answer(value, label) {
  const p = pending;
  clearReplies();
  if (!p) return;
  add('user', label);
  await api('answer', {id: p.id, answer: value});
}

function setStatus(state) {
  const map = {idle: ['Online', 'ok'], thinking: ['Thinking...', 'busy'], working: ['Working...', 'busy'],
               talking: ['Working...', 'busy'], waiting: ['Needs you!', 'wait'], success: ['Done ♪', 'ok'],
               error: ['Hit a snag', 'bad'], offline: ['Not running', 'bad']};
  const [label, cls] = map[state] || [state, 'ok'];
  $('status').textContent = '● ' + label;
  $('status').className = 'status ' + cls;
  busy = ['thinking', 'working', 'talking', 'waiting'].includes(state);
  $('stop').classList.toggle('hidden', !busy);
}

function apply(ev) {
  if (ev.seq) {
    if (shown.has(ev.seq)) return;
    shown.add(ev.seq);
  }
  switch (ev.type) {
    case 'log': add(ev.kind, ev.text); break;
    case 'status': setStatus(ev.state); break;
    case 'ask':
      add('ask', ev.question);
      showReplies(ev.id, (ev.choices || []).map(c => ({label: c, value: c})), 'ask');
      break;
    case 'confirm':
      add('ask', ev.title + (ev.detail ? '\n\n' + ev.detail : ''));
      showReplies(ev.id, [{label: 'Allow', value: true}, {label: 'Deny', value: false}], 'confirm');
      break;
    case 'answered': if (pending && pending.id === ev.id) clearReplies(); break;
    case 'clear': intro(); clearReplies(); break;
    case 'signin': $('signin').classList.toggle('hidden', !!ev.signed_in); break;
    case 'settings': fillSettings(ev.settings); break;
  }
}

// ------------------------------------------------------------- connection
function view(name) {
  for (const v of ['chatView', 'setupView', 'settingsView']) $(v).classList.toggle('hidden', v !== name);
}

async function connect() {
  for (;;) {
    try {
      const s = await api('state');
      BASE = BASE;   // reachable
      view('chatView');
      intro();
      shown.clear();
      for (const ev of s.history || []) {
        if (ev.type === 'ask' || ev.type === 'confirm') continue;   // only still-open ones matter
        apply(ev);
      }
      setStatus(s.status || 'idle');
      $('signin').classList.toggle('hidden', s.signed_in !== false);
      fillSettings(s.settings);
      $('version').textContent = 'Teto for Chromebook ' + s.version;
      last = s.last || 0;
      if (!(s.history || []).some(e => e.type === 'log')) {
        add('teto', "Hiii~ I'm Teto! Tell me what to do in your tabs and I'll handle it. ♪");
        add('system', 'Try: "do the quiz in my other tab" or "summarize this page"');
      }
      return;
    } catch (e) {
      BASE = null;
      setStatus('offline');
      view('setupView');
      await sleep(2500);
    }
  }
}

async function events() {
  for (;;) {
    try {
      const r = await fetch(`${await base()}/events?after=${last}&wait=20`, {headers: hdr(), cache: 'no-store'});
      const data = await r.json();
      for (const ev of data.events || []) { last = Math.max(last, ev.seq); apply(ev); }
    } catch (e) {
      BASE = null;
      setStatus('offline');
      view('setupView');
      await connect();
    }
  }
}

// ------------------------------------------------------------- input
async function send() {
  const text = $('input').value.trim();
  if (!text) return;
  $('input').value = '';
  grow();
  if (pending && pending.kind === 'ask') return answer(text, text);
  try {
    await api(eagle ? 'eagle' : 'chat', {text});
  } catch (e) { add('error', "I can't reach my brain - is the Teto app running?"); }
}

function grow() {
  const t = $('input');
  t.style.height = 'auto';
  t.style.height = Math.min(120, t.scrollHeight) + 'px';
}

$('input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
$('input').addEventListener('input', grow);
$('send').onclick = send;
document.addEventListener('keydown', e => { if (e.key === 'Escape') api('stop').catch(() => {}); });
$('stop').onclick = () => api('stop').catch(() => {});
$('newChat').onclick = () => api('new_chat').catch(() => {});
$('signinBtn').onclick = () => api('signin').then(() => add('system', 'A sign-in tab opened - sign in with your Claude account, then come back ♪')).catch(() => {});
$('eagleBtn').onclick = () => setEagle(!eagle);
$('eagleOff').onclick = () => setEagle(false);
function setEagle(on) {
  eagle = on;
  $('eagleBtn').classList.toggle('on', on);
  $('eagleBar').classList.toggle('hidden', !on);
  $('input').placeholder = on ? 'What should I do in this tab?' : 'Message Teto...';
  $('input').focus();
}

// ------------------------------------------------------------- settings
const KEYS = ['autonomous', 'pet', 'auto_screenshots', 'auto_update', 'speed', 'model'];
function fillSettings(s) {
  settings = s || {};
  for (const k of KEYS) {
    const el = $('s_' + k);
    if (!el || !(k in settings)) continue;
    if (el.type === 'checkbox') el.checked = !!settings[k]; else el.value = settings[k];
  }
  chrome.storage.local.set({pet: settings.pet !== false});
}
for (const k of KEYS) {
  $('s_' + k).addEventListener('change', e => {
    const el = e.target;
    api('settings', {set: {[k]: el.type === 'checkbox' ? el.checked : el.value}}).catch(() => {});
  });
}
$('gear').onclick = () => view($('settingsView').classList.contains('hidden') ? 'settingsView' : 'chatView');
$('closeSettings').onclick = () => view('chatView');
$('signout').onclick = () => api('signout').then(() => $('signin').classList.remove('hidden')).catch(() => {});
$('checkUpdate').onclick = async () => {
  $('checkUpdate').textContent = 'Checking...';
  try {
    const r = await api('update', {force: true});
    $('checkUpdate').textContent = r.updated ? 'Updating - back in a moment' : 'Up to date ♪';
  } catch (e) { $('checkUpdate').textContent = 'Check for updates'; }
};

connect().then(events);
