# Teto Desktop Agent ♪

A bubbly pixel-art **Kasane Teto** who lives on your Windows desktop and can **use your computer for you**. She sees the screen, moves the mouse, clicks, types, runs commands, and works through multi-step tasks on her own.

When she isn't working, she's alive:
- **Physics:** she falls with gravity. You can grab her and throw her, and she bounces off the screen edges.
- **Your windows:** she jumps onto them and rides along when you drag them around.
- **140+ idle animations:** singing, eating bread, dancing, backflips, napping, cat visits, juggling, holidays and more.
- **She notices you:** her eyes follow your cursor, she loves head pats, and she welcomes you back after a break.

![Teto moods](assets/preview.png)

## Quick start (Windows 10/11)

Teto's brain runs on your **Claude Pro or Max subscription**. You don't need an API key and you don't install Claude Code separately, because Teto ships with its own copy.

1. Unzip the folder anywhere and double-click **`START-TETO.bat`**.
   - The first run sets everything up, which takes about 2–5 minutes. If Python isn't installed, it installs it for you through Windows' built-in `winget`.
   - It also adds a **Teto** shortcut to your desktop and Start menu.
   - Later runs start instantly.
2. In Teto's chat window, click **SIGN IN WITH CLAUDE**. Your browser opens; sign in with your Claude account, and Teto notices automatically. If the browser can't hand the sign-in back, a small window asks you to paste a code.
3. Tell her what to do:
   - "Open Notepad and write a haiku about bread"
   - "Find the largest files in my Downloads folder"
   - "Turn on dark mode"
   - "Search the web for tomorrow's weather in Tokyo and tell me"

Her work counts toward your Claude plan's normal usage limits. If you hit the limit, she'll tell you.

If something doesn't start, run `run_debug.bat` to see errors in a console. Logs from windowless runs go to `%APPDATA%\TetoAgent\teto.log`.

### She works in the background (you keep using your PC)

**For brand-new web tasks**, she opens background tabs of *your* Edge, with your Google, Microsoft and school accounts already signed in. That Edge runs minimized and never touches your mouse or focus, so you can keep playing or working while she goes.

How it works: current Edge won't let any program control its main profile folder, so Teto keeps a synced copy of your Edge profile in `%APPDATA%\TetoAgent\edge-you`. The copy includes your cookies/logins, saved passwords, bookmarks and settings, and it runs as a second, minimized Edge that she drives directly. The first time, Edge has your logins locked while it's open. With **Full permission** on, Teto closes Edge for a second, copies them and reopens it with your tabs; otherwise she'll ask you to close Edge once. After that she reconnects instantly. Anything you sign in to inside her Edge stays signed in.

**She works in the tabs you already have open, and never opens new ones unless you ask (3.3).** "Do my quiz", "fill in this form" or "answer this email" happens *in your tab*. Opening a tab, a copy of your tab, a website or a search is **blocked in code** unless your message asks for it ("open YouTube", "search for...", "in a new tab", "make a new doc"...). If she thinks she needs another page, she has to ask you first.

**Connect my Edge (Teto Link) - do this once, ~30 seconds.** Right-click Teto > Settings > **Connect my Edge**. Edge's Extensions page and a folder open: turn on *Developer mode*, click *Load unpacked*, and pick that folder (its path is already copied). Teto says "Teto Link connected!" Now she can read and work in **any** tab you have open, including ones in the background and windows behind your game. She reads what's on the page and clicks answers, buttons and fields. She types into forms, presses keys, scrolls, and even types into Google Docs. She never opens a tab or moves your mouse. Teto Link only talks to Teto on your own PC (`127.0.0.1`).

Without Teto Link, she uses Windows UI Automation on the tab showing in your Edge window. That works for most pages, but not inside Google Docs, and it can't reach tabs that aren't showing.

**For brand-new web tasks**, she opens background tabs of *your* Edge, with your Google, Microsoft and school accounts already signed in. That Edge runs minimized and never touches your mouse or focus, so you can keep playing or working while she goes.

How it works: current Edge won't let any program control its main profile folder, so Teto keeps a synced copy of your Edge profile in `%APPDATA%\TetoAgent\edge-you`. The copy includes your cookies/logins, saved passwords, bookmarks and settings, and it runs as a second, minimized Edge that she drives directly. The first time, Edge has your logins locked while it's open. With **Full permission** on, Teto closes Edge for a second, copies them and reopens it with your tabs; otherwise she'll ask you to close Edge once. After that she reconnects instantly. Anything you sign in to inside her Edge stays signed in.

**She works in the tabs you already have open (3.2).** "Do my quiz" or "fill in this form" means *your* tab, not a new one. Teto reads the tab you're on (or any other tab you have open; she finds it by title) through Windows UI Automation. She sees the visible text, the questions and the buttons, then clicks answers, types in fields and presses **Next** right there in that tab. Your mouse never moves, so you can play a game or use another app while she works. After every click she immediately sees the page's new state and keeps going. She only opens tabs of her own for brand-new tasks, or if you ask.

**Fast by design (3.0):** no fixed waits anywhere. Pages are used as soon as they're loaded, scrolling is detected as finished in ~30 ms, and new tabs are awaited, not slept for. Every browser action comes back with the page's elements *and* a picture of the tab, so she sees the result without spending an extra turn. The main limit on speed is how long Claude takes to think each step (about 1-3 s), so **Speed → Fast** and fewer, bigger steps matter most.

**Full permission (on by default):** she acts without asking "should I?". There are no ALLOW/DENY prompts for shell commands or shortcuts. She'll still check with you before spending money, permanently deleting your files, or changing passwords/security settings. Turn it off in Settings → *Full permission* to get the old confirmations back.

#### 👁 Eagle Eyes - let Teto take the screen

Sometimes you *want* Teto to take over, like playing a game for you. Right-click Teto and choose **👁 Eagle Eyes**, then tell her what to do (for example, "play the Roblox game Jujutsu Shenanigans and fight for me"). She first researches the activity - looking up controls, mechanics and strategy in her browser - then watches your screen and controls the mouse and keyboard in a fast loop to do it, adapting to what's happening on screen. **How she sees a game:** a game has no text to read, so she looks at it the only way possible - by taking screenshots and reading the picture (your character, enemies, health, buttons) each loop. In Eagle Eyes these screenshots are kept small and quick so she can look and react fast. Her key presses are sent as real hardware input (scan codes), so they work in games like Roblox that ignore ordinary simulated keys, and she holds movement keys down to walk/act. You keep control the instant you want it back: press **Esc**, **Ctrl+Alt+Q**, or flick your mouse into a screen corner. She still asks before anything that spends money or changes account settings.


By default Teto **doesn't touch your mouse or keyboard**. While you do something else, she works in the background in three ways.

**Her own browser.** Teto runs a copy of Microsoft Edge (or Chrome) with **her own tabs**, separate from yours. It keeps its own logins and remembers them between sessions, so **the first time** a task needs one of your accounts (Google, email, etc.) her Edge window pops open and asks you to sign in once; after that she stays signed in and works there in the background. For example, "write a Google Doc about X" opens a new doc in her Edge and types it in. She reads web pages as **text** and acts on them directly, which is much faster than taking screenshots.
- She opens sites, reads them, clicks buttons, fills forms and types inside those tabs through the browser itself. Nothing appears on your screen, and your tabs and focus are never touched.
- The browser has its own profile, so it remembers logins between sessions. If a site needs you to sign in once, she'll ask. **Settings → Show Teto's browser window** (or asking her "show me your browser") lets you log in or watch her work.

**Other apps, without the mouse.**
- Using Windows UI Automation, she reads an app's buttons, text boxes, menus and lists. She presses them and fills them in directly, even when the app is behind your current window.
- She can take a picture of a single window while it's covered by others.
- Apps she launches open minimized, so they don't steal your focus.

**Files, settings and info** go through PowerShell commands (with your approval, as before).

**Borrowing your mouse and keyboard.** A few things need your real mouse and keyboard, such as some games or unusual apps. For those she **asks first**: "Can I use your mouse & keyboard?" If you say yes, she waits for a pause in your typing before each action, so she won't fight you for the cursor. If you say no, she keeps trying in the background.

Prefer the old behaviour? Choose **Settings → Sharing your PC → Foreground**.

### A standalone Teto.exe (no Python at all)

- **On your PC:** after one `START-TETO.bat` run, double-click `build_exe.bat`. You get `dist\Teto-Windows.zip`; unzip it anywhere and double-click `Teto.exe`. Copy that zip to any PC; nothing else is needed there except signing in.
- **On GitHub:** push this folder to a GitHub repository. The included workflow (`.github/workflows/build-windows.yml`) builds, tests and zips `Teto.exe` on Windows servers. Run it from the **Actions** tab, or push a tag like `v1.0`, and it attaches `Teto-Windows.zip` to a Release you can download or share.

### Speed

Teto's pace is set by how long the AI takes to decide each step (a quick request to Claude over the internet), not by anything local - the local work happens in milliseconds. **Settings -> Speed** trades that thinking time against thoroughness:

- **Fast** (default): low thinking effort and smaller screenshots, so each step comes back quickly. Best for everyday tasks and games.
- **Balanced** / **Max**: more careful (and slower) for harder tasks.

Teto also works in as few steps as possible - doing several actions in one go, and reading web pages as text instead of images - so there's less back-and-forth. Eagle Eyes always runs at the fastest setting. It still can't be instant, because a cloud AI decides each action, but Fast makes every step as quick as it can be.

### Updating (no re-downloading)

Teto updates herself and downloads **only the files that changed**, usually a few kilobytes. Python and Claude Code are never downloaded again; if an update needs a new component, only that piece is installed.

- **From GitHub (automatic):** put Teto's folder in a public GitHub repository. Then enter it in **Settings → Updates** as `yourname/teto-desktop-agent`. She checks every few hours and updates by herself when she's idle; you can turn that off to get an **UPDATE** button instead.
- **From a zip:** in **Settings → Updates → FROM ZIP…**, pick the newer Teto zip you downloaded. Only the changed files inside it are applied.

Every downloaded file is checked against its expected checksum, and the old files are backed up first. If an update fails to start twice in a row, Teto automatically goes back to the previous version. The standalone `Teto.exe` updates the same way: new code goes into `%APPDATA%\TetoAgent\app` and is used instead of the built-in copy.

### Using an API key instead (optional)

Right-click Teto, open **Settings → Brain**, and choose *Anthropic API key (advanced)*. Then paste a key from <https://console.anthropic.com/>. That mode bills to the API account instead of your subscription.

## Using your own Teto image

The built-in sprite is your reference pixel art, reproduced cell for cell (25×28 pixels, exact colours). Blinking, happy eyes, talking, and the bounce are small pixel edits on top of it.

To use your exact reference picture instead (for example the DinoPixel `teto.png`), save it as either of these:

- `assets\teto.png` (bundled into the .exe build), or
- `%APPDATA%\TetoAgent\teto.png` (per user)

A solid background colour is removed automatically. The image is scaled with nearest-neighbour so pixels stay crisp, and all the bouncing and effect animations still apply.

## Controls

| Action | What it does |
|---|---|
| Click Teto | She reacts with hearts and toggles the chat panel |
| Double-click | Opens the chat |
| Drag and let go | **Throw her!** She flies with momentum, tumbles, bounces off walls, and lands on the taskbar or a window. Throw her too often and she pouts. |
| Wiggle the mouse over her head | Head pats ♪ |
| Click a yellow-edged speech bubble | Accepts her suggestion (for example "check my Downloads folder") |
| Right-click | Menu: chat, stop, new chat, wander, nap, do a trick, settings, check for updates, quit |
| **Esc** (in chat) / **Ctrl+Alt+Q** (anywhere) / **■ STOP** | Stops the current task immediately and clears the queue |
| Fling the mouse into a screen corner | Emergency stop while she's working |

Messages you send while she's busy are **queued** and run in order. **Routines** in Settings let her do a task on her own at a set time every day, for example "09:00 – open my calendar and summarise today's meetings".

## Her life when she isn't busy

She picks from **143 behaviours** based on the time of day, the season and what she did recently, so she rarely repeats herself:

- **Everyday:** yawns, stretches, sneezes, hiccups, giggles, head tilts, winks, humming, daydreaming, light-bulb ideas, pouting.
- **Moves:** strolls, tiptoes, zoomies, moonwalk, skipping, cartwheels, backflips, handstands, spins, teleporting, floating, tripping, chasing your cursor, and climbing onto your windows.
- **Music** (she's a singer!): singing with a mic, karaoke, dancing, robot dance, guitar, drums, maracas, DJ headphones, beatboxing, ballet, cheerleading.
- **Food:** baguettes, of course, plus tea, morning coffee, onigiri, ice cream, lollipops and bubble gum that pops.
- **Hobbies:** reading, notes, video games, selfies, painting, sweeping, watering a plant that grows, juggling, yo-yo, fishing, kites, balloons, stargazing, magic tricks, workouts, yoga, meditation.
- **Friends:** a cat visits, and a bird lands on her head.
- **Seasons and dates:** snow, sakura, autumn leaves, and her birthday on April 1 (party hat and cake!). Halloween, Christmas, New Year fireworks and Valentine's Day.
- **Helpful moments:** a good-morning greeting, a lunch reminder and the hourly time.
  - Nudges to drink water, stretch, rest your eyes and check your posture.
  - Low-battery warnings, compliments, fun facts and jokes.
  - Clickable suggestions, for example checking what fills your Downloads folder, today's weather, a focus timer, or lo-fi music.
  - You can turn the nudges off in Settings.

While she's working for you, she shows her state:
- **Thinking:** looking up with `...` dots and light bulbs.
- **Working:** typing on a little laptop, buzzing.
- **Needs you:** waves.
- **Done:** jumps with confetti.
- **Error:** dizzy.

**Human-like typing:** she types with a natural rhythm. She speeds up on familiar letter pairs and pauses after sentences. Occasionally she hits a neighbouring key and fixes it with Backspace, so the final text is always exactly right. Her mouse glides along gentle curves instead of teleporting. Typing speed, typos and both behaviours can be changed in Settings.

**Her icon everywhere:** the taskbar and Alt-Tab show Teto's icon instead of Python's. So do her desktop and Start-menu shortcuts, a `Teto` shortcut inside her folder, and the folder itself.

## Safety

She operates your *real* PC, so these guardrails are built in:

- **Full permission is on by default (3.0)**: she just does the task. She still asks before purchases/payments, permanently deleting your files, or changing passwords/security settings. Turn *Full permission* off in Settings to bring back the stricter mode: she asks before anything irreversible or outward-facing, and shell commands and Shift+Delete need ALLOW/DENY.
- **Prompt-injection defence**: text on screen, in web pages or in command output is treated as data, never as instructions. Anthropic's screenshot classifiers add a second layer.
- **No secrets** are typed unless you supply them for the task. She won't try to bypass UAC, logins or CAPTCHAs.
- **Instant stop** works from anywhere, and every task has a step limit (Settings → Max steps).
- **Claude Code's own tools are switched off.** That includes its file editing and its own command runner. Claude can only act through Teto's tools, so every shell command goes through Teto's own permission rules.
- Your Claude sign-in is stored by Claude Code in your user profile (`%USERPROFILE%\.claude`). **SIGN OUT** in Settings removes it. An API key, if you use one, is stored in `%APPDATA%\TetoAgent\config.json`.

Even with these guardrails, for anything sensitive consider running her inside a VM or a separate Windows account.

## How it works (design notes)

Teto is a **Claude computer-use agent**. The design follows Anthropic's computer-use guidance plus lessons from open-source agents (OSWorld/pyautogui harnesses, Agent S-style planning plus grounding, safety-gate patterns). She has two interchangeable brains:

- **Subscription brain (default)**, in `teto/brain_cli.py`.
  - It uses the **Claude Agent SDK**, which bundles the Claude Code CLI and signs in with your claude.ai account (`claude auth login --claudeai`). It runs one long-lived session, so follow-up messages keep context.
  - Teto's screen, mouse, keyboard, shell and ask/say abilities are exposed as an in-process MCP tool server. Screenshots go back to Claude as images, and all of Claude Code's built-in tools are disabled.
  - On Windows, the CLI is started with `CREATE_NO_WINDOW` so no console pops up.
- **API-key brain (optional)**, in `teto/agent.py`. It uses the Messages API directly with Anthropic's `computer_toolset_20260801` (default model `claude-opus-5-5`).

**Perception**
- Screenshots come from `mss` and are scaled to fit the model's image limits (2576 px long edge, 4784 visual tokens). The default is 1568 px, which balances accuracy and cost.
- The mouse cursor is drawn into each screenshot, since Windows screen capture omits it.
- `zoom` captures a region at full resolution to read small text.

**Grounding**
- Claude's coordinates are mapped back to real screen pixels, including monitor offsets.
- The process is per-monitor DPI-aware, so 125%/150% scaling doesn't make clicks miss.

**Action**
- All 17 toolset actions are implemented: clicks with modifier keys, drags, scrolling, `type`, `key` with repeat, `hold_key` and `wait`.
- `type` uses Win32 `SendInput` with Unicode, so emoji, accents and CJK text all work.
- xdotool-style key names (`Return`, `ctrl+s`, `super`, `Page_Down`…) are translated for Windows.

**Self-awareness**
- Teto's own windows are hidden from screenshots (`WDA_EXCLUDEFROMCAPTURE`). If a click lands under her or the chat panel, she hops out of the way first.
- If keyboard focus is on her chat box, focus goes back to your previous app before typing.

**Agent loop**
- Several actions per turn are run in order and stop at the first failure.
- The history is append-only, so preserved thinking and the prompt cache stay valid.
- Adaptive thinking with live progress notes shows what she's doing in the chat.
- Refusals fall back to another model on the server side. Connection errors are retried.
- When context gets huge, she hands off to a fresh context: she writes progress notes and continues from them.

**Extra tools**
- `say` sends messages to your screen.
- `ask_user` is the human-in-the-loop channel.
- `open_target` launches apps, files, URLs and `ms-settings:` pages.
- `run_shell` runs PowerShell, which is often faster and more reliable than clicking.

**Threading**
- Tk runs on the main thread and the agent on a worker thread. They communicate through queues and events, so the pet keeps animating while she works and Stop always responds.

## Development

```
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt pytest
python -m pytest -q
python main.py
```

`python -m teto.sprites sheet.png` renders every animation frame to a preview sheet.

Project layout:

```
main.py              entry point (DPI awareness, single instance, logging)
teto/app.py          wiring: windows, worker thread, queue, routines, hotkey
teto/brain_cli.py    subscription brain: Claude Agent SDK + bundled Claude Code CLI
teto/background.py   background work: Teto's own browser + attach to your real browser (CDP) + UI Automation
teto/agent.py        API-key brain: Messages API computer-use loop + client tools
teto/behaviors.py    143 idle behaviours + the time/season-aware chooser
teto/physics.py      gravity, flings, bounces, window platforms
teto/humanize.py     human typing rhythm + curved mouse paths
teto/updater.py      delta self-updater (GitHub / zip), backups, rollback
teto/launcher.py     start-up (DPI, taskbar icon identity, self-test)
teto/computer.py     screenshot/zoom/mouse/keyboard executor (17 actions)
teto/platform_win.py Win32: DPI, capture exclusion, SendInput, focus, work area
teto/pet.py          pet window: physics, behaviour engine, reactions, speech bubble
teto/panel.py        chat panel, approvals, settings/routines
teto/sprites.py      the reference pixel-art Teto, expressions + effect sprites
tests/               150 tests (fake screen/input/Claude/GitHub + a real background browser)
START-TETO.bat       one-click setup + launch (installs Python via winget if needed)
build_exe.bat        builds the standalone Teto.exe zip
.github/workflows/   builds Teto-Windows.zip on GitHub's Windows servers
```
