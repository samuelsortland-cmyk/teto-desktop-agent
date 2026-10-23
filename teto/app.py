"""Wires the pet, the chat panel and the agent together.

Threading model: Tk runs on the main thread. The agent runs on one worker
thread that pulls tasks from a queue. The worker never touches Tk directly;
it posts events to `self._events`, which the UI thread drains every 50 ms.
Blocking requests from the worker (ask / confirm / dodge) wait on an Event
and are released by the UI thread (or by Stop).
"""

from __future__ import annotations

import datetime as _dt
import os
import queue
import sys
import threading
import time
import tkinter as tk
import traceback

from . import __version__, behaviors, brain_cli, platform_win, updater
from .agent import Agent, AgentSettings
from .background import BackgroundTools
from .computer import Computer, Hooks
from .config import Config, app_dir
from .panel import Panel, SettingsWindow
from .pet import Pet, pixel_font
from .sprites import custom_sprite_path


def app_root() -> str:
    """Folder holding main.py / teto/ / assets/ (PyInstaller: the unpacked bundle)."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resource_dir() -> str:
    """Bundled assets; for Teto.exe an updated copy in the overlay wins."""
    overlay = os.path.join(app_dir(), "app", "assets")
    if getattr(sys, "frozen", False) and os.path.isdir(overlay):
        return overlay
    return os.path.join(app_root(), "assets")


class _Request:
    def __init__(self):
        self.event = threading.Event()
        self.value = None

    def resolve(self, value):
        self.value = value
        self.event.set()


class App:
    def __init__(self):
        self.config = Config.load()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("Teto")
        self._set_icon()
        self._events: queue.Queue = queue.Queue()
        self._tasks: queue.Queue = queue.Queue()
        self._busy = threading.Event()
        self._quitting = False
        self._open_requests: list[_Request] = []
        self._our_hwnds: set[int] = set()
        self._last_external_fg: int | None = None
        self._engines: dict = {}
        self._engine_lock = threading.Lock()
        self.signed_in: bool | None = None       # Claude subscription sign-in state
        self._login_proc = None
        self.updater = updater.Updater(app_root(), app_dir(), frozen=bool(getattr(sys, "frozen", False)))
        self._update_plan = None
        self._update_source = None
        self._updating = False
        self._restart_pending = False
        self._was_away = False
        self._battery_warned = 100
        self._eagle_active = False
        self.background = self._make_background()

        self.font = pixel_font(self.root)
        self.pet = self._make_pet()
        self.panel = Panel(self.root, self, self.font)
        self.menu = self._make_menu()

        self._worker = threading.Thread(target=self._worker_loop, name="teto-agent", daemon=True)
        self._worker.start()
        self._start_hotkey()

        self.root.after(50, self._drain_events)
        self.root.after(500, self._track_windows)
        self.root.after(5000, self._check_routines)
        self.root.after(800, self._greet)
        self.root.after(20000, self._startup_ok)
        self.root.after(15000, self._auto_update_check)
        self.root.after(30000, self._companion_tick)

    # ------------------------------------------------------------- setup
    def _set_icon(self):
        ico = os.path.join(resource_dir(), "teto.ico")
        try:
            if sys.platform == "win32":
                self.root.iconbitmap(default=ico)       # applies to every window
            else:
                from PIL import Image, ImageTk
                self._icon = ImageTk.PhotoImage(Image.open(ico).convert("RGBA").resize((64, 64)))
                self.root.iconphoto(True, self._icon)
        except Exception:
            pass

    def ui_scale(self) -> float:
        """1.0 at 100% Windows display scaling, 1.5 at 150%, ..."""
        try:
            return max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            return 1.0

    def _make_pet(self) -> Pet:
        custom = custom_sprite_path(app_dir()) or custom_sprite_path(resource_dir())
        scale = max(2, round(self.config.pet_scale * self.ui_scale()))
        return Pet(self.root, self, scale=scale, custom_sprite=custom)

    def _make_menu(self) -> tk.Menu:
        m = tk.Menu(self.root, tearoff=0, bg="#3a2330", fg="#fff1f4", activebackground="#e0435f",
                    font=(self.font[0], 10))
        m.add_command(label="Chat with Teto", command=lambda: self.toggle_panel(force_show=True))
        m.add_command(label="Stop current task", command=self.stop_all)
        m.add_command(label="New chat", command=self.new_chat)
        m.add_separator()
        self._wander_var = tk.BooleanVar(value=self.config.wander)
        m.add_checkbutton(label="Wander around", variable=self._wander_var, command=self._toggle_wander)
        m.add_command(label="Take a nap", command=lambda: self.pet.set_mood("sleeping"))
        m.add_command(label="Do a trick!", command=self._random_trick)
        m.add_separator()
        m.add_command(label="\U0001F441  Eagle Eyes (take my screen)...", command=self.eagle_eyes)
        m.add_command(label="Settings...", command=self.open_settings)
        m.add_command(label="Check for updates", command=lambda: self.check_updates(manual=True))
        m.add_separator()
        m.add_command(label="Quit", command=self.quit)
        return m

    def _make_background(self) -> BackgroundTools:
        return BackgroundTools(
            profile_dir=os.path.join(app_dir(), "browser-profile"),
            settings=lambda: {"show_browser": self.config.show_browser, "browser_path": self.config.browser_path,
                              "human_typing": self.config.human_typing, "typing_wpm": self.config.typing_wpm,
                              "typos": self.config.typos},
            exclude=lambda: self._our_hwnds)

    API_MODEL_ALIASES = {"default": "claude-opus-5-5", "opus": "claude-opus-5-5",
                         "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}

    def _agent_settings(self, eagle: bool = False) -> AgentSettings:
        c = self.config
        m = c.model.strip()
        effort = "low" if eagle else c.effective_effort()      # Eagle Eyes is always snappy
        return AgentSettings(model=self.API_MODEL_ALIASES.get(m, m), effort=effort,
                             max_steps=c.max_steps, confirm_shell=c.confirm_shell, api_key=c.api_key,
                             cli_model="" if m == "default" else m, work_style=c.work_style)

    @property
    def agent(self):
        """The active brain: Claude subscription via the CLI, or an API key."""
        kind = self.config.brain
        with self._engine_lock:
            if kind not in self._engines:
                if kind == "api":
                    self._engines[kind] = Agent(self, self._make_computer, self._agent_settings(),
                                                background=self.background)
                else:
                    self._engines[kind] = brain_cli.CliAgent(self, self._make_computer, self._agent_settings(),
                                                             background=self.background)
            return self._engines[kind]

    def _make_computer(self) -> Computer:
        hooks = Hooks(
            should_stop=lambda: self.agent.stop_event.is_set(),
            before_pointer=self._dodge_from_worker,
            focus_is_ours=self._focus_is_ours,
            confirm=self.confirm,
            before_input=self._wait_for_user_pause,
        )
        c = self.config
        return Computer(hooks=hooks, max_long_edge=c.effective_screenshot_px(), monitor_index=c.monitor,
                        confirm_risky_keys=c.confirm_risky_keys, human=c.human_typing,
                        wpm=c.typing_wpm, typos=c.typos)

    def _start_hotkey(self):
        try:
            from pynput import keyboard
        except Exception:
            return
        try:
            self._hotkey = keyboard.GlobalHotKeys({self.config.hotkey_stop: lambda: self._events.put(("stop",))})
            self._hotkey.daemon = True
            self._hotkey.start()
        except Exception as e:
            print(f"[teto] global hotkey unavailable: {e}", file=sys.stderr)

    def _greet(self):
        if self.config.brain == "api":
            if not (self.config.api_key or os.environ.get("ANTHROPIC_API_KEY")):
                self.pet.say("I need an API key - right-click me > Settings ♪", 6)
            else:
                self.pet.say("Teto, ready to work! ♪ Click me to chat.", 4)
            return
        self.pet.say("Hiii~ Teto here! ♪ Click me to chat.", 4)
        self.check_sign_in()

    # ------------------------------------------------- Claude sign-in
    def check_sign_in(self, then=None):
        """Ask the CLI whether we're signed in (off the UI thread)."""
        def work():
            st = brain_cli.auth_status()
            self._events.put(("auth", bool(st.get("loggedIn")), st.get("error"), then))
        threading.Thread(target=work, daemon=True).start()

    def sign_in(self):
        """Open the claude.ai sign-in page, then poll until it completes."""
        try:
            self._login_proc = brain_cli.start_login()
        except Exception as e:
            self.panel.log("error", f"Couldn't start sign-in: {e}")
            return
        if self._login_proc is None:
            self.panel.log("error", "Claude Code wasn't found. Please reinstall Teto.")
            return
        self.panel.log("system", brain_cli.LOGIN_URL_HINT)
        self.pet.say("A browser tab opened - sign in with your Claude account! ♪", 6)
        self.panel.set_signin("waiting")
        self._poll_login(time.monotonic())

    def _poll_login(self, started: float):
        def after(ok):
            if ok or self._quitting:
                return
            if time.monotonic() - started > 600:
                self.panel.set_signin("signed_out")
                return
            self.root.after(2500, lambda: self._poll_login(started))
        self.check_sign_in(then=after)

    def sign_out(self):
        def work():
            cli = brain_cli.find_cli()
            if cli:
                import subprocess
                try:
                    subprocess.run([cli, "auth", "logout"], capture_output=True, timeout=30,
                                   stdin=subprocess.DEVNULL,
                                   creationflags=0x08000000 if sys.platform == "win32" else 0)
                except Exception as e:
                    self.log("error", f"Sign-out failed: {e}")
            self.agent.new_conversation()
            self.check_sign_in()
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------ UI <- worker
    # These are called from the worker thread (agent.UI protocol).
    def status(self, state: str) -> None:
        self._events.put(("status", state))

    def log(self, kind: str, text: str) -> None:
        self._events.put(("log", kind, text))

    def ask(self, question: str, choices: list[str]) -> str | None:
        req = _Request()
        self._events.put(("ask", question, choices, req))
        return self._wait(req, default=None)

    def confirm(self, title: str, detail: str) -> bool:
        req = _Request()
        self._events.put(("confirm", title, detail, req))
        return bool(self._wait(req, default=False))

    def _wait(self, req: _Request, default):
        while not req.event.wait(0.1):
            if self.agent.stop_event.is_set() or self._quitting:
                return default
        return req.value

    def _dodge_from_worker(self, x: int, y: int):
        req = _Request()
        self._events.put(("dodge", x, y, req))
        req.event.wait(2.0)
        time.sleep(0.05)   # let the window manager finish moving us

    def _wait_for_user_pause(self, last_ours: float) -> None:
        """Background work style: before borrowing the real mouse/keyboard, wait
        (up to 20 s) until the user hasn't touched them for a moment. Teto's own
        input ended at `last_ours`, so it isn't mistaken for the user's.

        Skipped during Eagle Eyes, where the user wants Teto to take the screen."""
        if self._eagle_active or self.config.work_style != "background":
            return
        end = time.monotonic() + 6                     # brief courtesy pause, not a long stall
        while time.monotonic() < end and not self.agent.stop_event.is_set():
            idle = platform_win.user_idle_seconds()
            if idle == float("inf"):
                return
            last_input_at = time.monotonic() - idle
            if idle >= 0.8 or last_input_at <= last_ours + 0.25:
                return
            time.sleep(0.15)

    def _focus_is_ours(self) -> bool:
        """True if keyboard focus is on one of Teto's windows. Tries first to
        hand focus back to the app the user was in before."""
        fg = platform_win.foreground_hwnd()
        if fg is None or fg not in self._our_hwnds:
            return False
        if self._last_external_fg and platform_win.set_foreground(self._last_external_fg):
            time.sleep(0.15)
            fg = platform_win.foreground_hwnd()
        return fg in self._our_hwnds

    # ------------------------------------------------------ UI thread loop
    def _drain_events(self):
        try:
            while True:
                ev = self._events.get_nowait()
                try:
                    self._handle(ev)
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass
        if not self._quitting:
            self.root.after(50, self._drain_events)

    def _handle(self, ev):
        kind = ev[0]
        if kind == "status":
            state = ev[1]
            self.panel.set_status(state)
            if state in ("success", "error"):
                self.pet.set_mood(state, 2.2)
                self.pet.set_mood("idle")
            elif state == "talking":
                self.pet.set_mood("talking", 1.5)
            elif state == "idle":
                self.pet.set_mood("idle")
            else:
                self.pet.set_mood(state)
        elif kind == "log":
            _, k, text = ev
            self.panel.log(k, text)
            if k == "teto":
                self.pet.say(text)
            elif k == "error" and not self.panel.visible:
                self.pet.say("Oops! " + text, 5)
        elif kind == "ask":
            _, question, choices, req = ev
            self._open_requests.append(req)
            self.pet.set_mood("waiting")
            self.pet.say(question, 6)
            self.panel.ask(question, choices, lambda v, r=req: self._resolve(r, v))
        elif kind == "confirm":
            _, title, detail, req = ev
            self._open_requests.append(req)
            self.pet.set_mood("waiting")
            self.pet.say(title, 5)
            self.panel.confirm(title, detail, lambda v, r=req: self._resolve(r, v))
        elif kind == "dodge":
            _, x, y, req = ev
            try:
                self.pet.dodge(x, y)
                self.panel.dodge(x, y)
                if self.pet.bubble.visible:
                    self.pet.bubble.hide()
                self.root.update_idletasks()
            finally:
                req.resolve(None)
        elif kind == "stop":
            self.stop_all()
        elif kind == "queue":
            self.panel.set_queue(ev[1])
        elif kind == "update_plan":
            self._on_update_plan(ev[1], ev[2], ev[3])
        elif kind == "update_done":
            self._on_update_done(ev[1])
        elif kind == "update_msg":
            level, text = ev[1], ev[2]
            if level == "error":
                if not self.agent_busy():
                    self.pet.set_mood("idle")
                self.panel.log("error", text)
            else:
                print(f"[update] {text}", file=sys.stderr)
        elif kind == "auth":
            _, ok, err, then = ev
            was = self.signed_in
            self.signed_in = ok
            if self.config.brain != "subscription":
                self.panel.set_signin("hidden")
            elif ok:
                self.panel.set_signin("hidden")
                if was is False:
                    self.panel.log("teto", "Signed in! My brain is awake now ♪ What should we do?")
                    self.pet.set_mood("success", 2.2)
                    self.pet.set_mood("idle")
            elif not (self._login_proc and self._login_proc.poll() is None):
                self.panel.set_signin("signed_out")
                if was is None:
                    self.panel.log("system", "Sign in with your Claude account (Pro or Max) so I can "
                                             "work on your PC - click the button above.")
            if err and was is None and "not found" in str(err).lower():
                self.panel.log("error", "Claude Code is missing from this install. Please reinstall Teto.")
            if then:
                then(ok)

    def _resolve(self, req: _Request, value):
        if req in self._open_requests:
            self._open_requests.remove(req)
        req.resolve(value)
        if self.agent_busy():
            self.pet.set_mood("working")

    def _track_windows(self):
        """Remember our HWNDs and the last foreground app that isn't us."""
        if self._quitting:
            return
        try:
            hw = set()
            for w in (self.pet.win, self.pet.bubble.win, self.panel.win, self.root):
                h = platform_win.toplevel_hwnd(w)
                if h:
                    hw.add(h)
            for w in self.root.winfo_children():
                if isinstance(w, tk.Toplevel):
                    h = platform_win.toplevel_hwnd(w)
                    if h:
                        hw.add(h)
            self._our_hwnds = hw
            fg = platform_win.foreground_hwnd()
            if fg and fg not in hw:
                self._last_external_fg = fg
        except tk.TclError:
            pass
        self.root.after(500, self._track_windows)

    # ---------------------------------------------------------- routines
    def _check_routines(self):
        if self._quitting:
            return
        now = _dt.datetime.now()
        today = now.strftime("%Y-%m-%d")
        changed = False
        for r in self.config.routines:
            try:
                if not r.get("enabled", True) or r.get("last_run") == today:
                    continue
                h, m = (int(v) for v in str(r.get("time", "")).split(":"))
                due = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if due <= now < due + _dt.timedelta(minutes=30):
                    r["last_run"] = today
                    changed = True
                    self.panel.log("system", f"Routine ({r['time']}): {r['task']}")
                    self.pet.say("Routine time! On it ♪", 3)
                    self.submit_task(r["task"], fresh=True)
            except (ValueError, KeyError, TypeError):
                continue
        if changed:
            self.config.save()
        self.root.after(20000, self._check_routines)

    # ----------------------------------------------------------- actions
    def agent_busy(self) -> bool:
        return self._busy.is_set()

    def submit_task(self, text: str, fresh: bool = False, from_suggestion: bool = False, eagle: bool = False):
        if from_suggestion:
            self.panel.log("user", text)
            self.panel.show()
        self.pet.poke()
        if self.pet.mood == "sleeping":
            self.pet.set_mood("idle")
        if self.agent_busy():
            self.panel.log("system", "Queued - I'll do that right after the current task.")
        self._tasks.put((text, fresh, eagle))
        self.panel.set_queue(self._tasks.qsize() if self.agent_busy() else 0)

    def _worker_loop(self):
        while not self._quitting:
            try:
                text, fresh, eagle = self._tasks.get(timeout=0.5)
            except queue.Empty:
                continue
            engine = self.agent
            engine.eagle = eagle           # Eagle Eyes: take the screen for this one task
            self._eagle_active = eagle
            self._busy.set()
            self._events.put(("queue", self._tasks.qsize()))
            try:
                if self.config.brain == "subscription" and not self.signed_in:
                    st = brain_cli.auth_status()          # maybe they signed in from a terminal
                    self.signed_in = bool(st.get("loggedIn"))
                    if not self.signed_in:
                        self.log("teto", "I need you to sign in with your Claude account first - "
                                         "click 'Sign in with Claude' in the chat window ♪")
                        self._events.put(("auth", False, st.get("error"), None))
                        continue
                    self._events.put(("auth", True, None, None))
                engine.run_task(text, fresh=fresh)
            except Exception as e:
                traceback.print_exc()
                self.log("error", f"Something went wrong: {type(e).__name__}: {e}")
                self.status("error")
            finally:
                engine.eagle = False
                self._eagle_active = False
                self._busy.clear()
                self._events.put(("queue", self._tasks.qsize()))

    def stop_all(self):
        """Stop the running task and drop anything queued."""
        dropped = 0
        while True:
            try:
                self._tasks.get_nowait()
                dropped += 1
            except queue.Empty:
                break
        if self.agent_busy():
            self.agent.stop()
            self.panel.log("system", "Stopping..." + (f" (cleared {dropped} queued)" if dropped else ""))
            self.pet.say("Okay, stopping!", 2)
        elif dropped:
            self.panel.log("system", f"Cleared {dropped} queued task(s).")
        self.panel.cancel_pending()
        for req in list(self._open_requests):
            req.resolve(None)
        self._open_requests.clear()
        self.panel.set_queue(0)

    def new_chat(self):
        if self.agent_busy():
            self.panel.log("system", "Stop the current task first (■ STOP), then start a new chat.")
            return
        threading.Thread(target=self.agent.new_conversation, daemon=True).start()
        self.panel.log("system", "--- new chat ---")

    def toggle_panel(self, force_show: bool = False):
        if self.panel.visible and not force_show:
            self.panel.hide()
        else:
            self.panel.show()

    def show_menu(self, x, y):
        self._wander_var.set(self.config.wander)
        try:
            self.menu.tk_popup(x, y)
        finally:
            self.menu.grab_release()

    EAGLE_PREFIX = (
        "[EAGLE EYES MODE] The user has handed you direct control of their screen to do this for them, right now, "
        "while they watch. Work on the foreground screen with screenshots, the mouse and the keyboard - you do NOT "
        "need to ask permission for mouse/keyboard this task; that is the whole point of Eagle Eyes. Work fast and "
        "keep acting - do not sit idle or insert long waits. Approach it like this:\n"
        "1. If it's a game or an app whose controls you aren't sure of, first research it: open your background "
        "browser (browser_open) and look up the controls, keybinds, objective and basic strategy, then tell the "
        "user the plan in one short 'say'.\n"
        "2. CLICK the game/app window once to make sure it has keyboard focus before sending any keys - games "
        "ignore keys that go to the wrong window. Take a screenshot to see the state.\n"
        "How you SEE a game: a game has no text or page content to read - you see it ONLY by taking a screenshot "
        "and looking at the picture (where's my character, enemies, health, buttons). So screenshot at the start "
        "of each loop and read the image; never try to read a game as text or wait for text.\n"
        "3. Then act in a tight loop: screenshot -> decide -> act -> screenshot. For games: to MOVE or hold an "
        "action use hold_key with a duration (e.g. hold 'w' for 1-2 seconds to walk, hold a mouse button to "
        "attack); use quick key presses for one-off actions (jump, abilities). Your key presses are sent as real "
        "hardware input, so they work in games. React to what's on screen and keep the loop going quickly; don't "
        "pause between actions.\n"
        "4. The user takes back control any time with Esc, Ctrl+Alt+Q, or by flicking the mouse into a screen "
        "corner; stop if they say to. Keep 'say' updates very short.\n"
        "Never spend money, make purchases, or change account/security settings without asking first.\n\n"
        "The task is: ")

    def eagle_eyes(self):
        """Ask what to do, then hand Teto the real screen to do it (foreground)."""
        from tkinter import simpledialog

        self.pet.poke()
        if self.pet.mood == "sleeping":
            self.pet.set_mood("idle")
        prompt = simpledialog.askstring(
            "Teto - Eagle Eyes \U0001F441",
            "I'll take control of your screen and do this for you.\n"
            "What should I do? (e.g. \"play the Roblox game Jujutsu Shenanigans and fight for me\",\n"
            "or \"fill out this form that's on my screen\")",
            parent=self.panel.win if self.panel.visible else self.root)
        if not prompt or not prompt.strip():
            return
        self.panel.show()
        self.panel.log("user", "\U0001F441 Eagle Eyes: " + prompt.strip())
        if self.config.work_style == "background":
            self.panel.log("system", "Eagle Eyes on - I'll control the screen directly for this. Press Esc, "
                                     "Ctrl+Alt+Q, or flick your mouse to a corner to take back control.")
        self.pet.say("Eagle Eyes! On it~ \U0001F441", 4)
        self.submit_task(self.EAGLE_PREFIX + prompt.strip(), fresh=True, eagle=True)

    def _random_trick(self):
        tricks = [b.name for b in behaviors.LIBRARY if b.tag == "idle"]
        self.pet.poke()
        if self.pet.mood == "sleeping":
            self.pet.set_mood("idle")
        self.pet.play(__import__("random").choice(tricks))

    def _toggle_wander(self):
        self.config.wander = bool(self._wander_var.get())
        self.config.save()

    def open_settings(self):
        SettingsWindow(self.root, self, self.font)

    def apply_settings(self, rebuild_pet: bool = False):
        for engine in self._engines.values():
            old = engine.settings
            engine.settings = self._agent_settings()
            if not self.agent_busy():
                engine._computer = None     # screenshot size / monitor / typing apply next task
                if (old.api_key, old.model, old.cli_model, old.effort, old.max_steps, old.work_style) != (
                        engine.settings.api_key, engine.settings.model, engine.settings.cli_model,
                        engine.settings.effort, engine.settings.max_steps, engine.settings.work_style):
                    engine.reset_client()
        if not self.agent_busy():
            b = self.background._browser
            if b is not None and b.headless == bool(self.config.show_browser):
                threading.Thread(target=self.background.shutdown, daemon=True).start()   # relaunch on next use
        self.check_sign_in()
        if rebuild_pet:
            old = self.pet
            self.pet = self._make_pet()
            old.destroy()
        self.panel.shell_var.set(self.config.confirm_shell)

    def quit(self):
        self._quitting = True
        for engine in self._engines.values():
            engine.stop()
            if hasattr(engine, "shutdown"):
                threading.Thread(target=engine.shutdown, daemon=True).start()
        closer = threading.Thread(target=self.background.shutdown, daemon=True)
        closer.start()
        closer.join(6)              # let the background browser close cleanly
        for req in list(self._open_requests):
            req.resolve(None)
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.quit()

    # ------------------------------------------------------------ updates
    def _ensure_icons(self):
        """Windows, source install: (re)create the Teto-icon shortcuts and folder
        icon once per version, so updates bring icon fixes along too."""
        if sys.platform != "win32" or getattr(sys, "frozen", False):
            return
        done = os.path.join(app_dir(), f"icons_{__version__}.done")
        script = os.path.join(app_root(), "tools", "make_shortcut.ps1")
        if os.path.isfile(done) or not os.path.isfile(script):
            return

        def work():
            import subprocess
            try:
                subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
                                "-AppDir", app_root()], capture_output=True, timeout=60,
                               stdin=subprocess.DEVNULL, creationflags=0x08000000)
                open(done, "w").close()
            except Exception as e:
                print(f"[icons] {e}", file=sys.stderr)
        threading.Thread(target=work, daemon=True).start()

    def _startup_ok(self):
        """We've been running a while: a fresh update is good, stop counting starts."""
        self._ensure_icons()
        self.updater.clear_marker()
        note = os.path.join(app_dir(), "rolled_back.txt")
        if os.path.isfile(note):
            try:
                os.remove(note)
            except OSError:
                pass
            self.panel.log("error", "The last update didn't start properly, so I went back to the previous "
                                    "version. I'll try again when a newer update is out.")

    def _auto_update_check(self):
        if self._quitting:
            return
        if self.config.update_repo and not self._updating:
            self.check_updates(manual=False)
        self.root.after(6 * 3600 * 1000, self._auto_update_check)

    def check_updates(self, manual: bool = True, zip_path: str | None = None):
        """Look for changed files (GitHub repo or a downloaded zip), off the UI thread."""
        if self._updating:
            return
        if not zip_path and not self.config.update_repo:
            if manual:
                self.panel.log("system", "Set an update source first: Settings > Updates > GitHub repository "
                                         "(like yourname/teto-desktop-agent), or use 'Update from zip'.")
                self.panel.show()
            return
        self._updating = True
        if manual:
            self.panel.log("system", "Checking for updates...")

        def work():
            try:
                src = (updater.ZipSource(zip_path) if zip_path else
                       updater.GitHubSource(self.config.update_repo, self.config.update_branch))
                plan = self.updater.check(src)
                self._events.put(("update_plan", plan, src, manual))
            except updater.UpdateError as e:
                self._events.put(("update_msg", "error" if manual else "quiet", str(e)))
            except Exception as e:
                self._events.put(("update_msg", "error" if manual else "quiet", f"Update check failed: {e}"))
            finally:
                self._updating = False
        threading.Thread(target=work, daemon=True).start()

    def _on_update_plan(self, plan, src, manual: bool):
        if plan.needs_full_download:
            self.panel.log("system", "A bigger Teto update is out (it adds new components), so it needs the "
                                     "full download once.")
            return
        if not plan.has_changes:
            if manual:
                self.panel.log("system", f"You're up to date! (Teto {__version__})")
            return
        self._update_plan, self._update_source = plan, src
        n = len(plan.changed) + len(plan.removed)
        label = plan.version or plan.label
        if self.config.auto_update and not manual and not self.agent_busy():
            self.install_update()
        else:
            self.panel.set_update(f"Teto update ready ({label}, {n} file{'s' * (n != 1)})")
            self.pet.say("There's a Teto update! Click UPDATE in my chat ♪", 5)

    def install_update(self):
        plan, src = self._update_plan, self._update_source
        if not plan or self._updating:
            return
        self._updating = True
        self.panel.set_update(None)
        self.panel.log("system", "Updating... (only the changed files)")
        self.pet.set_mood("working")

        def work():
            try:
                res = self.updater.apply(plan, src, progress=lambda s: None)
                self._events.put(("update_done", res))
            except updater.UpdateError as e:
                self._events.put(("update_msg", "error", str(e)))
            except Exception as e:
                self._events.put(("update_msg", "error", f"Update failed: {e}"))
            finally:
                self._updating = False
        threading.Thread(target=work, daemon=True).start()

    def _on_update_done(self, res: dict):
        self.pet.set_mood("success", 2.2)
        self.pet.set_mood("idle")
        msg = f"Updated to {res['version']}! ({res['files']} file{'s' * (res['files'] != 1)})"
        if not res.get("pip_ok", True):
            msg += " Some new components couldn't install - run START-TETO.bat once to finish."
        self.panel.log("teto", msg + " Restarting in a moment~")
        self.pet.say("New Teto! Brb~ ♪", 3)
        self._restart_pending = True
        self.root.after(3500, self._restart_when_idle)

    def _restart_when_idle(self):
        if self._quitting:
            return
        if self.agent_busy() or not self._tasks.empty():
            self.root.after(5000, self._restart_when_idle)
            return
        self.restart()

    def restart(self):
        """Start a fresh Teto (which waits for us to exit) and quit."""
        import subprocess

        if getattr(sys, "frozen", False):
            args = [sys.executable]
        else:
            args = [sys.executable, os.path.join(app_root(), "main.py")]
        args += ["--after-update", str(os.getpid())]
        try:
            subprocess.Popen(args, cwd=app_root(), close_fds=True)
        except OSError as e:
            self.panel.log("error", f"Couldn't restart automatically ({e}). Please start Teto again.")
            return
        self.quit()

    # ---------------------------------------------------------- companion
    def _companion_tick(self):
        """Small caring touches: low battery, welcome back after a break."""
        if self._quitting:
            return
        try:
            bat = platform_win.battery()
            if bat:
                pct, plugged = bat
                if plugged:
                    self._battery_warned = 100
                elif pct <= 10 < self._battery_warned:
                    self._battery_warned = 10
                    self.pet.say(f"Battery's at {pct}%! Please plug in soon~", 6)
                elif pct <= 20 < self._battery_warned:
                    self._battery_warned = 20
                    self.pet.say(f"Heads up: battery is at {pct}%.", 5)
            idle = platform_win.user_idle_seconds()
            if idle != float("inf"):
                if idle > 600:
                    self._was_away = True
                elif self._was_away and idle < 30:
                    self._was_away = False
                    if self.pet.mood == "sleeping":
                        self.pet.set_mood("idle")
                    if self.config.reminders and not self.agent_busy():
                        self.pet.play("wave_hello")
                        self.pet.say("Welcome back! ♪", 3)
        except Exception:
            traceback.print_exc()
        self.root.after(30000, self._companion_tick)
