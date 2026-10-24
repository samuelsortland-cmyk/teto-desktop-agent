"""Background work: Teto acts without touching your mouse or keyboard.

* Her own browser: an invisible Edge/Chrome (Playwright) with its own tabs and
  its own profile. She reads pages, clicks and types inside them through the
  browser itself, so you can keep using your PC.
* Desktop apps (Windows): she reads other windows' controls with UI
  Automation and presses buttons / fills fields through it, and captures a
  window's picture even when it's behind your other windows.

Playwright's sync API and COM both need a dedicated thread, so each runs on its
own small "actor" thread; tools can be called from any thread.
"""

from __future__ import annotations

import base64
import io
import json
import os
import queue
import random
import sys
import threading
import time
from typing import Any, Callable

from PIL import Image

from . import humanize, platform_win
from .computer import ActionError, UserAbort, fit_scale, parse_combo

IS_WINDOWS = sys.platform == "win32"
MAX_TEXT = 12000


# ------------------------------------------------------------------ actor
class Actor:
    """Runs callables one at a time on its own thread."""

    def __init__(self, name: str, init: Callable[[], None] | None = None):
        self._q: queue.Queue = queue.Queue()
        self._init = init
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def _run(self):
        if self._init:
            try:
                self._init()
            except Exception as e:
                print(f"[background] init failed: {e}", file=sys.stderr)
        while True:
            item = self._q.get()
            if item is None:
                return
            fn, args, box, done = item
            try:
                box["value"] = fn(*args)
            except BaseException as e:      # noqa: BLE001 - re-raised in the caller's thread
                box["error"] = e
            done.set()

    def call(self, fn, *args, timeout: float = 180.0, should_stop=lambda: False):
        box: dict = {}
        done = threading.Event()
        self._q.put((fn, args, box, done))
        end = time.monotonic() + timeout
        while not done.wait(0.1):
            if should_stop():
                raise UserAbort()
            if time.monotonic() > end:
                raise ActionError("That took too long and was abandoned.")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def stop(self):
        self._q.put(None)


def _which_browser() -> str:
    import shutil

    for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    return os.environ.get("TETO_BROWSER_PATH", "")


def _spawn(args: list[str]) -> None:
    import subprocess

    if hasattr(os, "geteuid") and os.geteuid() == 0 and "--no-sandbox" not in args:
        args = [*args, "--no-sandbox"]          # Chromium refuses to run as root otherwise (Linux CI)

    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)


def _image_block(img: Image.Image, max_long_edge: int = 1568) -> tuple[dict, float]:
    s = fit_scale(img.width, img.height, max_long_edge)
    if s < 1:
        img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=80)
    return ({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(buf.getvalue()).decode()}}, s)


# ------------------------------------------------- your-Edge profile sync
# Current Edge/Chrome refuse background (DevTools) control of the default
# profile folder. So Teto keeps a synced copy of the user's real profile - their
# cookies/logins, saved passwords, settings and last session - and runs it as a
# separate, minimized Edge she can drive. Same Windows account + same msedge.exe
# means the encrypted cookies stay readable, so the user stays signed in.
_MIRROR_FILES = ["Preferences", "Secure Preferences", "Cookies", "Cookies-journal", "Network/Cookies",
                 "Network/Cookies-journal", "Login Data", "Login Data-journal", "Web Data", "Bookmarks",
                 "History", "Favicons", "Extension Cookies"]
_MIRROR_DIRS = ["Local Storage", "Session Storage", "Network"]   # not "Sessions": no tab restore storm


def last_used_profile(user_data: str) -> str:
    try:
        with open(os.path.join(user_data, "Local State"), "r", encoding="utf-8") as f:
            name = (json.load(f).get("profile") or {}).get("last_used") or "Default"
    except Exception:
        name = "Default"
    return name if os.path.isdir(os.path.join(user_data, name)) else "Default"


def mirror_profile(src_user_data: str, dest: str, read=None) -> dict:
    """Copy the parts of a Chromium profile that carry the user's sign-ins into
    dest (its own 'User Data' folder). Files the running browser has locked are
    read with shared access when possible and otherwise skipped.
    Returns {"profile", "copied", "skipped", "cookies"}."""
    read = read or platform_win.read_shared
    profile = last_used_profile(src_user_data)
    copied, skipped = 0, []

    def put(rel_src: str, rel_dest: str):
        nonlocal copied
        data = read(os.path.join(src_user_data, rel_src))
        if data is None:
            skipped.append(rel_src)
            return False
        out = os.path.join(dest, rel_dest)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(data)
        copied += 1
        return True

    os.makedirs(dest, exist_ok=True)
    if os.path.isfile(os.path.join(src_user_data, "Local State")):
        put("Local State", "Local State")          # holds the key that decrypts cookies
    for name in _MIRROR_FILES:
        if os.path.isfile(os.path.join(src_user_data, profile, name)):
            put(os.path.join(profile, name), os.path.join("Default", name))
    for d in _MIRROR_DIRS:
        root = os.path.join(src_user_data, profile, d)
        for here, _dirs, files in os.walk(root):
            for fn in files:
                rel = os.path.relpath(os.path.join(here, fn), os.path.join(src_user_data, profile))
                if fn.upper() == "LOCK":
                    continue
                put(os.path.join(profile, rel), os.path.join("Default", rel))
    cookies = any(os.path.isfile(os.path.join(dest, "Default", c)) for c in ("Network/Cookies", "Cookies"))
    try:   # the copy always opens as its own profile, not as "profile 3"
        ls_path = os.path.join(dest, "Local State")
        with open(ls_path, "r", encoding="utf-8") as f:
            ls = json.load(f)
        ls.setdefault("profile", {})["last_used"] = "Default"
        with open(ls_path, "w", encoding="utf-8") as f:
            json.dump(ls, f)
    except Exception:
        pass
    return {"profile": profile, "copied": copied, "skipped": skipped, "cookies": cookies}


# ----------------------------------------------------------- tool specs
def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


_TAB = {"tab": {"type": "integer", "description": "Tab id (default: the current tab)."}}
BROWSER_SPECS: dict[str, tuple[str, dict]] = {
    "browser_use_my_browser": ("List the tabs of your own background Edge (the signed-in copy you open new tabs "
                               "in). For the user's real, already-open tabs use browser_screen_tab instead.",
                               _obj({}, [])),
    "browser_open": ("Open a URL in a new background tab of the USER'S OWN signed-in Edge (their logins, Google "
                     "account, etc.) - it runs minimized and never touches their mouse, keyboard or focus. Pass "
                     "own_browser:true only for a throwaway task that must be kept apart from their accounts. "
                     "Returns the tab id and the page's interactive elements.", _obj({"url": {"type": "string"},
                                        "new_tab": {"type": "boolean", "description": "Default true."},
                                        "own_browser": {"type": "boolean",
                                                        "description": "Default false (the user's Edge)."}},
                                       ["url"])),
    "browser_tabs": ("List the open background tabs.", _obj({}, [])),
    "browser_snapshot": ("Get the current page's title, URL, a short text preview and its numbered interactive "
                         "elements [ref]. Use the refs with browser_click / browser_type / browser_select.",
                         _obj(dict(_TAB), [])),
    "browser_read": ("Read the visible text of a page (articles, results, emails...).", _obj(dict(_TAB), [])),
    "browser_screenshot": ("Take a picture of a background tab (for visual layout). Coordinates in it can be "
                           "used with browser_click_xy.", _obj(dict(_TAB), [])),
    "browser_click": ("Click element [ref] from the latest snapshot.",
                      _obj({**_TAB, "ref": {"type": "integer"}}, ["ref"])),
    "browser_click_xy": ("Click at x,y in the latest browser_screenshot of that tab.",
                         _obj({**_TAB, "x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"])),
    "browser_type": ("Type into element [ref] (human-like). clear: replace existing text (default true). "
                     "submit: press Enter afterwards.",
                     _obj({**_TAB, "ref": {"type": "integer"}, "text": {"type": "string"},
                           "clear": {"type": "boolean"}, "submit": {"type": "boolean"}}, ["ref", "text"])),
    "browser_select": ("Choose an option (by its visible text) in dropdown [ref].",
                       _obj({**_TAB, "ref": {"type": "integer"}, "option": {"type": "string"}}, ["ref", "option"])),
    "browser_press": ("Press a key or combination in a tab, e.g. 'Return', 'Escape', 'ctrl+a', 'Page_Down'.",
                      _obj({**_TAB, "keys": {"type": "string"}}, ["keys"])),
    "browser_write": ("Type text into whatever is currently focused in the page - use for editors that aren't a "
                      "normal form field, like a Google Doc, Google Slides or a rich-text editor. Click into the "
                      "editor first, then call this. Newlines become real Enter presses.",
                      _obj({**_TAB, "text": {"type": "string"}}, ["text"])),
    "browser_scroll": ("Scroll a tab up or down by screens.",
                       _obj({**_TAB, "direction": {"type": "string", "enum": ["up", "down"]},
                             "amount": {"type": "number", "description": "Screens to scroll (default 1)."}},
                            ["direction"])),
    "browser_navigate": ("Go back, forward or reload in a tab.",
                         _obj({**_TAB, "action": {"type": "string", "enum": ["back", "forward", "reload"]}},
                              ["action"])),
    "browser_close_tab": ("Close one of Teto's background tabs.", _obj({"tab": {"type": "integer"}}, ["tab"])),
    "browser_show": ("Show Teto's browser window to the user (e.g. so they can log in to a site once, or to "
                     "show a result). Only when the user asks or it's needed.", _obj({}, [])),
}

_WIN = {"window": {"type": "integer", "description": "Window id from window_list."}}
WINDOW_SPECS: dict[str, tuple[str, dict]] = {
    "window_list": ("List open app windows (id, title, program) - including ones behind the user's current "
                    "window.", _obj({}, [])),
    "window_screenshot": ("Picture of one window, even if it's covered by others. Does not disturb the user.",
                          _obj(dict(_WIN), ["window"])),
    "window_elements": ("Numbered list of a window's controls (buttons, text boxes, menus, list items...) via "
                        "Windows UI Automation. Use the refs with window_click / window_type.",
                        _obj(dict(_WIN), ["window"])),
    "window_click": ("Press/activate control [ref] in a window without moving the mouse (button, checkbox, "
                     "menu or list item, tab...).", _obj({**_WIN, "ref": {"type": "integer"}}, ["window", "ref"])),
    "window_click_xy": ("Send a click at x,y of the latest window_screenshot to that window without moving the "
                        "mouse. Works in most classic apps (not in browsers - use browser_* tools there).",
                        _obj({**_WIN, "x": {"type": "integer"}, "y": {"type": "integer"},
                              "double": {"type": "boolean"}}, ["window", "x", "y"])),
    "window_type": ("Put text into text box [ref] without using the keyboard. mode: replace (default) or append.",
                    _obj({**_WIN, "ref": {"type": "integer"}, "text": {"type": "string"},
                          "mode": {"type": "string", "enum": ["replace", "append"]}}, ["window", "ref", "text"])),
    "window_key": ("Send a key (Return, Tab, Escape, arrows, Page_Up/Down, Home, End, Delete, BackSpace, F1-F12) "
                   "to a window without using the real keyboard.",
                   _obj({**_WIN, "keys": {"type": "string"}}, ["window", "keys"])),
    "window_scroll": ("Scroll a window's content (or control [ref]) up/down without the mouse.",
                      _obj({**_WIN, "ref": {"type": "integer"},
                            "direction": {"type": "string", "enum": ["up", "down"]}}, ["window", "direction"])),
}


SCREEN_TAB_SPECS: dict[str, tuple[str, dict]] = {
    "browser_take_screen_tab": ("Open a copy of the user's tab as a NEW tab in your own Edge. Only when the user "
                                "asks for that, or when the work truly can't be done in their tab (e.g. writing "
                                "long text into a Google Doc's canvas).",
                                _obj({"switch_to": {"type": "string"}}, [])),
}


def available_specs() -> dict[str, tuple[str, dict]]:
    specs = dict(BROWSER_SPECS)
    if IS_WINDOWS:
        specs.update(WINDOW_SPECS)
        specs.update(SCREEN_TAB_SPECS)
    return specs


BROWSER_EXES = ("msedge.exe", "chrome.exe", "brave.exe", "opera.exe", "vivaldi.exe", "firefox.exe")


def normalize_url(value: str) -> str:
    """Address-bar text -> a URL (Edge shows 'docs.google.com/...' without the scheme)."""
    v = (value or "").strip()
    if not v or " " in v:
        return ""
    if "://" in v or v.startswith(("about:", "edge:", "chrome:", "file:", "data:")):
        return v
    return "https://" + v


def pick_tab(tabs: list[tuple[str, bool]], want: str) -> int | None:
    """Index of the tab matching `want` (1-based number or part of the title)."""
    want = (want or "").strip()
    if not want:
        return None
    if want.isdigit() and 1 <= int(want) <= len(tabs):
        return int(want) - 1
    low = want.lower()
    for i, (name, _sel) in enumerate(tabs):
        if low in name.lower():
            return i
    return None


# ------------------------------------------------------- Playwright keys
_PW_KEYS = {"enter": "Enter", "esc": "Escape", "backspace": "Backspace", "tab": "Tab", "delete": "Delete",
            "insert": "Insert", "space": "Space", "up": "ArrowUp", "down": "ArrowDown", "left": "ArrowLeft",
            "right": "ArrowRight", "home": "Home", "end": "End", "pageup": "PageUp", "pagedown": "PageDown",
            "ctrl": "Control", "ctrlleft": "Control", "ctrlright": "Control", "alt": "Alt", "altleft": "Alt",
            "altright": "Alt", "shift": "Shift", "shiftleft": "Shift", "shiftright": "Shift", "win": "Meta",
            "winleft": "Meta", "winright": "Meta", "capslock": "CapsLock"}


def to_playwright_combo(text: str) -> str:
    out = []
    for k in parse_combo(text):
        if k in _PW_KEYS:
            out.append(_PW_KEYS[k])
        elif len(k) > 1 and k[0] == "f" and k[1:].isdigit():
            out.append(k.upper())
        elif len(k) == 1:
            out.append(k)
        else:
            raise ActionError(f"Key {k!r} isn't supported in the background browser")
    return "+".join(out)


_SNAPSHOT_JS = r"""
() => {
  const sel = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=link],' +
    '[role=checkbox],[role=radio],[role=tab],[role=menuitem],[role=option],[role=switch],[role=combobox],' +
    '[role=textbox],[role=searchbox],[contenteditable=""],[contenteditable=true],[onclick]';
  document.querySelectorAll('[data-teto-ref]').forEach(e => e.removeAttribute('data-teto-ref'));
  const items = []; let n = 0;
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect(), st = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none') continue;
    if (r.bottom < -innerHeight || r.top > innerHeight * 3) continue;
    n++; el.setAttribute('data-teto-ref', String(n));
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || (tag === 'input' ? 'input:' + (el.type || 'text') : tag);
    let name = (el.getAttribute('aria-label') || el.innerText || el.placeholder || el.title || el.alt ||
                el.getAttribute('name') || '').trim().replace(/\s+/g, ' ').slice(0, 80);
    if (!name && tag === 'input' && (el.type === 'submit' || el.type === 'button')) name = el.value || '';
    let val = '';
    if ((tag === 'input' || tag === 'textarea') && !['submit', 'button', 'checkbox', 'radio'].includes(el.type))
      val = el.type === 'password' ? (el.value ? '****' : '') : (el.value || '').slice(0, 60);
    if (tag === 'select') val = (el.options[el.selectedIndex] || {}).text || '';
    const checked = (el.type === 'checkbox' || el.type === 'radio') ? (el.checked ? ' [x]' : ' [ ]') : '';
    const where = (r.top >= 0 && r.bottom <= innerHeight) ? '' : ' (scroll to see)';
    items.push(`[${n}] ${role} "${name}"` + (val ? ` value="${val}"` : '') + checked +
               (el.disabled ? ' (disabled)' : '') + where);
    if (n >= 250) break;
  }
  const text = (document.body ? document.body.innerText : '').replace(/\n{3,}/g, '\n\n');
  return {title: document.title, url: location.href, items, text};
}
"""


class BackgroundBrowser:
    """Teto's own browser. Every method runs on the browser actor thread."""

    def __init__(self, profile_dir: str, headless: bool = True, browser_path: str = "",
                 typing: Callable[[], tuple] = lambda: (True, 90, True), debug_port: int = 9222,
                 prefer_real: bool = False, may_close_browser: bool = False):
        self.profile_dir = profile_dir
        self.headless = headless
        self.browser_path = browser_path or os.environ.get("TETO_BROWSER_PATH", "")
        self.typing = typing
        self.debug_port = debug_port
        self.attached = False          # True when driving the user's real running browser
        self.browser = None            # the CDP Browser object when attached
        self.pw = None
        self.ctx = None
        self.tabs: dict[int, Any] = {}
        self.current: int | None = None
        self._next = 1
        self.shot_scale: dict[int, float] = {}
        self.mirror_note = ""
        self.prefer_real = prefer_real    # open sites in the user's own Edge by default
        self.may_close_browser = may_close_browser   # full permission: may restart Edge once to copy logins

    # ---------------------------------------------------------- lifecycle
    def _ensure(self):
        if self.ctx is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ActionError("The background browser isn't installed yet. Run START-TETO.bat once to finish "
                              "installing Teto's new parts.")
        self.pw = sync_playwright().start()
        os.makedirs(self.profile_dir, exist_ok=True)
        common = dict(user_data_dir=self.profile_dir, headless=self.headless, viewport={"width": 1280, "height": 860},
                      args=["--disable-blink-features=AutomationControlled", "--no-first-run",
                            "--no-default-browser-check"] + (["--start-minimized"] if not self.headless else []))
        attempts = []
        if self.browser_path:
            attempts.append({"executable_path": self.browser_path})
        if IS_WINDOWS:
            attempts += [{"channel": "msedge"}, {"channel": "chrome"}]
        else:
            attempts += [{"channel": "chrome"}, {"channel": "msedge"}]
        attempts.append({})
        last = None
        for extra in attempts:
            try:
                self.ctx = self.pw.chromium.launch_persistent_context(**common, **extra)
                break
            except Exception as e:      # this browser isn't installed: try the next one
                last = e
        if self.ctx is None:
            self.pw.stop()
            self.pw = None
            raise ActionError(f"Couldn't start a background browser (Microsoft Edge or Google Chrome). {last}")
        try:   # look like a normal browser, not "HeadlessChrome"
            ua = self.ctx.pages[0].evaluate("navigator.userAgent") if self.ctx.pages else ""
            if "Headless" in ua:
                ua = ua.replace("HeadlessChrome", "Chrome")
                self.ctx.set_extra_http_headers({"User-Agent": ua})
                self.ctx.add_init_script(f"Object.defineProperty(navigator,'userAgent',{{get:()=>{ua!r}}})")
        except Exception:
            pass
        self.ctx.on("page", self._register)
        for p in list(self.ctx.pages):
            self._register(p)

    # ------------------------------------------------ attach to the real browser
    def _cdp_reachable(self) -> bool:
        import urllib.request

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # never proxy localhost
        try:
            with opener.open(f"http://127.0.0.1:{self.debug_port}/json/version", timeout=1.5) as r:
                return r.status == 200
        except Exception:
            return False

    def attach(self, launch_if_needed: bool = True) -> str:
        """Drive the user's ALREADY-OPEN Edge/Chrome through the DevTools protocol.

        This operates the real tabs directly (reads, clicks, types in the page),
        without moving the mouse or stealing focus - so the user can keep playing
        a game while Teto works in one of their real tabs. Needs the browser to
        expose a debug port; if it doesn't, Teto can relaunch it (reopening the
        user's tabs) with the port enabled.
        """
        if self.attached and self.browser is not None:
            return self.list_tabs()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ActionError("The background browser isn't installed yet. Run START-TETO.bat once to finish setup.")
        launched = False
        if not self._cdp_reachable():
            if not launch_if_needed:
                raise ActionError("Your browser isn't reachable for background control yet.")
            launched = False if IS_WINDOWS else self._launch_real_with_debug()
            if not (launched and self._wait_cdp(8.0)):
                # Current Edge ignores the debug port on its default folder (or Edge
                # was already open): run Teto's synced copy of the user's profile.
                self.mirror_note = self._launch_mirror()
                launched = True
                if not self._wait_cdp(15.0):
                    raise ActionError("I couldn't connect to your Edge/Chrome. Make sure Edge is installed.")
        if self.pw is None:
            self.pw = sync_playwright().start()
        try:
            self.browser = self.pw.chromium.connect_over_cdp(f"http://127.0.0.1:{self.debug_port}", timeout=15000)
        except Exception as e:
            raise ActionError(f"Couldn't attach to your browser: {str(e).splitlines()[0]}")
        self.attached = True
        self.ctx = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
        self.ctx.on("page", self._register)
        for p in list(self.ctx.pages):
            self._register(p)
        where = " (opened in the background with your profile)" if launched else ""
        return f"Connected to your Edge{where}.{self.mirror_note} Open tabs:\n" + self.list_tabs()

    def _wait_cdp(self, seconds: float) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self._cdp_reachable():
                return True
            time.sleep(0.15)
        return self._cdp_reachable()

    def _launch_mirror(self) -> str:
        exe = self.browser_path or (platform_win._browser_exe() if IS_WINDOWS else _which_browser())
        if not exe:
            raise ActionError("I couldn't find Microsoft Edge or Chrome on this PC.")
        dest = self.mirror_dir()
        src = platform_win.browser_user_data(exe) if IS_WINDOWS else ""
        note = ""
        if src and os.path.isdir(src):
            image = os.path.basename(exe)
            have = any(os.path.isfile(os.path.join(dest, "Default", c)) for c in ("Network/Cookies", "Cookies"))
            running = platform_win.process_running(image)
            reopen = False
            if running and not have:
                # First time: Edge locks its cookie file while open. With full permission
                # Teto closes it for a moment (tabs are saved), copies the logins, and
                # reopens it; otherwise she asks the user to.
                if self.may_close_browser and platform_win.close_browser(image):
                    running, reopen = False, True
            try:
                if not running or not have:
                    info = mirror_profile(src, dest)
                    if not info["cookies"]:
                        note = (" (Your Edge kept its sign-in data locked; close Edge once and I'll copy your "
                                "logins next time.)")
                    elif reopen:
                        note = " (I closed and reopened your Edge once to copy your logins - your tabs are back.)"
            except Exception as e:
                note = f" (Couldn't sync your logins: {e}.)"
            if reopen:
                platform_win.reopen_browser(exe)
        if IS_WINDOWS:
            platform_win.launch_browser_with_debug(self.debug_port, exe, user_data_dir=dest, restore=False)
        else:
            _spawn([exe, f"--remote-debugging-port={self.debug_port}", "--remote-allow-origins=*",
                    f"--user-data-dir={dest}", *platform_win.FAST_BACKGROUND_FLAGS])
        return note

    def mirror_dir(self) -> str:
        return os.path.join(os.path.dirname(self.profile_dir) or self.profile_dir, "edge-you")

    def _launch_real_with_debug(self) -> bool:
        """Relaunch the user's Edge/Chrome with the debug port and their tabs."""
        if not IS_WINDOWS:
            exe = self.browser_path or _which_browser()
            if not exe:
                return False
            _spawn([exe, f"--remote-debugging-port={self.debug_port}", "--remote-allow-origins=*",
                    f"--user-data-dir={os.path.join(self.profile_dir, 'attach')}", *platform_win.FAST_BACKGROUND_FLAGS])
            return True
        return platform_win.launch_browser_with_debug(self.debug_port, self.browser_path)

    def _register(self, page) -> int:
        for tid, p in self.tabs.items():
            if p is page:
                return tid
        tid = self._next
        self._next += 1
        self.tabs[tid] = page
        self.current = tid
        page.on("close", lambda _p, tid=tid: self._forget(tid))
        return tid

    def _forget(self, tid: int):
        self.tabs.pop(tid, None)
        if self.current == tid:
            self.current = max(self.tabs) if self.tabs else None

    def close(self):
        try:
            if self.attached and self.browser is not None:
                self.browser.close()          # just disconnect; the user's browser keeps running
            elif self.ctx:
                self.ctx.close()
        except Exception:
            pass
        try:
            if self.pw:
                self.pw.stop()
        except Exception:
            pass
        self.ctx = self.pw = self.browser = None
        self.attached = False
        self.tabs.clear()
        self.current = None

    def _page(self, tab: int | None):
        self._ensure()
        if tab is None:
            tab = self.current
        if tab is None or tab not in self.tabs:
            if tab is None and not self.tabs:
                raise ActionError("No tabs are open yet - use browser_open first.")
            raise ActionError(f"There's no tab {tab}. Open tabs: {sorted(self.tabs)}")
        self.current = tab
        return tab, self.tabs[tab]

    def _settle(self, page, wait: int = 0):
        """Let the page catch up. Kept short so background work stays snappy;
        navigations get a longer load wait, in-page clicks only a brief tick."""
        try:
            page.wait_for_load_state("domcontentloaded", timeout=6000)
        except Exception:
            pass
        if wait:
            try:
                page.wait_for_timeout(wait)
            except Exception:
                pass
        if self.ctx is not None:
            for p in list(self.ctx.pages):       # pick up tabs opened by the page
                self._register(p)

    _SCROLL_STILL = """() => new Promise(done => {
        let last = -1, still = 0, t0 = Date.now();
        const tick = () => {
            const y = window.scrollY + window.scrollX * 1e6;
            still = (y === last) ? still + 1 : 0; last = y;
            if (still >= 2 || Date.now() - t0 > 400) return done(true);
            setTimeout(tick, 16);
        };
        tick();
    })"""

    def _scroll_done(self, page):
        """Return as soon as (smooth) scrolling has stopped - usually ~30 ms -
        instead of sleeping a fixed time."""
        try:
            page.evaluate(self._SCROLL_STILL)
        except Exception:
            pass

    # -------------------------------------------------------------- tools
    def open(self, url: str, new_tab: bool = True, own_browser: bool | None = None) -> str:
        if own_browser is None:
            own_browser = not self.prefer_real
        fallback = ""
        if not own_browser and not self.attached and self.ctx is None:
            try:
                self.attach()                   # work in the user's own signed-in Edge
            except ActionError as e:
                fallback = f"\n(Couldn't use your Edge - {e} - so I used my own background browser.)"
        self._ensure()
        url = url.strip()
        if "://" not in url and not url.startswith(("about:", "data:", "file:")):
            url = "https://" + url
        if new_tab or not self.tabs:
            blank = [t for t, p in self.tabs.items() if p.url in ("about:blank", "")]
            tid = blank[0] if blank else self._register(self.ctx.new_page())
        else:
            tid, _ = self._page(None)
        page = self.tabs[tid]
        self.current = tid
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            raise ActionError(f"Couldn't load {url}: {str(e).splitlines()[0]}")
        self._settle(page)
        where = "your Edge" if self.attached else "my background browser"
        return (f"Opened in {where}, background tab {tid}.{fallback}\n" + self.snapshot(tid)
                + self._login_note(page))

    _LOGIN_HOSTS = ("accounts.google.com", "login.microsoftonline.com", "login.live.com", "login.yahoo.com",
                    "appleid.apple.com", "signin.aws", "auth0.com")

    def _on_login_wall(self, page) -> bool:
        try:
            host = (page.url.split("/")[2] if "://" in page.url else "").lower()
        except Exception:
            host = ""
        if any(h in host for h in self._LOGIN_HOSTS):
            return True
        try:
            return bool(page.query_selector("input[type=password]")) and \
                ("sign in" in (page.title() or "").lower() or "log in" in (page.title() or "").lower())
        except Exception:
            return False

    def _login_note(self, page) -> str:
        """If the page is a sign-in wall, pop the browser open so the user can log
        in once (the profile is persistent, so it stays logged in afterwards)."""
        if not self._on_login_wall(page):
            return ""
        shown = ""
        if self.headless:
            try:
                self.show()
                shown = " I've opened my browser window so you can sign in."
            except Exception:
                shown = " (open my browser with browser_show so the user can sign in.)"
        return ("\n\n[SIGN-IN NEEDED] This site needs the user to sign in. Tell the user to sign in to their "
                "account in the Teto browser window that is now open" + shown + " Once they say they're done, "
                "call browser_snapshot again to continue - the login is remembered for next time.")

    def list_tabs(self) -> str:
        self._ensure()
        if not self.tabs:
            return "No background tabs open."
        lines = []
        for tid, p in sorted(self.tabs.items()):
            try:
                title = p.title()
            except Exception:
                title = "?"
            lines.append(f"{'*' if tid == self.current else ' '} tab {tid}: {title} - {p.url}")
        return "\n".join(lines)

    def snapshot(self, tab: int | None = None) -> str:
        tid, page = self._page(tab)
        try:
            data = page.evaluate(_SNAPSHOT_JS)
        except Exception as e:
            raise ActionError(f"Couldn't read the page: {str(e).splitlines()[0]}")
        preview = data["text"].strip()[:1500]
        items = "\n".join(data["items"]) or "(no interactive elements found)"
        return (f"Tab {tid}: {data['title']}\nURL: {data['url']}\n\nText preview:\n{preview}\n\n"
                f"Interactive elements:\n{items}")

    def read(self, tab: int | None = None) -> str:
        tid, page = self._page(tab)
        try:
            text = page.evaluate("() => document.body ? document.body.innerText : ''")
        except Exception as e:
            raise ActionError(f"Couldn't read the page: {e}")
        text = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT] + f"\n...[{len(text) - MAX_TEXT} more characters]"
        return f"Tab {tid}: {page.title()}\n{page.url}\n\n{text or '(empty page)'}"

    def screenshot(self, tab: int | None = None) -> list:
        tid, page = self._page(tab)
        png = page.screenshot(type="png")
        img = Image.open(io.BytesIO(png))
        block, s = _image_block(img)
        self.shot_scale[tid] = s
        w, h = int(img.width * s), int(img.height * s)
        return [block, {"type": "text", "text": f"Tab {tid} screenshot, {w}x{h}: {page.title()}"}]

    def glance(self, tab: int | None = None, max_long_edge: int = 1024) -> dict | None:
        """A quick, small picture of the tab for the model to see after every
        action (no extra round trip). Returns an image block or None."""
        try:
            tid, page = self._page(tab)
            png = page.screenshot(type="jpeg", quality=60, timeout=2500, animations="allow")
        except Exception:
            return None
        img = Image.open(io.BytesIO(png))
        block, s = _image_block(img, max_long_edge)
        self.shot_scale[tid] = s
        return block

    def _ref(self, page, ref: int):
        loc = page.locator(f'[data-teto-ref="{int(ref)}"]')
        if loc.count() == 0:
            raise ActionError(f"Element [{ref}] isn't on the page anymore - take a new browser_snapshot.")
        return loc.first

    def click(self, ref: int, tab: int | None = None) -> str:
        tid, page = self._page(tab)
        el = self._ref(page, ref)
        before = page.url
        try:
            popup = el.evaluate("e => { const a = e.closest('a,form'); return !!a && a.target === '_blank'; }")
        except Exception:
            popup = False
        try:
            el.scroll_into_view_if_needed(timeout=5000)
            if popup and self.ctx is not None:      # wait for the new tab instead of a fixed sleep
                try:
                    with self.ctx.expect_page(timeout=8000) as info:
                        el.click(timeout=10000)
                    self._register(info.value)
                except Exception as e:
                    if "Timeout" not in type(e).__name__:
                        raise
            else:
                el.click(timeout=10000)
        except Exception as e:
            raise ActionError(f"Couldn't click [{ref}]: {str(e).splitlines()[0]}")
        self._settle(page)
        if self.current != tid and self.current in self.tabs:      # it opened a new tab
            new = self.tabs[self.current]
            self._settle(new)
            return f"Clicked [{ref}]; it opened tab {self.current}.\n\n" + self.snapshot(self.current)
        self.current = tid
        moved = f" Now at {page.url}." if page.url != before else ""
        return f"Clicked [{ref}].{moved}\n\n" + self.snapshot(tid)

    def click_xy(self, x: int, y: int, tab: int | None = None) -> str:
        tid, page = self._page(tab)
        s = self.shot_scale.get(tid, 1.0)
        page.mouse.click(x / s, y / s)
        self._settle(page)
        return f"Clicked at ({x}, {y}) in tab {tid}.\n\n" + self.snapshot(self.current)

    def type(self, ref: int, text: str, clear: bool = True, submit: bool = False, tab: int | None = None,
             should_stop=lambda: False) -> str:
        # In a background tab the user doesn't watch the keystrokes, so type the
        # text instantly (fill) - fast and reliable - rather than key-by-key.
        tid, page = self._page(tab)
        el = self._ref(page, ref)
        try:
            el.scroll_into_view_if_needed(timeout=4000)
            if clear:
                el.fill(text, timeout=5000)
            else:
                el.click(timeout=6000)
                page.keyboard.insert_text(text)
        except Exception as e:
            raise ActionError(f"Couldn't type into [{ref}]: {str(e).splitlines()[0]}")
        if submit:
            page.keyboard.press("Enter")
            self._settle(page)
        return f"Typed into [{ref}]{' and pressed Enter' if submit else ''}.\n\n" + self.snapshot(self.current)

    def select(self, ref: int, option: str, tab: int | None = None) -> str:
        tid, page = self._page(tab)
        el = self._ref(page, ref)
        try:
            el.select_option(label=option, timeout=8000)
        except Exception:
            try:
                el.select_option(value=option, timeout=8000)
            except Exception as e:
                raise ActionError(f"Couldn't choose {option!r} in [{ref}]: {str(e).splitlines()[0]}")
        return f"Selected {option!r} in [{ref}]."

    def press(self, keys: str, tab: int | None = None) -> str:
        tid, page = self._page(tab)
        page.keyboard.press(to_playwright_combo(keys))
        self._settle(page)
        self._scroll_done(page)
        return f"Pressed {keys} in tab {tid}."

    def write(self, text: str, tab: int | None = None) -> str:
        """Type into the focused element. Uses real key events (keyboard.type), which
        canvas editors like Google Docs require - they ignore programmatic text
        insertion and only react to actual keydown/keypress events."""
        tid, page = self._page(tab)
        page.keyboard.type(text.replace("\r\n", "\n"), delay=0)   # \n becomes a real Enter
        return f"Wrote {len(text)} characters into the focused editor in tab {tid}."

    def scroll(self, direction: str, amount: float = 1.0, tab: int | None = None) -> str:
        tid, page = self._page(tab)
        dy = (1 if direction == "down" else -1) * max(0.1, min(float(amount or 1), 20)) * 700
        page.mouse.wheel(0, dy)
        self._scroll_done(page)
        return f"Scrolled {direction} in tab {tid}.\n\n" + self.snapshot(tid)

    def navigate(self, action: str, tab: int | None = None) -> str:
        tid, page = self._page(tab)
        {"back": page.go_back, "forward": page.go_forward, "reload": page.reload}[action](timeout=30000)
        self._settle(page)
        return self.snapshot(tid)

    def close_tab(self, tab: int) -> str:
        tid, page = self._page(tab)
        page.close()
        self._forget(tid)
        return f"Closed tab {tid}."

    def show(self) -> str:
        """Re-open the browser visibly (same profile and tabs)."""
        if not self.headless and self.ctx is not None:
            for p in self.tabs.values():
                try:
                    p.bring_to_front()
                except Exception:
                    pass
            return "Teto's browser window is open."
        urls = [p.url for _, p in sorted(self.tabs.items()) if p.url not in ("about:blank", "")]
        self.close()
        self.headless = False
        self._ensure()
        first = True
        for u in urls or ["about:blank"]:
            page = self.ctx.pages[0] if first and self.ctx.pages else self.ctx.new_page()
            self._register(page)
            first = False
            try:
                page.goto(u, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
        return "Opened Teto's browser window for the user (the same tabs)."


# ----------------------------------------------------- desktop (Windows)
class BackgroundDesktop:
    """Other apps' windows through UI Automation + window messages. Runs on the UIA actor thread."""

    def __init__(self, exclude: Callable[[], set] = set):
        self.exclude = exclude
        self.elements: dict[int, dict[int, Any]] = {}
        self.shot_scale: dict[int, float] = {}
        self.web_windows: set[int] = set()     # the user's browser windows we've read as web pages
        self.last_hwnd: int | None = None

    @staticmethod
    def init_thread():
        import uiautomation  # noqa: F401  (Windows only)

        uiautomation.InitializeUIAutomationInCurrentThread()

    def _check(self, hwnd: int) -> int:
        from ctypes import wintypes

        if not platform_win.user32.IsWindow(wintypes.HWND(hwnd)):
            raise ActionError(f"Window {hwnd} doesn't exist anymore - use window_list.")
        return hwnd

    def list(self) -> str:
        rows = []
        for hwnd, l, t, r, b in platform_win.list_windows(exclude=self.exclude()):
            rows.append(f"[{hwnd}] {platform_win.window_title(hwnd)} - {platform_win.window_process(hwnd)} "
                        f"({r - l}x{b - t})")
        for hwnd, title, proc in platform_win.minimized_windows(exclude=self.exclude()):
            rows.append(f"[{hwnd}] {title} - {proc} (minimized)")
        return "\n".join(rows) or "No app windows are open."

    def screenshot(self, hwnd: int) -> list:
        self._check(hwnd)
        platform_win.restore_behind(hwnd)
        img = platform_win.capture_window(hwnd)
        if img is None:
            raise ActionError("Couldn't capture that window.")
        block, s = _image_block(img)
        self.shot_scale[hwnd] = s
        return [block, {"type": "text", "text": f"Window {hwnd} ({platform_win.window_title(hwnd)}), "
                                                f"{int(img.width * s)}x{int(img.height * s)}."}]

    USEFUL = {"ButtonControl", "EditControl", "CheckBoxControl", "RadioButtonControl", "ComboBoxControl",
              "ListItemControl", "MenuItemControl", "TabItemControl", "HyperlinkControl", "TreeItemControl",
              "DocumentControl", "DataItemControl", "SplitButtonControl", "SliderControl", "SpinnerControl",
              "TextControl", "MenuBarControl", "HeaderItemControl"}

    def _collect(self, root, max_depth: int = 14, max_refs: int = 300, seconds: float = 6.0,
                 skip_root: bool = False, offscreen: bool = False):
        import uiautomation as auto

        refs: dict[int, Any] = {}
        lines = []
        frontier = [(root, 0)]
        visited = 0
        deadline = time.monotonic() + seconds
        while frontier and visited < 4000 and len(refs) < max_refs and time.monotonic() < deadline:
            ctrl, depth = frontier.pop() if offscreen else frontier.pop(0)   # web: reading order
            visited += 1
            try:
                kind = ctrl.ControlTypeName
                name = (ctrl.Name or "").strip().replace("\n", " ")[:80]
                hidden = ctrl.IsOffscreen
                if (kind in self.USEFUL and not (kind == "TextControl" and not name)
                        and (offscreen or not hidden) and not (skip_root and depth == 0)):
                    n = len(refs) + 1
                    refs[n] = ctrl
                    extra = ""
                    vp = ctrl.GetPattern(auto.PatternId.ValuePattern)
                    if vp is not None:
                        try:
                            v = (vp.Value or "")[:60]
                            extra = f' value="{v}"' if v else ""
                        except Exception:
                            pass
                    tp = ctrl.GetPattern(auto.PatternId.TogglePattern)
                    if tp is not None:
                        try:
                            extra += " [x]" if tp.ToggleState == 1 else " [ ]"
                        except Exception:
                            pass
                    off = ("" if ctrl.IsEnabled else " (disabled)") + (" (scrolled off)" if hidden else "")
                    lines.append(f"[{n}] {kind.replace('Control', '')} \"{name}\"{extra}{off}")
                if depth < max_depth:
                    kids = [(c, depth + 1) for c in ctrl.GetChildren()]
                    frontier.extend(reversed(kids) if offscreen else kids)
            except Exception:
                continue
        return refs, lines

    def elements_list(self, hwnd: int) -> str:
        import uiautomation as auto

        self._check(hwnd)
        root = auto.ControlFromHandle(hwnd)
        if root is None:
            raise ActionError("UI Automation can't see inside that window.")
        refs, lines = self._collect(root)
        self.elements[hwnd] = refs
        return (f"Window {hwnd}: {platform_win.window_title(hwnd)}\n" + ("\n".join(lines) or
                "(no controls exposed - try window_screenshot + window_click_xy)"))

    # ------------------------------------- the user's own, already-open tabs
    def browser_windows(self) -> list[int]:
        """The user's browser windows: on-screen ones topmost first, then minimized ones."""
        ex = self.exclude()
        wins = [h for h, *_ in platform_win.list_windows(exclude=ex)
                if platform_win.window_process(h).lower() in BROWSER_EXES]
        wins += [h for h, _t, proc in platform_win.minimized_windows(exclude=ex)
                 if (proc or "").lower() in BROWSER_EXES and h not in wins]
        return wins

    def screen_browser(self) -> int:
        """The browser window the user is looking at (or last looked at)."""
        wins = self.browser_windows()
        if not wins:
            raise ActionError("I don't see an Edge/Chrome window open.")
        return wins[0]

    def _chrome_parts(self, root):
        """Tab strip items and the address bar, without walking into the page."""
        tabs, address = [], None
        frontier = [(root, 0)]
        deadline = time.monotonic() + 3
        while frontier and time.monotonic() < deadline:
            ctrl, depth = frontier.pop(0)
            try:
                kind = ctrl.ControlTypeName
                if kind == "DocumentControl":
                    continue                       # page content: not part of the browser frame
                if kind == "TabItemControl":
                    tabs.append(ctrl)
                elif kind == "EditControl" and address is None and "address" in (ctrl.Name or "").lower():
                    address = ctrl
                if depth < 16:
                    frontier.extend((c, depth + 1) for c in ctrl.GetChildren())
            except Exception:
                continue
        return tabs, address

    def _page_document(self, root):
        frontier = [(root, 0)]
        deadline = time.monotonic() + 3
        while frontier and time.monotonic() < deadline:
            ctrl, depth = frontier.pop(0)
            try:
                if ctrl.ControlTypeName == "DocumentControl":
                    return ctrl
                if depth < 20:
                    frontier.extend((c, depth + 1) for c in ctrl.GetChildren())
            except Exception:
                continue
        return None

    @staticmethod
    def _selected(tab) -> bool:
        import uiautomation as auto

        try:
            sp = tab.GetPattern(auto.PatternId.SelectionItemPattern)
            return bool(sp and sp.IsSelected)
        except Exception:
            return False

    def _find_tab(self, want: str):
        """(hwnd, root) of the user's window holding the tab `want`, with that tab
        brought to the front. Searches all their browser windows."""
        import uiautomation as auto

        everything = []
        for k, hwnd in enumerate(self.browser_windows()):
            root = auto.ControlFromHandle(hwnd)
            if root is None:
                continue
            tabs, _ = self._chrome_parts(root)
            names = [((t.Name or "").strip(), False) for t in tabs]
            everything += [n for n, _ in names]
            i = pick_tab(names, want) if (k == 0 or not want.isdigit()) else None   # numbers: the front window
            if i is None:
                continue
            if not self._selected(tabs[i]):
                before = platform_win.window_title(hwnd)
                pat = tabs[i].GetPattern(auto.PatternId.SelectionItemPattern)
                if pat is None or not pat.Select():
                    raise ActionError("Couldn't bring that tab to the front.")
                end = time.monotonic() + 1.5           # until the window shows that page
                while time.monotonic() < end and platform_win.window_title(hwnd) == before:
                    time.sleep(0.03)
            return hwnd, root
        raise ActionError(f"No open tab matching {want!r}. Your tabs: " + "; ".join(everything))

    def _window(self, want: str = ""):
        import uiautomation as auto

        if want:
            hwnd, root = self._find_tab(want)
        else:
            hwnd = self.screen_browser()
            root = auto.ControlFromHandle(hwnd)
            if root is None:
                raise ActionError("UI Automation can't see inside your browser window.")
        self._wake(hwnd, root)
        return hwnd, root

    def _wake(self, hwnd: int, root) -> None:
        """Edge only builds a page's accessibility tree on request, and drops it
        for minimized windows: un-minimize it behind everything (no focus change),
        ask Chromium to turn accessibility on, then wait for the page to appear."""
        platform_win.restore_behind(hwnd)
        platform_win.wake_chromium_accessibility(hwnd)
        end = time.monotonic() + 2.5
        while time.monotonic() < end:
            doc = self._page_document(root)
            try:
                if doc is not None and doc.GetChildren():
                    return
            except Exception:
                pass
            time.sleep(0.1)

    def _url(self, address) -> str:
        import uiautomation as auto

        if address is None:
            return ""
        try:
            vp = address.GetPattern(auto.PatternId.ValuePattern)
            return normalize_url(vp.Value if vp is not None else "")
        except Exception:
            return ""

    def screen_tab_url(self, switch_to: str = "") -> tuple[int, str, str]:
        """(hwnd, url, title) of the user's tab."""
        hwnd, root = self._window(switch_to)
        _tabs, address = self._chrome_parts(root)
        return hwnd, self._url(address), platform_win.window_title(hwnd)

    def _visible_text(self, doc, limit: int = 4000) -> str:
        import uiautomation as auto

        try:
            tp = doc.GetPattern(auto.PatternId.TextPattern)
            if tp is None:
                return ""
            try:
                ranges = tp.GetVisibleRanges() or []
                text = "\n".join((r.GetText(-1) or "") for r in ranges).strip()
            except Exception:
                text = ""
            return (text or (tp.DocumentRange.GetText(limit) or "")).strip()[:limit]
        except Exception:
            return ""

    def tab_state(self, hwnd: int, root=None, header: bool = True) -> str:
        import uiautomation as auto

        root = root or auto.ControlFromHandle(hwnd)
        tabs, address = self._chrome_parts(root)
        out = []
        if header:
            rows = [f"{'*' if self._selected(t) else ' '} {n}. {(t.Name or '').strip()[:70]}"
                    for n, t in enumerate(tabs, 1)]
            out += [f"Your browser: window {hwnd} ({platform_win.window_process(hwnd)})",
                    f"Showing tab: {platform_win.window_title(hwnd)}", f"URL: {self._url(address) or '(unknown)'}"]
            if rows:
                out.append("Tabs in this window (* = showing):\n" + "\n".join(rows))
        doc = self._page_document(root)
        lines = []
        if doc is not None:
            text = self._visible_text(doc)
            if text:
                out.append("What's visible on the page:\n" + text)
            refs, lines = self._collect(doc, max_depth=45, max_refs=250, seconds=4.0, skip_root=True,
                                        offscreen=True)
            self.elements[hwnd] = refs
        self.web_windows.add(hwnd)
        out.append("Page elements - act on them with window_click / window_type, window=%d:\n" % hwnd
                   + ("\n".join(lines) or "(the page exposes no elements)"))
        return "\n\n".join(out)

    def screen_tab(self, switch_to: str = "") -> str:
        hwnd, root = self._window(switch_to)
        self.last_hwnd = hwnd
        return self.tab_state(hwnd, root)

    def list_tabs_text(self) -> str:
        import uiautomation as auto

        rows = []
        for hwnd in self.browser_windows():
            root = auto.ControlFromHandle(hwnd)
            if root is None:
                continue
            tabs, _ = self._chrome_parts(root)
            for t in tabs:
                rows.append(f"{'*' if self._selected(t) else ' '} {(t.Name or '').strip()[:80]}  (window {hwnd})")
        return "Your open tabs (* = showing in its window):\n" + ("\n".join(rows) or "(none found)")

    def _after(self, hwnd: int, msg: str) -> str:
        """After acting in one of the user's web tabs, show the page's new state
        right away so the model doesn't spend a turn re-reading it."""
        if hwnd not in self.web_windows:
            return msg
        time.sleep(0.12)                             # let the page react to the click
        try:
            return msg + "\n\n" + self.tab_state(hwnd, header=False)
        except Exception:
            return msg

    def _el(self, hwnd: int, ref: int):
        ctrl = self.elements.get(hwnd, {}).get(int(ref))
        if ctrl is None:
            raise ActionError(f"No control [{ref}] for window {hwnd} - call window_elements first.")
        return ctrl

    def click(self, hwnd: int, ref: int) -> str:
        import uiautomation as auto

        self._check(hwnd)
        ctrl = self._el(hwnd, ref)
        P = auto.PatternId
        try:
            if ctrl.IsOffscreen:
                sp = ctrl.GetPattern(P.ScrollItemPattern)
                if sp is not None:
                    sp.ScrollIntoView()
        except Exception:
            pass
        # Web pages often make a <div> clickable around the text: if the element
        # itself has no action, its nearest actionable parent gets it.
        chain, node = [ctrl], ctrl
        for _ in range(3):
            try:
                node = node.GetParentControl()
            except Exception:
                node = None
            if node is None or node.ControlTypeName in ("DocumentControl", "WindowControl", "PaneControl"):
                break
            chain.append(node)
        for target in chain:
            for pid, method in ((P.InvokePattern, "Invoke"), (P.SelectionItemPattern, "Select"),
                                (P.TogglePattern, "Toggle"), (P.ExpandCollapsePattern, "Expand"),
                                (P.LegacyIAccessiblePattern, "DoDefaultAction")):
                pat = target.GetPattern(pid)
                if pat is not None:
                    try:
                        if getattr(pat, method)() is False:
                            continue
                        return self._after(hwnd, f"Activated [{ref}] ({method}).")
                    except Exception:
                        continue
        rect = ctrl.BoundingRectangle
        cx, cy = (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
        if not platform_win.post_click(hwnd, cx, cy):
            raise ActionError(f"Control [{ref}] can't be pressed in the background.")
        return self._after(hwnd, f"Sent a click to [{ref}].")

    def click_xy(self, hwnd: int, x: int, y: int, double: bool = False) -> str:
        self._check(hwnd)
        s = self.shot_scale.get(hwnd, 1.0)
        left, top = platform_win.window_origin(hwnd)
        if not platform_win.post_click(hwnd, left + int(x / s), top + int(y / s), double=double):
            raise ActionError("That window didn't accept a background click.")
        return f"Sent a {'double-' if double else ''}click at ({x}, {y}) to window {hwnd}."

    def type(self, hwnd: int, ref: int, text: str, mode: str = "replace") -> str:
        import uiautomation as auto

        self._check(hwnd)
        ctrl = self._el(hwnd, ref)
        vp = ctrl.GetPattern(auto.PatternId.ValuePattern)
        if vp is not None:
            new = text if mode != "append" else (vp.Value or "") + text
            if vp.SetValue(new):
                return self._after(hwnd, f"Set the text of [{ref}].")
        native = ctrl.NativeWindowHandle
        if native and platform_win.post_text(native, text, replace=(mode != "append")):
            return f"Typed into [{ref}]."
        raise ActionError(f"Control [{ref}] doesn't accept text in the background.")

    def key(self, hwnd: int, keys: str) -> str:
        self._check(hwnd)
        names = parse_combo(keys)
        if len(names) != 1 or not platform_win.post_key(platform_win.focus_child(hwnd), names[0]):
            raise ActionError("Only single keys like Return, Tab, Escape or arrows can be sent in the background.")
        return f"Sent {keys} to window {hwnd}."

    def scroll(self, hwnd: int, direction: str, ref: int | None = None) -> str:
        import uiautomation as auto

        self._check(hwnd)
        if ref is not None:
            sp = self._el(hwnd, ref).GetPattern(auto.PatternId.ScrollPattern)
            if sp is not None:
                amount = auto.ScrollAmount.LargeIncrement if direction == "down" else auto.ScrollAmount.LargeDecrement
                sp.Scroll(auto.ScrollAmount.NoAmount, amount)
                return f"Scrolled [{ref}] {direction}."
        platform_win.post_scroll(hwnd, direction)
        return f"Scrolled window {hwnd} {direction}."


# -------------------------------------------------------------- facade
class BackgroundTools:
    """What the brains call. Thread-safe; creates the browser lazily."""

    def __init__(self, profile_dir: str, settings: Callable[[], dict], exclude: Callable[[], set] = set,
                 link=None):
        from . import link as link_mod
        from .mytabs import UserTabs

        self.settings = settings
        self.profile_dir = profile_dir
        self.exclude = exclude
        self.link = link if link is not None else link_mod.shared()
        self.user_tabs = UserTabs(self.link, self._d if IS_WINDOWS else None, settings)
        self._browser: BackgroundBrowser | None = None
        self._browser_actor: Actor | None = None
        self._desktop: BackgroundDesktop | None = None
        self._desktop_actor: Actor | None = None
        self._lock = threading.Lock()

    def specs(self) -> dict[str, tuple[str, dict]]:
        from .mytabs import MY_TAB_SPECS

        return {**MY_TAB_SPECS, **available_specs()}

    def _b(self):
        with self._lock:
            if self._browser is None:
                s = self.settings()
                self._browser = BackgroundBrowser(self.profile_dir, headless=not s.get("show_browser", False),
                                                  browser_path=s.get("browser_path", ""),
                                                  prefer_real=bool(s.get("prefer_real_browser", False)),
                                                  may_close_browser=bool(s.get("autonomous", False)),
                                                  typing=lambda: (self.settings().get("human_typing", True),
                                                                  self.settings().get("typing_wpm", 90),
                                                                  self.settings().get("typos", True)))
                self._browser_actor = Actor("teto-browser")
            return self._browser, self._browser_actor

    def _d(self):
        if not IS_WINDOWS:
            raise ActionError("Background desktop control is only available on Windows.")
        with self._lock:
            if self._desktop is None:
                self._desktop = BackgroundDesktop(self.exclude)
                self._desktop_actor = Actor("teto-uia", init=BackgroundDesktop.init_thread)
            return self._desktop, self._desktop_actor

    def run(self, name: str, a: dict, should_stop=lambda: False):
        """Returns a string or a list of content blocks (Anthropic format)."""
        if name.startswith("my_tab") or name == "browser_screen_tab":
            if name == "browser_screen_tab":                     # older name
                name, a = "my_tab_read", {"tab": a.get("switch_to", "")}
            return self.user_tabs.run(name, a)
        if name in SCREEN_TAB_SPECS:
            return self._screen_tab_tool(name, a, should_stop)
        if name.startswith("browser_"):
            b, act = self._b()
            tab = a.get("tab")
            calls = {
                "browser_use_my_browser": b.attach,
                "browser_open": lambda: b.open(str(a.get("url", "")), a.get("new_tab", True) is not False,
                                               (None if a.get("own_browser") is None else bool(a.get("own_browser")))),
                "browser_tabs": b.list_tabs,
                "browser_snapshot": lambda: b.snapshot(tab),
                "browser_read": lambda: b.read(tab),
                "browser_screenshot": lambda: b.screenshot(tab),
                "browser_click": lambda: b.click(int(a["ref"]), tab),
                "browser_click_xy": lambda: b.click_xy(int(a["x"]), int(a["y"]), tab),
                "browser_type": lambda: b.type(int(a["ref"]), str(a.get("text", "")), a.get("clear", True) is not False,
                                               bool(a.get("submit", False)), tab, should_stop),
                "browser_select": lambda: b.select(int(a["ref"]), str(a.get("option", "")), tab),
                "browser_press": lambda: b.press(str(a.get("keys", "")), tab),
                "browser_write": lambda: b.write(str(a.get("text", "")), tab),
                "browser_scroll": lambda: b.scroll(str(a.get("direction", "down")), a.get("amount", 1), tab),
                "browser_navigate": lambda: b.navigate(str(a.get("action", "reload")), tab),
                "browser_close_tab": lambda: b.close_tab(int(a["tab"])),
                "browser_show": b.show,
            }
        elif name.startswith("window_"):
            d, act = self._d()
            w = int(a.get("window", 0) or 0)
            calls = {
                "window_list": d.list,
                "window_screenshot": lambda: d.screenshot(w),
                "window_elements": lambda: d.elements_list(w),
                "window_click": lambda: d.click(w, int(a["ref"])),
                "window_click_xy": lambda: d.click_xy(w, int(a["x"]), int(a["y"]), bool(a.get("double", False))),
                "window_type": lambda: d.type(w, int(a["ref"]), str(a.get("text", "")), a.get("mode", "replace")),
                "window_key": lambda: d.key(w, str(a.get("keys", ""))),
                "window_scroll": lambda: d.scroll(w, str(a.get("direction", "down")), a.get("ref")),
            }
        else:
            raise ActionError(f"Unknown background tool {name}")
        if name not in calls:
            raise ActionError(f"Unknown background tool {name}")
        try:
            out = act.call(calls[name], should_stop=should_stop)
        except KeyError as e:
            raise ActionError(f"Missing argument {e}")
        if (name in self.SEE_AFTER and isinstance(out, str)
                and self.settings().get("auto_screenshots", False)):
            px = int(self.settings().get("screenshot_px", 1024) or 1024)
            img = act.call(lambda: b.glance(None, px), should_stop=should_stop)
            if img is not None:
                return [{"type": "text", "text": out}, img]
        return out

    def _screen_tab_tool(self, name: str, a: dict, should_stop):
        d, dact = self._d()
        want = str(a.get("switch_to", "") or "")
        if name == "browser_screen_tab":
            out = dact.call(lambda: d.screen_tab(want), should_stop=should_stop)
            if self.settings().get("auto_screenshots", False):
                try:
                    hwnd = dact.call(d.screen_browser, should_stop=should_stop)
                    shot = dact.call(lambda: d.screenshot(hwnd), should_stop=should_stop)
                    return [{"type": "text", "text": out}, *shot]
                except ActionError:
                    pass
            return out
        hwnd, url, title = dact.call(lambda: d.screen_tab_url(want), should_stop=should_stop)
        if not url.startswith(("http://", "https://")):
            raise ActionError(f"The tab on your screen ({title}) has no web address I can open.")
        out = self.run("browser_open", {"url": url}, should_stop)
        note = f"Took your on-screen tab ({title}) into my Edge - same page, same account.\n"
        if isinstance(out, list):
            return [{"type": "text", "text": note + out[0]["text"]}, *out[1:]]
        return note + out

    # browser actions that come back with a fresh picture of the tab
    SEE_AFTER = {"browser_open", "browser_click", "browser_click_xy", "browser_type", "browser_press",
                 "browser_write", "browser_scroll", "browser_navigate", "browser_select"}

    def shutdown(self):
        with self._lock:
            if self._browser_actor:
                try:
                    self._browser_actor.call(self._browser.close, timeout=15)
                except Exception:
                    pass
                self._browser_actor.stop()
            if self._desktop_actor:
                self._desktop_actor.stop()
            self._browser = self._browser_actor = self._desktop = self._desktop_actor = None


def work_style_prompt(style: str, has_background: bool) -> str:
    """The system-prompt section that tells Claude how to share the PC with the user."""
    if not has_background:
        return ""
    desktop = ("- Desktop apps: window_list, then window_elements to read a window's controls and window_click / "
               "window_type to operate them, and window_screenshot to see a window even when it is behind others. "
               "Launch apps with open_target (they open minimised, without stealing focus).\n") if IS_WINDOWS else ""
    if style == "background":
        return ("Working alongside the user (IMPORTANT): the user keeps using their PC while you work, so work in "
                "the background and never wait for them:\n"
                "- Only when the user explicitly asks for something new (a new tab, a website, a search, a new "
                "doc): browser_open opens a background tab in your copy of their signed-in Edge (minimized, no focus stealing - they can keep gaming). Their Google/Microsoft/school "
                "accounts are already signed in, so just go.\n"
                + "- THE USER'S OWN TABS COME FIRST (hard rule): if the task is about anything they already have "
                  "open (a quiz, test, form, email, document, 'this page', 'my tab'), do it IN THAT TAB: "
                  "my_tab_read (tab: part of its title, or empty for the one they're looking at), then "
                  "my_tab_click / my_tab_type / my_tab_select / my_tab_key / my_tab_scroll. Every action returns "
                  "the page's new state - read it and keep going (answer, Next, answer...). NEVER open a new tab, "
                  "a copy of their tab, or a search unless the user asked for that; it is blocked anyway.\n"
                "- After every browser action you get the page's numbered elements AND a picture of the tab. Look "
                "at both and keep going - no separate screenshot call needed.\n"
                "- If a page still returns a [SIGN-IN NEEDED] note, tell the user in one line and keep doing any "
                "other part of the task meanwhile; re-snapshot after.\n"
                "- Google Docs/Sheets/Slides: to CREATE a new Google Doc open "
                "'https://docs.google.com/document/create' (Sheets: '.../spreadsheets/create', Slides: "
                "'.../presentation/create'). A Google Doc is a canvas editor: click into the body, then use "
                "browser_write to type the content. It autosaves; give the user the URL when done.\n"
                + desktop +
                "- Files, settings and information: run_shell.\n"
                "- The real mouse/keyboard/screenshot tools act on the user's screen: do NOT take over their mouse and "
                "keyboard unless a job truly can't be done in a background tab or window.\n"
                "Pace: go, go, go. Chain actions back to back with no waits and no check-ins; you have full "
                "permission, so never ask \"should I?\" - just do it and report when done.")
    return ("Background tools: besides the real mouse and keyboard, you have your own background browser "
            "(browser_*)" + (" and background desktop control (window_*)" if IS_WINDOWS else "") +
            ". Prefer them when they are more reliable, e.g. browser_snapshot + browser_click for web pages.")
