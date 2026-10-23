"""Pixel-art sprites for the Teto desktop pet.

The body is the user's reference pixel art, stored cell-for-cell below. The
animation frames are small edits on top of it: blinking, happy eyes, talking
mouths, and a one-row squash for bouncing. Frames are scaled up with
nearest-neighbour so every pixel stays crisp. If the user drops their own
`assets/teto.png` next to the app, that image is used for the body instead.

Nothing here depends on tkinter, so the sprite code can be unit-tested and
previewed headlessly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from PIL import Image

# Exact colours from the reference image.
PALETTE = {
    "K": (0, 0, 0),         # outline
    "R": (232, 30, 70),     # hair / red
    "r": (181, 29, 54),     # hair shade
    "H": (230, 120, 131),   # hair shine
    "S": (255, 227, 208),   # skin
    "P": (255, 138, 128),   # eye / face shading
    "B": (248, 187, 208),   # blush
    "E": (92, 21, 33),      # pupil
    "G": (55, 71, 79),      # uniform grey
    "g": (38, 50, 56),      # uniform dark grey
    "D": (33, 33, 33),      # socks
    "M": (150, 20, 45),     # open mouth
    "T": (232, 30, 70),     # effects: red
    "W": (255, 255, 255),   # effects: white
    "Q": (255, 120, 170),   # effects: heart pink
    "C": (120, 205, 255),   # tears / water
    "Y": (255, 214, 92),    # yellow
    "O": (255, 150, 60),    # orange
    "N": (130, 82, 45),     # wood / brown
    "n": (232, 168, 90),    # bread crust
    "w": (246, 214, 160),   # bread score marks
    "L": (196, 200, 210),   # light grey / metal
    "U": (80, 140, 230),    # blue
    "V": (95, 195, 105),    # green
    "v": (40, 125, 60),     # dark green
    "I": (150, 95, 215),    # purple
}

# The reference sprite, one character per pixel ("." = transparent).
BASE = [
    "............K............",
    "...........KRK...........",
    "..........KRK............",
    "........KKKKRKKKK........",
    ".KKKKK.KRRRRRRRRRK.KKKKK.",
    "KRRRRRKRHHRHHHRHHRKRRRRRK",
    "KRRRRrRHRRRRRRRRRHRrRRRRK",
    "KrrrrrrRrRRRRRrRrRrrrrrrK",
    ".KrrrrRrRRrRRRrrRrRrrrrK.",
    ".KRRRrrRRrPrRrPPrRrrRRRK.",
    ".KrrrrRrrEPrRrSEPrRrrrrK.",
    "..KrrrrrPrSPrPSrSrrrrrK..",
    "..KRRrRrSRSSPSSRSrRrRRK..",
    "..KrrKKrBBSSSSSBBrKKRrK..",
    "...KRK.rKSSSSSSSKr.KRK...",
    "....K....KKKKKKK....K....",
    "..........KGSGK..........",
    ".........KSGRGSK.........",
    "........KSGGRGGSK........",
    ".......KRRGgrgGRRK.......",
    ".......KgGGGRGGGgK.......",
    "......KggGGGRGGGggK......",
    "......KRrgggggggrRK......",
    ".......KKrGgGgGrKK.......",
    ".........KRRRRRK.........",
    ".........KDK.KDK.........",
    ".........KRK.KRK.........",
    ".........KKK.KKK.........",
]

GRID_W, GRID_H = len(BASE[0]), len(BASE)
SQUASH_ROW = 20          # torso row dropped when squashing / duplicated when stretching
HEAD_ROWS = 16           # rows 0..15 are the head (tilted by lean_l / lean_r)
MOUTH = (12, 13)         # centre of the mouth, on the face's skin

# Every frame is drawn on a square canvas with her feet at the bottom centre,
# so rotations (lying down, tumbling) keep the same size.
FRAME_W = FRAME_H = 30
OFF_X = (FRAME_W - GRID_W) // 2
OFF_Y = FRAME_H - GRID_H

# Where props attach, in frame pixels (unflipped).
ANCHORS = {
    "hand_r": (OFF_X + 17, OFF_Y + 22), "hand_l": (OFF_X + 7, OFF_Y + 22),
    "hand_r_up": (OFF_X + 18, OFF_Y + 15), "hand_l_up": (OFF_X + 6, OFF_Y + 15),
    "head": (OFF_X + 12, OFF_Y + 1), "eyes": (OFF_X + 12, OFF_Y + 10), "mouth": (OFF_X + 12, OFF_Y + 13),
    "front": (OFF_X + 12, OFF_Y + 21), "feet": (OFF_X + 12, FRAME_H - 1),
    "ground_r": (OFF_X + 26, FRAME_H - 1), "ground_l": (OFF_X - 2, FRAME_H - 1),
    "above": (OFF_X + 12, OFF_Y - 6),
}

# ------------------------------------------------------------- expressions
# Pixel edits on the reference grid: {(x, y): colour}.
_BLINK = {(9, 10): "K", (10, 10): "K", (15, 10): "K", (16, 10): "K", (10, 9): "r", (14, 9): "r", (15, 9): "r"}
EYES = {
    "open": {},
    "wide": {(10, 9): "S", (14, 9): "S", (15, 9): "S"},
    "blink": _BLINK,
    "closed": _BLINK,
    "sleepy": {**_BLINK, (9, 10): "E", (15, 10): "E"},
    "happy": {(9, 10): "K", (10, 9): "K", (11, 10): "K", (10, 10): "S",
              (14, 10): "K", (15, 9): "K", (16, 10): "K", (15, 10): "S", (14, 9): "r"},
    "dizzy": {(9, 10): "K", (10, 9): "K", (10, 10): "K", (15, 10): "K", (14, 9): "K", (16, 10): "K"},
    "look_l": {(9, 10): "E", (10, 10): "P", (14, 10): "E", (15, 10): "P"},
    "look_r": {(9, 10): "P", (10, 10): "E", (15, 10): "P", (16, 10): "E"},
    "look_u": {(10, 9): "E", (9, 10): "P", (15, 9): "E", (15, 10): "P"},
    "wink": {(15, 10): "K", (16, 10): "K", (14, 9): "r", (15, 9): "r", (14, 10): "K"},
    "heart": {(9, 10): "Q", (10, 10): "Q", (10, 9): "Q", (15, 10): "Q", (16, 10): "Q", (15, 9): "Q"},
    "star": {(9, 10): "W", (10, 10): "Y", (15, 10): "W", (16, 10): "Y"},
    "angry": {(9, 9): "K", (10, 10): "K", (16, 9): "K", (15, 10): "K", (10, 9): "E", (14, 9): "E"},
    "sad": {**_BLINK, (9, 11): "C", (16, 11): "C"},
    "cry": {**_BLINK, (9, 11): "C", (16, 11): "C", (9, 12): "C", (16, 12): "C"},
}

_mx, _my = MOUTH
MOUTHS = {
    "smile": {},
    "flat": {(_mx - 1, _my): "P", (_mx, _my): "P", (_mx + 1, _my): "P"},
    "open": {(_mx, _my): "M", (_mx, _my + 1): "M"},
    "o": {(_mx, _my): "M"},
    "wobble": {(_mx - 1, _my): "K", (_mx + 1, _my): "K"},
    "grin": {(_mx - 1, _my): "K", (_mx, _my + 1): "M", (_mx + 1, _my): "K", (_mx - 1, _my + 1): "M",
             (_mx + 1, _my + 1): "M"},
    "cat": {(_mx - 2, _my): "K", (_mx - 1, _my + 1): "K", (_mx, _my): "K", (_mx + 1, _my + 1): "K",
            (_mx + 2, _my): "K"},
    "yawn": {(_mx - 1, _my): "M", (_mx, _my): "M", (_mx + 1, _my): "M", (_mx - 1, _my + 1): "M",
             (_mx, _my + 1): "M", (_mx + 1, _my + 1): "M"},
    "tongue": {(_mx, _my): "M", (_mx, _my + 1): "Q"},
    "frown": {(_mx - 1, _my + 1): "K", (_mx, _my): "K", (_mx + 1, _my + 1): "K"},
    "chew": {(_mx - 1, _my): "K", (_mx, _my): "M", (_mx + 1, _my): "K"},
}

# ------------------------------------------------------------------- arms
# Viewer's right arm (cols 16-18). Left-arm versions are mirrored around x=12.
_ERASE_R = {(16, 20): "G", (17, 20): "K", (16, 21): "G", (17, 21): "K", (18, 21): ".",
            (16, 22): "g", (17, 22): "K", (18, 22): "."}
_UP_R = {**_ERASE_R, (17, 18): "g", (18, 18): "g", (19, 18): "K", (16, 17): "K", (17, 17): "g",
         (18, 17): "g", (19, 17): "K", (16, 16): "K", (17, 16): "R", (18, 16): "R", (19, 16): "K",
         (16, 15): "K", (17, 15): "S", (18, 15): "S", (19, 15): "K", (17, 14): "K", (18, 14): "K"}
_WAVE_R = {**_ERASE_R, (17, 18): "g", (18, 18): "K", (16, 17): "K", (17, 17): "g", (18, 17): "g",
           (19, 17): "K", (17, 16): "K", (18, 16): "R", (19, 16): "R", (20, 16): "K", (17, 15): "K",
           (18, 15): "S", (19, 15): "S", (20, 15): "K", (18, 14): "K", (19, 14): "K"}
_POINT_R = {**_ERASE_R, (17, 18): "K", (18, 18): "K", (19, 18): "K", (20, 18): "K",
            (17, 19): "g", (18, 19): "g", (19, 19): "R", (20, 19): "S", (21, 19): "K",
            (17, 20): "K", (18, 20): "K", (19, 20): "K", (20, 20): "K"}


def _mirror(d: dict) -> dict:
    return {(GRID_W - 1 - x, y): c for (x, y), c in d.items()}


ARMS = {
    "down": {},
    "up_r": _UP_R,
    "wave_r": _WAVE_R,
    "up_l": _mirror(_UP_R),
    "up_both": {**_UP_R, **_mirror(_UP_R)},
    "point_r": _POINT_R,
    "point_l": _mirror(_POINT_R),
}

BODIES = ("", "bob", "squash", "stretch", "lean_l", "lean_r", "lie_l", "lie_r", "upside",
          "rot90", "rot180", "rot270")


@dataclass(frozen=True)
class Pose:
    eyes: str = "open"
    mouth: str = "smile"
    bob: int = 0             # legacy: 1 == body "bob"
    arms: str = "down"
    body: str = ""


class Grid:
    def __init__(self, rows: list[str]):
        self.px = [list(r) for r in rows]
        self.h = len(self.px)
        self.w = len(self.px[0])

    def set(self, x: int, y: int, c: str) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = c

    def to_image(self) -> Image.Image:
        img = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        for y, row in enumerate(self.px):
            for x, c in enumerate(row):
                if c != ".":
                    img.putpixel((x, y), PALETTE[c] + (255,))
        return img


def build_grid(pose: Pose = Pose()) -> Grid:
    """The reference sprite with an expression and arm pose applied."""
    g = Grid(BASE)
    edits = {**ARMS.get(pose.arms, {}), **EYES[pose.eyes], **MOUTHS[pose.mouth]}
    for (x, y), c in edits.items():
        g.set(x, y, c)
    if pose.bob or pose.body == "bob":
        g.px = [["."] * g.w] + g.px[:SQUASH_ROW] + g.px[SQUASH_ROW + 1:]
    return g


def _apply_body(sprite: Image.Image, body: str, unit: int) -> Image.Image:
    """Image-space body moves on a grid-unit sprite (unit = pixels per grid cell)."""
    w, h = sprite.size
    if body == "squash":
        top = sprite.crop((0, 0, w, SQUASH_ROW * unit))
        rest = sprite.crop((0, (SQUASH_ROW + 2) * unit, w, h))
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        out.alpha_composite(top, (0, 2 * unit))
        out.alpha_composite(rest, (0, (SQUASH_ROW + 2) * unit))
        return out
    if body == "stretch":
        top = sprite.crop((0, unit, w, (SQUASH_ROW + 1) * unit))
        row = sprite.crop((0, SQUASH_ROW * unit, w, (SQUASH_ROW + 1) * unit))
        rest = sprite.crop((0, (SQUASH_ROW + 1) * unit, w, h))
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        out.alpha_composite(top, (0, 0))
        out.alpha_composite(row, (0, SQUASH_ROW * unit))
        out.alpha_composite(rest, (0, (SQUASH_ROW + 1) * unit))
        return out
    if body in ("lean_l", "lean_r"):
        dx = -unit if body == "lean_l" else unit
        head = sprite.crop((0, 0, w, HEAD_ROWS * unit))
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        out.alpha_composite(sprite.crop((0, HEAD_ROWS * unit, w, h)), (0, HEAD_ROWS * unit))
        out.alpha_composite(head, (max(0, dx), 0), (max(0, -dx), 0))
        return out
    return sprite


def _place(sprite: Image.Image, body: str, fw: int, fh: int) -> Image.Image:
    """Put the (possibly rotated) sprite bottom-centre on the square frame."""
    rot = {"lie_l": 90, "rot90": 90, "lie_r": 270, "rot270": 270, "upside": 180, "rot180": 180}.get(body)
    if rot:
        sprite = sprite.rotate(rot, expand=True)
    frame = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    frame.alpha_composite(sprite, ((fw - sprite.width) // 2, fh - sprite.height))
    return frame


def render_pose(pose: Pose, scale: int = 1, flip: bool = False, custom: Image.Image | None = None) -> Image.Image:
    """Final RGBA frame (FRAME_W*scale square) for a pose."""
    if custom is not None:
        unit = max(1, custom.height // GRID_H)
        sprite = custom
        if pose.bob or pose.body == "bob":
            sprite = _apply_body(sprite, "squash", max(1, unit // 2))
        elif pose.body in ("squash", "stretch", "lean_l", "lean_r"):
            sprite = _apply_body(sprite, pose.body, unit)
        frame = _place(sprite, pose.body, FRAME_W * scale, FRAME_H * scale)
    else:
        sprite = build_grid(pose).to_image()
        if pose.body in ("squash", "stretch", "lean_l", "lean_r"):
            sprite = _apply_body(sprite, pose.body, 1)
        frame = _place(sprite, pose.body, FRAME_W, FRAME_H)
        if scale != 1:
            frame = frame.resize((FRAME_W * scale, FRAME_H * scale), Image.NEAREST)
    if flip:
        frame = frame.transpose(Image.FLIP_LEFT_RIGHT)
    return frame


# ------------------------------------------------------------------ frames
FRAME_POSES = {
    "idle_0": Pose(),
    "idle_1": Pose(bob=1),
    "blink": Pose(eyes="blink"),
    "happy_0": Pose(eyes="happy", mouth="open"),
    "happy_1": Pose(eyes="happy", mouth="open", bob=1, arms="up_both"),
    "wave": Pose(eyes="happy", mouth="o", arms="wave_r"),
    "work_0": Pose(mouth="flat"),
    "work_1": Pose(mouth="flat", bob=1),
    "think": Pose(eyes="look_u", mouth="o"),
    "sleep": Pose(eyes="closed", mouth="flat", bob=1),
    "dizzy": Pose(eyes="dizzy", mouth="wobble"),
    "drag": Pose(eyes="wide", mouth="open", arms="up_both"),
    "talk_0": Pose(mouth="open"),
    "talk_1": Pose(mouth="smile"),
}


def pixels(img: Image.Image) -> list:
    """All pixels as a flat list (Pillow 12+ renamed getdata)."""
    get = getattr(img, "get_flattened_data", None) or img.getdata
    return list(get())


def load_custom(path: str, scale: int) -> Image.Image | None:
    """A user-supplied sprite (e.g. assets/teto.png), keyed and sized to fit
    the 25x28-cell body box at this scale. None if unreadable."""
    try:
        img = Image.open(path).convert("RGBA")
    except Exception:
        return None
    w, h = img.size
    corners = {img.getpixel((0, 0)), img.getpixel((w - 1, 0)),
               img.getpixel((0, h - 1)), img.getpixel((w - 1, h - 1))}
    if len(corners) == 1:
        bg = corners.pop()
        if bg[3] == 255:
            img.putdata([(0, 0, 0, 0) if p[:3] == bg[:3] else p for p in pixels(img)])
    img.putdata([p if p[3] >= 128 else (0, 0, 0, 0) for p in pixels(img)])
    box = img.getbbox()
    if not box:
        return None
    img = img.crop(box)
    max_w, max_h = GRID_W * scale, GRID_H * scale
    if img.width <= max_w and img.height <= max_h:
        k = max(1, min(max_w // img.width, max_h // img.height))
        return img.resize((img.width * k, img.height * k), Image.NEAREST)
    r = min(max_w / img.width, max_h / img.height)
    return img.resize((max(1, int(img.width * r)), max(1, int(img.height * r))), Image.NEAREST)


def custom_sprite_path(base_dir: str) -> str | None:
    for name in ("teto.png", "pet.png"):
        p = os.path.join(base_dir, name)
        if os.path.isfile(p):
            return p
    return None


def make_frames(scale: int = 6, custom_path: str | None = None) -> dict[str, Image.Image]:
    """The classic named frames (used by previews and tests)."""
    custom = load_custom(custom_path, scale) if custom_path else None
    return {name: render_pose(pose, scale, custom=custom) for name, pose in FRAME_POSES.items()}


# ------------------------------------------------------------------ props
# name: (pixel rows, grip pixel (x, y), default anchor). The grip pixel is
# placed on the anchor point of the frame.
PROPS: dict[str, tuple[list[str], tuple[int, int], str]] = {
    "bread": (["......KK.", ".....KnnK", "....KnwnK", "...KnnnK.", "..KnwnK..", ".KnnnK...",
               "KnnK.....", "KKK......"], (2, 6), "hand_r"),
    "mic": ([".KK.", "KLLK", "KLLK", ".KK.", ".KK.", ".KK."], (1, 4), "hand_r"),
    "cup": (["KKKKK.", "KWWWKK", "KWWWK.", ".KKK.."], (2, 2), "hand_r"),
    "mug": (["KKKK..", "KNNKK.", "KNNK.K", "KNNKK.", ".KK..."], (1, 2), "hand_r"),
    "book": (["KKKKKKK", "KWWKWWK", "KWWKWWK", "KKKKKKK"], (3, 3), "hand_r"),
    "notebook": (["KKKKK.N", "KWWWKN.", "KWKWK..", "KKKKK.."], (2, 3), "hand_r"),
    "phone": (["KKK", "KUK", "KUK", "KKK"], (1, 3), "hand_r"),
    "gamepad": ([".KKKKK.", "KLYLULK", "KLLLLLK", "KK...KK"], (3, 2), "hand_r"),
    "brush": (["KTK", "KLK", ".N.", ".N.", ".N."], (1, 3), "hand_r"),
    "broom": (["..N..", "..N..", "..N..", "..N..", "..N..", ".YYY.", "YYYYY", "Y.Y.Y"], (2, 2), "hand_r"),
    "can": (["..KKK...", ".KUUUK.K", "KUUUUKK.", ".KUUUK..", "..KKK..."], (2, 1), "hand_r"),
    "umbrella": (["...KKKKK...", ".KKRRRRRKK.", "KRRRWRRRRRK", "KKKKKKKKKKK"] + [".....K....."] * 14
                 + ["....KK....."], (5, 17), "hand_r"),
    "balloon": ([".KKK.", "KTTTK", "KTWTK", "KTTTK", ".KTK."] + ["..K.."] * 12, (2, 16), "hand_r"),
    "heart_balloon": ([".KK.KK.", "KQQKQQK", "KQWQQQK", ".KQQQK.", "..KQK.."] + ["...K..."] * 11,
                      (3, 15), "hand_r"),
    "flower": ([".Q.", "QYQ", ".Q.", ".v.", ".v."], (1, 4), "hand_r"),
    "icecream": ([".QQ.", "QQWQ", "nnnn", ".nn.", ".n.."], (1, 4), "hand_r"),
    "camera": (["..KK..", "KKKKKK", "KLKKLK", "KKKKKK"], (0, 2), "hand_r"),
    "guitar": (["....KK", "...KNK", "..KNK.", "KTTK..", "TTTT..", "KTTK.."], (1, 4), "front"),
    "headphones": ([".KKKKKKKKKKKKKKKKK.", "K.................K"] + ["K.................K"] * 5
                   + ["II...............II"] * 3, (9, 0), "head"),
    "sunglasses": (["KKKKKKKKK", ".KKK.KKK."], (4, 0), "eyes"),
    "party_hat": (["...Y...", "...T...", "..TYT..", "..YTY..", ".TYTYT.", "TYTYTYT"], (3, 5), "head"),
    "santa_hat": (["......W", "....TT.", "..TTTT.", ".TTTTT.", "WWWWWWW"], (3, 4), "head"),
    "witch_hat": (["...K....", "...KK...", "..KIK...", "..KIIK..", ".KIIIK..", "KKKKKKKK"], (3, 5), "head"),
    "crown": (["Y.Y.Y", "YYYYY", "YTYUY"], (2, 2), "head"),
    "flower_crown": (["Q.Y.Q.Y.Q", "vvvvvvvvv"], (4, 1), "head"),
    "wand": ([".Y.", "YYY", ".Y.", ".K.", ".K.", ".K."], (1, 4), "hand_r"),
    "flag": (["KTTTT", "KTWTT", "KTTTT", "K....", "K....", "K...."], (0, 5), "hand_r"),
    "pompom": ([".QYQ.", "QYQYQ", ".QYQ."], (2, 1), "hand_r"),
    "pompom_l": ([".QYQ.", "QYQYQ", ".QYQ."], (2, 1), "hand_l"),
    "fan": (["YTYTY", ".YTY.", "..K.."], (2, 2), "hand_r"),
    "ball": ([".KK.", "KTUK", "KYWK", ".KK."], (2, 3), "ground_r"),
    "yoyo_up": (["K", "K", "KK", "TT"], (0, 0), "hand_r"),
    "yoyo_down": (["K"] * 7 + ["KK", "TT"], (0, 0), "hand_r"),
    "gum1": (["QQ", "QQ"], (1, 0), "mouth"),
    "gum2": ([".QQ.", "QQWQ", "QQQQ", ".QQ."], (1, 0), "mouth"),
    "gum3": ([".QQQ.", "QQQWQ", "QQQQQ", "QQQQQ", ".QQQ."], (2, 0), "mouth"),
    "rod": (["........K", ".......K.", "......K..", ".....K...", "....K....", "...K.....",
             "..K......", ".N.......", "N........"], (0, 8), "hand_r"),
    "cat": (["O...O..", "OO.OO..", "OKOKO..", "OOWOO.O", ".OOOO.O", ".OOOOOO"], (3, 5), "ground_r"),
    "cat_blink": (["O...O..", "OO.OO..", "OOOOO..", "OOWOO.O", ".OOOO.O", ".OOOOOO"], (3, 5), "ground_r"),
    "bird": ([".UUY", "UUUU", ".K.K"], (2, 2), "head"),
    "laptop": ([".KKKKKK.", ".KUUUUK.", ".KUUUUK.", "KLLLLLLK", "KKKKKKKK"], (4, 4), "front"),
    "onigiri": (["..K..", ".KWK.", "KWWWK", "KKKKK"], (2, 3), "hand_r"),
    "lollipop": ([".QQ.", "QWQQ", ".QQ.", "..N.", "..N."], (2, 4), "hand_r"),
    "sparkler": (["Y.Y", ".Y.", "Y.Y", ".N.", ".N.", ".N."], (1, 5), "hand_r"),
    "dumbbell": (["L...L", "LKKKL", "L...L"], (2, 1), "hand_r"),
    "maracas": ([".O.", "OOO", ".O.", ".N.", ".N."], (1, 4), "hand_r"),
    "maracas_l": ([".O.", "OOO", ".O.", ".N.", ".N."], (1, 4), "hand_l"),
    "drumstick": (["..N", ".N.", "N.."], (0, 2), "hand_r"),
    "baton": (["..W", ".N.", "N.."], (0, 2), "hand_r"),
    "telescope": (["......KK", "....KKLK", "..KKLLK.", "KKLLK...", "KLLK....", ".K......"], (2, 4), "hand_r"),
    "pumpkin": (["..v...", ".OOOO.", "OKOOKO", "OOKKOO", ".OOOO."], (3, 4), "ground_l"),
    "gift": (["..T..", "TTTTT", "UUTUU", "UUTUU"], (2, 3), "ground_r"),
    "cake": ([".Y.Y.", ".W.W.", "QQQQQ", "WWWWW", "NNNNN"], (2, 4), "ground_r"),
    "snowball": ([".WW.", "WWWW", ".WW."], (1, 1), "hand_r"),
    "clock": ([".KKK.", "KWKWK", "KWKKK", "KWWWK", ".KKK."], (2, 4), "hand_r"),
    "bottle": ([".K.", "KUK", "KCK", "KCK", "KKK"], (1, 3), "hand_r"),
    "sign_heart": (["KKKKK", "KQWQK", "KQQQK", "KKKKK", "..N..", "..N.."], (2, 5), "hand_r"),
    "plant": (["V.V.V", ".VVV.", "..v..", ".NNN.", ".NNN."], (2, 4), "ground_l"),
    "plant_big": (["Q.V.Q", "VVVVV", ".VVV.", "..v..", ".NNN.", ".NNN."], (2, 5), "ground_l"),
    "pencil": (["Y", "Y", "Y", "K"], (0, 2), "hand_r"),
    "kite": (["..T..", ".TYT.", "TYTYT", ".TYT.", "..T..", "...K.", "....K", ".....K"], (5, 7), "hand_r_up"),
    "pillow": (["WWWWWWW", "WLWWWLW", "WWWWWWW"], (3, 2), "ground_r"),
}

# ----------------------------------------------------------- particles
EFFECTS = {
    "heart": [".KK.KK.", "KQQKQQK", "KQWQQQK", "KQQQQQK", ".KQQQK.", "..KQK..", "...K..."],
    "sparkle": ["...W...", "...W...", ".WWWWW.", "WWWHWWW", ".WWWWW.", "...W...", "...W..."],
    "note": ["..KKKK", "..K..K", "..K..K", "KKK.KK", "KKK.KK"],
    "sweat": ["..W.", ".WWW", "WWWW", ".WW."],
    "z": ["KKKK", "..K.", ".K..", "KKKK"],
    "gear": [".K.K.", "KKKKK", ".K.K.", "KKKKK", ".K.K."],
    "dot": ["KK", "KK"],
    "bang": ["T", "T", "T", ".", "T"],
    "question": [".KK.", "K..K", "..K.", ".K..", "....", ".K.."],
    "tear": [".C.", "CCC", ".C."],
    "steam": [".W.", "W.W", ".W."],
    "crumb": ["n"],
    "confetti_r": ["TT"], "confetti_y": ["YY"], "confetti_b": ["UU"], "confetti_g": ["VV"],
    "drop": [".C", "CC"],
    "dust": [".L.", "LLL", ".L."],
    "star": ["..Y..", ".YYY.", "YYYYY", ".YYY.", ".Y.Y."],
    "bulb": [".YYY.", "YYWYY", "YYYYY", ".YYY.", ".LLL.", "..L.."],
    "anger": ["T.T", ".T.", "T.T"],
    "flash": ["W.W.W", ".WWW.", "WWWWW", ".WWW.", "W.W.W"],
    "petal": ["QQ", ".Q"],
    "snow": [".W.", "WWW", ".W."],
    "leaf": [".V", "VV", "v."],
    "bubble": [".CC.", "C..C", "C..C", ".CC."],
    "fish": ["..OO.O", ".OOKOO", "..OO.O"],
    "butterfly": ["I.I", ".K.", "I.I"],
    "butterfly2": [".I.", "IKI", ".I."],
    "tap": ["K"],
    "cloud": [".WWW.", "WWWWW", ".WWW."],
    "firework_r": ["T.T.T", ".TTT.", "TT.TT", ".TTT.", "T.T.T"],
    "firework_y": ["Y.Y.Y", ".YYY.", "YY.YY", ".YYY.", "Y.Y.Y"],
    "firework_b": ["U.U.U", ".UUU.", "UU.UU", ".UUU.", "U.U.U"],
    "plane": ["W....", "WWW..", ".WWWW", "WWW.."],
    "juggle_r": [".KK.", "KTTK", "KTTK", ".KK."],
    "juggle_y": [".KK.", "KYYK", "KYYK", ".KK."],
    "juggle_b": [".KK.", "KUUK", "KUUK", ".KK."],
    "rain": ["C", "C"],
    "smoke": [".LL.", "LLLL", ".LL."],
    "music_r": ["..TTTT", "..T..T", "..T..T", "TTT.TT", "TTT.TT"],
}


def sprite_from_rows(rows: list[str], scale: int = 3, color: tuple | None = None) -> Image.Image:
    w, h = max(len(r) for r in rows), len(rows)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for y, row in enumerate(rows):
        for x, c in enumerate(row):
            if c != ".":
                rgb = color if color else PALETTE[c]
                img.putpixel((x, y), tuple(rgb) + (255,))
    return img.resize((w * scale, h * scale), Image.NEAREST)


def make_effect(name: str, scale: int = 3, color: tuple | None = None) -> Image.Image:
    return sprite_from_rows(EFFECTS[name], scale, color)


def make_prop(name: str, scale: int, flip: bool = False) -> tuple[Image.Image, tuple[int, int]]:
    """(image, grip offset in scaled pixels)."""
    rows, (gx, gy), _ = PROPS[name]
    img = sprite_from_rows(rows, scale)
    w = max(len(r) for r in rows)
    if flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
        gx = w - 1 - gx
    return img, (gx * scale + scale // 2, gy * scale + scale // 2)


def anchor_point(name: str, flip: bool = False) -> tuple[int, int]:
    x, y = ANCHORS[name]
    if flip:
        x = FRAME_W - 1 - x
    return x, y


if __name__ == "__main__":  # quick preview sheet: python -m teto.sprites out.png
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "sprite_sheet.png"
    fr = make_frames(scale=8)
    names = list(fr)
    fw, fh = fr[names[0]].size
    sheet = Image.new("RGBA", (fw * 7, fh * ((len(names) + 6) // 7)), (187, 222, 251, 255))
    for i, n in enumerate(names):
        sheet.alpha_composite(fr[n], ((i % 7) * fw, (i // 7) * fh))
    sheet.save(out)
    print("saved", out)
