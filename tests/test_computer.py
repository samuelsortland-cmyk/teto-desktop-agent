import base64
import io

import pytest
from PIL import Image

from teto.computer import (ActionError, Computer, Hooks, UserAbort, describe, fit_scale,
                           parse_combo, visual_tokens)
from tests.fakes import FakeInputs, FakeScreen


def make(w=2560, h=1440, left=0, top=0, **hook_kw):
    inputs, screen = FakeInputs(), FakeScreen(w, h, left, top)
    c = Computer(hooks=Hooks(**hook_kw), max_long_edge=1568, inputs=inputs, screen=screen)
    return c, inputs, screen


def decode(result):
    block = result[0]
    assert block["type"] == "image"
    return Image.open(io.BytesIO(base64.b64decode(block["source"]["data"])))


@pytest.mark.parametrize("w,h", [(1920, 1080), (2560, 1440), (3840, 2160), (1366, 768), (1024, 768),
                                 (5120, 1440), (1080, 1920)])
def test_screenshot_fits_model_limits(w, h):
    s = fit_scale(w, h, 2560)
    sw, sh = int(w * s), int(h * s)
    assert max(sw, sh) <= 2576
    assert visual_tokens(sw, sh) <= 4784


def test_screenshot_is_scaled_and_coordinates_map_back():
    c, inputs, _ = make(2560, 1440)
    img = decode(c.run("screenshot", {}))
    assert img.size == (1568, 882)
    c.run("left_click", {"coordinate": [784, 441]})
    assert inputs.calls[-1] == ("click", 1280, 720, "left", 1)


def test_monitor_offset_applies():
    c, inputs, _ = make(1920, 1080, left=-1920, top=0)
    c.run("left_click", {"coordinate": [0, 0]})
    assert inputs.calls[-1][1:3] == (-1920, 0)


def test_out_of_bounds_and_bad_coordinates_raise():
    c, _, _ = make()
    with pytest.raises(ActionError):
        c.run("left_click", {"coordinate": [5000, 10]})
    with pytest.raises(ActionError):
        c.run("left_click", {"coordinate": ["a", 1]})
    with pytest.raises(ActionError):
        c.run("left_click", {"coordinate": [True, 1]})


def test_all_click_variants_and_modifiers():
    c, inputs, _ = make(1568, 882)
    c.run("double_click", {"coordinate": [10, 10]})
    assert inputs.calls[-1] == ("click", 10, 10, "left", 2)
    c.run("triple_click", {"coordinate": [10, 10]})
    assert inputs.calls[-1][4] == 3
    c.run("right_click", {"coordinate": [10, 10]})
    assert inputs.calls[-1][3] == "right"
    c.run("middle_click", {"coordinate": [10, 10]})
    assert inputs.calls[-1][3] == "middle"
    inputs.calls.clear()
    c.run("left_click", {"coordinate": [5, 5], "text": "ctrl+shift"})
    assert inputs.calls == [("keydown", "ctrl"), ("keydown", "shift"), ("click", 5, 5, "left", 1),
                            ("keyup", "shift"), ("keyup", "ctrl")]
    with pytest.raises(ActionError):
        c.run("left_click", {"coordinate": [5, 5], "text": "a"})


def test_click_without_coordinate_uses_cursor():
    c, inputs, _ = make(1568, 882)
    inputs.pos = (300, 200)
    c.run("left_click", {})
    assert inputs.calls[-1] == ("click", 300, 200, "left", 1)


def test_drag_mouse_buttons_move_and_cursor_position():
    c, inputs, _ = make(1568, 882)
    c.run("left_click_drag", {"start_coordinate": [10, 10], "coordinate": [110, 60]})
    kinds = [k[0] for k in inputs.calls]
    assert kinds[0] == "move" and "down" in kinds and kinds[-1] == "up"
    assert inputs.calls[-2] == ("move", 110, 60)
    c.run("mouse_move", {"coordinate": [50, 40]})
    assert inputs.pos == (50, 40)
    assert c.run("cursor_position", {}) == "X=50,Y=40"
    c.run("left_mouse_down", {})
    c.run("left_mouse_up", {})
    assert inputs.calls[-2:] == [("down", "left"), ("up", "left")]


def test_scroll_directions():
    c, inputs, _ = make(1568, 882)
    c.run("scroll", {"scroll_direction": "down", "scroll_amount": 5, "coordinate": [100, 100]})
    assert inputs.calls[-1] == ("scroll", 0, -5, 100, 100)
    c.run("scroll", {"scroll_direction": "right", "scroll_amount": 2})
    assert inputs.calls[-1][1:3] == (2, 0)
    with pytest.raises(ActionError):
        c.run("scroll", {"scroll_direction": "sideways", "scroll_amount": 1})


def test_type_key_hold_wait():
    c, inputs, _ = make(1568, 882)
    c.run("type", {"text": "héllo 世界\n"})
    assert inputs.calls[-1] == ("type", "héllo 世界\n")
    c.run("key", {"text": "ctrl+s"})
    assert inputs.calls[-1] == ("hotkey", ("ctrl", "s"))
    c.run("key", {"text": "Return", "repeat": 3})
    assert [x for x in inputs.calls if x == ("hotkey", ("enter",))].__len__() == 3
    c.run("hold_key", {"text": "shift", "duration": 0.01})
    assert inputs.calls[-2:] == [("keydown", "shift"), ("keyup", "shift")]
    assert c.run("wait", {"duration": 0.01}) == "OK"
    with pytest.raises(ActionError):
        c.run("key", {"text": "ctrl+s", "repeat": 0})
    with pytest.raises(ActionError):
        c.run("wait", {"duration": 999})


@pytest.mark.parametrize("combo,expected", [
    ("Return", ["enter"]), ("ctrl+shift+Escape", ["ctrl", "shift", "esc"]), ("super", ["win"]),
    ("alt+Tab", ["alt", "tab"]), ("ctrl++", ["ctrl", "+"]), ("+", ["+"]), ("Page_Down", ["pagedown"]),
    ("F5", ["f5"]), ("ctrl+A", ["ctrl", "a"]), ("XF86AudioRaiseVolume", ["volumeup"]), ("KP_Enter", ["enter"]),
    ("ctrl+minus", ["ctrl", "-"]), ("BackSpace", ["backspace"]),
])
def test_parse_combo(combo, expected):
    assert parse_combo(combo) == expected


def test_parse_combo_rejects_unknown():
    with pytest.raises(ActionError):
        parse_combo("ctrl+NotAKey")
    with pytest.raises(ActionError):
        parse_combo("")


def test_zoom_returns_region_scaled_to_screenshot_size():
    c, _, screen = make(2560, 1440)
    img = decode(c.run("zoom", {"region": [0, 0, 392, 220]}))
    assert screen.grabs[-1]["width"] == 640 and screen.grabs[-1]["height"] == 359
    assert img.width <= 1568 and img.height <= 882
    assert img.width == 1568 or img.height == 882
    with pytest.raises(ActionError):
        c.run("zoom", {"region": [100, 100, 50, 50]})


def test_unknown_action():
    c, _, _ = make()
    with pytest.raises(ActionError):
        c.run("teleport", {})


def test_stop_flag_aborts():
    c, _, _ = make(should_stop=lambda: True)
    with pytest.raises(UserAbort):
        c.run("left_click", {"coordinate": [1, 1]})


def test_user_flinging_mouse_into_corner_aborts_but_agent_corner_click_does_not():
    c, inputs, _ = make(1568, 882)
    c.run("left_click", {"coordinate": [0, 881]})   # agent clicks bottom-left corner (Start)
    c.run("screenshot", {})                          # still fine: cursor is where Teto left it
    inputs.pos = (1567, 0)                           # user slams the mouse to top-right
    with pytest.raises(UserAbort):
        c.run("screenshot", {})


def test_before_pointer_hook_called_with_screen_coords():
    seen = []
    c, _, _ = make(3136, 1764, before_pointer=lambda x, y: seen.append((x, y)))
    c.run("left_click", {"coordinate": [100, 50]})
    assert seen == [(200, 100)]


def test_keyboard_guard_when_focus_is_ours():
    c, _, _ = make(focus_is_ours=lambda: True)
    with pytest.raises(ActionError, match="Teto's own chat window"):
        c.run("type", {"text": "x"})


def test_risky_key_needs_confirmation():
    c, inputs, _ = make(confirm=lambda t, d: False)
    with pytest.raises(ActionError, match="declined"):
        c.run("key", {"text": "shift+Delete"})
    c2, inputs2, _ = make(confirm=lambda t, d: True)
    c2.run("key", {"text": "shift+Delete"})
    assert inputs2.calls[-1] == ("hotkey", ("shift", "delete"))


def test_describe():
    assert describe("left_click", {"coordinate": [1, 2]}) == "left click at (1, 2)"
    assert describe("type", {"text": "x" * 100}).endswith('..."')
    assert describe("key", {"text": "ctrl+s", "repeat": 2}) == "key ctrl+s x2"


def test_every_mapped_key_is_a_valid_pyautogui_key():
    pyautogui = pytest.importorskip("pyautogui", exc_type=Exception)  # needs a display on Linux
    from teto.computer import _KEY_ALIASES

    valid = set(pyautogui.KEYBOARD_KEYS)
    bad = sorted({v for v in _KEY_ALIASES.values() if v not in valid})
    assert not bad, bad
