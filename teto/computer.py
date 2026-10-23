"""Executes Claude's computer-toolset actions on the real desktop.

Implements all 17 members of `computer_toolset_20260801`:
screenshot, zoom, left_click, right_click, middle_click, double_click,
triple_click, left_click_drag, mouse_move, left_mouse_down, left_mouse_up,
cursor_position, scroll, type, key, hold_key, wait.

Coordinates from Claude are in the pixel space of the (possibly downscaled)
screenshots we send; they are mapped back to real screen pixels here.
"""

from __future__ import annotations

import base64
import io
import math
import random
import time
from dataclasses import dataclass
from typing import Callable

from PIL import Image, ImageDraw

from . import humanize, platform_win

MAX_VISUAL_TOKENS = 4784          # Opus 4.7+ image limit (ceil(w/28) * ceil(h/28))
MAX_LONG_EDGE = 2576


class ActionError(Exception):
    """An action failed; the message is returned to Claude as an error result."""


class UserAbort(Exception):
    """The user asked Teto to stop (stop button, hotkey or mouse-in-corner)."""


# ------------------------------------------------------------- key mapping
_KEY_ALIASES = {
    "return": "enter", "enter": "enter", "kp_enter": "enter",
    "escape": "esc", "esc": "esc",
    "backspace": "backspace", "back_space": "backspace",
    "tab": "tab", "iso_left_tab": "tab", "space": "space",
    "delete": "delete", "del": "delete", "kp_delete": "delete",
    "insert": "insert", "ins": "insert",
    "home": "home", "kp_home": "home", "end": "end", "kp_end": "end",
    "page_up": "pageup", "pageup": "pageup", "prior": "pageup", "pgup": "pageup",
    "page_down": "pagedown", "pagedown": "pagedown", "next": "pagedown", "pgdn": "pagedown",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "kp_up": "up", "kp_down": "down", "kp_left": "left", "kp_right": "right",
    "ctrl": "ctrl", "control": "ctrl", "control_l": "ctrlleft", "control_r": "ctrlright",
    "ctrl_l": "ctrlleft", "ctrl_r": "ctrlright",
    "alt": "alt", "alt_l": "altleft", "alt_r": "altright", "option": "alt",
    "shift": "shift", "shift_l": "shiftleft", "shift_r": "shiftright",
    "super": "win", "super_l": "winleft", "super_r": "winright", "win": "win",
    "windows": "win", "meta": "win", "cmd": "win", "command": "win",
    "menu": "apps", "apps": "apps",
    "print": "printscreen", "printscreen": "printscreen", "prtsc": "printscreen",
    "caps_lock": "capslock", "capslock": "capslock",
    "num_lock": "numlock", "scroll_lock": "scrolllock", "pause": "pause",
    "minus": "-", "plus": "+", "equal": "=", "equals": "=", "comma": ",",
    "period": ".", "dot": ".", "slash": "/", "backslash": "\\", "semicolon": ";",
    "apostrophe": "'", "quote": "'", "grave": "`", "backtick": "`",
    "bracketleft": "[", "bracketright": "]", "asterisk": "*",
    "xf86audiomute": "volumemute", "xf86audioraisevolume": "volumeup",
    "xf86audiolowervolume": "volumedown", "xf86audioplay": "playpause",
    "xf86audionext": "nexttrack", "xf86audioprev": "prevtrack",
    "volumeup": "volumeup", "volumedown": "volumedown", "volumemute": "volumemute",
}
for _i in range(1, 25):
    _KEY_ALIASES[f"f{_i}"] = f"f{_i}"
for _i in range(10):
    _KEY_ALIASES[f"kp_{_i}"] = f"num{_i}"

_MODIFIERS = {"ctrl", "ctrlleft", "ctrlright", "alt", "altleft", "altright",
              "shift", "shiftleft", "shiftright", "win", "winleft", "winright"}


def parse_combo(text: str) -> list[str]:
    """'ctrl+shift+Escape' -> ['ctrl', 'shift', 'esc'];  'ctrl++' -> ['ctrl', '+']."""
    if not isinstance(text, str) or not text.strip():
        raise ActionError("key: 'text' must be a non-empty key name such as 'Return' or 'ctrl+s'")
    raw = text.strip()
    if raw == "+":
        parts = ["+"]
    else:
        parts = raw.split("+")
        if raw.endswith("++"):
            parts = parts[:-2] + ["+"]
        elif raw.endswith("+"):
            parts = parts[:-1] + ["+"]
        parts = [p.strip() for p in parts if p.strip() != ""]
    keys = []
    for p in parts:
        low = p.lower()
        if low in _KEY_ALIASES:
            keys.append(_KEY_ALIASES[low])
        elif len(p) == 1:
            keys.append(p.lower())
        else:
            raise ActionError(f"Unknown key name: {p!r}")
    if not keys:
        raise ActionError(f"Could not parse key combination {text!r}")
    return keys


def modifier_keys(text: str | None) -> list[str]:
    if not text:
        return []
    keys = parse_combo(text)
    for k in keys:
        if k not in _MODIFIERS:
            raise ActionError(f"Mouse modifier must be shift/ctrl/alt/super, got {k!r}")
    return keys


RISKY_COMBOS = [
    {"shift", "delete"},            # permanent delete, skips the Recycle Bin
    {"ctrl", "shift", "delete"},
]


def visual_tokens(w: int, h: int) -> int:
    return math.ceil(w / 28) * math.ceil(h / 28)


def fit_scale(w: int, h: int, max_long_edge: int) -> float:
    """Scale factor (<= 1) so the screenshot fits the model's image limits."""
    long_edge = min(max_long_edge, MAX_LONG_EDGE)
    s = min(1.0, long_edge / max(w, h))
    while visual_tokens(int(w * s), int(h * s)) > MAX_VISUAL_TOKENS:
        s *= 0.97
    return s


# ---------------------------------------------------------------- backends
class InputBackend:
    """Real mouse/keyboard via pyautogui (+ native Win32 for text/scroll).

    With `human=True` the pointer glides along curved paths and typing has a
    natural rhythm with the odd self-corrected typo (see humanize.py)."""

    def __init__(self, human: bool = True, wpm: float = 90.0, typos: bool = True):
        import pyautogui  # imported lazily: needs a display

        pyautogui.FAILSAFE = False   # we implement a smarter corner-abort ourselves
        pyautogui.PAUSE = 0.0
        self.pg = pyautogui
        self.human, self.wpm, self.typos = human, wpm, typos
        self.fast = False            # True in Eagle Eyes / games: direct, snappy input
        self.rng = random.Random()

    def _human_now(self) -> bool:
        return self.human and not self.fast

    def position(self) -> tuple[int, int]:
        p = self.pg.position()
        return int(p[0]), int(p[1])

    def _glide(self, x, y):
        x0, y0 = self.position()
        pts, duration = humanize.mouse_path(x0, y0, x, y, self.rng)
        if not pts:
            return
        pause = duration / len(pts)
        for px, py in pts:
            self.pg.moveTo(px, py, _pause=False)
            time.sleep(pause)

    def move(self, x, y, duration=0.0):
        if self._human_now():
            self._glide(x, y)
        else:
            self.pg.moveTo(x, y, _pause=False)

    def click(self, x, y, button="left", clicks=1):
        if self._human_now():
            self._glide(x, y)
            time.sleep(self.rng.uniform(0.03, 0.09))          # settle before pressing
            self.pg.click(x=x, y=y, button=button, clicks=clicks, interval=self.rng.uniform(0.07, 0.12))
        else:
            self.pg.moveTo(x, y, _pause=False)
            self.pg.click(x=x, y=y, button=button, clicks=clicks, interval=0.02)

    def mouse_down(self, button="left"):
        self.pg.mouseDown(button=button, _pause=False)

    def mouse_up(self, button="left"):
        self.pg.mouseUp(button=button, _pause=False)

    def key_down(self, key):
        if platform_win.IS_WINDOWS and platform_win.key_scancode(key, keyup=False):
            return                                            # hardware scan code (works in games)
        self.pg.keyDown(key)

    def key_up(self, key):
        if platform_win.IS_WINDOWS and platform_win.key_scancode(key, keyup=True):
            return
        self.pg.keyUp(key)

    def hotkey(self, keys):
        if platform_win.IS_WINDOWS and platform_win.press_scancodes(list(keys)):
            return
        self.pg.hotkey(*keys, interval=0.0)

    def scroll(self, dx_clicks: int, dy_clicks: int, x: int, y: int):
        if platform_win.IS_WINDOWS:
            platform_win.wheel(dx_clicks, dy_clicks)
        else:
            if dy_clicks:
                self.pg.scroll(dy_clicks, x=x, y=y)
            if dx_clicks:
                self.pg.hscroll(dx_clicks, x=x, y=y)

    def _send_char(self, ch: str):
        if platform_win.IS_WINDOWS:
            platform_win.type_unicode(ch, interval=0)
        elif ch == "\n":
            self.pg.press("enter")
        elif ch == "\t":
            self.pg.press("tab")
        elif ch.isascii():
            self.pg.write(ch, _pause=False)
        else:
            raise ActionError("Non-ASCII typing is only supported on Windows")

    def type_text(self, text: str, should_stop):
        if not self._human_now():
            plan = [("char", ch, 0.0) for ch in text]
        else:
            plan = humanize.plan_typing(text, self.rng, wpm=self.wpm, typos=self.typos)
        for step in plan:
            delay = step[-1]
            end = time.monotonic() + delay
            while True:                                   # interruptible wait
                if should_stop():
                    raise UserAbort()
                left = end - time.monotonic()
                if left <= 0:
                    break
                time.sleep(min(0.05, left))
            if step[0] == "char":
                self._send_char(step[1])
            else:
                self.pg.press("backspace", _pause=False)


def _mss():
    import mss

    return getattr(mss, "MSS", None) or mss.mss   # mss>=10 renamed the class


class ScreenBackend:
    """Screen capture via mss (a fresh instance per call: mss is thread-local)."""

    def __init__(self, monitor_index: int = 1):
        self.monitor_index = monitor_index

    def monitor(self) -> dict:
        with _mss()() as sct:
            mons = sct.monitors
            idx = self.monitor_index if 0 < self.monitor_index < len(mons) else 1
            m = mons[idx]
            return {"left": m["left"], "top": m["top"], "width": m["width"], "height": m["height"]}

    def grab(self, region: dict) -> Image.Image:
        with _mss()() as sct:
            shot = sct.grab(region)
            return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


# ---------------------------------------------------------------- computer
@dataclass
class Hooks:
    """Callbacks into the UI layer (all optional)."""
    should_stop: Callable[[], bool] = lambda: False
    before_pointer: Callable[[int, int], None] = lambda x, y: None   # dodge our windows
    focus_is_ours: Callable[[], bool] = lambda: False
    confirm: Callable[[str, str], bool] = lambda title, detail: True
    # Called before real mouse/keyboard input with the time Teto's own last input
    # ended, so the app can wait for a pause in the user's own activity.
    before_input: Callable[[float], None] = lambda last_ours: None


INPUT_ACTIONS = {"left_click", "right_click", "middle_click", "double_click", "triple_click", "left_click_drag",
                 "mouse_move", "left_mouse_down", "left_mouse_up", "scroll", "type", "key", "hold_key"}


class Computer:
    def __init__(self, hooks: Hooks | None = None, max_long_edge: int = 1568,
                 monitor_index: int = 1, inputs=None, screen=None,
                 confirm_risky_keys: bool = True, human: bool = True, wpm: float = 90.0,
                 typos: bool = True):
        self.hooks = hooks or Hooks()
        self.max_long_edge = max_long_edge
        self.base_long_edge = max_long_edge        # restored after Eagle Eyes
        self.screen = screen or ScreenBackend(monitor_index)
        self.inputs = inputs or InputBackend(human=human, wpm=wpm, typos=typos)
        self.confirm_risky_keys = confirm_risky_keys
        self.scale = 1.0
        self.mon = self.screen.monitor()
        self._update_scale()
        self._last_cursor: tuple[int, int] | None = None
        self._last_input = 0.0

    # ----------------------------------------------------------- geometry
    def _update_scale(self):
        self.mon = self.screen.monitor()
        self.scale = fit_scale(self.mon["width"], self.mon["height"], self.max_long_edge)

    @property
    def shot_size(self) -> tuple[int, int]:
        return (max(1, int(self.mon["width"] * self.scale)),
                max(1, int(self.mon["height"] * self.scale)))

    def to_screen(self, coord) -> tuple[int, int]:
        if (not isinstance(coord, (list, tuple)) or len(coord) != 2
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in coord)):
            raise ActionError(f"coordinate must be [x, y] numbers, got {coord!r}")
        sw, sh = self.shot_size
        x, y = coord
        if not (0 <= x <= sw and 0 <= y <= sh):
            raise ActionError(f"coordinate {list(coord)} is outside the screenshot ({sw}x{sh})")
        rx = self.mon["left"] + int(round(x / self.scale))
        ry = self.mon["top"] + int(round(y / self.scale))
        rx = min(max(rx, self.mon["left"]), self.mon["left"] + self.mon["width"] - 1)
        ry = min(max(ry, self.mon["top"]), self.mon["top"] + self.mon["height"] - 1)
        return rx, ry

    def to_shot(self, sx: int, sy: int) -> tuple[int, int]:
        return (int((sx - self.mon["left"]) * self.scale), int((sy - self.mon["top"]) * self.scale))

    # ------------------------------------------------------------- safety
    def _check_user_abort(self):
        """Abort if the user pressed stop, or flung the mouse into a corner
        (only counts when the cursor isn't where Teto last left it)."""
        if self.hooks.should_stop():
            raise UserAbort()
        try:
            x, y = self.inputs.position()
        except Exception:
            return
        if self._last_cursor is not None:
            lx, ly = self._last_cursor
            moved_by_user = abs(x - lx) > 40 or abs(y - ly) > 40
            m = self.mon
            corners = [(m["left"], m["top"]), (m["left"] + m["width"] - 1, m["top"]),
                       (m["left"], m["top"] + m["height"] - 1),
                       (m["left"] + m["width"] - 1, m["top"] + m["height"] - 1)]
            in_corner = any(abs(x - cx) <= 2 and abs(y - cy) <= 2 for cx, cy in corners)
            if moved_by_user and in_corner:
                raise UserAbort()

    def _remember_cursor(self):
        try:
            self._last_cursor = self.inputs.position()
        except Exception:
            self._last_cursor = None

    def _guard_keyboard(self):
        if self.hooks.focus_is_ours():
            raise ActionError("Keyboard focus is on Teto's own chat window, which is hidden from "
                              "your screenshots. Click on the target window first, then type.")

    def _sleep(self, seconds: float):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.hooks.should_stop():
                raise UserAbort()
            time.sleep(max(0.0, min(0.1, end - time.monotonic())))

    # -------------------------------------------------------- screenshots
    def capture(self) -> Image.Image:
        self._update_scale()
        img = self.screen.grab(self.mon)
        w, h = self.shot_size
        if img.size != (w, h):
            img = img.resize((w, h), Image.LANCZOS)
        self._draw_cursor(img)
        return img

    def _draw_cursor(self, img: Image.Image):
        try:
            cx, cy = self.to_shot(*self.inputs.position())
        except Exception:
            return
        if not (0 <= cx < img.width and 0 <= cy < img.height):
            return
        d = ImageDraw.Draw(img)
        s = 1.0
        pts = [(0, 0), (0, 16), (4, 12), (7, 19), (10, 18), (7, 11), (12, 11)]
        poly = [(cx + px * s, cy + py * s) for px, py in pts]
        d.polygon(poly, fill=(255, 255, 255), outline=(0, 0, 0))

    @staticmethod
    def encode(img: Image.Image) -> dict:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True)
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(buf.getvalue()).decode("ascii")}}

    # ------------------------------------------------------------ dispatch
    def run(self, name: str, inp: dict):
        """Run one member action. Returns a string or a list of content blocks."""
        if not isinstance(inp, dict):
            raise ActionError("input must be an object")
        handler = getattr(self, f"_a_{name}", None)
        if handler is None:
            raise ActionError(f"Unsupported computer action: {name}")
        self._check_user_abort()
        if name in INPUT_ACTIONS:
            self.hooks.before_input(self._last_input)
            self._check_user_abort()
        try:
            return handler(inp)
        finally:
            if name in INPUT_ACTIONS:
                self._last_input = time.monotonic()
            self._remember_cursor()

    # --------------------------------------------------------------- actions
    def _a_screenshot(self, inp):
        return [self.encode(self.capture())]

    def _a_zoom(self, inp):
        region = inp.get("region")
        if not (isinstance(region, (list, tuple)) and len(region) == 4):
            raise ActionError("zoom: 'region' must be [x0, y0, x1, y1]")
        x0, y0 = self.to_screen(region[:2])
        x1, y1 = self.to_screen(region[2:])
        if x1 <= x0 or y1 <= y0:
            raise ActionError("zoom: region must have x1 > x0 and y1 > y0")
        crop = self.screen.grab({"left": x0, "top": y0, "width": x1 - x0, "height": y1 - y0})
        sw, sh = self.shot_size
        r = min(sw / crop.width, sh / crop.height)
        out = crop.resize((max(1, int(crop.width * r)), max(1, int(crop.height * r))),
                          Image.LANCZOS if r < 1 else Image.NEAREST)
        return [self.encode(out)]

    def _point(self, inp, required=False):
        coord = inp.get("coordinate")
        if coord is None:
            if required:
                raise ActionError("'coordinate' is required")
            return self.inputs.position()
        x, y = self.to_screen(coord)
        self.hooks.before_pointer(x, y)
        return x, y

    def _click(self, inp, button="left", clicks=1):
        x, y = self._point(inp)
        mods = modifier_keys(inp.get("text"))
        for k in mods:
            self.inputs.key_down(k)
        try:
            self.inputs.click(x, y, button=button, clicks=clicks)
        finally:
            for k in reversed(mods):
                self.inputs.key_up(k)
        return "OK"

    def _a_left_click(self, inp):
        return self._click(inp, "left", 1)

    def _a_right_click(self, inp):
        return self._click(inp, "right", 1)

    def _a_middle_click(self, inp):
        return self._click(inp, "middle", 1)

    def _a_double_click(self, inp):
        return self._click(inp, "left", 2)

    def _a_triple_click(self, inp):
        return self._click(inp, "left", 3)

    def _a_left_click_drag(self, inp):
        if "start_coordinate" not in inp:
            raise ActionError("left_click_drag: 'start_coordinate' is required")
        sx, sy = self.to_screen(inp["start_coordinate"])
        self.hooks.before_pointer(sx, sy)
        ex, ey = self._point(inp, required=True)
        mods = modifier_keys(inp.get("text"))
        for k in mods:
            self.inputs.key_down(k)
        try:
            self.inputs.move(sx, sy)
            self.inputs.mouse_down("left")
            try:
                self._sleep(0.08)
                # move in steps so apps see a real drag
                for i in range(1, 11):
                    self.inputs.move(sx + (ex - sx) * i / 10, sy + (ey - sy) * i / 10)
                    time.sleep(0.015)
            finally:
                self.inputs.mouse_up("left")
        finally:
            for k in reversed(mods):
                self.inputs.key_up(k)
        return "OK"

    def _a_mouse_move(self, inp):
        x, y = self._point(inp, required=True)
        self.inputs.move(x, y, duration=0.1)
        return "OK"

    def _a_left_mouse_down(self, inp):
        self.inputs.mouse_down("left")
        return "OK"

    def _a_left_mouse_up(self, inp):
        self.inputs.mouse_up("left")
        return "OK"

    def _a_cursor_position(self, inp):
        x, y = self.to_shot(*self.inputs.position())
        return f"X={x},Y={y}"

    def _a_scroll(self, inp):
        direction = inp.get("scroll_direction")
        amount = inp.get("scroll_amount", 3)
        if direction not in ("up", "down", "left", "right"):
            raise ActionError("scroll: 'scroll_direction' must be up/down/left/right")
        if not isinstance(amount, int) or isinstance(amount, bool) or not 0 <= amount <= 100:
            raise ActionError("scroll: 'scroll_amount' must be an integer 0-100")
        x, y = self._point(inp)
        self.inputs.move(x, y)
        dy = amount if direction == "up" else -amount if direction == "down" else 0
        dx = amount if direction == "right" else -amount if direction == "left" else 0
        mods = modifier_keys(inp.get("text"))
        for k in mods:
            self.inputs.key_down(k)
        try:
            self.inputs.scroll(dx, dy, x, y)
        finally:
            for k in reversed(mods):
                self.inputs.key_up(k)
        return "OK"

    def _a_type(self, inp):
        text = inp.get("text")
        if not isinstance(text, str):
            raise ActionError("type: 'text' must be a string")
        self._guard_keyboard()
        self.inputs.type_text(text, self.hooks.should_stop)
        return "OK"

    def _a_key(self, inp):
        keys = parse_combo(inp.get("text"))
        repeat = inp.get("repeat", 1)
        if not isinstance(repeat, int) or isinstance(repeat, bool) or not 1 <= repeat <= 100:
            raise ActionError("key: 'repeat' must be an integer 1-100")
        self._guard_keyboard()
        if self.confirm_risky_keys and set(keys) in RISKY_COMBOS:
            if not self.hooks.confirm("Allow key press?", f"Teto wants to press {inp['text']} "
                                      "(permanently deletes without the Recycle Bin)."):
                raise ActionError("The user declined this key press.")
        for i in range(repeat):
            if i:
                self._check_user_abort()
            self.inputs.hotkey(keys)
        return "OK"

    def _a_hold_key(self, inp):
        keys = parse_combo(inp.get("text"))
        duration = inp.get("duration")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not 0 <= duration <= 300:
            raise ActionError("hold_key: 'duration' must be 0-300 seconds")
        self._guard_keyboard()
        for k in keys:
            self.inputs.key_down(k)
        try:
            self._sleep(float(duration))
        finally:
            for k in reversed(keys):
                self.inputs.key_up(k)
        return "OK"

    def _a_wait(self, inp):
        duration = inp.get("duration", 1)
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not 0 <= duration <= 300:
            raise ActionError("wait: 'duration' must be 0-300 seconds")
        self._sleep(float(duration))
        return "OK"


def describe(name: str, inp: dict) -> str:
    """Short human-readable line for the activity log."""
    c = inp.get("coordinate")
    at = f" at ({c[0]}, {c[1]})" if isinstance(c, (list, tuple)) and len(c) == 2 else ""
    if name == "type":
        t = str(inp.get("text", ""))
        return f"type \"{t[:60]}{'...' if len(t) > 60 else ''}\""
    if name in ("key", "hold_key"):
        return f"{name} {inp.get('text')}" + (f" x{inp['repeat']}" if inp.get("repeat", 1) != 1 else "")
    if name == "scroll":
        return f"scroll {inp.get('scroll_direction')} {inp.get('scroll_amount', 3)}{at}"
    if name == "wait":
        return f"wait {inp.get('duration')}s"
    if name == "zoom":
        return f"zoom {inp.get('region')}"
    return name.replace("_", " ") + at

