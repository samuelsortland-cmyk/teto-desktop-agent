"""Start-up: DPI awareness, taskbar identity, logging, self-test, single instance."""

from __future__ import annotations

import os
import sys
import time

from . import platform_win


def _ensure_log_streams() -> None:
    """pythonw.exe / Teto.exe have no console: send prints and tracebacks to a log file."""
    if sys.stderr is not None and sys.stdout is not None:
        return
    try:
        from .config import app_dir

        log = open(os.path.join(app_dir(), "teto.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    except Exception:
        pass


def _selftest() -> int:
    """`Teto --selftest`: check the install without opening any windows."""
    from . import __version__, brain_cli

    print("Teto version:", __version__)
    cli = brain_cli.find_cli()
    print("Claude Code CLI:", cli or "NOT FOUND")
    print("Signed in:", brain_cli.auth_status().get("loggedIn"))
    mods = ["tkinter", "PIL.ImageTk", "mss", "pyautogui", "pynput", "anthropic", "claude_agent_sdk", "playwright"]
    if sys.platform == "win32":
        mods.append("uiautomation")
    failed = not cli
    for mod in mods:
        try:
            __import__(mod)
            print("ok  ", mod)
        except Exception as e:
            print("FAIL", mod, e)
            failed = True
    if "--browser" in sys.argv:          # also start the background browser once
        from .background import BackgroundTools
        from .config import Config, app_dir

        cfg = Config.load()
        bg = BackgroundTools(os.path.join(app_dir(), "browser-profile"),
                             settings=lambda: {"browser_path": cfg.browser_path})
        try:
            out = bg.run("browser_open", {"url": "data:text/html,<title>Teto selftest</title><button>ok</button>"})
            print("ok   background browser:", out.splitlines()[1])
        except Exception as e:
            print("FAIL background browser:", e)
            failed = True
        finally:
            bg.shutdown()
    return 1 if failed else 0


def _wait_for_exit(pid: int, timeout: float = 20.0) -> None:
    """After a self-update restart, wait for the old Teto to close first."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if sys.platform == "win32":
            import ctypes

            h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)   # SYNCHRONIZE
            if not h:
                return
            r = ctypes.windll.kernel32.WaitForSingleObject(h, 500)
            ctypes.windll.kernel32.CloseHandle(h)
            if r == 0:
                return
        else:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.3)


def main() -> int:
    # Before any window exists: real pixel coordinates on scaled displays, and
    # Teto's own taskbar identity (so Windows shows her icon, not Python's).
    platform_win.enable_dpi_awareness()
    platform_win.set_app_id()
    _ensure_log_streams()
    if "--selftest" in sys.argv:
        return _selftest()
    if "--after-update" in sys.argv:
        try:
            _wait_for_exit(int(sys.argv[sys.argv.index("--after-update") + 1]))
        except (IndexError, ValueError):
            pass
    try:
        from .app import App
    except ModuleNotFoundError as e:
        print(f"Missing dependency: {e.name}. Run: pip install -r requirements.txt", file=sys.stderr)
        return 1
    if not platform_win.single_instance():
        print("Teto is already running.", file=sys.stderr)
        return 0
    App().run()
    return 0
