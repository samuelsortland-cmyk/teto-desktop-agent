import os
import types

import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    r.withdraw()
    yield r
    r.destroy()


def test_settings_window_saves_every_page(root, tmp_path, monkeypatch):
    from teto import config as config_mod
    from teto import panel as P
    monkeypatch.setattr(config_mod, "app_dir", lambda: str(tmp_path))
    cfg = config_mod.Config()
    applied = {}
    app = types.SimpleNamespace(config=cfg, link_connected=lambda: True, connect_edge=lambda: "",
                                sign_out=lambda: None, check_updates=lambda **k: None,
                                apply_settings=lambda **k: applied.update(k))
    s = P.SettingsWindow(root, app, ("TkDefaultFont", 10))
    for key, _ in s.PAGES:
        s.show_page(key)
        root.update()
    assert s.v_auton.get() is True
    s.v_auton.set(False)                       # flip a switch
    s.speed.set(P.SPEEDS["balanced"])
    s.style.set(P.WORK_STYLES["foreground"])
    s.r_time.delete(0, "end"); s.r_time.insert(0, "7:30")
    s.r_task.insert(0, "water reminder")
    s._add_routine()
    s.scale.delete(0, "end"); s.scale.insert(0, "8")
    s._save()
    assert cfg.autonomous is False and cfg.speed == "balanced" and cfg.work_style == "foreground"
    assert cfg.routines[-1]["time"] == "07:30" and cfg.pet_scale == 8
    assert applied == {"rebuild_pet": True}
    assert os.path.exists(tmp_path / "config.json")


def test_toggle_switch_flips_on_click(root):
    from teto import panel as P
    f = tk.Frame(root, bg="white")
    var = tk.BooleanVar(value=False)
    t = P.Toggle(f, "Thing", var, ("TkDefaultFont", 10), ("TkDefaultFont", 8))
    t._flip()
    assert var.get() is True
