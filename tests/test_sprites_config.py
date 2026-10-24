import json

from PIL import Image

from teto import config as config_mod
from teto import sprites


def test_all_frames_same_size_and_crisp():
    frames = sprites.make_frames(scale=4)
    sizes = {im.size for im in frames.values()}
    assert sizes == {(sprites.FRAME_W * 4, sprites.FRAME_H * 4)}
    for im in frames.values():
        alphas = {a for *_, a in sprites.pixels(im)}
        assert alphas <= {0, 255}     # no semi-transparent pixels -> clean colour-key edges


def test_frames_differ_for_animation():
    f = sprites.make_frames(scale=1)
    assert f["idle_0"].tobytes() != f["idle_1"].tobytes()
    assert f["idle_0"].tobytes() != f["blink"].tobytes()
    assert f["happy_0"].tobytes() != f["idle_0"].tobytes()


def test_custom_sprite_with_solid_background(tmp_path):
    img = Image.new("RGB", (20, 30), (255, 255, 255))
    for x in range(5, 15):          # a plus shape, so the cropped corners are background
        for y in range(5, 25):
            if 8 <= x <= 11 or 12 <= y <= 17:
                img.putpixel((x, y), (224, 67, 95))
    p = tmp_path / "teto.png"
    img.save(p)
    assert sprites.custom_sprite_path(str(tmp_path)) == str(p)
    frames = sprites.make_frames(scale=4, custom_path=str(p))
    base = frames["idle_0"]
    assert base.getpixel((0, 0))[3] == 0          # background keyed out
    assert base.getpixel((base.width // 2, base.height // 2)) == (224, 67, 95, 255)
    assert base.height == sprites.FRAME_H * 4
    assert set(frames) == set(sprites.FRAME_POSES)


def test_custom_sprite_unreadable_falls_back(tmp_path):
    p = tmp_path / "teto.png"
    p.write_bytes(b"not an image")
    frames = sprites.make_frames(scale=2, custom_path=str(p))
    assert frames["idle_0"].size == (sprites.FRAME_W * 2, sprites.FRAME_H * 2)


def test_effects_render():
    for name in sprites.EFFECTS:
        im = sprites.make_effect(name, 3)
        assert im.width > 0 and im.height > 0


def test_config_roundtrip_and_sanitize(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "app_dir", lambda: str(tmp_path))
    c = config_mod.Config.load()
    assert c.model == "default" and c.brain == "subscription"
    c.effort = "bogus"
    c.max_steps = 99999
    c.routines = [{"time": "09:00", "task": "check mail", "enabled": True, "last_run": ""}]
    c.save()
    data = json.loads((tmp_path / "config.json").read_text())
    assert data["effort"] == "medium" and data["max_steps"] == 0
    c2 = config_mod.Config.load()
    assert c2.routines[0]["task"] == "check mail"


def test_config_corrupt_file_uses_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "app_dir", lambda: str(tmp_path))
    (tmp_path / "config.json").write_text("{not json")
    assert config_mod.Config.load().brain == "subscription"


def test_reference_grid_is_well_formed():
    assert all(len(r) == sprites.GRID_W for r in sprites.BASE)
    used = set("".join(sprites.BASE)) - {"."}
    assert used <= set(sprites.PALETTE)
    for edits in list(sprites.EYES.values()) + list(sprites.MOUTHS.values()):
        for (x, y), c in edits.items():
            assert 0 <= x < sprites.GRID_W and 0 <= y < sprites.GRID_H and c in sprites.PALETTE
    # the bounce frame keeps the feet planted on the same row
    assert sprites.build_grid(sprites.Pose(bob=1)).px[-1] == list(sprites.BASE[-1])


def test_update_repo_defaults_even_for_old_configs(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "app_dir", lambda: str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps({"update_repo": ""}))   # saved by an older Teto
    assert config_mod.Config.load().update_repo == config_mod.DEFAULT_UPDATE_REPO
