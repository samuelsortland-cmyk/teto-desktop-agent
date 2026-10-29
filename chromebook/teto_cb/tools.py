"""Teto's hands on a Chromebook: the user's Chrome tabs, through the extension.

Reuses the Windows tab tools (teto.mytabs) for working inside existing tabs,
and adds tab pictures plus real mouse/keyboard input into a tab (for Eagle
Eyes on browser games and canvas pages).
"""

from __future__ import annotations

import base64
import io

from PIL import Image

from teto.background import _image_block
from teto.computer import ActionError
from teto.mytabs import MY_TAB_SPECS, UserTabs


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


_TAB = {"tab": {"type": "string", "description": "Which tab: part of its title or its id. Empty = the one the user "
                                             "is looking at."}}
CB_SPECS: dict[str, tuple[str, dict]] = {
    "browser_open": ("Open a URL in a NEW background tab of the user's Chrome. Only when the user asked for "
                     "something new (a site, a search, a new doc) - otherwise work in their existing tabs.",
                     _obj({"url": {"type": "string"}}, ["url"])),
    "tab_screenshot": ("A picture of one of the user's tabs (default: the one they're looking at). Coordinates in "
                       "it are used by tab_click_xy.", _obj(dict(_TAB), [])),
    "tab_click_xy": ("Real mouse click at x,y of the latest tab_screenshot, inside that tab (for games, canvas "
                     "pages, anything without element refs). double: double-click. button: left/right.",
                     _obj({"x": {"type": "integer"}, "y": {"type": "integer"}, "double": {"type": "boolean"},
                           "button": {"type": "string", "enum": ["left", "right"]}}, ["x", "y"])),
    "tab_press": ("Real key press in the tab of the latest tab_screenshot / my_tab_read (Enter, Space, arrows, "
                  "w, ctrl+a ...).", _obj({"keys": {"type": "string"}}, ["keys"])),
    "tab_hold": ("Hold a key down in that tab for some seconds (games: walk with w, etc.).",
                 _obj({"key": {"type": "string"}, "seconds": {"type": "number"}}, ["key"])),
}


class ChromeUserTabs(UserTabs):
    def _uia(self):
        raise ActionError("The Teto extension in Chrome isn't connected. Ask the user to make sure Teto for "
                          "Chromebook is turned on in chrome://extensions (and the Teto app is running).")


class ChromeTools:
    """specs()/run() like Teto's Windows background tools, for the agent."""

    def __init__(self, server, settings=lambda: {}):
        self.server = server
        self.settings = settings
        self.tabs = ChromeUserTabs(server, None, settings)
        self._shot: dict | None = None      # {"tab", "scale_x", "scale_y"} of the latest tab_screenshot

    def specs(self) -> dict[str, tuple[str, dict]]:
        return {**MY_TAB_SPECS, **CB_SPECS}

    def _call(self, cmd: str, timeout: float = 20.0, **args):
        from .server import LinkError
        try:
            return self.server.call(cmd, timeout=timeout, **args)
        except LinkError as e:
            raise ActionError(f"Chrome: {e}")

    def _tab_id(self, want: str = "") -> int:
        if want or self.tabs.current is None:
            tabs = self._call("tabs")
            return self.tabs._pick(tabs, want)["id"]
        return self.tabs.current[1]

    def run(self, name: str, a: dict, should_stop=lambda: False):
        a = a or {}
        if name.startswith("my_tab"):
            return self.tabs.run(name, a)
        if name == "browser_open":
            url = str(a.get("url", "")).strip()
            if not url:
                raise ActionError("url is required")
            if "://" not in url:
                url = "https://" + url
            res = self._call("open", timeout=15, url=url)
            self.tabs.current = ("link", int(res["id"]))
            return self.tabs._with_picture("Opened a new background tab.\n\n" +
                                           self.tabs._link_state(int(res["id"])))
        if name == "tab_screenshot":
            tab = self._tab_id(str(a.get("tab", "") or ""))
            shot = self._call("screenshot2", timeout=10, tabId=tab)
            img = Image.open(io.BytesIO(base64.b64decode(shot["data"])))
            px = int(self.settings().get("screenshot_px", 1280) or 1280)
            block, s = _image_block(img, px)
            w, h = int(img.width * s), int(img.height * s)
            self._shot = {"tab": tab, "sx": shot["cssWidth"] / max(1, w), "sy": shot["cssHeight"] / max(1, h)}
            self.tabs.current = ("link", tab)
            return [block, {"type": "text", "text": f"Tab {tab} picture, {w}x{h}."}]
        if name == "tab_click_xy":
            if not self._shot:
                raise ActionError("Take a tab_screenshot first.")
            s = self._shot
            self._call("click_xy", tabId=s["tab"], x=int(a["x"]) * s["sx"], y=int(a["y"]) * s["sy"],
                       button=str(a.get("button", "left")), double=bool(a.get("double", False)))
            return f"Clicked at ({a['x']}, {a['y']}) in tab {s['tab']}."
        if name == "tab_press":
            tab = self._shot["tab"] if self._shot else self._tab_id()
            self._call("key", tabId=tab, keys=str(a.get("keys", "")))
            return f"Pressed {a.get('keys')}."
        if name == "tab_hold":
            tab = self._shot["tab"] if self._shot else self._tab_id()
            secs = max(0.05, min(float(a.get("seconds", 0.5) or 0.5), 10.0))
            self._call("hold", timeout=secs + 10, tabId=tab, key=str(a.get("key", "")), seconds=secs)
            return f"Held {a.get('key')} for {secs:g}s."
        raise ActionError(f"Unknown tool {name}")
