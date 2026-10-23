import asyncio

import claude_agent_sdk
import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from teto import brain_cli
from teto.agent import AgentSettings
from teto.brain_cli import CliAgent, to_computer_call, to_mcp_content
from teto.computer import ActionError, Computer, Hooks
from tests.fakes import FakeInputs, FakeScreen, RecordingUI


def result(subtype="success", is_error=False, text=None):
    return ResultMessage(subtype=subtype, duration_ms=1, duration_api_ms=1, is_error=is_error,
                         num_turns=1, session_id="s", result=text)


def say(text):
    return AssistantMessage(content=[TextBlock(text=text)], model="claude")


class FakeSDKClient:
    """Stands in for ClaudeSDKClient: scripted replies per query."""
    instances = []
    script: list = []
    fail_connect = None

    def __init__(self, options=None):
        self.options = options
        self.queries = []
        self.interrupted = False
        self.closed = False
        FakeSDKClient.instances.append(self)

    async def __aenter__(self):
        if FakeSDKClient.fail_connect:
            raise FakeSDKClient.fail_connect
        return self

    async def __aexit__(self, *a):
        self.closed = True
        return False

    async def query(self, text):
        self.queries.append(text)

    async def interrupt(self):
        self.interrupted = True

    async def receive_response(self):
        step = FakeSDKClient.script.pop(0)
        for item in step:
            if callable(item):
                await item(self)
                continue
            yield item


@pytest.fixture
def fake_sdk(monkeypatch):
    FakeSDKClient.instances = []
    FakeSDKClient.script = []
    FakeSDKClient.fail_connect = None
    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", FakeSDKClient)
    return FakeSDKClient


def make_agent(ui=None, confirm_shell=True):
    ui = ui or RecordingUI()
    inputs, screen = FakeInputs(), FakeScreen(1568, 882)
    holder = {}

    def factory():
        return Computer(hooks=Hooks(should_stop=holder["a"].stop_event.is_set), inputs=inputs, screen=screen)

    a = CliAgent(ui, factory, AgentSettings(confirm_shell=confirm_shell, max_steps=20))
    holder["a"] = a
    return a, ui, inputs


# ------------------------------------------------------------ mapping
@pytest.mark.parametrize("name,args,expected", [
    ("click", {"x": 1, "y": 2}, ("left_click", {"coordinate": [1, 2]})),
    ("click", {"x": 1, "y": 2, "clicks": 2}, ("double_click", {"coordinate": [1, 2]})),
    ("click", {"x": 1, "y": 2, "button": "right", "modifiers": "ctrl"},
     ("right_click", {"coordinate": [1, 2], "text": "ctrl"})),
    ("drag", {"start_x": 1, "start_y": 2, "x": 3, "y": 4},
     ("left_click_drag", {"start_coordinate": [1, 2], "coordinate": [3, 4]})),
    ("scroll", {"direction": "down"}, ("scroll", {"scroll_direction": "down", "scroll_amount": 3})),
    ("scroll", {"direction": "up", "amount": 5, "x": 9, "y": 8},
     ("scroll", {"scroll_direction": "up", "scroll_amount": 5, "coordinate": [9, 8]})),
    ("type_text", {"text": "hi"}, ("type", {"text": "hi"})),
    ("press_key", {"keys": "ctrl+s"}, ("key", {"text": "ctrl+s", "repeat": 1})),
    ("zoom", {"x0": 0, "y0": 0, "x1": 10, "y1": 10}, ("zoom", {"region": [0, 0, 10, 10]})),
    ("wait", {"seconds": 2}, ("wait", {"duration": 2})),
])
def test_to_computer_call(name, args, expected):
    assert to_computer_call(name, args) == expected


def test_to_computer_call_rejects_bad_input():
    with pytest.raises(ActionError):
        to_computer_call("click", {"x": 1, "y": 1, "clicks": 5})
    with pytest.raises(ActionError):
        to_computer_call("wait", {"seconds": 999})


def test_to_mcp_content_converts_images():
    out = to_mcp_content([{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                         "data": "abc"}}])
    assert out == [{"type": "image", "data": "abc", "mimeType": "image/jpeg"}]
    assert to_mcp_content("OK") == [{"type": "text", "text": "OK"}]


def test_every_tool_has_valid_schema():
    for name, (desc, schema) in brain_cli.TOOL_SPECS.items():
        assert desc and schema["type"] == "object"
        assert set(schema["required"]) <= set(schema["properties"])


# ------------------------------------------------------------- tools
def test_screenshot_tool_returns_mcp_image_and_size():
    a, ui, _ = make_agent()
    res = a._handle_tool("screenshot", {})
    assert res["content"][0]["type"] == "image" and res["content"][0]["mimeType"] == "image/jpeg"
    assert res["content"][1]["text"] == "Screenshot is 1568x882 pixels."
    a.shutdown()


def test_click_and_type_tools_drive_the_computer():
    a, ui, inputs = make_agent()
    assert "is_error" not in a._handle_tool("click", {"x": 10, "y": 20})
    a._handle_tool("type_text", {"text": "hello"})
    assert ("click", 10, 20, "left", 1) in inputs.calls and ("type", "hello") in inputs.calls
    assert ("action", "left click at (10, 20)") in ui.logs
    a.shutdown()


def test_tool_errors_are_reported_not_raised():
    a, ui, _ = make_agent()
    res = a._handle_tool("click", {"x": 99999, "y": 1})
    assert res["is_error"] and "outside the screenshot" in res["content"][0]["text"]
    res = a._handle_tool("say", {"message": ""})
    assert res["is_error"]
    a.shutdown()


def test_say_ask_and_shell_tools():
    ui = RecordingUI(answers=["Yes"], confirms=[False])
    a, ui, _ = make_agent(ui)
    a._handle_tool("say", {"message": "On it!"})
    assert ("teto", "On it!") in ui.logs
    assert a._handle_tool("ask_user", {"question": "Go?", "choices": ["Yes"]})["content"][0]["text"] == \
        "The user answered: Yes"
    res = a._handle_tool("run_shell", {"command": "echo hi"})
    assert "declined" in res["content"][0]["text"]
    a.shutdown()


def test_unanswered_question_stops_the_task():
    a, ui, _ = make_agent(RecordingUI(answers=[]))
    res = a._handle_tool("ask_user", {"question": "Go?"})
    assert res["is_error"] and a.stop_event.is_set()
    a.shutdown()


def test_shell_runs_when_approval_disabled():
    a, ui, _ = make_agent(confirm_shell=False)
    res = a._handle_tool("run_shell", {"command": "echo teto-cli-ok"})
    assert "teto-cli-ok" in res["content"][0]["text"]
    a.shutdown()


# ----------------------------------------------------------- session
def test_options_lock_down_builtin_tools(fake_sdk):
    a, ui, _ = make_agent()
    fake_sdk.script = [[say("hi"), result()]]
    assert a.run_task("hello") == "done"
    opts = fake_sdk.instances[0].options
    assert opts.tools == []
    assert opts.setting_sources == []
    assert set(opts.allowed_tools) == {f"mcp__teto__{n}" for n in brain_cli.TOOL_SPECS}
    assert "teto" in opts.mcp_servers
    assert opts.model is None              # "" -> the plan's default model
    a.shutdown()


def test_follow_up_reuses_session_and_new_chat_resets(fake_sdk):
    a, ui, _ = make_agent()
    fake_sdk.script = [[say("one"), result()], [say("two"), result()], [say("three"), result()]]
    assert a.run_task("first") == "done"
    assert a.run_task("second") == "done"
    assert len(fake_sdk.instances) == 1 and fake_sdk.instances[0].queries == ["first", "second"]
    a.new_conversation()
    assert fake_sdk.instances[0].closed
    assert a.run_task("third") == "done"
    assert len(fake_sdk.instances) == 2
    assert [t for k, t in ui.logs if k == "teto"] == ["one", "two", "three"]
    assert ui.states[-1] == "idle" and "success" in ui.states
    a.shutdown()


def test_stop_interrupts_and_reports_stopped(fake_sdk):
    a, ui, _ = make_agent()

    async def press_stop(client):
        a.stop()
        for _ in range(50):
            if client.interrupted:
                break
            await asyncio.sleep(0.01)

    fake_sdk.script = [[press_stop, result(subtype="error_during_execution", is_error=True)]]
    assert a.run_task("long task") == "stopped"
    assert fake_sdk.instances[0].interrupted
    assert ("system", "Stopped.") in ui.logs
    a.shutdown()


def test_error_results_are_friendly(fake_sdk):
    a, ui, _ = make_agent()
    fake_sdk.script = [[result(subtype="success", is_error=True, text="Invalid API key · Please run /login")]]
    assert a.run_task("x") == "error"
    assert any("Sign in with Claude" in t for k, t in ui.logs if k == "error")
    a.shutdown()


def test_max_turns(fake_sdk):
    a, ui, _ = make_agent()
    fake_sdk.script = [[result(subtype="error_max_turns", is_error=True)]]
    assert a.run_task("x") == "limit"
    a.shutdown()


def test_connection_failure_is_reported(fake_sdk):
    fake_sdk.fail_connect = claude_agent_sdk.CLINotFoundError("Claude Code not found")
    a, ui, _ = make_agent()
    assert a.run_task("x") == "error"
    assert any("couldn't find Claude Code" in t for k, t in ui.logs if k == "error")
    fake_sdk.fail_connect = None
    fake_sdk.script = [[say("ok"), result()]]
    assert a.run_task("again") == "done"       # recovers on the next task
    a.shutdown()


def test_find_cli_prefers_bundled():
    p = brain_cli.find_cli()
    assert p and "_bundled" in p


def test_hide_console_windows_adds_flag_once():
    import types

    seen = []

    async def fake_open_process(*args, **kwargs):
        seen.append(kwargs.get("creationflags"))

    mod = types.SimpleNamespace(open_process=fake_open_process)
    brain_cli.hide_console_windows(mod)
    brain_cli.hide_console_windows(mod)          # idempotent: no double wrapping
    asyncio.run(mod.open_process(["claude"]))
    asyncio.run(mod.open_process(["claude"], creationflags=0x10))
    assert seen == [brain_cli.CREATE_NO_WINDOW, 0x10]
