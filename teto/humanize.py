"""Human-like keyboard and mouse timing.

Pure functions (no OS access), so the rhythm can be unit-tested:

* `plan_typing` turns text into keystrokes with natural delays: faster inside
  familiar letter pairs, slower after punctuation and between words, occasional
  "thinking" pauses, and rare typos on neighbouring keys that are noticed and
  fixed with Backspace right away (the final text is always exactly `text`).
* `mouse_path` gives a gently curved, eased path between two points with a
  little overshoot, the way a hand moves a mouse.
"""

from __future__ import annotations

import math
import random

# Neighbouring keys on a QWERTY keyboard (for realistic typos).
_ROWS = ["1234567890-=", "qwertyuiop[]", "asdfghjkl;'", "zxcvbnm,./"]
_POS = {c: (r, i) for r, row in enumerate(_ROWS) for i, c in enumerate(row)}

_FAST_PAIRS = {
    "th", "he", "in", "er", "an", "re", "on", "at", "en", "nd", "ti", "es", "or", "te", "of", "ed",
    "is", "it", "al", "ar", "st", "to", "nt", "ng", "se", "ha", "as", "ou", "io", "le", "ve", "co",
    "me", "de", "hi", "ri", "ro", "ic", "ne", "ea", "ra", "ce", "li", "ch", "ll", "be", "ma", "si",
}


def neighbour_key(ch: str, rng: random.Random) -> str | None:
    low = ch.lower()
    if low not in _POS:
        return None
    r, i = _POS[low]
    options = []
    for dr, di in ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, 1), (1, -1)):
        rr, ii = r + dr, i + di
        if 0 <= rr < len(_ROWS) and 0 <= ii < len(_ROWS[rr]):
            options.append(_ROWS[rr][ii])
    if not options:
        return None
    wrong = rng.choice(options)
    return wrong.upper() if ch.isupper() else wrong


def plan_typing(text: str, rng: random.Random | None = None, wpm: float = 90.0,
                typos: bool = True, typo_rate: float = 0.025) -> list[tuple]:
    """Keystroke plan: [("char", c, delay_before) | ("backspace", delay_before)].

    Average speed follows `wpm` (5 characters per word). Very long text speeds
    up gradually so a page of text doesn't take forever.
    """
    rng = rng or random.Random()
    base = 60.0 / (max(10.0, wpm) * 5.0)          # seconds per character
    plan: list[tuple] = []
    prev = ""
    for i, ch in enumerate(text):
        speed_up = 1.0 + min(2.0, max(0, i - 300) / 400.0)   # long texts get quicker
        b = base / speed_up
        d = rng.lognormvariate(math.log(b), 0.35)
        pair = (prev + ch).lower()
        if pair in _FAST_PAIRS:
            d *= 0.7                                  # practised finger rolls
        if prev == ch:
            d *= 0.85
        if ch.isupper() or ch in "!@#$%^&*()_+{}|:\"<>?~":
            d *= 1.35                                 # reaching for Shift
        if prev in " ":
            d *= 1.15
        if prev in ".!?\n":
            d += rng.uniform(0.15, 0.45)              # end of a sentence
        elif prev in ",;:":
            d += rng.uniform(0.05, 0.2)
        if prev == " " and rng.random() < 0.04:
            d += rng.uniform(0.25, 0.8)               # a little "what next?" pause
        d = min(d, 1.5)

        if (typos and ch.isalpha() and len(text) > 3 and rng.random() < typo_rate
                and (wrong := neighbour_key(ch, rng)) and wrong != ch):
            plan.append(("char", wrong, d))
            plan.append(("backspace", rng.uniform(0.18, 0.45)))   # notice the mistake
            d = rng.uniform(0.08, 0.16)
        plan.append(("char", ch, d))
        prev = ch
    return plan


def typed_result(plan: list[tuple]) -> str:
    """What the plan leaves on screen (used by tests)."""
    out: list[str] = []
    for step in plan:
        if step[0] == "char":
            out.append(step[1])
        elif step[0] == "backspace" and out:
            out.pop()
    return "".join(out)


def mouse_path(x0: float, y0: float, x1: float, y1: float, rng: random.Random | None = None,
               ) -> tuple[list[tuple[int, int]], float]:
    """Curved, eased points from (x0,y0) to (x1,y1) and the total duration.

    Uses a quadratic Bezier with a random bend, ease-in-out timing, and a tiny
    overshoot that settles back on long moves."""
    rng = rng or random.Random()
    dist = math.hypot(x1 - x0, y1 - y0)
    if dist < 3:
        return [(int(round(x1)), int(round(y1)))], 0.0
    duration = min(0.75, 0.12 + 0.09 * math.log2(1 + dist / 40))   # Fitts-like
    steps = max(6, min(40, int(duration * 90)))
    nx, ny = -(y1 - y0) / dist, (x1 - x0) / dist                   # normal to the line
    bend = rng.uniform(-0.18, 0.18) * dist
    cx, cy = (x0 + x1) / 2 + nx * bend, (y0 + y1) / 2 + ny * bend
    over = rng.uniform(0.0, 0.035) if dist > 200 else 0.0
    ex, ey = x1 + (x1 - x0) * over, y1 + (y1 - y0) * over
    pts = []
    for k in range(1, steps + 1):
        t = k / steps
        t = t * t * (3 - 2 * t)                                     # ease in-out
        px = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * ex
        py = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * ey
        pts.append((int(round(px)), int(round(py))))
    if over:
        pts.append((int(round(x1)), int(round(y1))))
    if pts[-1] != (int(round(x1)), int(round(y1))):
        pts.append((int(round(x1)), int(round(y1))))
    return pts, duration
