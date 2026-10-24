import json
import os
import shutil
import threading
import time
import urllib.request

import pytest

from teto import link as link_mod
from teto.computer import ActionError
from teto.mytabs import BLOCKED, TabPolicy, UserTabs, new_tab_allowed

CHROMIUM = os.environ.get("TETO_BROWSER_PATH") or shutil.which("chromium") or "/opt/pw-browsers/chromium"
EXT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "teto-link")


# ------------------------------------------------------------------ the rule
@pytest.mark.parametrize("task", [
    "do my quiz", "answer the questions on this page", "finish my AP world history practice test",
    "fill out this form for me", "reply to the email I have open", "fix the grammar in my essay"])
def test_tasks_about_open_things_do_not_allow_new_tabs(task):
    assert not new_tab_allowed(task)


@pytest.mark.parametrize("task", [
    "open youtube", "open a new tab and check the weather", "search for the answer to question 3",
    "go to gmail.com", "look it up", "research the french revolution", "make a new google doc about cats",
    "visit https://example.com", "do it in a new tab"])
def test_explicit_requests_allow_new_tabs(task):
    assert new_tab_allowed(task)


def test_policy_blocks_every_way_of_opening_a_tab():
    p = TabPolicy()
    p.note_task("do my quiz")
    for name, args in (("browser_open", {"url": "https://google.com"}), ("browser_take_screen_tab", {}),
                       ("open_target", {"target": "https://google.com"}), ("open_target", {"target": "bing.com/x"}),
                       ("press_key", {"keys": "ctrl+t"}), ("key", {"text": "ctrl+n"}),
                       ("press_key", {"keys": "ctrl+shift+n"})):
        with pytest.raises(ActionError, match="did NOT ask"):
            p.check(name, args)
    p.check("open_target", {"target": "notepad"})               # apps are fine
    p.check("press_key", {"keys": "ctrl+a"})
    p.check("my_tab_click", {"ref": 1})
    p.note_answer("Can I open a new tab to look this up?", "yes")
    p.check("browser_open", {"url": "https://google.com"})
    p.note_task("now do question 5")                             # next message: back to the rule
    with pytest.raises(ActionError):
        p.check("browser_open", {"url": "x.com"})
    p.note_task("search for it")
    p.note_task("yes")                                           # agreeing keeps the permission
    p.check("browser_open", {"url": "x.com"})


def test_cli_brain_enforces_the_rule():
    from teto.agent import AgentSettings
    from teto.brain_cli import CliAgent
    from teto.computer import Computer, Hooks
    from tests.fakes import FakeInputs, FakeScreen, RecordingUI

    class BG:
        calls = []

        def specs(self):
            from teto.background import BROWSER_SPECS
            return dict(BROWSER_SPECS)

        def run(self, name, a, should_stop=None):
            self.calls.append(name)
            return "ok"

    bg = BG()
    a = CliAgent(RecordingUI(), lambda: Computer(hooks=Hooks(), inputs=FakeInputs(), screen=FakeScreen(800, 600)),
                 AgentSettings(work_style="background"), background=bg)
    a.tab_policy.note_task("do my quiz")
    res = a._handle_tool("browser_open", {"url": "https://google.com"})
    assert res["is_error"] and "did NOT ask" in res["content"][0]["text"] and bg.calls == []
    a.tab_policy.note_task("open google")
    assert not a._handle_tool("browser_open", {"url": "https://google.com"}).get("is_error")
    a.shutdown()


# ------------------------------------------------------------------ the bridge
def _req(port, path, method="GET", body=None, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers or {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=30) as r:
            return r.status, (json.loads(r.read() or b"null") if r.status == 200 else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_link_server_round_trip_and_security(monkeypatch):
    monkeypatch.setattr(link_mod, "POLL_SECONDS", 1.0)
    port = _free_port()
    srv = link_mod.LinkServer(port)
    assert srv.start()
    try:
        assert not srv.connected()
        assert _req(port, "/poll")[0] == 403                                   # no header
        assert _req(port, "/poll", headers={"X-Teto-Link": "1", "Origin": "https://evil.example"})[0] == 403
        assert _req(port, "/poll", method="OPTIONS")[0] == 403
        ext = {"X-Teto-Link": "1", "Origin": "chrome-extension://abc"}
        assert _req(port, "/poll", headers=ext)[0] == 204                       # nothing to do
        assert srv.connected()

        def fake_extension():
            code, cmd = _req(port, "/poll", headers=ext)
            _req(port, "/result", "POST", {"id": cmd["id"], "ok": True, "result": {"echo": cmd["args"]}},
                 headers={**ext, "Content-Type": "application/json"})

        t = threading.Thread(target=fake_extension)
        t.start()
        assert srv.call("ping", x=1) == {"echo": {"x": 1}}
        t.join()

        with pytest.raises(link_mod.LinkError, match="in time"):               # nobody answers
            srv.call("ping", timeout=0.3)
        assert _req(port, "/poll", headers=ext)[0] == 204                       # the stale one was dropped
    finally:
        srv.stop()


# ------------------------------------------------------------------ user tabs over the link
class FakeLink:
    def __init__(self):
        self.calls = []
        self.tabs = [{"id": 5, "windowId": 1, "active": False, "frontWindow": True, "title": "New tab", "url": "edge://newtab"},
                     {"id": 7, "windowId": 1, "active": True, "frontWindow": True,
                      "title": "AP World History Unit 1 Practice Test", "url": "https://highschooltestprep.com/ap"},
                     {"id": 9, "windowId": 2, "active": True, "frontWindow": False, "title": "Inbox - Gmail",
                      "url": "https://mail.google.com"}]
        self.clicked = []

    def connected(self):
        return True

    def call(self, cmd, timeout=20.0, **a):
        self.calls.append((cmd, a))
        if cmd == "tabs":
            return self.tabs
        if cmd == "read":
            q = "Q2" if self.clicked else "Q1"
            return {"title": "AP Test", "url": "https://highschooltestprep.com/ap", "active": a["tabId"] != 9,
                    "visible": f"{q}. The author's point of view...", "scroll": "0 of 900",
                    "items": ['[1] clickable "Critical of the peasant class"', '[2] button "Next"']}
        if cmd == "click":
            if a["ref"] == 99:
                return "missing"
            self.clicked.append(a["ref"])
            return "ok"
        return "ok"


def test_user_tabs_work_in_the_open_tab_never_a_new_one():
    fl = FakeLink()
    ut = UserTabs(fl, None, lambda: {})
    out = ut.read("")
    assert "Your tab [7]" in out and "Q1." in out and '[1] clickable "Critical' in out   # the one they're looking at
    out = ut.click(1)
    assert "Clicked [1]" in out and "Q2." in out                  # new state comes back right away
    with pytest.raises(ActionError, match="my_tab_read again"):
        ut.click(99)
    out = ut.read("gmail")
    assert "Your tab [9]" in out and "in the background" in out
    assert all(c[0] != "open" for c in fl.calls)                  # never opened anything
    assert "[7] AP World History" in ut.tabs()


def test_user_tabs_without_link_or_windows_explains_setup():
    class Off:
        def connected(self):
            return False
    with pytest.raises(ActionError, match="Teto Link"):
        UserTabs(Off(), None).read("")


# ------------------------------------------------------------------ the real extension, end to end
QUIZ = """<!doctype html><title>AP World History Unit 1 Practice Test</title>
<style>.opt{border:1px solid #ccc;padding:8px;margin:4px;cursor:pointer}</style>
<p id=q>1. The author's point of view regarding the above passage can best be categorized as:</p>
<div class=opt onclick="pick(this)">Critical of the peasant class</div>
<div class=opt onclick="pick(this)">Sympathetic to the nobility</div>
<p id=res></p>
<label>Name <input id=name></label>
<div style="height:1500px"></div>
<button onclick="document.getElementById('q').innerText='2. Next question text'">Next</button>
<script>function pick(el){document.getElementById('res').innerText='Correct: '+el.innerText}</script>"""


@pytest.mark.skipif(not os.path.exists(CHROMIUM), reason="no Chromium available")
def test_real_extension_drives_an_existing_tab(tmp_path):
    from playwright.sync_api import sync_playwright

    srv = link_mod.shared()                       # the same server Teto runs
    if srv._httpd is None:
        pytest.skip("Teto Link port busy")
    quiz = tmp_path / "quiz.html"
    quiz.write_text(QUIZ)
    pw = sync_playwright().start()
    ctx = None
    try:
        ctx = pw.chromium.launch_persistent_context(
            str(tmp_path / "prof"), headless=False, executable_path=CHROMIUM,
            args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}", "--no-sandbox"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(quiz.as_uri())                  # the user's already-open tab
        ctx.new_page().goto("about:blank")         # ...and another tab in front of it
        end = time.monotonic() + 20
        while not srv.connected() and time.monotonic() < end:
            time.sleep(0.2)
        assert srv.connected(), "extension never connected"
        ut = UserTabs(srv, None, lambda: {})
        tabs = ut.tabs()
        assert "AP World History" in tabs
        n_pages = len(ctx.pages)

        out = ut.read("AP World")                  # a background tab, read without switching to it
        assert "1. The author's point of view" in out and "in the background" in out
        refs = {l.split("]")[0][1:]: l for l in out.splitlines() if l.startswith("[")}
        answer = next(k for k, v in refs.items() if "Critical of the peasant" in v)
        name = next(k for k, v in refs.items() if "input" in v)
        nxt = next(k for k, v in refs.items() if '"Next"' in v)
        assert "(scroll to see)" in refs[nxt]

        out = ut.click(int(answer))
        assert "Correct: Critical of the peasant class" in out
        out = ut.type(int(name), "Teto")
        assert page.input_value("#name") == "Teto"
        out = ut.click(int(nxt))
        assert "Clicked" in out and page.inner_text("#q") == "2. Next question text"
        out = ut.scroll("up", 5)
        assert "2. Next question text" in out             # scrolled back: the new question is visible
        assert len(ctx.pages) == n_pages          # no new tab, ever
    finally:
        if ctx:
            ctx.close()
        pw.stop()
