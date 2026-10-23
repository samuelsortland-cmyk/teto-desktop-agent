"""Tests for the pet's life: human-like input, physics, behaviours, sprites."""

import datetime as dt
import random

import pytest

from teto import behaviors, humanize, physics, sprites
from teto.computer import InputBackend, UserAbort


# ------------------------------------------------------------- humanize
@pytest.mark.parametrize("text", ["hello world", "Hello, World! How are you?", "ctrl+s isn't a key here",
                                  "https://example.com/a?b=c", "名前 émoji ✓", "", "a\nb\tc"])
def test_typing_plan_always_produces_exact_text(text):
    for seed in range(30):
        plan = humanize.plan_typing(text, random.Random(seed), typos=True, typo_rate=0.3)
        assert humanize.typed_result(plan) == text


def test_typing_has_human_rhythm():
    text = "The quick brown fox jumps over the lazy dog. " * 4
    plan = humanize.plan_typing(text, random.Random(1), wpm=90, typos=False)
    delays = [s[-1] for s in plan]
    assert all(0 < d <= 2.0 for d in delays)
    mean = sum(delays) / len(delays)
    spread = (sum((d - mean) ** 2 for d in delays) / len(delays)) ** 0.5
    assert spread / mean > 0.3                                           # not robotic
    total = sum(delays)
    assert 15 < total < 60                                               # ~90 wpm for 180 chars
    after_period = [plan[i][-1] for i, s in enumerate(plan) if i and text[i - 1] == "."]
    assert min(after_period) > sum(delays) / len(delays)                 # pauses after sentences


def test_typos_happen_and_get_fixed():
    plan = humanize.plan_typing("supercalifragilistic " * 5, random.Random(3), typo_rate=0.1)
    assert any(s[0] == "backspace" for s in plan)


def test_no_typos_when_disabled():
    plan = humanize.plan_typing("abcdefghij" * 20, random.Random(3), typos=False)
    assert not any(s[0] == "backspace" for s in plan)


def test_long_text_speeds_up():
    rng = random.Random(5)
    plan = humanize.plan_typing("a" * 1200, rng, wpm=90, typos=False)
    first = sum(s[-1] for s in plan[:200]) / 200
    last = sum(s[-1] for s in plan[-200:]) / 200
    assert last < first * 0.6


def test_mouse_path_curves_and_ends_exactly():
    pts, dur = humanize.mouse_path(0, 0, 800, 300, random.Random(2))
    assert pts[-1] == (800, 300)
    assert 0.1 < dur <= 0.75 and len(pts) >= 6
    # not a straight line: some point is off the direct line
    off = max(abs(300 * x - 800 * y) / 854 for x, y in pts)
    assert off > 3
    assert humanize.mouse_path(5, 5, 6, 6)[0] == [(6, 6)]


class _FakePG:
    def __init__(self):
        self.out = []

    def write(self, ch, _pause=True):
        self.out.append(ch)

    def press(self, key, _pause=True):
        if key == "backspace":
            self.out.pop()
        elif key == "enter":
            self.out.append("\n")
        elif key == "tab":
            self.out.append("\t")


def _backend(human=True, typos=True):
    b = object.__new__(InputBackend)
    b.pg, b.human, b.wpm, b.typos, b.rng = _FakePG(), human, 2500, typos, random.Random(7)
    return b


def test_input_backend_types_exact_text_humanly(monkeypatch):
    monkeypatch.setattr("teto.platform_win.IS_WINDOWS", False)
    b = _backend()
    b.rng = random.Random(11)
    b.type_text("Hello there friend", lambda: False)
    assert "".join(b.pg.out) == "Hello there friend"


def test_input_backend_typing_can_be_stopped(monkeypatch):
    monkeypatch.setattr("teto.platform_win.IS_WINDOWS", False)
    b = _backend()
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 3
    with pytest.raises(UserAbort):
        b.type_text("a long sentence that will be interrupted", stop)
    assert len(b.pg.out) < 10


# -------------------------------------------------------------- physics
AREA = (0, 0, 1600, 900)


def run(body, platforms=(), seconds=3.0, dt=1 / 30):
    events = []
    for _ in range(int(seconds / dt)):
        events += physics.step(body, dt, list(platforms), AREA)
    return events


def test_falls_and_lands_on_floor():
    b = physics.Body(x=800, y=100)
    ev = run(b)
    assert b.grounded and b.y == 900 and any(e[0] == "land" for e in ev)


def test_hard_fall_bounces_then_settles():
    b = physics.Body(x=800, y=-1500)
    b.vy = 2000
    ev = run(b, seconds=4)
    assert any(e[0] == "impact" for e in ev) and b.grounded


def test_fling_bounces_off_walls_and_stays_on_screen():
    b = physics.Body(x=800, y=500)
    b.launch(9000, -2000)            # clamped to MAX_FLING
    assert abs(b.vx) <= physics.MAX_FLING
    ev = run(b, seconds=6)
    assert any(e == ("bounce", "wall") for e in ev)
    assert 0 + b.half_w <= b.x <= 1600 - b.half_w and b.grounded


def test_lands_on_window_top_and_rides_it():
    win = physics.Platform(42, 300, 500, 900)
    b = physics.Body(x=600, y=200)
    run(b, [win], seconds=2)
    assert b.support == win and b.y == 500
    moved = physics.Platform(42, 400, 450, 1000)          # window dragged right and up
    physics.step(b, 1 / 30, [moved], AREA)
    assert b.y == 450 and b.x == pytest.approx(700)


def test_falls_when_window_closes_or_walks_off_edge():
    win = physics.Platform(42, 300, 500, 900)
    b = physics.Body(x=600, y=200)
    run(b, [win], seconds=2)
    ev = physics.step(b, 1 / 30, [], AREA)
    assert ("fall",) in ev and not b.grounded
    b2 = physics.Body(x=880, y=200)
    run(b2, [win], seconds=2)
    b2.walk_vx = 200
    ev = run(b2, [win], seconds=0.5)
    assert ("fall",) in ev


def test_visible_tops_clip_covered_edges_and_skip_maximised():
    wins = [(1, 400, 100, 700, 600),        # topmost
            (2, 200, 300, 1000, 800),       # its top edge is partly covered by window 1
            (3, 0, 0, 1600, 900)]           # maximised: ignored
    tops = physics.visible_tops(wins, AREA)
    assert physics.Platform(1, 400, 100, 700) in tops
    segs = sorted((p.left, p.right) for p in tops if p.key == 2)
    assert segs == [(200, 400), (700, 1000)]
    assert not any(p.key == 3 for p in tops)


def test_fling_tracker_velocity():
    t = physics.FlingTracker()
    for i in range(6):
        t.add(i * 0.016, 100 + i * 20, 500 - i * 10)
    vx, vy = t.velocity(5 * 0.016)
    assert vx == pytest.approx(1250, rel=0.01) and vy == pytest.approx(-625, rel=0.01)
    assert physics.FlingTracker().velocity(0) == (0.0, 0.0)


# ----------------------------------------------------------- behaviours
def test_library_has_over_100_valid_behaviours():
    lib = behaviors.LIBRARY
    assert len(lib) >= 100
    assert len({b.name for b in lib}) == len(lib)
    for b in lib:
        assert b.when in behaviors.CONDITIONS and b.steps and b.duration > 0
        for s in b.steps:
            assert s.move in behaviors.MOVES
            for p in s.poses:
                assert p["eyes"] in sprites.EYES and p["mouth"] in sprites.MOUTHS
                assert p["arms"] in sprites.ARMS and p["body"] in sprites.BODIES
            flat = [x for t in s.props for x in (t if isinstance(t, tuple) else (t,))]
            assert all(x in sprites.PROPS for x in flat), (b.name, flat)
            for kind, rate, at in s.fx:
                assert kind in sprites.EFFECTS and rate > 0 and (at in sprites.ANCHORS or at == "around")
        if b.task:
            assert b.tag == "helpful"


def test_conditions():
    assert behaviors.condition_met("april1", dt.datetime(2027, 4, 1, 12))
    assert not behaviors.condition_met("april1", dt.datetime(2027, 4, 2, 12))
    assert behaviors.condition_met("halloween", dt.datetime(2026, 10, 31, 20))
    assert behaviors.condition_met("night", dt.datetime(2026, 10, 31, 23, 30))
    assert behaviors.condition_met("hourly", dt.datetime(2026, 10, 31, 15, 1))
    assert behaviors.condition_met("weekend", dt.datetime(2026, 10, 24, 10))   # Saturday


def test_chooser_respects_time_cooldowns_and_variety():
    ch = behaviors.Chooser(rng=random.Random(4))
    noon = dt.datetime(2026, 7, 15, 12, 30)       # summer weekday lunchtime
    picks = [ch.pick(noon, clock=i * 30.0).name for i in range(60)]
    assert len(set(picks)) > 30
    assert "nap" not in picks and "halloween" not in picks   # wrong time / season
    for i in range(1, len(picks)):
        assert picks[i] not in picks[max(0, i - 6):i]


def test_chooser_without_helpful():
    ch = behaviors.Chooser(rng=random.Random(4), helpful=False)
    now = dt.datetime(2026, 7, 15, 9, 1)
    picks = {ch.pick(now, clock=i * 30.0).name for i in range(80)}
    helpful = {b.name for b in behaviors.LIBRARY if b.tag == "helpful"}
    assert not picks & helpful


def test_fill_placeholders():
    t = behaviors.fill("It's {time} on {day}", dt.datetime(2026, 10, 23, 9, 5))
    assert t == "It's 09:05 on Friday"


# --------------------------------------------------------------- sprites
def test_every_pose_combination_renders_same_size():
    for body in sprites.BODIES:
        for arms in sprites.ARMS:
            img = sprites.render_pose(sprites.Pose(arms=arms, body=body), 2)
            assert img.size == (sprites.FRAME_W * 2, sprites.FRAME_H * 2)
    for e in sprites.EYES:
        for m in sprites.MOUTHS:
            sprites.render_pose(sprites.Pose(eyes=e, mouth=m), 1, flip=True)


def test_feet_stay_on_the_bottom_row():
    for body in ("", "bob", "squash", "stretch", "lean_l"):
        img = sprites.render_pose(sprites.Pose(body=body), 1)
        assert img.getbbox()[3] == sprites.FRAME_H


def test_props_and_anchors():
    for name, (rows, (gx, gy), anchor) in sprites.PROPS.items():
        assert anchor in sprites.ANCHORS
        assert 0 <= gy < len(rows) and 0 <= gx < max(len(r) for r in rows), name
        img, grip = sprites.make_prop(name, 3, flip=True)
        assert img.width > 0
    for name in sprites.EFFECTS:
        sprites.make_effect(name, 2)
