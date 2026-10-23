"""2D physics for the pet: gravity, flings, bounces, and standing on windows.

Everything is in screen pixels with the body's position at her *feet* (centre
bottom). Pure Python with no Tk or OS access, so it is fully unit-testable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

GRAVITY = 2600.0          # px/s^2
TERMINAL = 3200.0         # px/s
WALL_BOUNCE = 0.55
CEILING_BOUNCE = 0.35
FLOOR_BOUNCE = 0.32       # hard landings bounce a little
BOUNCE_MIN = 950.0        # impacts slower than this just land
GROUND_FRICTION = 7.0     # 1/s, slide slows on the ground
AIR_DRAG = 0.15           # 1/s
MAX_FLING = 4200.0


@dataclass(frozen=True)
class Platform:
    """Something she can stand on: a horizontal edge from left to right at y=top."""
    key: object            # stable id (e.g. window handle) to ride moving windows
    left: float
    top: float
    right: float


@dataclass
class Body:
    x: float
    y: float
    half_w: float = 30.0
    height: float = 120.0
    vx: float = 0.0
    vy: float = 0.0
    support: Platform | None = None
    walk_vx: float = 0.0               # set by behaviours while grounded
    spin: float = 0.0                  # tumble angle (degrees) while flying
    events: list = field(default_factory=list)

    @property
    def grounded(self) -> bool:
        return self.support is not None

    def launch(self, vx: float, vy: float):
        speed = math.hypot(vx, vy)
        if speed > MAX_FLING:
            vx, vy = vx * MAX_FLING / speed, vy * MAX_FLING / speed
        self.vx, self.vy = vx, vy
        self.support = None


def step(b: Body, dt: float, platforms: list[Platform], bounds: tuple[float, float, float, float]) -> list:
    """Advance the body by dt seconds. Returns events: ("land", impact), ("bounce", "wall"|"ceiling"|"floor"),
    ("fall",) when the support disappears."""
    dt = max(0.0, min(dt, 0.05))           # stay stable if a frame was late
    left, top, right, bottom = bounds
    events: list = []
    platforms = list(platforms) + [Platform("floor", left, bottom, right)]

    if b.support is not None:
        p = _find(platforms, b.support.key, b.x)
        if p is None:
            b.support = None
            events.append(("fall",))
        else:
            if p != b.support:                         # the window moved: ride along
                b.x += _ride_dx(b.support, p, b.x)
                b.support = p
            b.y = p.top
            if b.walk_vx:
                b.vx = b.walk_vx
            else:
                b.vx *= math.exp(-GROUND_FRICTION * dt)
                if abs(b.vx) < 5:
                    b.vx = 0.0
            b.x += b.vx * dt
            b.vy = 0.0
            if b.x - b.half_w < left:
                b.x, b.vx = left + b.half_w, abs(b.vx) * WALL_BOUNCE
                events.append(("bounce", "wall"))
            elif b.x + b.half_w > right:
                b.x, b.vx = right - b.half_w, -abs(b.vx) * WALL_BOUNCE
                events.append(("bounce", "wall"))
            if not (p.left <= b.x <= p.right):        # walked off the edge
                b.support = None
                events.append(("fall",))
            return events

    # airborne
    b.vy = min(TERMINAL, b.vy + GRAVITY * dt)
    b.vx *= math.exp(-AIR_DRAG * dt)
    nx, ny = b.x + b.vx * dt, b.y + b.vy * dt
    if nx - b.half_w < left:
        nx, b.vx = left + b.half_w, abs(b.vx) * WALL_BOUNCE
        events.append(("bounce", "wall"))
    elif nx + b.half_w > right:
        nx, b.vx = right - b.half_w, -abs(b.vx) * WALL_BOUNCE
        events.append(("bounce", "wall"))
    if ny - b.height < top and b.vy < 0:
        ny, b.vy = top + b.height, -b.vy * CEILING_BOUNCE
        events.append(("bounce", "ceiling"))

    if b.vy > 0:
        hit = None
        for p in platforms:
            if p.left <= nx <= p.right and b.y <= p.top + 0.5 and ny >= p.top:
                if hit is None or p.top < hit.top:
                    hit = p
        if hit is None and ny >= bottom:              # never fall off the screen
            hit = platforms[-1]
        if hit is not None:
            impact = b.vy
            ny = hit.top
            if impact > BOUNCE_MIN:
                b.vy = -impact * FLOOR_BOUNCE
                b.vx *= 0.8
                events.append(("bounce", "floor"))
                events.append(("impact", impact))
            else:
                b.vy = 0.0
                b.vx *= 0.6
                b.support = hit
                b.spin = 0.0
                events.append(("land", impact))
    b.x, b.y = nx, ny
    if not b.grounded:
        b.spin = (b.spin + b.vx * dt * 0.9) % 360
    return events


def _find(platforms: list[Platform], key, x: float) -> Platform | None:
    best = None
    for p in platforms:
        if p.key == key:
            if best is None or abs((p.left + p.right) / 2 - x) < abs((best.left + best.right) / 2 - x):
                best = p
    return best


def _ride_dx(old: Platform, new: Platform, x: float) -> float:
    # Only follow horizontal moves when the whole edge shifted (window dragged),
    # not when a visible segment was clipped by another window.
    if abs((new.right - new.left) - (old.right - old.left)) < 2:
        return new.left - old.left
    return 0.0


# ------------------------------------------------------ window top edges
def visible_tops(windows: list[tuple], area: tuple[float, float, float, float],
                 min_width: float = 120) -> list[Platform]:
    """Turn window rectangles into standable platforms.

    `windows` is [(key, left, top, right, bottom), ...] in z-order, topmost first.
    Each window's top edge is clipped by windows above it, so she never stands
    on an edge you can't see. Maximised/full-screen windows are skipped."""
    a_left, a_top, a_right, a_bottom = area
    out: list[Platform] = []
    for i, (key, l, t, r, b) in enumerate(windows):
        if r - l < min_width or t <= a_top + 2 or t >= a_bottom - 4 or b - t < 40:
            continue
        segs = [(max(l, a_left), min(r, a_right))]
        for (_, l2, t2, r2, b2) in windows[:i]:
            if t2 <= t - 1 < b2:
                segs = _subtract(segs, l2, r2)
            if not segs:
                break
        for s0, s1 in segs:
            if s1 - s0 >= 40:
                out.append(Platform(key, s0, t, s1))
    return out


def _subtract(segs, l, r):
    res = []
    for a, b in segs:
        if r <= a or l >= b:
            res.append((a, b))
            continue
        if l > a:
            res.append((a, l))
        if r < b:
            res.append((r, b))
    return res


class FlingTracker:
    """Estimates release velocity from the last ~90 ms of drag samples."""

    def __init__(self, window: float = 0.09):
        self.window = window
        self.samples: list[tuple[float, float, float]] = []

    def add(self, t: float, x: float, y: float):
        self.samples.append((t, x, y))
        while self.samples and t - self.samples[0][0] > 0.25:
            self.samples.pop(0)

    def velocity(self, now: float) -> tuple[float, float]:
        recent = [s for s in self.samples if now - s[0] <= self.window]
        if len(recent) < 2:
            return 0.0, 0.0
        (t0, x0, y0), (t1, x1, y1) = recent[0], recent[-1]
        dt = max(1e-3, t1 - t0)
        return (x1 - x0) / dt, (y1 - y0) / dt
