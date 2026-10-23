import copy
import sys

import anthropic
import httpx2 as httpx
import pytest

from teto import agent as agent_mod
from teto.agent import NOT_EXECUTED, Agent, AgentSettings
from teto.computer import Computer, Hooks
from tests.fakes import FakeClient, FakeInputs, FakeScreen, RecordingUI, message, tool_use


def make_agent(responses, ui=None, settings=None, on_iter=None):
    ui = ui or RecordingUI()
    inputs, screen = FakeInputs(), FakeScreen(1568, 882)
    client = FakeClient(responses, on_iter=on_iter)
    holder = {}

    def factory():
        return Computer(hooks=Hooks(should_stop=holder["agent"].stop_event.is_set),
                        inputs=inputs, screen=screen)

    a = Agent(ui, factory, settings or AgentSettings(), client=client)
    holder["agent"] = a
    return a, ui, client, inputs


THINK = {"type": "thinking", "thinking": "Opening Notepad next.", "signature": "sig123"}


def test_simple_task_request_shape_and_completion():
    a, ui, client, _ = make_agent([message([{"type": "text", "text": "Hi! Done."}])])
    assert a.run_task("say hi") == "done"
    req = client.requests[0]
    assert req["model"] == "claude-opus-5-5"
    assert {"type": "computer_toolset_20260801"} in req["tools"]
    assert req["thinking"] == {"type": "adaptive", "display": "updates"}
    assert req["output_config"] == {"effort": "medium"}
    assert req["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in req["betas"]
    assert "thinking-display-updates-2026-08-18" in req["betas"]
    assert req["cache_control"] == {"type": "ephemeral"}
    # no forced tool choice (400s on Opus 5.5), no sampling params
    assert "tool_choice" not in req and "temperature" not in req
    for t in req["tools"]:
        if t.get("type") == "computer_toolset_20260801":
            assert "name" not in t and "display_width_px" not in t
    assert ("teto", "Hi! Done.") in ui.logs
    assert ui.states[-1] == "idle" and "success" in ui.states


def test_computer_batch_results_echo_toolset_and_history_is_append_only():
    responses = [
        message([THINK,
                 tool_use("t1", "left_click", {"coordinate": [100, 100]}),
                 tool_use("t2", "type", {"text": "hello"}),
                 tool_use("t3", "screenshot", {})], "tool_use"),
        message([{"type": "text", "text": "Typed hello!"}]),
    ]
    a, ui, client, inputs = make_agent(responses)
    assert a.run_task("type hello") == "done"
    second = client.requests[1]["messages"]
    # 1) the first request's messages are an exact prefix of the second's (append-only)
    first = client.requests[0]["messages"]
    assert second[:len(first)][0]["content"][0] == first[0]["content"][0]
    # 2) thinking block passed back unchanged
    assistant = second[1]
    assert assistant["role"] == "assistant"
    assert assistant["content"][0] == THINK
    assert all(b.get("toolset_name") == "computer" for b in assistant["content"][1:])
    # 3) every tool_use answered, in order, each echoing toolset_name
    results = second[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2", "t3"]
    assert all(r["toolset_name"] == "computer" for r in results)
    assert results[0]["content"] == [{"type": "text", "text": "OK"}]
    assert results[2]["content"][0]["type"] == "image"
    assert ("thought", "Opening Notepad next.") in ui.logs
    assert ("type", "hello") in inputs.calls


def test_batch_halts_at_first_failure():
    responses = [
        message([tool_use("t1", "left_click", {"coordinate": [99999, 1]}),
                 tool_use("t2", "type", {"text": "should not type"}),
                 tool_use("t3", "screenshot", {})], "tool_use"),
        message([{"type": "text", "text": "ok"}]),
    ]
    a, ui, client, inputs = make_agent(responses)
    a.run_task("x")
    results = client.requests[1]["messages"][2]["content"]
    assert results[0]["is_error"] and "outside the screenshot" in results[0]["content"]
    assert results[1] == {"type": "tool_result", "tool_use_id": "t2", "toolset_name": "computer",
                          "content": NOT_EXECUTED, "is_error": True}
    assert results[2]["content"] == NOT_EXECUTED
    assert not any(c[0] == "type" for c in inputs.calls)


def test_client_tools_say_ask_and_shell_decline():
    responses = [
        message([tool_use("s1", "say", {"message": "On it!"}, toolset=False),
                 tool_use("a1", "ask_user", {"question": "Send it?", "choices": ["Yes", "No"]}, toolset=False),
                 tool_use("r1", "run_shell", {"command": "echo hi"}, toolset=False)], "tool_use"),
        message([{"type": "text", "text": "Done"}]),
    ]
    ui = RecordingUI(answers=["Yes"], confirms=[False])
    a, ui, client, _ = make_agent(responses, ui=ui)
    a.run_task("x")
    results = client.requests[1]["messages"][2]["content"]
    assert all("toolset_name" not in r for r in results)
    assert results[0]["content"][0]["text"] == "Shown to the user."
    assert results[1]["content"][0]["text"] == "The user answered: Yes"
    assert "declined" in results[2]["content"][0]["text"]
    assert ("teto", "On it!") in ui.logs
    assert ui.asked[0] == ("Send it?", ["Yes", "No"])


def test_run_shell_executes_when_allowed():
    cmd = "echo teto-ok" if sys.platform != "win32" else "Write-Output teto-ok"
    responses = [message([tool_use("r1", "run_shell", {"command": cmd}, toolset=False)], "tool_use"),
                 message([{"type": "text", "text": "Done"}])]
    a, ui, client, _ = make_agent(responses, ui=RecordingUI(confirms=[True]))
    a.run_task("x")
    out = client.requests[1]["messages"][2]["content"][0]["content"][0]["text"]
    assert "teto-ok" in out and "[exit code 0]" in out


def test_invalid_client_tool_input_is_an_error_result():
    responses = [message([tool_use("s1", "say", {"message": ""}, toolset=False)], "tool_use"),
                 message([{"type": "text", "text": "ok"}])]
    a, _, client, _ = make_agent(responses)
    a.run_task("x")
    r = client.requests[1]["messages"][2]["content"][0]
    assert r["is_error"] and "non-empty" in r["content"]


def test_refusal_is_reported():
    a, ui, _, _ = make_agent([message([], "refusal")])
    assert a.run_task("x") == "refused"
    assert any(k == "error" for k, _ in ui.logs)


def test_max_tokens_with_partial_tool_call_never_executes_it():
    responses = [message([tool_use("t1", "type", {"text": "partial"})], "max_tokens"),
                 message([{"type": "text", "text": "continuing"}])]
    a, ui, client, inputs = make_agent(responses)
    assert a.run_task("x") == "error"
    assert not any(c[0] == "type" for c in inputs.calls)
    # follow-up message merges into the user turn holding the error results
    a.run_task("continue")
    last_user = client.requests[1]["messages"][-1]
    assert last_user["role"] == "user"
    assert last_user["content"][0]["tool_use_id"] == "t1"
    assert last_user["content"][-1] == {"type": "text", "text": "continue"}


def test_stop_during_stream_then_follow_up_keeps_valid_alternation():
    holder = {}

    def stop_now():
        holder["a"].stop()

    a, ui, client, _ = make_agent([message([{"type": "text", "text": "never seen"}]),
                                   message([{"type": "text", "text": "ok"}])], on_iter=stop_now)
    holder["a"] = a
    assert a.run_task("first") == "stopped"
    client.on_iter = None
    assert a.run_task("second") == "done"
    msgs = client.requests[1]["messages"]
    roles = [m["role"] for m in msgs]
    assert roles == ["user"]  # no orphaned assistant turn; both texts in one user turn
    texts = [b["text"] for b in msgs[0]["content"]]
    assert texts[0].endswith("first") and texts[1] == "second"


def test_step_limit():
    responses = [message([tool_use(f"t{i}", "screenshot", {})], "tool_use") for i in range(3)]
    a, ui, _, _ = make_agent(responses, settings=AgentSettings(max_steps=2))
    assert a.run_task("loop") == "limit"


def test_auth_error_is_fatal_with_helpful_message():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.AuthenticationError("bad key", response=httpx.Response(401, request=req), body=None)
    a, ui, _, _ = make_agent([err])
    assert a.run_task("x") == "error"
    assert any("API key" in t for k, t in ui.logs if k == "error")


def test_bad_request_resets_conversation():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.BadRequestError("nope", response=httpx.Response(400, request=req),
                                    body={"error": {"message": "invalid thing"}})
    a, ui, _, _ = make_agent([err])
    assert a.run_task("x") == "error"
    assert a.messages == []
    assert any("invalid thing" in t for _, t in ui.logs)


def test_connection_errors_retry(monkeypatch):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.APIConnectionError(request=req)
    a, ui, client, _ = make_agent([err, message([{"type": "text", "text": "ok"}])])
    monkeypatch.setattr(a, "_interruptible_sleep", lambda s: None)
    assert a.run_task("x") == "done"


def test_handoff_when_images_get_large(monkeypatch):
    monkeypatch.setattr(agent_mod, "MAX_REQUEST_IMAGE_BYTES", 10)
    responses = [
        message([tool_use("t1", "screenshot", {})], "tool_use"),
        message([{"type": "text", "text": "Handoff: opened Notepad, need to type."}]),
        message([{"type": "text", "text": "All done"}]),
    ]
    a, ui, client, _ = make_agent(responses)
    assert a.run_task("write a note") == "done"
    final = client.requests[2]["messages"]
    assert len(final) == 1
    assert "Handoff: opened Notepad" in final[0]["content"][0]["text"]
    assert "write a note" in final[0]["content"][0]["text"]


def test_fallbacks_only_for_supported_models():
    a, _, client, _ = make_agent([message([{"type": "text", "text": "ok"}])],
                                 settings=AgentSettings(model="claude-haiku-5-5"))
    a.run_task("x")
    assert "fallbacks" not in client.requests[0]


def test_first_message_has_timestamp_followups_do_not():
    a, _, client, _ = make_agent([message([{"type": "text", "text": "a"}]),
                                  message([{"type": "text", "text": "b"}])])
    a.run_task("one")
    a.run_task("two")
    msgs = client.requests[1]["messages"]
    assert msgs[0]["content"][0]["text"].startswith("[")
    assert msgs[2]["content"][0]["text"] == "two"
    # earlier turns identical between requests (prompt cache + preserved thinking)
    assert copy.deepcopy(client.requests[0]["messages"][0]) == msgs[0]
