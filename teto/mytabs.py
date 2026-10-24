"""Working in the tabs the user ALREADY has open - never new ones unless asked.

Two ways in:
* Teto Link (the small extension in the user's Edge): full access to every open
  tab, including ones that aren't showing, by tab id. Preferred.
* Windows UI Automation (no setup): the tab showing in each Edge window.

TabPolicy is the hard rule that stops Teto from opening new tabs/pages unless
the user's own words ask for it.
"""

from __future__ import annotations

import base64
import io
import re
import time

from PIL import Image

from .computer import ActionError

# ------------------------------------------------------------- the rule
_ASKS_FOR_NEW = re.compile(
    r"(https?://|www\.|\b[\w-]+\.(com|org|net|edu|gov|io|ai|app|dev|co|us|uk)\b"
    r"|\bnew (tab|window|page|site|doc|document|sheet|spreadsheet|slides?|presentation|email|google doc)"
    r"|\b(another|separate|second|other) (tab|window)"
    r"|\bopen (up )?(a |an |the |my )?(new |another )?(tab|page|site|website|link|browser|youtube|google|gmail|"
    r"docs?|sheets?|slides|outlook|netflix|spotify|amazon|wikipedia|reddit)"
    r"|\b(go|navigate|head|take me) to\b|\bvisit\b|\bsearch (the web|online|google|the internet|for|up)\b"
    r"|\bgoogle (it|this|that|for|the)\b|\blook (it |this |that |them )?up\b|\bresearch\b|\bbrowse\b"
    r"|\b(create|make|start|write|draft) (me )?(a |an )?(new )?(google |word )?"
    r"(doc|document|sheet|spreadsheet|slides?|presentation|email|tab|essay in a new)"
    r"|\b(in|on) (a |your )?(own|new|separate) (tab|browser|window)\b)", re.I)

_YES = re.compile(r"^\s*(y|yes|yeah|yep|sure|ok|okay|go|go ahead|do it|fine|allow|please)\b", re.I)
_NEW_TAB_KEYS = re.compile(r"^\s*(ctrl|control)\s*\+\s*(shift\s*\+\s*)?[tn]\s*$", re.I)
NEW_TAB_TOOLS = {"browser_open", "browser_take_screen_tab"}
KEY_TOOLS = {"press_key", "key", "hold_key"}

BLOCKED = ("Blocked: the user did NOT ask you to open a new tab or page. Work in the tab they ALREADY have open: "
           "call my_tab_read (tab: part of its title, or leave empty for the one they're looking at), then "
           "my_tab_click / my_tab_type / my_tab_key / my_tab_scroll IN THAT TAB. Only if the job truly needs "
           "another page, ask the user first with ask_user (e.g. \"Can I open a new tab to look this up?\").")


def new_tab_allowed(text: str) -> bool:
    return bool(_ASKS_FOR_NEW.search(text or ""))


def _looks_like_web(target: str) -> bool:
    t = (target or "").strip().lower()
    return t.startswith(("http:", "https:", "www.", "microsoft-edge:")) or bool(
        re.match(r"^[\w-]+(\.[\w-]+)+(/|$)", t))


class TabPolicy:
    """Opening new tabs is off unless the user's words (this conversation) ask for it."""

    def __init__(self):
        self.allowed = False

    def note_task(self, text: str, fresh: bool = False):
        """Each new message decides for itself - except a bare "yes" agreeing to
        something Teto just proposed, which keeps the previous permission."""
        if _YES.match(text or "") and len((text or "").split()) <= 4:
            return
        self.allowed = new_tab_allowed(text)

    def note_answer(self, question: str, answer: str):
        if "tab" in (question or "").lower() and _YES.match(answer or ""):
            self.allowed = True
        elif new_tab_allowed(answer):
            self.allowed = True

    def check(self, name: str, args: dict):
        """Raise ActionError if this tool call would open a new tab/page against the rule."""
        if self.allowed:
            return
        args = args or {}
        if name in NEW_TAB_TOOLS:
            raise ActionError(BLOCKED)
        if name == "open_target" and _looks_like_web(str(args.get("target", ""))):
            raise ActionError(BLOCKED)
        if name in KEY_TOOLS or name == "computer":
            combo = str(args.get("keys") or args.get("text") or args.get("key") or "")
            if _NEW_TAB_KEYS.match(combo):
                raise ActionError(BLOCKED)


# ------------------------------------------------------------- tool specs
def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


_TABSEL = {"tab": {"type": "string", "description": "Which of the user's tabs: part of its title, or its id "
                                               "from my_tabs. Empty = the tab they're looking at."}}
_REF = {"ref": {"type": "integer"}}
MY_TAB_SPECS: dict[str, tuple[str, dict]] = {
    "my_tabs": ("List ALL the tabs the user already has open in their Edge (ids, titles, which are showing).",
                _obj({}, [])),
    "my_tab_read": ("Read one of the user's ALREADY-OPEN tabs - by default the one they're looking at - "
                    "WITHOUT opening anything new: its URL, the text visible on the page right now, and its "
                    "numbered elements (answers, buttons, fields, links). Works while they use another app. "
                    "This is how you start ANY task about something they have open (a quiz, a form, an email, "
                    "'this page').", _obj(dict(_TABSEL), [])),
    "my_tab_click": ("Click element [ref] (from the latest my_tab_read) in the user's tab - no mouse, no new "
                     "tab. Returns the page's new state. trusted: true sends a real mouse click into the tab "
                     "(use it if a normal click didn't register).",
                     _obj({**_REF, "trusted": {"type": "boolean"}}, ["ref"])),
    "my_tab_type": ("Type text into field [ref] in the user's tab. clear: replace existing text (default true). "
                    "submit: press Enter after.",
                    _obj({**_REF, "text": {"type": "string"}, "clear": {"type": "boolean"},
                          "submit": {"type": "boolean"}}, ["ref", "text"])),
    "my_tab_select": ("Choose an option in dropdown [ref] in the user's tab.",
                      _obj({**_REF, "option": {"type": "string"}}, ["ref", "option"])),
    "my_tab_key": ("Press a key or combo in the user's tab (Enter, Tab, Escape, arrows, ctrl+a ...).",
                   _obj({"keys": {"type": "string"}}, ["keys"])),
    "my_tab_write": ("Type text into whatever is focused in the user's tab with real key presses - for editors "
                     "like Google Docs (click into the document first). Needs Teto Link.",
                     _obj({"text": {"type": "string"}}, ["text"])),
    "my_tab_scroll": ("Scroll the user's tab up/down (amount = screens, default 1).",
                      _obj({"direction": {"type": "string", "enum": ["up", "down"]},
                            "amount": {"type": "number"}}, ["direction"])),
    "my_tab_navigate": ("In the user's SAME tab: go back, forward, reload, or to a URL the task requires "
                        "(not a new tab).",
                        _obj({"action": {"type": "string", "enum": ["back", "forward", "reload", "url"]},
                              "url": {"type": "string"}}, ["action"])),
}


# ------------------------------------------------------------- the user's tabs
class UserTabs:
    """Reads and operates the user's existing tabs. Uses Teto Link when it's
    connected, otherwise Windows UI Automation on the tab showing in Edge."""

    def __init__(self, link, desktop=None, settings=lambda: {}):
        self.link = link                     # teto.link.LinkServer (or a stand-in)
        self.desktop = desktop               # callable -> (BackgroundDesktop, Actor) or raises
        self.settings = settings
        self.current: tuple[str, int] | None = None     # ("link", tab id) | ("uia", hwnd)

    # ---------------------------------------------------------- helpers
    def _linked(self) -> bool:
        try:
            return bool(self.link and self.link.connected())
        except Exception:
            return False

    def _call(self, cmd: str, timeout: float = 20.0, **args):
        from .link import LinkError

        try:
            return self.link.call(cmd, timeout=timeout, **args)
        except LinkError as e:
            raise ActionError(f"Teto Link: {e}")

    def _uia(self):
        if self.desktop is None:
            raise ActionError("Install Teto Link (Settings -> Connect my Edge) so I can work in your tabs.")
        return self.desktop()

    def _pick(self, tabs: list[dict], want: str) -> dict:
        want = (want or "").strip()
        if not want:
            for t in tabs:
                if t.get("frontWindow") and t.get("active"):
                    return t
            for t in tabs:
                if t.get("active"):
                    return t
            if tabs:
                return tabs[0]
            raise ActionError("You don't have any tabs open in Edge.")
        if want.isdigit():
            for t in tabs:
                if t["id"] == int(want):
                    return t
        low = want.lower()
        hits = [t for t in tabs if low in (t.get("title") or "").lower()] or \
               [t for t in tabs if low in (t.get("url") or "").lower()]
        if not hits:
            raise ActionError(f"No open tab matching {want!r}. Your tabs:\n" + self._format_tabs(tabs))
        hits.sort(key=lambda t: (not t.get("frontWindow"), not t.get("active")))
        return hits[0]

    @staticmethod
    def _format_tabs(tabs: list[dict]) -> str:
        rows = []
        for t in tabs:
            where = "SHOWING" if t.get("active") and t.get("frontWindow") else \
                    ("showing in another window" if t.get("active") else "in the background")
            rows.append(f"[{t['id']}] {t.get('title', '')[:80]} - {t.get('url', '')[:100]} ({where})")
        return "\n".join(rows) or "(no tabs)"

    def _picture(self) -> dict | None:
        if not self.settings().get("auto_screenshots", False) or self.current is None:
            return None
        kind, ident = self.current
        try:
            if kind == "link":
                if not self._last_active:
                    return None              # no picture of hidden tabs (would need the debugger banner)
                data = self._call("screenshot", timeout=6, tabId=ident)
                img = Image.open(io.BytesIO(base64.b64decode(data)))
            else:
                d, act = self._uia()
                from . import platform_win
                img = act.call(lambda: platform_win.capture_window(ident))
                if img is None:
                    return None
            from .background import _image_block
            block, _s = _image_block(img, int(self.settings().get("screenshot_px", 1024) or 1024))
            return block
        except Exception:
            return None

    def _with_picture(self, text: str):
        pic = self._picture()
        return [{"type": "text", "text": text}, pic] if pic else text

    _last_active = False

    def _link_state(self, tab_id: int, header: bool = True) -> str:
        end = time.monotonic() + 4
        while True:
            try:
                s = self._call("read", timeout=10, tabId=tab_id)
                break
            except ActionError:
                if time.monotonic() > end:          # e.g. mid-navigation: retry briefly
                    raise
                time.sleep(0.15)
        self._last_active = bool(s.get("active"))
        out = []
        if header:
            out.append(f"Your tab [{tab_id}]: {s.get('title', '')}\nURL: {s.get('url', '')}\n"
                       f"({'showing' if s.get('active') else 'in the background - you can work in it anyway'}; "
                       f"scrolled {s.get('scroll', '?')}px)")
        else:
            out.append(f"Now: {s.get('title', '')} - {s.get('url', '')} (scrolled {s.get('scroll', '?')}px)")
        if s.get("visible"):
            out.append("What's visible on the page:\n" + s["visible"][:5000])
        out.append("Page elements (my_tab_click / my_tab_type with these refs):\n"
                   + ("\n".join(s.get("items") or []) or "(none found)"))
        return "\n\n".join(out)

    def _need_current(self):
        if self.current is None:
            self.read("")
        return self.current

    def _after(self, msg: str):
        kind, ident = self.current
        if kind == "link":
            time.sleep(0.15)                          # let the page react
            return self._with_picture(msg + "\n\n" + self._link_state(ident, header=False))
        return self._with_picture(msg)

    # ---------------------------------------------------------- tools
    def tabs(self) -> str:
        if self._linked():
            return "Your open tabs:\n" + self._format_tabs(self._call("tabs"))
        d, act = self._uia()
        return act.call(d.list_tabs_text)

    def read(self, want: str = ""):
        if self._linked():
            t = self._pick(self._call("tabs"), want)
            self.current = ("link", t["id"])
            return self._with_picture(self._link_state(t["id"]))
        d, act = self._uia()
        text = act.call(lambda: d.screen_tab(want))
        self.current = ("uia", act.call(lambda: d.last_hwnd))
        return self._with_picture(text)

    def click(self, ref: int, trusted: bool = False):
        kind, ident = self._need_current()
        if kind == "link":
            r = self._call("click", tabId=ident, ref=int(ref), trusted=bool(trusted))
            if r == "missing":
                raise ActionError(f"Element [{ref}] isn't on the page anymore - my_tab_read again.")
            return self._after(f"Clicked [{ref}].")
        d, act = self._uia()
        return self._with_picture(act.call(lambda: d.click(ident, int(ref))))

    def type(self, ref: int, text: str, clear: bool = True, submit: bool = False):
        kind, ident = self._need_current()
        if kind == "link":
            r = self._call("type", tabId=ident, ref=int(ref), text=text, clear=clear, submit=submit)
            if r == "missing":
                raise ActionError(f"Element [{ref}] isn't on the page anymore - my_tab_read again.")
            return self._after(f"Typed into [{ref}]{' and pressed Enter' if submit else ''}.")
        d, act = self._uia()
        out = act.call(lambda: d.type(ident, int(ref), text, "replace" if clear else "append"))
        if submit:
            act.call(lambda: d.key(ident, "Return"))
        return self._with_picture(out)

    def select(self, ref: int, option: str):
        kind, ident = self._need_current()
        if kind == "link":
            r = self._call("select", tabId=ident, ref=int(ref), option=option)
            if r != "ok":
                raise ActionError(f"Couldn't choose {option!r} in [{ref}].")
            return self._after(f"Selected {option!r} in [{ref}].")
        d, act = self._uia()
        return self._with_picture(act.call(lambda: d.click(ident, int(ref))))

    def key(self, keys: str):
        kind, ident = self._need_current()
        if kind == "link":
            self._call("key", tabId=ident, keys=keys)
            return self._after(f"Pressed {keys}.")
        d, act = self._uia()
        return self._with_picture(act.call(lambda: d.key(ident, keys)))

    def write(self, text: str):
        kind, ident = self._need_current()
        if kind != "link":
            raise ActionError("Typing into editors like Google Docs in your own tab needs Teto Link "
                              "(Settings -> Connect my Edge). Ask the user to set it up, or use my_tab_type on a "
                              "text field.")
        self._call("write", timeout=max(20.0, len(text) / 50), tabId=ident, text=text)
        return self._after(f"Wrote {len(text)} characters.")

    def scroll(self, direction: str, amount: float = 1.0):
        kind, ident = self._need_current()
        amount = max(0.1, min(float(amount or 1), 20))
        if kind == "link":
            self._call("scroll", tabId=ident, dy=int((1 if direction == "down" else -1) * amount * 700))
            return self._after(f"Scrolled {direction}.")
        d, act = self._uia()
        out = act.call(lambda: d.scroll(ident, direction))
        return self._with_picture(out + "\n\n" + act.call(lambda: d.tab_state(ident, header=False)))

    def navigate(self, action: str, url: str = ""):
        kind, ident = self._need_current()
        if kind != "link":
            raise ActionError("Navigating your tab needs Teto Link; read and click links in it instead.")
        if action == "url":
            if not url:
                raise ActionError("url is required for action 'url'.")
            self._call("navigate", timeout=15, tabId=ident, url=url if "://" in url else "https://" + url)
        else:
            self._call("navigate", timeout=15, tabId=ident, action=action)
        return self._after(f"Navigated ({action}) in your tab.")

    def run(self, name: str, a: dict):
        calls = {
            "my_tabs": self.tabs,
            "my_tab_read": lambda: self.read(str(a.get("tab", "") or "")),
            "my_tab_click": lambda: self.click(int(a["ref"]), bool(a.get("trusted", False))),
            "my_tab_type": lambda: self.type(int(a["ref"]), str(a.get("text", "")), a.get("clear", True) is not False,
                                             bool(a.get("submit", False))),
            "my_tab_select": lambda: self.select(int(a["ref"]), str(a.get("option", ""))),
            "my_tab_key": lambda: self.key(str(a.get("keys", ""))),
            "my_tab_write": lambda: self.write(str(a.get("text", ""))),
            "my_tab_scroll": lambda: self.scroll(str(a.get("direction", "down")), a.get("amount", 1)),
            "my_tab_navigate": lambda: self.navigate(str(a.get("action", "reload")), str(a.get("url", "") or "")),
        }
        if name not in calls:
            raise ActionError(f"Unknown tool {name}")
        try:
            return calls[name]()
        except KeyError as e:
            raise ActionError(f"Missing argument {e}")
