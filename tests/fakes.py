"""Test doubles: fake screen, fake mouse/keyboard, fake Claude client."""

from __future__ import annotations

import copy

from anthropic.types.beta import BetaMessage
from PIL import Image


class FakeScreen:
    def __init__(self, w=2560, h=1440, left=0, top=0):
        self.mon = {"left": left, "top": top, "width": w, "height": h}
        self.grabs = []

    def monitor(self):
        return dict(self.mon)

    def grab(self, region):
        self.grabs.append(dict(region))
        return Image.new("RGB", (region["width"], region["height"]), (40, 80, 120))


class FakeInputs:
    def __init__(self):
        self.calls = []
        self.pos = (100, 100)

    def position(self):
        return self.pos

    def move(self, x, y, duration=0.0):
        self.pos = (int(x), int(y))
        self.calls.append(("move", int(x), int(y)))

    def click(self, x, y, button="left", clicks=1):
        self.pos = (x, y)
        self.calls.append(("click", x, y, button, clicks))

    def mouse_down(self, button="left"):
        self.calls.append(("down", button))

    def mouse_up(self, button="left"):
        self.calls.append(("up", button))

    def key_down(self, key):
        self.calls.append(("keydown", key))

    def key_up(self, key):
        self.calls.append(("keyup", key))

    def hotkey(self, keys):
        self.calls.append(("hotkey", tuple(keys)))

    def scroll(self, dx, dy, x, y):
        self.calls.append(("scroll", dx, dy, x, y))

    def type_text(self, text, should_stop):
        self.calls.append(("type", text))


def message(content, stop_reason="end_turn"):
    return BetaMessage.model_validate({
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    })


def tool_use(id_, name, inp, toolset=True):
    b = {"type": "tool_use", "id": id_, "name": name, "input": inp}
    if toolset:
        b["toolset_name"] = "computer"
    return b


class _Stream:
    def __init__(self, msg, on_iter=None):
        self.msg = msg
        self.on_iter = on_iter

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        if self.on_iter:
            self.on_iter()
        yield {"type": "message_start"}

    def get_final_message(self):
        return self.msg


class FakeClient:
    """Replays scripted responses and records a deep copy of every request."""

    def __init__(self, responses, on_iter=None):
        self.responses = list(responses)
        self.requests = []
        self.on_iter = on_iter
        outer = self

        class _Messages:
            def stream(self, **kwargs):
                outer.requests.append(copy.deepcopy(kwargs))
                if not outer.responses:
                    raise AssertionError("FakeClient ran out of scripted responses")
                r = outer.responses.pop(0)
                if isinstance(r, Exception):
                    raise r
                return _Stream(r, outer.on_iter)

        class _Beta:
            messages = _Messages()

        self.beta = _Beta()


class RecordingUI:
    def __init__(self, answers=None, confirms=None):
        self.logs = []
        self.states = []
        self.answers = list(answers or [])
        self.confirms = list(confirms or [])
        self.asked = []

    def status(self, state):
        self.states.append(state)

    def log(self, kind, text):
        self.logs.append((kind, text))

    def ask(self, question, choices):
        self.asked.append((question, choices))
        return self.answers.pop(0) if self.answers else None

    def confirm(self, title, detail):
        self.asked.append((title, detail))
        return self.confirms.pop(0) if self.confirms else False
