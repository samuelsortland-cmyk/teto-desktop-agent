import os
import shutil
import time
import types

import pytest

from teto import background
from teto.agent import Agent, AgentSettings
from teto.app import App
from teto.background import BackgroundTools, to_playwright_combo, work_style_prompt
from teto.brain_cli import CliAgent
from teto.computer import ActionError, Computer, Hooks
from tests.fakes import FakeClient, FakeInputs, FakeScreen, RecordingUI, message, tool_use

CHROMIUM = os.environ.get("TETO_BROWSER_PATH") or shutil.which("chromium") or "/opt/pw-browsers/chromium"
HAVE_BROWSER = os.path.exists(CHROMIUM)

PAGE = """<!doctype html><html><head><title>Teto Test Shop</title></head><body>
<h1>Bread shop</h1>
<label>Name <input id="name" placeholder="Your name"></label>
<select id="kind"><option>Baguette</option><option>Melon pan</option></select>
<label><input type="checkbox" id="fresh"> Extra fresh</label>
<button id="order" onclick="document.getElementById('out').innerText =
  'Ordered ' + document.getElementById('kind').value + ' for ' + document.getElementById('name').value +
  (document.getElementById('fresh').checked ? ' (fresh)' : '')">Order</button>
<p id="out">nothing yet</p>
<a href="receipt.html" target="_blank">Open receipt</a>
<div style="height:3000px"></div><p>bottom of the page</p>
</body></html>"""


@pytest.fixture
def bg(tmp_path):
    page = tmp_path / "shop.html"
    page.write_text(PAGE)
    (tmp_path / "receipt.html").write_text("<title>Second</title><p>second page</p>")
    tools = BackgroundTools(str(tmp_path / "profile"),
                            settings=lambda: {"show_browser": False, "browser_path": CHROMIUM,
                                              "human_typing": True, "typing_wpm": 600, "typos": True})
    yield tools, page.as_uri()
    tools.shutdown()


@pytest.mark.skipif(not HAVE_BROWSER, reason="no Chromium available")
def test_background_browser_end_to_end(bg):
    tools, url = bg
    out = tools.run("browser_open", {"url": url})
    assert "Teto Test Shop" in out and "Interactive elements" in out
    refs = {line.split("]")[0][1:]: line for line in out.splitlines() if line.startswith("[")}
    name_ref = next(k for k, v in refs.items() if "Your name" in v)
    sel_ref = next(k for k, v in refs.items() if v.split()[1] == "select")
    box_ref = next(k for k, v in refs.items() if "checkbox" in v)
    btn_ref = next(k for k, v in refs.items() if '"Order"' in v)
    link_ref = next(k for k, v in refs.items() if "Open receipt" in v)

    out = tools.run("browser_type", {"ref": int(name_ref), "text": "Teto Kasane"})
    assert 'value="Teto Kasane"' in out                        # human typing (typos fixed) is exact
    tools.run("browser_select", {"ref": int(sel_ref), "option": "Melon pan"})
    tools.run("browser_click", {"ref": int(box_ref)})
    tools.run("browser_click", {"ref": int(btn_ref)})
    text = tools.run("browser_read", {})
    assert "Ordered Melon pan for Teto Kasane (fresh)" in text

    shot = tools.run("browser_screenshot", {})
    assert shot[0]["type"] == "image" and "1280x860" in shot[1]["text"]

    out = tools.run("browser_scroll", {"direction": "down", "amount": 3})
    assert "Scrolled down" in out
    tools.run("browser_press", {"keys": "ctrl+Home"})
    snap = tools.run("browser_snapshot", {})              # refs are renumbered by every snapshot
    link_ref = next(line.split("]")[0][1:] for line in snap.splitlines()
                    if line.startswith("[") and "Open receipt" in line)

    out = tools.run("browser_click", {"ref": int(link_ref)})
    assert "opened tab 2" in out and "Second" in out
    tabs = tools.run("browser_tabs", {})
    assert "tab 1" in tabs and "* tab 2" in tabs
    tools.run("browser_close_tab", {"tab": 2})
    assert "tab 2" not in tools.run("browser_tabs", {})

    with pytest.raises(ActionError, match="new browser_snapshot"):
        tools.run("browser_click", {"ref": 999})
    with pytest.raises(ActionError, match="no tab"):
        tools.run("browser_read", {"tab": 42})


@pytest.mark.skipif(not HAVE_BROWSER, reason="no Chromium available")
def test_background_browser_profile_persists(bg, tmp_path):
    tools, url = bg
    tools.run("browser_open", {"url": url})
    tools.run("browser_open", {"url": "about:blank"})
    tools.shutdown()
    # a fresh instance reuses the same profile folder (logins survive restarts)
    assert os.path.isdir(tmp_path / "profile") and os.listdir(tmp_path / "profile")


def test_window_tools_only_on_windows():
    specs = background.available_specs()
    assert "browser_open" in specs
    assert ("window_list" in specs) == background.IS_WINDOWS
    if not background.IS_WINDOWS:
        t = BackgroundTools("/tmp/x", settings=dict)
        with pytest.raises(ActionError, match="only available on Windows"):
            t.run("window_list", {})


@pytest.mark.parametrize("combo,expected", [("Return", "Enter"), ("ctrl+a", "Control+a"), ("Page_Down", "PageDown"),
                                            ("alt+Left", "Alt+ArrowLeft"), ("F5", "F5"), ("shift+Tab", "Shift+Tab")])
def test_playwright_key_mapping(combo, expected):
    assert to_playwright_combo(combo) == expected


def test_work_style_prompt():
    bgp = work_style_prompt("background", True)
    assert "do NOT take over their mouse and keyboard" in bgp and "browser_open" in bgp
    assert "Background tools" in work_style_prompt("foreground", True)
    assert work_style_prompt("background", False) == ""


def test_actor_propagates_errors_and_stop():
    a = background.Actor("t")
    assert a.call(lambda: 41 + 1) == 42
    with pytest.raises(ValueError):
        a.call(lambda: (_ for _ in ()).throw(ValueError("boom")))
    from teto.computer import UserAbort
    with pytest.raises(UserAbort):
        a.call(lambda: time.sleep(1), should_stop=lambda: True)
    a.stop()


# --------------------------------------------------- brains + gating
class FakeBG:
    def __init__(self):
        self.calls = []

    def specs(self):
        return {"browser_open": ("open", {"type": "object", "properties": {"url": {"type": "string"}},
                                          "required": ["url"]})}

    def run(self, name, args, should_stop=lambda: False):
        self.calls.append((name, args))
        return "Opened in background tab 1."


def _cli(style, confirms):
    ui = RecordingUI(confirms=confirms)
    inputs, screen = FakeInputs(), FakeScreen(1568, 882)
    h = {}
    bgt = FakeBG()
    a = CliAgent(ui, lambda: Computer(hooks=Hooks(should_stop=h["a"].stop_event.is_set), inputs=inputs,
                                      screen=screen),
                 AgentSettings(work_style=style), background=bgt)
    h["a"] = a
    return a, ui, inputs, bgt


def test_cli_background_tools_registered_and_dispatched():
    a, ui, _, bgt = _cli("background", [])
    assert "browser_open" in a.tool_specs
    res = a._handle_tool("browser_open", {"url": "example.com"})
    assert res["content"][0]["text"].startswith("Opened") and bgt.calls == [("browser_open", {"url": "example.com"})]
    assert ui.asked == []                                  # background tools never need permission
    a.shutdown()


def test_cli_foreground_needs_permission_once_per_task():
    a, ui, inputs, _ = _cli("background", [False])
    res = a._handle_tool("click", {"x": 5, "y": 5})
    assert res["is_error"] and "background tools" in res["content"][0]["text"]
    assert not any(c[0] == "click" for c in inputs.calls)
    a._fg_allowed = False
    ui.confirms = [True]
    a._handle_tool("click", {"x": 5, "y": 5})
    a._handle_tool("type_text", {"text": "hi"})
    assert len(ui.asked) == 2 and ("click", 5, 5, "left", 1) in inputs.calls
    # screenshots never ask
    a._fg_allowed = False
    a._handle_tool("screenshot", {})
    assert len(ui.asked) == 2
    a.shutdown()


def test_cli_foreground_style_never_asks():
    a, ui, inputs, _ = _cli("foreground", [])
    a._handle_tool("click", {"x": 5, "y": 5})
    assert ui.asked == [] and inputs.calls
    a.shutdown()


def test_api_brain_gates_computer_actions_and_runs_background_tools():
    responses = [
        message([tool_use("t1", "left_click", {"coordinate": [10, 10]}),
                 tool_use("b1", "browser_open", {"url": "x.com"}, toolset=False)], "tool_use"),
        message([{"type": "text", "text": "ok"}]),
    ]
    ui = RecordingUI(confirms=[False])
    inputs, screen = FakeInputs(), FakeScreen(1568, 882)
    bgt = FakeBG()
    h = {}
    a = Agent(ui, lambda: Computer(hooks=Hooks(should_stop=h["a"].stop_event.is_set), inputs=inputs, screen=screen),
              AgentSettings(work_style="background"), client=FakeClient(responses), background=bgt)
    h["a"] = a
    a.run_task("x")
    req0 = a._client.requests[0]
    assert any(t.get("name") == "browser_open" for t in req0["tools"])
    assert "do NOT take over" in req0["system"]
    results = a._client.requests[1]["messages"][2]["content"]
    assert results[0]["is_error"] and "declined" in results[0]["content"]
    assert results[1]["content"] == "Not executed: an earlier computer action in this turn failed."
    assert not inputs.calls


def test_before_input_hook_only_for_real_input():
    seen = []
    c = Computer(hooks=Hooks(before_input=lambda t: seen.append(t)), inputs=FakeInputs(), screen=FakeScreen())
    c.run("screenshot", {})
    c.run("wait", {"duration": 0})
    assert seen == []
    c.run("left_click", {"coordinate": [1, 1]})
    c.run("type", {"text": "x"})
    assert len(seen) == 2 and seen[1] > seen[0] >= 0


def test_wait_for_user_pause(monkeypatch):
    fake = types.SimpleNamespace(config=types.SimpleNamespace(work_style="background"), _eagle_active=False,
                                 agent=types.SimpleNamespace(stop_event=types.SimpleNamespace(is_set=lambda: False)))
    clock = {"idle": 0.1}
    monkeypatch.setattr("teto.platform_win.user_idle_seconds", lambda: clock["idle"])
    # user is typing: we wait until they pause
    calls = {"n": 0}

    def idle():
        calls["n"] += 1
        return 0.1 if calls["n"] < 4 else 2.0
    monkeypatch.setattr("teto.platform_win.user_idle_seconds", idle)
    t0 = time.monotonic()
    App._wait_for_user_pause(fake, last_ours=0.0)
    assert calls["n"] == 4 and time.monotonic() - t0 >= 0.3
    # the "recent input" was Teto's own: no waiting
    calls["n"] = 0
    monkeypatch.setattr("teto.platform_win.user_idle_seconds", lambda: 0.1)
    t0 = time.monotonic()
    App._wait_for_user_pause(fake, last_ours=time.monotonic())
    assert time.monotonic() - t0 < 0.1
    # foreground style never waits
    fake.config.work_style = "foreground"
    App._wait_for_user_pause(fake, last_ours=0.0)


def test_eagle_eyes_takes_screen_without_asking():
    a, ui, inputs, _ = _cli("background", [False])     # background style: a click would ask, user denies
    res = a._handle_tool("click", {"x": 5, "y": 5})
    assert res["is_error"] and len(ui.asked) == 1 and not inputs.calls
    inputs.calls.clear(); a._fg_allowed = False; ui.asked.clear()
    a.eagle = True
    a._handle_tool("click", {"x": 7, "y": 8})
    a._handle_tool("type_text", {"text": "go"})
    assert ("click", 7, 8, "left", 1) in inputs.calls and ("type", "go") in inputs.calls
    assert a.ui.asked == []                              # Eagle Eyes never prompts for input
    a.shutdown()


def test_wait_for_user_pause_skipped_in_eagle(monkeypatch):
    import types
    from teto.app import App
    fake = types.SimpleNamespace(config=types.SimpleNamespace(work_style="background"), _eagle_active=True,
                                 agent=types.SimpleNamespace(stop_event=types.SimpleNamespace(is_set=lambda: False)))
    monkeypatch.setattr("teto.platform_win.user_idle_seconds", lambda: 0.0)   # user is actively playing
    import time as _t
    t0 = _t.monotonic()
    App._wait_for_user_pause(fake, last_ours=0.0)       # must return at once, not wait for a pause
    assert _t.monotonic() - t0 < 0.1


@pytest.mark.skipif(not HAVE_BROWSER, reason="no Chromium available")
def test_open_in_own_browser_still_works_without_attach(bg):
    tools, url = bg
    out = tools.run("browser_open", {"url": url, "own_browser": True})
    assert "Teto Test Shop" in out and not tools._browser.attached


@pytest.mark.skipif(not HAVE_BROWSER, reason="no Chromium available")
def test_browser_write_types_into_focused_editor(bg, tmp_path):
    tools, _ = bg
    page = tmp_path / "editor.html"
    page.write_text('<!doctype html><title>Editor</title>'
                    '<div id="ed" contenteditable="true" style="height:200px;border:1px solid"></div>'
                    '<script>document.getElementById("ed").focus()</script>')
    tools.run("browser_open", {"url": page.as_uri()})
    out = tools.run("browser_write", {"text": "Hello Teto\nsecond line"})
    assert "Wrote" in out
    text = tools.run("browser_read", {})
    assert "Hello Teto" in text and "second line" in text


@pytest.mark.skipif(not HAVE_BROWSER, reason="no Chromium available")
def test_login_wall_detection_adds_sign_in_note(bg, tmp_path):
    tools, _ = bg
    page = tmp_path / "login.html"
    page.write_text('<!doctype html><title>Sign in - Example</title><h1>Sign in</h1>'
                    '<input type="password" placeholder="Password"><button>Next</button>')
    out = tools.run("browser_open", {"url": page.as_uri()})
    assert "[SIGN-IN NEEDED]" in out


def test_browser_write_in_specs():
    assert "browser_write" in background.available_specs()


def test_eagle_uses_fast_game_screenshot_size_and_restores():
    from teto.agent import Agent
    responses = [message([{"type": "text", "text": "done"}]), message([{"type": "text", "text": "done"}])]
    ui = RecordingUI()
    inputs, screen = FakeInputs(), FakeScreen(1920, 1080)
    h = {}
    comp = Computer(hooks=Hooks(), inputs=inputs, screen=screen, max_long_edge=1568)
    a = Agent(ui, lambda: comp, AgentSettings(work_style="foreground"), client=FakeClient(responses))
    assert comp.base_long_edge == 1568
    a.eagle = True
    a.run_task("play")
    assert comp.max_long_edge == 1280 and inputs.fast is True   # game-ready vision + input
    a.eagle = False
    a.run_task("normal", fresh=True)
    assert comp.max_long_edge == 1568 and inputs.fast is False  # restored for ordinary tasks
