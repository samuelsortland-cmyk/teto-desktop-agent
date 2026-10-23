import json
import os
import subprocess
import sys
import zipfile

import pytest

from teto import updater
from teto.updater import GitHubSource, Updater, UpdateError, ZipSource, git_blob_sha

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_install(tmp_path, files: dict[str, bytes]):
    app = tmp_path / "app_root"
    for p, data in files.items():
        f = app / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    state = tmp_path / "state"
    state.mkdir()
    return str(app), str(state)


class FakeGitHub:
    """Serves the commit / tree / raw endpoints from a dict of files."""

    def __init__(self, files: dict[str, bytes], corrupt: str | None = None):
        self.files, self.corrupt, self.calls = files, corrupt, []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        if url.endswith("/commits/main"):
            return json.dumps({"sha": "abc1234def"}).encode()
        if "/git/trees/" in url:
            return json.dumps({"tree": [{"path": p, "type": "blob", "sha": git_blob_sha(d)}
                                        for p, d in self.files.items()]}).encode()
        path = url.split("/abc1234def/", 1)[1]
        data = self.files[path]
        return data + b"tampered" if path == self.corrupt else data


OLD = {"teto/__init__.py": b'__version__ = "2.0.0"\n', "teto/a.py": b"A = 1\n", "teto/gone.py": b"x\n",
       "main.py": b"main\n", "requirements.txt": b"pillow\n", "assets/teto.ico": b"ICO"}
NEW = {"teto/__init__.py": b'__version__ = "2.1.0"\n', "teto/a.py": b"A = 2\n", "teto/b.py": b"B = 1\n",
       "main.py": b"main\n", "requirements.txt": b"pillow\n", "assets/teto.ico": b"ICO",
       "tests/test_x.py": b"not tracked\n"}


def test_git_blob_sha_matches_git():
    assert git_blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_check_finds_only_changed_files(tmp_path):
    app, state = make_install(tmp_path, OLD)
    gh = FakeGitHub(NEW)
    plan = Updater(app, state).check(GitHubSource("me/teto", get=gh))
    assert plan.changed == ["teto/__init__.py", "teto/a.py", "teto/b.py"]
    assert plan.removed == ["teto/gone.py"]
    assert plan.version == "2.1.0" and not plan.requirements_changed
    # only the tiny version file was downloaded during the check
    assert sum("raw.githubusercontent" in c for c in gh.calls) == 1


def test_apply_updates_in_place_and_backs_up(tmp_path):
    app, state = make_install(tmp_path, OLD)
    u = Updater(app, state)
    src = GitHubSource("https://github.com/me/teto.git", get=FakeGitHub(NEW))
    res = u.apply(u.check(src), src)
    assert res["files"] == 3 and res["removed"] == 1 and res["version"] == "2.1.0"
    assert open(os.path.join(app, "teto", "a.py"), "rb").read() == b"A = 2\n"
    assert not os.path.exists(os.path.join(app, "teto", "gone.py"))
    assert not os.path.exists(os.path.join(app, "tests", "test_x.py"))
    assert os.path.isfile(os.path.join(state, "pending_update.json"))
    # nothing left to do
    assert not u.check(GitHubSource("me/teto", get=FakeGitHub(NEW))).has_changes
    # rollback restores the old files exactly
    assert u.rollback()
    for p, data in OLD.items():
        assert open(os.path.join(app, *p.split("/")), "rb").read() == data
    assert not os.path.exists(os.path.join(app, "teto", "b.py"))


def test_corrupt_download_changes_nothing(tmp_path):
    app, state = make_install(tmp_path, OLD)
    u = Updater(app, state)
    src = GitHubSource("me/teto", get=FakeGitHub(NEW, corrupt="teto/b.py"))
    with pytest.raises(UpdateError, match="checksum"):
        u.apply(u.check(src), src)
    for p, data in OLD.items():
        assert open(os.path.join(app, *p.split("/")), "rb").read() == data


def test_zip_source(tmp_path):
    app, state = make_install(tmp_path, OLD)
    z = tmp_path / "new.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for p, d in NEW.items():
            zf.writestr("teto-desktop-agent/" + p, d)
    u = Updater(app, state)
    src = ZipSource(str(z))
    plan = u.check(src)
    assert plan.changed == ["teto/__init__.py", "teto/a.py", "teto/b.py"]
    u.apply(plan, src)
    assert open(os.path.join(app, "teto", "b.py"), "rb").read() == b"B = 1\n"


def test_bad_inputs(tmp_path):
    with pytest.raises(UpdateError):
        GitHubSource("not a repo")
    bad = tmp_path / "x.zip"
    bad.write_bytes(b"nope")
    with pytest.raises(UpdateError):
        ZipSource(str(bad))


def test_frozen_uses_overlay_and_build_manifest(tmp_path):
    # Teto.exe: .py files are baked in (not on disk); the build manifest holds their hashes
    baked = {p: d for p, d in OLD.items() if not p.endswith(".py") or p == "main.py"}
    app, state = make_install(tmp_path, baked)
    manifest = {"files": {p: git_blob_sha(d) for p, d in OLD.items()}}
    os.makedirs(os.path.join(app, "assets"), exist_ok=True)
    with open(os.path.join(app, "assets", "build_manifest.json"), "w") as f:
        json.dump(manifest, f)
    u = Updater(app, state, frozen=True)
    src = GitHubSource("me/teto", get=FakeGitHub(NEW))
    plan = u.check(src)
    assert plan.changed == ["teto/__init__.py", "teto/a.py", "teto/b.py"] and not plan.needs_full_download
    u.apply(plan, src)
    assert open(os.path.join(state, "app", "teto", "a.py"), "rb").read() == b"A = 2\n"
    assert not os.path.exists(os.path.join(app, "teto", "a.py"))           # bundle untouched
    # a requirements change can't be applied to the exe
    newer = dict(NEW, **{"requirements.txt": b"pillow\nnewpkg\n"})
    plan2 = u.check(GitHubSource("me/teto", get=FakeGitHub(newer)))
    assert plan2.needs_full_download


def test_build_manifest_roundtrip(tmp_path):
    app, state = make_install(tmp_path, OLD)
    out = os.path.join(app, "assets", "build_manifest.json")
    updater.write_build_manifest(app, out)
    data = json.load(open(out))["files"]
    assert data["teto/a.py"] == git_blob_sha(OLD["teto/a.py"]) and "assets/build_manifest.json" not in data


def test_main_py_safety_net_rolls_back_after_two_failed_starts(tmp_path):
    """Run the real main.py: a broken update gets rolled back automatically."""
    app = tmp_path / "install"
    app.mkdir()
    (app / "main.py").write_bytes(open(os.path.join(ROOT, "main.py"), "rb").read())
    (app / "teto").mkdir()
    (app / "teto" / "__init__.py").write_text("")
    (app / "teto" / "launcher.py").write_text("def main():\n    return 0\n")
    cfg = tmp_path / "cfg"
    state = cfg / ("TetoAgent" if sys.platform == "win32" else "teto-agent")   # matches main._state_dir
    state.mkdir(parents=True)
    u = Updater(str(app), str(state))
    good = (app / "teto" / "launcher.py").read_bytes()
    broken = {"teto/launcher.py": b"raise SystemExit(3)\n"}
    src_files = {"teto/__init__.py": b"", "teto/launcher.py": broken["teto/launcher.py"],
                 "main.py": (app / "main.py").read_bytes()}
    src = GitHubSource("me/teto", get=FakeGitHub(src_files))
    u.apply(u.check(src), src)
    env = dict(os.environ, XDG_CONFIG_HOME=str(cfg), APPDATA=str(cfg))
    codes = [subprocess.run([sys.executable, str(app / "main.py")], env=env, cwd=str(app)).returncode
             for _ in range(3)]
    assert codes[:2] == [3, 3]                       # the broken update ran twice...
    assert (app / "teto" / "launcher.py").read_bytes() == good   # ...then was rolled back
    assert codes[2] == 0
    assert (state / "rolled_back.txt").exists()
