"""The desktop pet: a transparent, always-on-top pixel Teto with physics.

* Gravity, flinging (throw her!), wall/ceiling bounces, tumbling in the air,
  landing on top of your windows and riding them when they move.
* 140+ idle behaviours from behaviors.py, eyes that follow your cursor,
  blinking, head pats (wiggle the mouse over her head), naps when you're away.
* Agent moods while she works: thinking, working (laptop), talking, waiting
  for you, success and error.
"""

from __future__ import annotations

import datetime as _dt
import math
import random
import sys
import time
import tkinter as tk

from PIL import ImageTk

from . import behaviors, physics, platform_win, sprites
from .sprites import FRAME_H, FRAME_W, GRID_H, GRID_W, OFF_X, OFF_Y, Pose

TRANSPARENT = "#ff00fe"
FPS_MS = 33
SLEEP_AFTER_S = 300          # nap when you've been away this long
LOCOMOTION = {"walk", "run", "tiptoe", "moonwalk", "dash", "chase_cursor", "to_window", "teleport"}

# Particle motion: kind -> (vx range, vy range, gravity, life seconds)
_RISE = ((-25, 25), (-70, -40), 0, 1.4)
PARTICLE_PHYSICS = {
    "crumb": ((-60, 60), (-60, 0), 500, 0.9), "tear": ((-20, 20), (0, 30), 400, 0.9),
    "drop": ((-20, 20), (10, 40), 600, 0.9), "rain": ((-10, 0), (220, 300), 0, 1.0),
    "snow": ((-20, 20), (25, 45), 0, 2.2), "petal": ((-30, 30), (20, 45), 0, 2.2),
    "leaf": ((-35, 35), (20, 50), 0, 2.2), "confetti_r": ((-90, 90), (-160, -60), 380, 1.6),
    "confetti_y": ((-90, 90), (-160, -60), 380, 1.6), "confetti_b": ((-90, 90), (-160, -60), 380, 1.6),
    "confetti_g": ((-90, 90), (-160, -60), 380, 1.6), "dust": ((-60, 60), (-30, -10), 0, 0.6),
    "juggle_r": ((-60, 60), (-260, -200), 520, 0.9), "juggle_y": ((-60, 60), (-260, -200), 520, 0.9),
    "juggle_b": ((-60, 60), (-260, -200), 520, 0.9), "fish": ((30, 60), (-260, -200), 600, 0.9),
    "plane": ((160, 220), (-30, -10), 0, 1.6), "flash": ((0, 0), (0, 0), 0, 0.25),
    "firework_r": ((-50, 50), (-90, -40), 0, 1.0), "firework_y": ((-50, 50), (-90, -40), 0, 1.0),
    "firework_b": ((-50, 50), (-90, -40), 0, 1.0), "tap": ((-40, 40), (-50, -20), 0, 0.35),
    "sweat": ((10, 40), (-40, -10), 300, 0.8), "bang": ((0, 0), (-25, -10), 0, 0.8),
    "smoke": ((-15, 15), (-40, -20), 0, 1.2),
}

OUCH = ("Waaah~!", "Ow ow ow...", "Hey! Gentle!", "Dizzyyy~", "Wheee— oof!", "My drills!")
WHEE = ("Wheee!", "Kyaa~!", "I can fly!", "Waaa!")


def _window_bg() -> str:
    # Windows keys this colour out (per-pixel transparency); elsewhere a soft sky blue.
    return TRANSPARENT if sys.platform == "win32" else "#c9e4f2"


def pixel_font(root) -> tuple:
    from tkinter import font as tkfont

    fams = set(tkfont.families(root))
    for fam in ("Press Start 2P", "Pixel Operator", "Consolas", "Cascadia Mono", "Lucida Console",
                "DejaVu Sans Mono", "Courier New", "Courier"):
        if fam in fams:
            return (fam, 10, "bold")
    return ("TkFixedFont", 10, "bold")


class Particle:
    __slots__ = ("item", "x", "y", "vx", "vy", "g", "life", "wobble")

    def __init__(self, item, x, y, vx, vy, g, life):
        self.item, self.x, self.y, self.vx, self.vy, self.g, self.life = item, x, y, vx, vy, g, life
        self.wobble = random.uniform(0, 6.28)


class SpeechBubble:
    """A pixel-styled speech bubble that floats above the pet. Can be clickable."""

    def __init__(self, root: tk.Tk, font):
        self.root = root
        self.font = font
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.canvas = tk.Canvas(self.win, highlightthickness=0, bd=0, bg=_window_bg())
        self.canvas.pack()
        if sys.platform == "win32":
            self.win.attributes("-transparentcolor", TRANSPARENT)
        self.canvas.bind("<Button-1>", self._clicked)
        self._hide_job = None
        self._on_click = None
        self.visible = False
        self._captured_excluded = False

    def show(self, text: str, anchor_x: int, anchor_y: int, seconds: float | None = None, on_click=None):
        text = " ".join(text.split())
        if len(text) > 220:
            text = text[:217] + "..."
        self._on_click = on_click
        c = self.canvas
        c.delete("all")
        tid = c.create_text(0, 0, text=text, font=self.font, width=230, anchor="nw", fill="#341422")
        x0, y0, x1, y1 = c.bbox(tid)
        pad, b = 10, 3
        w, h = (x1 - x0) + pad * 2 + b * 2, (y1 - y0) + pad * 2 + b * 2
        tail = 12
        c.config(width=w, height=h + tail, cursor="hand2" if on_click else "")
        ink, paper, shade = "#341422", "#fff6f8", ("#ffd98a" if on_click else "#ffc9d6")
        c.create_rectangle(b * 2, 0, w - b * 2, h, fill=ink, outline="")
        c.create_rectangle(0, b * 2, w, h - b * 2, fill=ink, outline="")
        c.create_rectangle(b, b, w - b, h - b, fill=ink, outline="")
        c.create_rectangle(b * 2, b, w - b * 2, h - b, fill=paper, outline="")
        c.create_rectangle(b, b * 2, w - b, h - b * 2, fill=paper, outline="")
        c.create_rectangle(b * 2, h - b * 3, w - b * 2, h - b, fill=shade, outline="")
        tx = w // 2
        for i in range(4):
            c.create_rectangle(tx - 8 + i * 3, h - b + i * 3, tx + 4 - i * 1, h + i * 3 + 3, fill=ink, outline="")
        for i in range(3):
            c.create_rectangle(tx - 5 + i * 3, h - b - 1 + i * 3, tx + 1 - i * 1, h + i * 3, fill=paper, outline="")
        c.tag_raise(tid)
        c.coords(tid, pad + b, pad + b)
        x, y = self._clamp(anchor_x - w / 2, anchor_y - h - tail, w)
        self.win.geometry(f"{w}x{h + tail}+{x}+{y}")
        self.win.deiconify()
        self.win.lift()
        if not self._captured_excluded:
            self._captured_excluded = platform_win.exclude_from_capture(self.win)
        self.visible = True
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
        secs = seconds if seconds is not None else min(10.0, 2.8 + len(text) * 0.05)
        if on_click:
            secs = max(secs, 9.0)
        self._hide_job = self.root.after(int(secs * 1000), self.hide)

    def _clicked(self, _e):
        cb = self._on_click
        self.hide()
        if cb:
            cb()

    def follow(self, anchor_x: int, anchor_y: int):
        if not self.visible:
            return
        w, h = self.win.winfo_width(), self.win.winfo_height()
        x, y = self._clamp(anchor_x - w / 2, anchor_y - h, w)
        self.win.geometry(f"+{x}+{y}")

    def _clamp(self, x, y, w) -> tuple[int, int]:
        sw = self.root.winfo_screenwidth()
        return int(min(max(0, x), sw - w)), int(max(0, y))

    def hide(self):
        self._hide_job = None
        self._on_click = None
        self.visible = False
        self.win.withdraw()


class Pet:
    def __init__(self, root: tk.Tk, app, scale: int = 6, custom_sprite: str | None = None):
        self.root = root
        self.app = app
        self.scale = scale
        self.font = pixel_font(root)
        self.custom = sprites.load_custom(custom_sprite, scale) if custom_sprite else None
        self._frames: dict = {}
        self._props: dict = {}
        self._fx: dict = {}

        self.mx, self.mt, self.mb = 11 * scale, 14 * scale, 1
        self.fw = FRAME_W * scale
        self.cw = self.fw + 2 * self.mx
        self.ch = FRAME_H * scale + self.mt + self.mb

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.title("Teto")
        self.canvas = tk.Canvas(self.win, width=self.cw, height=self.ch, highlightthickness=0, bd=0,
                                bg=_window_bg())
        self.canvas.pack()
        if sys.platform == "win32":
            self.win.attributes("-transparentcolor", TRANSPARENT)
        self.sprite_item = self.canvas.create_image(self.mx, self.mt, anchor="nw")
        self.prop_items: dict = {}
        self.particles: list[Particle] = []
        self.bubble = SpeechBubble(root, self.font)

        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.area = platform_win.work_area(sw, sh)
        left, top, right, bottom = self.area
        self.body = physics.Body(x=right - 200, y=top + 40, half_w=10 * scale, height=GRID_H * scale)
        self.platforms: list[physics.Platform] = []
        self._next_platform_scan = 0.0

        # state
        self.mood = "idle"            # agent / reaction mood
        self.base_mood = "idle"
        self.mood_until = 0.0
        self.facing = 1
        self.hidden = False
        self.now = time.monotonic()
        self.last_interaction = self.now
        self.next_blink = self.now + 2.0
        self.blink_until = 0.0
        self.chooser = behaviors.Chooser(helpful=getattr(app.config, "reminders", True))
        self.behavior: behaviors.Behavior | None = None
        self.b_start = 0.0
        self.b_step = -1
        self.rest_until = self.now + 3.0
        self.fx_acc: dict = {}
        self.render_dy = 0.0
        self.render_dx = 0.0
        self.last_hop = 0.0
        self.walk_target: float | None = None
        self.fling_times: list[float] = []
        self.last_ouch = 0.0
        self.pat_motion: list[tuple[float, int]] = []
        self.last_pat = 0.0
        self._key = None
        self._pos = None
        self._after_landing = None

        # input
        self._press = None
        self._dragging = False
        self._grab = (0.0, 0.0)
        self.tracker = physics.FlingTracker()
        c = self.canvas
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<Button-3>", self._on_right)
        c.bind("<Double-Button-1>", lambda e: self.app.toggle_panel(force_show=True))
        c.bind("<Motion>", self._on_hover)

        self._place(force=True)
        self.win.after(200, lambda: platform_win.exclude_from_capture(self.win))
        self._last_tick = time.monotonic()
        self._tick()

    # ------------------------------------------------------------ images
    def _frame_image(self, pose: dict, flip: bool):
        key = (pose["eyes"], pose["mouth"], pose["arms"], pose["body"], flip)
        img = self._frames.get(key)
        if img is None:
            p = Pose(eyes=pose["eyes"], mouth=pose["mouth"], arms=pose["arms"], body=pose["body"])
            img = ImageTk.PhotoImage(sprites.render_pose(p, self.scale, flip=flip, custom=self.custom))
            self._frames[key] = img
        return img

    def _prop_image(self, name: str, flip: bool):
        key = (name, flip)
        if key not in self._props:
            img, grip = sprites.make_prop(name, self.scale, flip)
            self._props[key] = (ImageTk.PhotoImage(img), grip)
        return self._props[key]

    def _fx_image(self, kind: str):
        if kind not in self._fx:
            self._fx[kind] = ImageTk.PhotoImage(sprites.make_effect(kind, max(2, self.scale - 2)))
        return self._fx[kind]

    # ---------------------------------------------------------- geometry
    def _win_xy(self) -> tuple[int, int]:
        return (int(self.body.x - self.cw / 2), int(self.body.y - (self.mt + FRAME_H * self.scale)))

    def _place(self, force: bool = False):
        pos = self._win_xy()
        if force or pos != self._pos:
            self._pos = pos
            self.win.geometry(f"{self.cw}x{self.ch}+{pos[0]}+{pos[1]}")
            self.bubble.follow(*self.head_anchor())

    def head_anchor(self) -> tuple[int, int]:
        return int(self.body.x), int(self.body.y - GRID_H * self.scale - 4)

    def rect(self) -> tuple[int, int, int, int]:
        """Screen rectangle of the visible sprite (for dodging clicks)."""
        x0 = int(self.body.x - GRID_W * self.scale / 2)
        return x0, int(self.body.y - GRID_H * self.scale - 20), x0 + GRID_W * self.scale, int(self.body.y)

    def _anchor_canvas(self, name: str) -> tuple[float, float]:
        if name == "around":
            return (self.cw / 2 + random.uniform(-0.45, 0.45) * GRID_W * self.scale,
                    self.mt + random.uniform(0.1, 0.9) * FRAME_H * self.scale)
        ax, ay = sprites.anchor_point(name, flip=self.facing < 0)
        return (self.mx + ax * self.scale + self.scale / 2 + self.render_dx,
                self.mt + ay * self.scale + self.scale / 2 + self.render_dy)

    def dodge(self, px: int, py: int):
        """Hop out of the way if the agent is about to click under us."""
        x0, y0, x1, y1 = self.rect()
        pad = 30
        if not (x0 - pad <= px <= x1 + pad and y0 - pad <= py <= y1 + pad):
            return
        left, top, right, bottom = self.area
        self.body.x = left + 120 if px > (left + right) / 2 else right - 120
        self.body.y = bottom
        self.body.vx = self.body.vy = 0.0
        self.body.support = physics.Platform("floor", left, bottom, right)
        self.behavior = None
        self._place()
        self._burst("sweat", 2)

    # ---------------------------------------------------------- reactions
    def say(self, text: str, seconds: float | None = None, on_click=None):
        self.bubble.show(text, *self.head_anchor(), seconds=seconds, on_click=on_click)
        if self.mood in ("idle", "sleeping") and not self.behavior:
            self.set_mood("talking", 1.2 + min(4.0, len(text) * 0.04))

    def set_mood(self, mood: str, seconds: float | None = None):
        now = time.monotonic()
        if seconds is None:
            self.base_mood = mood
            if self.mood_until and now < self.mood_until:
                return
            self.mood = mood
            self.mood_until = 0.0
        else:
            self.mood = mood
            self.mood_until = now + seconds
        if mood != "idle":
            self.behavior = None
            self.body.walk_vx = 0.0
        if mood == "success":
            self._hop(-700)
            self._burst("star", 5)
            self._burst("confetti_r", 6)
            self._burst("confetti_y", 6)
        elif mood == "happy":
            self._hop(-450)
            self._burst("heart", 4)
        elif mood == "error":
            self._burst("sweat", 2)
        elif mood == "waiting":
            self._burst("bang", 1)

    def poke(self):
        self.last_interaction = time.monotonic()

    def play(self, name: str):
        """Start a specific behaviour now (used by the menu and tests)."""
        self.behavior = behaviors.by_name(name)
        self._start_behavior()

    # ------------------------------------------------------------- input
    def _on_press(self, e):
        self.poke()
        self._press = (e.x_root, e.y_root)
        self._grab = (e.x_root - self.body.x, e.y_root - self.body.y)
        self._dragging = False
        self.tracker = physics.FlingTracker()
        self.tracker.add(time.monotonic(), e.x_root, e.y_root)

    def _on_drag(self, e):
        if not self._press:
            return
        if not self._dragging and abs(e.x_root - self._press[0]) + abs(e.y_root - self._press[1]) > 5:
            self._dragging = True
            self.behavior = None
            self.body.support = None
            self.body.walk_vx = 0.0
            if self.bubble.visible:
                self.bubble.hide()
        if self._dragging:
            self.tracker.add(time.monotonic(), e.x_root, e.y_root)
            self.body.x = e.x_root - self._grab[0]
            self.body.y = e.y_root - self._grab[1]
            self.body.vx = self.body.vy = 0.0
            self._place()

    def _on_release(self, e):
        was_drag = self._dragging
        self._press = None
        self._dragging = False
        self.poke()
        if was_drag:
            vx, vy = self.tracker.velocity(time.monotonic())
            self.body.launch(vx, vy)
            if math.hypot(vx, vy) > 900:
                now = time.monotonic()
                self.fling_times = [t for t in self.fling_times if now - t < 30] + [now]
                if len(self.fling_times) >= 4:
                    self.fling_times.clear()
                    self._after_landing = ("pout", None)
                elif random.random() < 0.5:
                    self.say(random.choice(WHEE), 1.6)
            return
        if self.mood == "sleeping":
            self.set_mood("idle")
            self.say("Huh?! I'm awake! ♪", 2.5)
            return
        self.set_mood("happy", 1.6)
        self.app.toggle_panel()

    def _on_right(self, e):
        self.poke()
        self.app.show_menu(e.x_root, e.y_root)

    def _on_hover(self, e):
        """Wiggle the mouse over her head to pat her."""
        hx0, hy0, hx1, _ = self.rect()
        if not (hx0 <= e.x_root <= hx1 and hy0 <= e.y_root <= hy0 + 16 * self.scale) or self._press:
            return
        now = time.monotonic()
        self.pat_motion = [(t, x) for t, x in self.pat_motion if now - t < 1.2] + [(now, e.x_root)]
        travel = sum(abs(b[1] - a[1]) for a, b in zip(self.pat_motion, self.pat_motion[1:]))
        if travel > 22 * self.scale and now - self.last_pat > 3:
            self.last_pat = now
            self.pat_motion.clear()
            self.poke()
            if self.mood == "sleeping":
                self.set_mood("idle")
            self.set_mood("patted", 1.8)
            self._burst("heart", 5)
            self.say(random.choice(("Ehehe~ ♪", "*happy drill wiggle*", "Mmm, more pats!", "Hehe, that tickles!")), 2.2)

    # -------------------------------------------------------- particles
    def _emit(self, kind: str, x: float, y: float):
        if len(self.particles) > 80:
            return
        (vx0, vx1), (vy0, vy1), g, life = PARTICLE_PHYSICS.get(kind, _RISE)
        item = self.canvas.create_image(x, y, image=self._fx_image(kind))
        self.particles.append(Particle(item, x, y, random.uniform(vx0, vx1), random.uniform(vy0, vy1), g,
                                       life * random.uniform(0.8, 1.2)))

    def _burst(self, kind: str, n: int, at: str = "around"):
        for _ in range(n):
            x, y = self._anchor_canvas(at)
            self._emit(kind, x, y)

    def _update_particles(self, dt: float):
        alive = []
        for p in self.particles:
            p.life -= dt
            if p.life <= 0:
                self.canvas.delete(p.item)
                continue
            p.wobble += dt * 6
            p.vy += p.g * dt
            p.x += (p.vx + math.sin(p.wobble) * 12) * dt
            p.y += p.vy * dt
            self.canvas.coords(p.item, p.x, p.y)
            alive.append(p)
        self.particles = alive

    # ------------------------------------------------------------ physics
    def _hop(self, vy: float, vx: float = 0.0):
        if self.body.grounded:
            self.body.launch(vx, vy)

    def _scan_platforms(self):
        if self.now < self._next_platform_scan:
            return
        self._next_platform_scan = self.now + 0.3
        if not getattr(self.app.config, "stand_on_windows", True):
            self.platforms = []
            return
        wins = platform_win.list_windows(exclude=getattr(self.app, "_our_hwnds", set()))
        self.platforms = physics.visible_tops(wins, self.area)

    def _physics(self, dt: float):
        if self._dragging:
            return
        self._scan_platforms()
        for ev in physics.step(self.body, dt, self.platforms, self.area):
            kind = ev[0]
            if kind == "land":
                if ev[1] > 500:
                    self.set_mood("landed", 0.18)
                    self._burst("dust", 4, "feet")
                if self._after_landing:
                    self._after_landing = None
                    self.set_mood("pout", 2.2)
                    self.say("Stop flinging me around! Hmph!", 2.5)
            elif kind == "impact" and ev[1] > 1700:
                self.set_mood("dizzy", 1.8)
                self._burst("star", 4, "head")
                if self.now - self.last_ouch > 4:
                    self.last_ouch = self.now
                    self.say(random.choice(OUCH), 1.8)
            elif kind == "bounce" and ev[1] == "wall" and abs(self.body.vx) > 600:
                self._burst("sweat", 1)
            elif kind == "fall" and not self.behavior:
                self.set_mood("surprised", 0.6)

    # -------------------------------------------------------------- loop
    def _tick(self):
        try:
            now = time.monotonic()
            dt = min(0.05, now - self._last_tick)
            self._last_tick = now
            self.now = now
            self._step(dt)
        except tk.TclError:
            return      # window destroyed during shutdown
        self.root.after(FPS_MS, self._tick)

    def _step(self, dt: float):
        if self.mood_until and self.now >= self.mood_until:
            self.mood_until = 0.0
            self.mood = self.base_mood
        busy = self.app.agent_busy()
        if (self.mood == "idle" and not busy and self.body.grounded and not self.behavior
                and self.now - self.last_interaction > SLEEP_AFTER_S
                and platform_win.user_idle_seconds() > SLEEP_AFTER_S):
            self.set_mood("sleeping")

        self._physics(dt)
        self.render_dx = 0.0
        self.render_dy = 0.0
        pose, props, fxs = self._decide(busy, dt)
        self._emit_fx(fxs, dt)

        if self.hidden:
            self.canvas.itemconfigure(self.sprite_item, state="hidden")
        else:
            self.canvas.itemconfigure(self.sprite_item, state="normal")
            key = (tuple(pose.values()), self.facing < 0)
            if key != self._key:
                self._key = key
                self.canvas.itemconfigure(self.sprite_item, image=self._frame_image(pose, self.facing < 0))
            self.canvas.coords(self.sprite_item, self.mx + self.render_dx, self.mt + self.render_dy)
        self._draw_props(props if not self.hidden else ())
        self._update_particles(dt)
        self._place()

    # ------------------------------------------------------ what to show
    def _decide(self, busy: bool, dt: float) -> tuple[dict, list, list]:
        b, now, t = self.body, self.now, self.now
        P = behaviors.P
        if self._dragging:
            self.behavior = None
            arms = "up_both" if int(t * 8) % 2 else "down"
            if int(t * 10) % 7 == 0:
                self._burst("sweat", 1, "head")
            return P("wide", "open", arms), [], []
        if not b.grounded and math.hypot(b.vx, b.vy) > 250:
            speed = math.hypot(b.vx, b.vy)
            if speed > 1500:
                rot = ("", "rot90", "rot180", "rot270")[int(b.spin // 90) % 4]
                return P("dizzy", "open", "up_both", rot), [], [("sparkle", 6, "around")]
            self.facing = 1 if b.vx >= 0 else -1
            return P("wide", "open", "up_both" if int(t * 10) % 2 else "down"), [], []

        mood = self.mood
        reaction = {
            "landed": (P("closed", "flat", body="squash"), [], []),
            "surprised": (P("wide", "o", "up_both"), [], [("bang", 3, "head")]),
            "dizzy": (P("dizzy", "wobble"), [], [("star", 3, "head")]),
            "pout": (P("angry", "frown"), [], [("anger", 2, "head")]),
            "patted": (P("happy", "cat"), [], [("heart", 2, "head")]),
            "happy": (P("happy", "open", "up_both" if int(t * 6) % 2 else "down"), [], [("heart", 3, "head")]),
            "talking": (P(mouth="open" if int(t * 7) % 2 else "smile"), [], []),
            "success": (P("happy", "open", "up_both", "bob" if int(t * 6) % 2 else ""), [],
                        [("sparkle", 6, "around"), ("confetti_y", 3, "above")]),
            "error": (P("dizzy", "wobble"), [], [("sweat", 1.5, "head")]),
            "thinking": (P("look_u" if int(t * 1.2) % 3 else "blink", "o"), [],
                         [("dot", 2.5, "above")] + ([("bulb", 0.4, "above")] if int(t) % 5 == 0 else [])),
            "working": (P("open", "chew" if int(t * 6) % 2 else "flat", body="bob" if int(t * 7) % 2 else ""),
                        ["laptop"], [("tap", 7, "front"), ("gear", 0.8, "head")]),
            "waiting": (P("happy", "o", "wave_r" if int(t * 4) % 2 else "up_r"), [], [("question", 0.8, "head")]),
            "sleeping": (P("closed", "o" if int(t * 0.8) % 2 else "smile", body="lie_r"), ["pillow"],
                         [("z", 0.7, "above")]),
        }
        if mood in reaction:
            pose, props, fxs = reaction[mood]
            if mood == "working":
                self.render_dx = (1, -1, 0)[int(t * 30) % 3] * (self.scale // 3)    # busy buzz
            b.walk_vx = 0.0
            return pose, props, fxs

        if busy or not b.grounded:
            return self._idle_face(P(), now), [], []

        # idle life
        if self.behavior is None:
            if now >= self.rest_until:
                lib = behaviors.LIBRARY
                if not getattr(self.app.config, "wander", True):
                    lib = [x for x in lib if not any(s.move in LOCOMOTION or (s.move == "hop" and s.speed)
                                                     for s in x.steps)]
                self.chooser.helpful = getattr(self.app.config, "reminders", True)
                self.behavior = self.chooser.pick(_dt.datetime.now(), now, lib)
                self._start_behavior()
            else:
                b.walk_vx = 0.0
                pose = P(body="bob" if int(t * 1.6) % 2 else "")
                return self._idle_face(pose, now), [], []
        return self._run_behavior(now, dt)

    def _idle_face(self, pose: dict, now: float) -> dict:
        """Blink now and then, and look toward the mouse pointer."""
        pose = dict(pose)
        if pose["eyes"] in ("open", "wide"):
            try:
                px, py = self.root.winfo_pointerxy()
                dx, dy = px - self.body.x, py - (self.body.y - GRID_H * self.scale * 0.7)
                if math.hypot(dx, dy) < 900:
                    if dy < -abs(dx) * 1.2 and dy < -60:
                        pose["eyes"] = "look_u"
                    elif dx * self.facing < -40:
                        pose["eyes"] = "look_l" if self.facing > 0 else "look_r"
                    elif dx * self.facing > 40:
                        pose["eyes"] = "look_r" if self.facing > 0 else "look_l"
            except tk.TclError:
                pass
        if now >= self.next_blink:
            self.blink_until = now + 0.13
            self.next_blink = now + random.uniform(2.0, 5.5)
        if now < self.blink_until and pose["eyes"] in ("open", "wide", "look_l", "look_r", "look_u"):
            pose["eyes"] = "blink"
        return pose

    def _start_behavior(self):
        self.b_start = self.now
        self.b_step = -1
        self.fx_acc = {}

    def _end_behavior(self):
        self.behavior = None
        self.body.walk_vx = 0.0
        self.hidden = False
        self.rest_until = self.now + random.uniform(1.5, 5.0)

    def _run_behavior(self, now: float, dt: float):
        beh = self.behavior
        elapsed = now - self.b_start
        acc, idx = 0.0, None
        for i, s in enumerate(beh.steps):
            if elapsed < acc + s.dur:
                idx = i
                break
            acc += s.dur
        if idx is None:
            if self.hidden:
                self._finish_teleport()
            self._end_behavior()
            return self._idle_face(behaviors.P(), now), [], []
        step = beh.steps[idx]
        local = elapsed - acc
        if idx != self.b_step:
            if self.hidden and self.b_step >= 0 and beh.steps[self.b_step].move == "teleport":
                self._finish_teleport()
            self.b_step = idx
            self._enter_step(step, beh)
        self._move(step, local, dt)
        pose = step.poses[int(local / max(0.05, step.period)) % len(step.poses)]
        props = step.props
        if props and isinstance(props[0], tuple):
            props = props[int(local / max(0.05, step.prop_period)) % len(props)]
        if pose["body"] in ("lie_l", "lie_r", "upside", "rot90", "rot180", "rot270"):
            props = [p for p in props if sprites.PROPS[p][2].startswith("ground")]
        return self._idle_face(pose, now), list(props), list(step.fx)

    def _enter_step(self, step: behaviors.Step, beh: behaviors.Behavior):
        if step.say:
            text = behaviors.fill(random.choice(step.say), _dt.datetime.now())
            on_click = None
            if beh.task:
                on_click = (lambda task=beh.task: self.app.submit_task(task, from_suggestion=True))
            self.say(text, on_click=on_click)
        left, _, right, _ = self.area
        b = self.body
        if step.move in ("walk", "run", "tiptoe", "moonwalk", "dash", "hop"):
            if step.speed < 0:
                self.facing = -self.facing                       # turn around (zoomies)
            elif b.x < left + 250:
                self.facing = 1
            elif b.x > right - 250:
                self.facing = -1
            else:
                self.facing = random.choice((-1, 1))
        if step.move == "jump":
            self._hop(-900)
        elif step.move == "bigjump":
            self._hop(-1350)
        elif step.move == "to_window":
            self._jump_to_window()
        elif step.move == "teleport":
            self.hidden = True
            self._burst("sparkle", 8)

    def _move(self, step: behaviors.Step, local: float, dt: float):
        b = self.body
        move, speed = step.move, abs(step.speed) * self.scale / 6
        b.walk_vx = 0.0
        if move in ("walk", "run", "tiptoe", "dash"):
            b.walk_vx = self.facing * speed
        elif move == "moonwalk":
            b.walk_vx = -self.facing * speed                    # face one way, glide the other
        elif move == "chase_cursor":
            try:
                px, _ = self.root.winfo_pointerxy()
            except tk.TclError:
                px = b.x
            if abs(px - b.x) > 40:
                self.facing = 1 if px > b.x else -1
                b.walk_vx = self.facing * speed
        elif move == "hop":
            if b.grounded and self.now - self.last_hop > max(0.25, step.period):
                self.last_hop = self.now
                b.launch(self.facing * speed, -480)
        elif move == "float":
            self.render_dy = -min(1.0, local / 0.6) * 5 * self.scale + math.sin(local * 3) * self.scale
        elif move == "shake":
            self.render_dx = random.choice((-1, 1)) * (self.scale // 2)
        elif move == "spin":
            self.facing = 1 if int(local / max(0.05, step.period)) % 2 == 0 else -1
        if b.walk_vx:
            left, _, right, _ = self.area
            if (b.x < left + b.half_w + 5 and b.walk_vx < 0) or (b.x > right - b.half_w - 5 and b.walk_vx > 0):
                self.facing = -self.facing
                b.walk_vx = -b.walk_vx

    def _jump_to_window(self):
        """Ballistic jump onto the nearest reachable window top above her."""
        b = self.body
        best = None
        for p in self.platforms:
            rise = b.y - p.top
            if 60 < rise < 650:
                tx = min(max(b.x, p.left + 40), p.right - 40)
                if abs(tx - b.x) < 700 and (best is None or rise < best[0]):
                    best = (rise, tx, p)
        if best is None or not b.grounded:
            self._hop(-1000)
            return
        rise, tx, _p = best
        g = physics.GRAVITY
        vy0 = -math.sqrt(2 * g * (rise + 50))
        t = (-vy0 + math.sqrt(max(0.0, vy0 * vy0 - 2 * g * rise))) / g
        vx = (tx - b.x) / max(0.2, t)
        self.facing = 1 if vx >= 0 else -1
        b.launch(vx, vy0)

    def _finish_teleport(self):
        left, _, right, bottom = self.area
        self.body.x = random.uniform(left + 150, right - 150)
        self.body.y = bottom - 300
        self.body.support = None
        self.body.vx = self.body.vy = 0.0
        self.hidden = False
        self._place()
        self._burst("flash", 4)

    def _emit_fx(self, fxs: list, dt: float):
        for kind, rate, at in fxs:
            k = (kind, at)
            self.fx_acc[k] = self.fx_acc.get(k, random.random()) + rate * dt
            while self.fx_acc[k] >= 1.0:
                self.fx_acc[k] -= 1.0
                x, y = self._anchor_canvas(at)
                self._emit(kind, x + random.uniform(-2, 2) * self.scale, y)

    def _draw_props(self, props):
        flip = self.facing < 0
        wanted = {(name, flip) for name in props}
        for key in list(self.prop_items):
            if key not in wanted:
                self.canvas.delete(self.prop_items.pop(key))
        for name in props:
            img, (gx, gy) = self._prop_image(name, flip)
            ax, ay = self._anchor_canvas(sprites.PROPS[name][2])
            x, y = ax - gx, ay - gy
            item = self.prop_items.get((name, flip))
            if item is None:
                self.prop_items[(name, flip)] = self.canvas.create_image(x, y, image=img, anchor="nw")
            else:
                self.canvas.coords(item, x, y)
        for item in self.prop_items.values():
            self.canvas.tag_raise(item, self.sprite_item)

    def destroy(self):
        try:
            self.bubble.win.destroy()
            self.win.destroy()
        except tk.TclError:
            pass
