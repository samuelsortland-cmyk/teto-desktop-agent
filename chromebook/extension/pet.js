// Teto walking on your web pages (Teto for Chromebook).
(() => {
  if (window.top !== window || document.getElementById('teto-pet-host')) return;
  const S = 3;                         // pixels per sprite pixel
  const GRAV = 2200, FPS_STEP = 1 / 120;
  let sheet = null, meta = null, host, canvas, ctx, bubble;
  let x = 0, y = 0, vx = 0, vy = 0, flip = false, onFloor = false;
  let mode = 'idle', modeUntil = 0, target = null, frame = 'idle_0', drag = null;
  let agentState = 'idle', lastActive = performance.now(), visible = true, enabled = true, online = true;
  let anim = null;       // {frames, fps, until, then}

  const W = () => meta.w * S, H = () => meta.h * S;
  const floorY = () => window.innerHeight - H();

  async function init() {
    const st = await chrome.storage.local.get('pet');
    enabled = st.pet !== false;
    meta = await (await fetch(chrome.runtime.getURL('sprites/frames.json'))).json();
    sheet = new Image();
    sheet.src = chrome.runtime.getURL('sprites/teto.png');
    await sheet.decode();
    host = document.createElement('div');
    host.id = 'teto-pet-host';
    host.style.cssText = 'all:initial;position:fixed;left:0;top:0;width:0;height:0;z-index:2147483646;';
    const root = host.attachShadow({mode: 'closed'});
    root.innerHTML = `<style>
      canvas{position:fixed;image-rendering:pixelated;cursor:grab;touch-action:none;pointer-events:auto}
      canvas:active{cursor:grabbing}
      .b{position:fixed;max-width:220px;background:#fff;color:#2a1822;border-radius:14px;padding:8px 11px;
         font:600 12.5px/1.35 system-ui,sans-serif;box-shadow:0 2px 0 #ece2e7,0 4px 14px rgba(0,0,0,.15);
         border:2px solid #e0435f;pointer-events:auto;cursor:pointer;opacity:0;transition:opacity .2s;
         white-space:pre-wrap;word-wrap:break-word}
      .b.on{opacity:1}
    </style><canvas></canvas><div class="b"></div>`;
    canvas = root.querySelector('canvas');
    bubble = root.querySelector('.b');
    canvas.width = W(); canvas.height = H();
    canvas.style.width = W() + 'px'; canvas.style.height = H() + 'px';
    ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;
    document.documentElement.append(host);
    x = window.innerWidth - W() - 40 - Math.random() * 200;
    y = -H();                           // drop in from the top
    vy = 200;
    bindInput();
    bubble.onclick = openPanel;
    setEnabled(enabled);
    let t0 = performance.now(), acc = 0;
    const tick = now => {
      acc += Math.min(0.1, (now - t0) / 1000);
      t0 = now;
      while (acc >= FPS_STEP) { step(FPS_STEP); acc -= FPS_STEP; }
      draw(now);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  function setEnabled(on) {
    enabled = on;
    host.style.display = on && visible ? '' : 'none';
  }

  // ------------------------------------------------------------- physics
  function step(dt) {
    if (drag) return;
    const fl = floorY();
    if (!onFloor || y < fl) {
      vy += GRAV * dt;
      x += vx * dt; y += vy * dt;
      if (x < 0) { x = 0; vx = -vx * 0.5; }
      if (x > window.innerWidth - W()) { x = window.innerWidth - W(); vx = -vx * 0.5; }
      if (y >= fl) {
        const hard = vy > 1400;
        y = fl;
        if (vy > 500) { vy = -vy * 0.28; onFloor = false; }
        else { vy = 0; vx = 0; onFloor = true; play(hard ? ['land', 'dizzy', 'dizzy'] : ['land'], 6); }
      }
      return;
    }
    y = fl;
    if (mode === 'walk' && target != null && !anim) {
      const dir = Math.sign(target - x);
      flip = dir < 0;
      x += dir * 55 * dt;
      if (Math.abs(target - x) < 2) { target = null; mode = 'idle'; modeUntil = performance.now() + 1500; }
    }
    x = Math.max(0, Math.min(window.innerWidth - W(), x));
  }

  // ------------------------------------------------------------- what she's doing
  const IDLE_TRICKS = [
    () => play(['wave_0', 'wave_1', 'wave_0', 'wave_1', 'wave_0'], 5),
    () => play(['look_l', 'look_l', 'idle_0', 'look_r', 'look_r', 'idle_0'], 3),
    () => play(['dance_0', 'dance_1', 'dance_0', 'dance_1', 'dance_0', 'dance_1', 'happy_1'], 5),
    () => play(['hips', 'hips', 'hips', 'happy_0'], 2),
    () => { vy = -620; onFloor = false; play(['jump', 'jump', 'happy_1'], 5); },
    () => play(['heart', 'heart', 'heart'], 2),
    () => play(['yawn', 'yawn', 'idle_0'], 2),
    () => play(['wink', 'wink', 'happy_0'], 3),
    () => play(['cheer_0', 'cheer_1', 'cheer_0', 'cheer_1'], 5),
  ];

  function play(frames, fps) { anim = {frames, fps, start: performance.now()}; }

  function think(now) {
    if (anim) {
      const i = Math.floor((now - anim.start) / 1000 * anim.fps);
      if (i < anim.frames.length) return anim.frames[i];
      anim = null;
    }
    if (drag) return 'drag';
    if (!onFloor) return vy < 0 ? 'jump' : 'fall';
    const t2 = Math.floor(now / 250) % 2;
    if (agentState === 'working' || agentState === 'talking') return t2 ? 'work_1' : 'work_0';
    if (agentState === 'thinking') return 'think';
    if (agentState === 'waiting') return 'point';
    if (!online) return t2 ? 'sleep_1' : 'sleep_0';
    if (mode === 'walk') return Math.floor(now / 180) % 2 ? 'walk_1' : 'walk_0';
    if (now - lastActive > 90000) return Math.floor(now / 900) % 2 ? 'sleep_1' : 'sleep_0';
    if (now > modeUntil) {
      const r = Math.random();
      if (r < 0.45) {
        mode = 'walk';
        target = Math.max(0, Math.min(window.innerWidth - W(), x + (Math.random() - 0.5) * 600));
      } else if (r < 0.75) {
        IDLE_TRICKS[Math.floor(Math.random() * IDLE_TRICKS.length)]();
        modeUntil = now + 3000;
      } else {
        modeUntil = now + 2500 + Math.random() * 4000;
      }
    }
    if (Math.floor(now / 100) % 40 === 0) return 'blink';
    return Math.floor(now / 600) % 2 ? 'idle_1' : 'idle_0';
  }

  function draw(now) {
    if (!enabled || !visible) return;
    frame = think(now);
    const idx = meta.frames[frame] ?? 0;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    if (flip) { ctx.translate(canvas.width, 0); ctx.scale(-1, 1); }
    ctx.drawImage(sheet, idx * meta.w, 0, meta.w, meta.h, 0, 0, W(), H());
    ctx.restore();
    canvas.style.left = Math.round(x) + 'px';
    canvas.style.top = Math.round(y) + 'px';
    if (bubble.classList.contains('on')) placeBubble();
  }

  // ------------------------------------------------------------- input: drag, fling, click
  function bindInput() {
    let moves = [];
    canvas.addEventListener('pointerdown', e => {
      e.preventDefault();
      canvas.setPointerCapture(e.pointerId);
      drag = {dx: e.clientX - x, dy: e.clientY - y, sx: e.clientX, sy: e.clientY, moved: false};
      moves = [[e.clientX, e.clientY, performance.now()]];
      lastActive = performance.now();
    });
    canvas.addEventListener('pointermove', e => {
      if (!drag) return;
      if (Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) > 4) drag.moved = true;
      x = e.clientX - drag.dx; y = Math.min(floorY(), e.clientY - drag.dy);
      moves.push([e.clientX, e.clientY, performance.now()]);
      if (moves.length > 6) moves.shift();
    });
    canvas.addEventListener('pointerup', e => {
      if (!drag) return;
      const wasClick = !drag.moved;
      drag = null;
      onFloor = false;
      if (wasClick) { vx = 0; vy = 0; openPanel(); return; }
      const [a, b] = [moves[0], moves[moves.length - 1]];
      const dt = Math.max(0.016, (b[2] - a[2]) / 1000);
      vx = Math.max(-2500, Math.min(2500, (b[0] - a[0]) / dt));
      vy = Math.max(-2500, Math.min(2500, (b[1] - a[1]) / dt));
      mode = 'idle';
    });
  }

  function openPanel() {
    lastActive = performance.now();
    play(['wave_0', 'wave_1', 'wave_0'], 6);
    chrome.runtime.sendMessage({type: 'open_panel'}).then(r => {
      if (!r || !r.ok) say("Click my icon in the toolbar to chat with me ♪", 4000);
    }).catch(() => say("Click my icon in the toolbar to chat with me ♪", 4000));
  }

  // ------------------------------------------------------------- speech
  let bubbleTimer = null;
  function say(text, ms = 5000) {
    if (!enabled) return;
    bubble.textContent = text.length > 160 ? text.slice(0, 157) + '...' : text;
    bubble.classList.add('on');
    placeBubble();
    clearTimeout(bubbleTimer);
    bubbleTimer = setTimeout(() => bubble.classList.remove('on'), ms);
  }

  function placeBubble() {
    const bw = bubble.offsetWidth, bh = bubble.offsetHeight;
    const bx = Math.max(6, Math.min(window.innerWidth - bw - 6, x + W() / 2 - bw / 2));
    bubble.style.left = bx + 'px';
    bubble.style.top = Math.max(6, y - bh - 6) + 'px';
  }

  // ------------------------------------------------------------- messages from Teto
  chrome.runtime.onMessage.addListener((msg, _s, reply) => {
    if (msg.type === 'pet_visible') {
      visible = msg.on;
      host.style.display = enabled && visible ? '' : 'none';
      reply && reply({ok: true});
      return;
    }
    if (msg.type !== 'teto' || !msg.event) return;
    const ev = msg.event;
    lastActive = performance.now();
    if (ev.type === 'online') { online = ev.online; return; }
    if (ev.type === 'settings') { setEnabled(ev.settings.pet !== false); return; }
    if (ev.type === 'status') {
      agentState = ev.state;
      if (ev.state === 'success') { play(['cheer_0', 'cheer_1', 'cheer_0', 'cheer_1', 'happy_0'], 5); agentState = 'idle'; }
      if (ev.state === 'error') { play(['sad', 'sad', 'sad'], 2); agentState = 'idle'; }
    }
    if (ev.type === 'log' && ev.kind === 'teto') say(ev.text, 6000);
    if (ev.type === 'ask') say(ev.question + '\n(answer me in the chat ♪)', 9000);
    if (ev.type === 'confirm') say(ev.title, 9000);
  });

  chrome.storage.onChanged.addListener(ch => { if (ch.pet && host) setEnabled(ch.pet.newValue !== false); });
  document.addEventListener('fullscreenchange', () => {
    visible = !document.fullscreenElement;
    if (host) host.style.display = enabled && visible ? '' : 'none';
  });
  window.addEventListener('resize', () => { onFloor = false; });
  chrome.runtime.sendMessage({type: 'pet_state'}).then(r => { if (r) online = r.online; }).catch(() => {});
  init().catch(() => {});
})();
