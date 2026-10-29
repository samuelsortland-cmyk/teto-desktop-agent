"""Render Teto's frames (from teto/sprites.py) into the extension's sprite sheet.

Run from the repo root:  python chromebook/tools/build_sprites.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from PIL import Image  # noqa: E402

from teto import sprites  # noqa: E402

P = sprites.Pose
FRAMES = {
    "idle_0": P(), "idle_1": P(bob=1), "blink": P(eyes="blink"),
    "walk_0": P(arms="swing_a"), "walk_1": P(arms="swing_b", bob=1),
    "happy_0": P(eyes="happy", mouth="open"), "happy_1": P(eyes="happy", mouth="open", arms="up_both"),
    "wave_0": P(eyes="happy", mouth="o", arms="wave_r"), "wave_1": P(eyes="happy", mouth="smile", arms="up_r"),
    "cheer_0": P(eyes="star", mouth="grin", arms="cheer"),
    "cheer_1": P(eyes="happy", mouth="open", arms="up_both", body="stretch"),
    "think": P(eyes="look_u", mouth="o"),
    "work_0": P(mouth="flat", arms="clap_a"), "work_1": P(mouth="flat", arms="clap_b", bob=1),
    "talk_0": P(mouth="open"), "talk_1": P(mouth="smile"),
    "sleep_0": P(eyes="closed", mouth="flat", bob=1), "sleep_1": P(eyes="closed", mouth="o", bob=1),
    "dizzy": P(eyes="dizzy", mouth="wobble"), "drag": P(eyes="wide", mouth="open", arms="up_both"),
    "fall": P(eyes="wide", mouth="o", arms="out_both"), "land": P(eyes="closed", mouth="flat", body="squash"),
    "jump": P(eyes="happy", mouth="open", arms="up_both", body="stretch"),
    "hips": P(eyes="happy", mouth="grin", arms="hips"), "point": P(mouth="open", arms="point_r"),
    "look_l": P(eyes="look_l"), "look_r": P(eyes="look_r"),
    "sad": P(eyes="sad", mouth="frown"), "heart": P(eyes="heart", mouth="cat"),
    "yawn": P(eyes="sleepy", mouth="yawn", arms="up_both"), "wink": P(eyes="wink", mouth="tongue", arms="point_r"),
    "dance_0": P(eyes="happy", mouth="grin", arms="out_r", body="lean_l"),
    "dance_1": P(eyes="happy", mouth="grin", arms="out_l", body="lean_r"),
}


def build(out_dir: str):
    names = list(FRAMES)
    fw, fh = sprites.FRAME_W, sprites.FRAME_H
    sheet = Image.new("RGBA", (fw * len(names), fh), (0, 0, 0, 0))
    for i, n in enumerate(names):
        sheet.alpha_composite(sprites.render_pose(FRAMES[n], 1), (i * fw, 0))
    os.makedirs(out_dir, exist_ok=True)
    sheet.save(os.path.join(out_dir, "teto.png"))
    with open(os.path.join(out_dir, "frames.json"), "w", encoding="utf-8") as f:
        json.dump({"w": fw, "h": fh, "frames": {n: i for i, n in enumerate(names)}}, f)
    # a crisp face for the side panel header
    head = sprites.render_pose(P(eyes="happy", mouth="smile"), 4)
    s = 4
    face = head.crop((sprites.OFF_X * s, sprites.OFF_Y * s, (sprites.OFF_X + sprites.GRID_W) * s,
                      (sprites.OFF_Y + 16) * s))
    face.crop(face.getbbox()).save(os.path.join(out_dir, "face.png"))
    return names


if __name__ == "__main__":
    names = build(os.path.join(REPO, "chromebook", "extension", "sprites"))
    print(f"{len(names)} frames")
