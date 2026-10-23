"""Windows integration helpers.

Every function is safe to call on any OS: off Windows (or if a Win32 call
fails) it quietly does nothing / returns a sensible fallback, so the rest of
the app never needs its own platform checks.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                    ("wParamH", wintypes.WORD)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004

    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.restype = wintypes.HWND
    user32.SetWindowDisplayAffinity.argtypes = (wintypes.HWND, wintypes.DWORD)
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.GetParent.argtypes = (wintypes.HWND,)
    user32.GetParent.restype = wintypes.HWND


def enable_dpi_awareness() -> None:
    """Make screen pixels == mouse pixels on scaled (125%/150%...) displays.

    Must run before any window is created and before pyautogui is imported.
    """
    if not IS_WINDOWS:
        return
    try:  # Windows 10 1703+: per-monitor v2
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:  # Windows 8.1+
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def toplevel_hwnd(tk_widget) -> int | None:
    """The real top-level HWND for a Tk window (Tk wraps it in a frame)."""
    if not IS_WINDOWS:
        return None
    try:
        tk_widget.update_idletasks()
        hwnd = user32.GetParent(tk_widget.winfo_id()) or tk_widget.winfo_id()
        return int(hwnd)
    except Exception:
        return None


def exclude_from_capture(tk_widget) -> bool:
    """Hide a window from screenshots (Win10 2004+), so the agent never sees
    or tries to click the pet / chat panel. Returns True on success."""
    hwnd = toplevel_hwnd(tk_widget)
    if not hwnd:
        return False
    try:
        WDA_EXCLUDEFROMCAPTURE = 0x00000011
        return bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False


def foreground_hwnd() -> int | None:
    if not IS_WINDOWS:
        return None
    try:
        h = user32.GetForegroundWindow()
        if not h:
            return None
        root = user32.GetAncestor(h, 2)  # GA_ROOT
        return int(root or h)
    except Exception:
        return None


def work_area(default_w: int, default_h: int) -> tuple[int, int, int, int]:
    """Desktop area not covered by the taskbar: (left, top, right, bottom)."""
    if IS_WINDOWS:
        try:
            rect = wintypes.RECT()
            SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            pass
    return 0, 0, default_w, default_h - 48


def type_unicode(text: str, interval: float = 0.004, should_stop=None) -> None:
    """Type arbitrary Unicode text with SendInput (works for emoji, accents,
    CJK...). Newlines/tabs are sent as real Enter/Tab key presses."""
    VK_RETURN, VK_TAB = 0x0D, 0x09
    for ch in text.replace("\r\n", "\n"):
        if should_stop and should_stop():
            raise InterruptedError("stopped")
        if ch == "\n":
            _send_vk(VK_RETURN)
        elif ch == "\t":
            _send_vk(VK_TAB)
        else:
            data = ch.encode("utf-16-le")
            units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
            inputs = []
            for u in units:  # surrogate pairs need both halves
                inputs.append(_kbd(0, u, KEYEVENTF_UNICODE))
            for u in units:
                inputs.append(_kbd(0, u, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
            arr = (INPUT * len(inputs))(*inputs)
            if user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT)) != len(inputs):
                raise OSError(f"SendInput failed (error {ctypes.get_last_error()}); "
                              "the target app may be running as administrator")
        if interval:
            time.sleep(interval)


def _kbd(vk: int, scan: int, flags: int):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return inp


def _send_vk(vk: int) -> None:
    arr = (INPUT * 2)(_kbd(vk, 0, 0), _kbd(vk, 0, KEYEVENTF_KEYUP))
    user32.SendInput(2, arr, ctypes.sizeof(INPUT))


def wheel(dx_clicks: int, dy_clicks: int) -> None:
    """Scroll by whole wheel notches (positive dy = up, positive dx = right)."""
    WHEEL_DELTA = 120
    MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
    events = []
    if dy_clicks:
        events.append((MOUSEEVENTF_WHEEL, dy_clicks))
    if dx_clicks:
        events.append((MOUSEEVENTF_HWHEEL, dx_clicks))
    for flag, clicks in events:
        step = 1 if clicks > 0 else -1
        for _ in range(abs(clicks)):   # one notch at a time, like a real wheel
            inp = INPUT()
            inp.type = 0  # INPUT_MOUSE
            inp.u.mi = MOUSEINPUT(0, 0, ctypes.c_uint32(step * WHEEL_DELTA).value, flag, 0, 0)
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            time.sleep(0.01)


def set_foreground(hwnd: int) -> bool:
    """Give keyboard focus back to another window (allowed while we hold it)."""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        h = wintypes.HWND(hwnd)
        if not user32.IsWindow(h):
            return False
        if user32.IsIconic(h):
            user32.ShowWindow(h, 9)  # SW_RESTORE
        return bool(user32.SetForegroundWindow(h))
    except Exception:
        return False


_mutex = None


def single_instance(name: str = "TetoDesktopAgent") -> bool:
    """False if another copy of Teto is already running (Windows only)."""
    global _mutex
    if not IS_WINDOWS:
        return True
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        _mutex = kernel32.CreateMutexW(None, False, f"Local\\{name}")
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def set_app_id(app_id: str = "Teto.DesktopAgent") -> None:
    """Give Teto her own taskbar identity, so Windows shows Teto's icon instead
    of grouping her under Python's. Must run before any window is created."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id))
    except Exception:
        pass


def list_windows(exclude: set[int] | frozenset = frozenset()) -> list[tuple[int, int, int, int, int]]:
    """Visible app windows, topmost first: [(hwnd, left, top, right, bottom)]."""
    if not IS_WINDOWS:
        return []
    out: list[tuple[int, int, int, int, int]] = []
    try:
        dwm = ctypes.WinDLL("dwmapi")
        dwm.DwmGetWindowAttribute.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
        for fn in ("IsWindowVisible", "IsIconic", "GetWindowTextLengthW"):
            getattr(user32, fn).argtypes = (wintypes.HWND,)
        user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
        user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, _lparam):
            try:
                h = int(hwnd or 0)
                if not h or h in exclude:
                    return True
                if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                    return True
                if user32.GetWindowTextLengthW(hwnd) == 0:
                    return True
                if user32.GetWindowLongW(hwnd, -20) & 0x00000080:     # WS_EX_TOOLWINDOW
                    return True
                cloaked = wintypes.DWORD(0)
                if dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4) == 0 and cloaked.value:
                    return True                                      # on another virtual desktop
                rect = wintypes.RECT()
                if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))   # 9 = extended frame bounds
                out.append((h, rect.left, rect.top, rect.right, rect.bottom))
            except Exception:
                pass
            return True

        user32.EnumWindows(proc_type(callback), 0)
    except Exception:
        return []
    return out


def battery() -> tuple[int, bool] | None:
    """(percent, plugged_in), or None on desktops / unknown."""
    if not IS_WINDOWS:
        return None

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]

    try:
        st = SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
            return None
        if st.BatteryFlag & 128 or st.BatteryLifePercent > 100:   # no battery / unknown
            return None
        return int(st.BatteryLifePercent), st.ACLineStatus == 1
    except Exception:
        return None


def user_idle_seconds() -> float:
    """Seconds since the user last touched the mouse or keyboard (Windows).
    Elsewhere: infinity, so only interaction with Teto herself counts."""
    if not IS_WINDOWS:
        return float("inf")

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    try:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        return 0.0


# ------------------------------------------------- background window control
def window_title(hwnd: int) -> str:
    if not IS_WINDOWS:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buf, 512)
    return buf.value


def window_process(hwnd: int) -> str:
    if not IS_WINDOWS:
        return ""
    try:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(0x1000, False, pid.value)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value.rsplit("\\", 1)[-1]
        finally:
            k32.CloseHandle(h)
    except Exception:
        pass
    return ""


def minimized_windows(exclude=frozenset()) -> list[tuple[int, str, str]]:
    if not IS_WINDOWS:
        return []
    out = []
    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _lp):
        h = int(hwnd or 0)
        try:
            if (h and h not in exclude and user32.IsWindowVisible(hwnd) and user32.IsIconic(hwnd)
                    and not user32.GetWindowLongW(hwnd, -20) & 0x80):
                title = window_title(h)
                if title:
                    out.append((h, title, window_process(h)))
        except Exception:
            pass
        return True
    try:
        user32.EnumWindows(proc_type(cb), 0)
    except Exception:
        return []
    return out


def restore_behind(hwnd: int) -> None:
    """Un-minimise a window *behind* everything else, without focusing it, so it
    can be captured without covering what the user is doing."""
    if not IS_WINDOWS:
        return
    h = wintypes.HWND(hwnd)
    if user32.IsIconic(h):
        user32.ShowWindow(h, 4)                                 # SW_SHOWNOACTIVATE
        user32.SetWindowPos(h, wintypes.HWND(1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # HWND_BOTTOM, no move/size/activate
        time.sleep(0.35)


def window_origin(hwnd: int) -> tuple[int, int]:
    rect = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    return rect.left, rect.top


def capture_window(hwnd: int):
    """Picture of one window via PrintWindow (works when it's covered by others)."""
    if not IS_WINDOWS:
        return None
    from PIL import Image

    gdi32 = ctypes.WinDLL("gdi32")
    H = wintypes.HANDLE
    user32.GetWindowDC.argtypes = (wintypes.HWND,)
    user32.GetWindowDC.restype = H
    user32.ReleaseDC.argtypes = (wintypes.HWND, H)
    user32.PrintWindow.argtypes = (wintypes.HWND, H, wintypes.UINT)
    gdi32.CreateCompatibleDC.argtypes = (H,)
    gdi32.CreateCompatibleDC.restype = H
    gdi32.CreateCompatibleBitmap.argtypes = (H, ctypes.c_int, ctypes.c_int)
    gdi32.CreateCompatibleBitmap.restype = H
    gdi32.SelectObject.argtypes = (H, H)
    gdi32.SelectObject.restype = H
    gdi32.GetDIBits.argtypes = (H, H, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT)
    gdi32.DeleteObject.argtypes = (H,)
    gdi32.DeleteDC.argtypes = (H,)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    rect = wintypes.RECT()
    hw = wintypes.HWND(hwnd)
    user32.GetWindowRect(hw, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    wdc = user32.GetWindowDC(hw)
    mdc = gdi32.CreateCompatibleDC(wdc)
    bmp = gdi32.CreateCompatibleBitmap(wdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        if not user32.PrintWindow(hw, mdc, 2):                  # PW_RENDERFULLCONTENT (Chrome, UWP...)
            user32.PrintWindow(hw, mdc, 0)
        bih = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
        return Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    finally:
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(hw, wdc)


class _POINT(ctypes.Structure if IS_WINDOWS else object):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)] if IS_WINDOWS else []


def _deepest_child(top: int, sx: int, sy: int) -> tuple[int, int, int]:
    """Child window under screen point (sx, sy) inside `top`, ignoring other
    windows covering it. Returns (hwnd, client_x, client_y)."""
    user32.ChildWindowFromPointEx.argtypes = (wintypes.HWND, _POINT, wintypes.UINT)
    user32.ChildWindowFromPointEx.restype = wintypes.HWND
    cur = top
    for _ in range(12):
        pt = _POINT(sx, sy)
        user32.ScreenToClient(wintypes.HWND(cur), ctypes.byref(pt))
        child = user32.ChildWindowFromPointEx(wintypes.HWND(cur), pt, 0x0001 | 0x0002 | 0x0004)
        if not child or int(child) == cur:
            return cur, pt.x, pt.y
        cur = int(child)
    pt = _POINT(sx, sy)
    user32.ScreenToClient(wintypes.HWND(cur), ctypes.byref(pt))
    return cur, pt.x, pt.y


def _post(hwnd: int, msg: int, wparam: int, lparam: int) -> bool:
    fn = user32.PostMessageW
    fn.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    return bool(fn(wintypes.HWND(hwnd), msg, wparam & 0xFFFFFFFFFFFFFFFF, lparam))


def post_click(top: int, sx: int, sy: int, double: bool = False) -> bool:
    """Click inside a window by message, without moving the real mouse."""
    if not IS_WINDOWS:
        return False
    target, cx, cy = _deepest_child(top, sx, sy)
    lp = (cy & 0xFFFF) << 16 | (cx & 0xFFFF)
    ok = _post(target, 0x0200, 0, lp)                           # WM_MOUSEMOVE
    ok = _post(target, 0x0201, 1, lp) and ok                    # WM_LBUTTONDOWN (MK_LBUTTON)
    ok = _post(target, 0x0202, 0, lp) and ok                    # WM_LBUTTONUP
    if double:
        ok = _post(target, 0x0203, 1, lp) and _post(target, 0x0202, 0, lp) and ok   # WM_LBUTTONDBLCLK
    return bool(ok)


def focus_child(hwnd: int) -> int:
    """The control that has keyboard focus inside a (possibly background) window."""
    if not IS_WINDOWS:
        return hwnd

    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hwndActive", wintypes.HWND),
                    ("hwndFocus", wintypes.HWND), ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                    ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND), ("rcCaret", wintypes.RECT)]
    try:
        tid = user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), None)
        info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
        if user32.GetGUIThreadInfo(tid, ctypes.byref(info)) and info.hwndFocus:
            return int(info.hwndFocus)
    except Exception:
        pass
    return hwnd


_VK = {"enter": 0x0D, "tab": 0x09, "esc": 0x1B, "backspace": 0x08, "delete": 0x2E, "space": 0x20,
       "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23,
       "pageup": 0x21, "pagedown": 0x22, "insert": 0x2D}
for _i in range(1, 13):
    _VK[f"f{_i}"] = 0x6F + _i


def post_key(hwnd: int, name: str) -> bool:
    if not IS_WINDOWS or name not in _VK:
        return False
    vk = _VK[name]
    scan = user32.MapVirtualKeyW(vk, 0) & 0xFF
    down = _post(hwnd, 0x0100, vk, 1 | scan << 16)                       # WM_KEYDOWN
    up = _post(hwnd, 0x0101, vk, 1 | scan << 16 | 0xC0000000)            # WM_KEYUP
    return down and up


def post_text(hwnd: int, text: str, replace: bool = True) -> bool:
    """Type into a classic text box by message (no real keyboard)."""
    if not IS_WINDOWS:
        return False
    send = user32.SendMessageW
    send.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    h = wintypes.HWND(hwnd)
    if replace:
        send(h, 0x00B1, 0, -1)                                  # EM_SETSEL all
    else:
        send(h, 0x00B1, 0xFFFFFFFF, -1)                         # caret to the end
    ok = True
    for ch in text.replace("\r\n", "\n"):
        code = 13 if ch == "\n" else ord(ch)
        for unit in ([code] if code < 0x10000 else
                     [0xD800 + ((code - 0x10000) >> 10), 0xDC00 + ((code - 0x10000) & 0x3FF)]):
            ok = _post(hwnd, 0x0102, unit, 1) and ok           # WM_CHAR
    return ok


def post_scroll(hwnd: int, direction: str) -> None:
    target = focus_child(hwnd)
    code = 3 if direction == "down" else 2                      # SB_PAGEDOWN / SB_PAGEUP
    _post(target, 0x0115, code, 0)                              # WM_VSCROLL


def open_background(target: str) -> bool:
    """Launch an app/file/URL minimised and without taking focus (where the app allows)."""
    if not IS_WINDOWS:
        return False
    shell32 = ctypes.WinDLL("shell32")
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    r = shell32.ShellExecuteW(None, "open", target, None, None, 7)   # SW_SHOWMINNOACTIVE
    return (r or 0) > 32


def _browser_exe() -> str:
    """Path to the user's Edge (preferred) or Chrome."""
    if not IS_WINDOWS:
        return ""
    candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                     r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                     r"Google\Chrome\Application\chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     r"Google\Chrome\Application\chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return ""


def launch_browser_with_debug(port: int, browser_path: str = "") -> bool:
    """Relaunch the user's real browser with a DevTools debug port and their
    normal session, so Teto can drive the tabs they already have open. Opens
    minimized / without stealing focus. Uses an explicit user-data-dir pointed
    at their default profile so remote debugging is permitted."""
    import os as _os
    import subprocess

    exe = browser_path or _browser_exe()
    if not exe:
        return False
    low = exe.lower()
    if "edge" in low:
        data = _os.path.join(_os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Edge\User Data")
    else:
        data = _os.path.join(_os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\User Data")
    args = [exe, f"--remote-debugging-port={int(port)}", "--remote-allow-origins=*", "--restore-last-session",
            "--no-first-run", "--no-default-browser-check"]
    if data and _os.path.isdir(data):
        args.append(f"--user-data-dir={data}")
    try:
        subprocess.Popen(args, stdin=subprocess.DEVNULL, creationflags=0x08000000)
        return True
    except Exception:
        return False


# ------------------------------------------------- hardware scan-code keyboard
# Games (Roblox, most DirectInput/raw-input titles) ignore virtual-key input
# and only react to hardware SCAN CODES. SendInput with KEYEVENTF_SCANCODE is
# what actually reaches them.
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP_F = 0x0002
KEYEVENTF_SCANCODE = 0x0008

# pyautogui-style key names (what computer.parse_combo returns) -> virtual-key code.
_NAMED_VK = {
    "enter": 0x0D, "esc": 0x1B, "backspace": 0x08, "tab": 0x09, "space": 0x20, "delete": 0x2E,
    "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "ctrl": 0x11, "ctrlleft": 0xA2, "ctrlright": 0xA3, "alt": 0x12, "altleft": 0xA4, "altright": 0xA5,
    "shift": 0x10, "shiftleft": 0xA0, "shiftright": 0xA1, "win": 0x5B, "winleft": 0x5B, "winright": 0x5C,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91, "printscreen": 0x2C, "pause": 0x13, "apps": 0x5D,
    "volumemute": 0xAD, "volumeup": 0xAF, "volumedown": 0xAE, "playpause": 0xB3,
    "nexttrack": 0xB0, "prevtrack": 0xB1,
}
for _i in range(1, 25):
    _NAMED_VK[f"f{_i}"] = 0x6F + _i
for _i in range(10):
    _NAMED_VK[f"num{_i}"] = 0x60 + _i
# extended-key virtual codes (need the EXTENDEDKEY flag)
_EXTENDED_VK = {0xA3, 0xA5, 0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, 0x26, 0x28, 0x25, 0x27, 0x5B, 0x5C, 0x5D,
                0x90, 0x2C, 0xAD, 0xAF, 0xAE, 0xB3, 0xB0, 0xB1}


def name_to_vk(name: str) -> int | None:
    """Virtual-key code for a key name ('w', 'ctrl', 'up', 'space', ...)."""
    if not IS_WINDOWS:
        return None
    low = name.lower()
    if low in _NAMED_VK:
        return _NAMED_VK[low]
    if len(name) == 1:
        res = user32.VkKeyScanW(ord(name))
        if res != -1:
            return res & 0xFF
    return None


def _scancode_input(vk: int, keyup: bool):
    scan = user32.MapVirtualKeyW(vk, 0) & 0xFF            # MAPVK_VK_TO_VSC
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP_F if keyup else 0)
    if vk in _EXTENDED_VK:
        flags |= KEYEVENTF_EXTENDEDKEY
    return _kbd(0, scan, flags)


def key_scancode(name: str, keyup: bool) -> bool:
    """Press or release one key as a hardware scan code. Returns False if the
    name is unknown (caller can fall back)."""
    vk = name_to_vk(name)
    if vk is None:
        return False
    arr = (INPUT * 1)(_scancode_input(vk, keyup))
    return user32.SendInput(1, arr, ctypes.sizeof(INPUT)) == 1


def press_scancodes(names: list[str]) -> bool:
    """Press a key or chord (modifiers first) via scan codes, release in reverse."""
    vks = [name_to_vk(n) for n in names]
    if any(v is None for v in vks):
        return False
    inputs = [_scancode_input(v, False) for v in vks] + [_scancode_input(v, True) for v in reversed(vks)]
    arr = (INPUT * len(inputs))(*inputs)
    return user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT)) == len(inputs)
