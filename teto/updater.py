"""Self-updater: fetch only the files that changed.

Sources:
* GitHubSource - any public GitHub repository holding Teto's code. One API
  call lists every file's git hash; only files whose hash differs from the
  copy on this PC are downloaded (usually a few KB).
* ZipSource - a new Teto zip you downloaded; again only changed files are
  copied in.

Python, the pip packages and Claude Code are never downloaded again unless
`requirements.txt` changes (then just the changed packages are installed).

Running from source, files are updated in place. The standalone Teto.exe
can't rewrite itself, so updated code goes to an "overlay" folder in
%APPDATA%\\TetoAgent\\app that main.py puts first on the import path.

Safety: every downloaded file is checked against its expected hash, files are
staged before anything is replaced, the previous files are backed up, and if
the updated Teto fails to start twice in a row, main.py rolls the update back.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from typing import Callable

TRACKED_DIRS = ("teto/", "assets/", "tools/")
TRACKED_FILES = ("main.py", "requirements.txt", "START-TETO.bat", "run_debug.bat", "build_exe.bat", "README.md")
FROZEN_DIRS = ("teto/", "assets/")          # what the overlay can update inside Teto.exe
USER_AGENT = "TetoDesktopAgent-Updater"
MARKER = "pending_update.json"


class UpdateError(Exception):
    pass


def git_blob_sha(data: bytes) -> str:
    """The hash git (and GitHub) uses for file contents."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def tracked(path: str) -> bool:
    if "/__pycache__/" in path or path.endswith((".pyc", ".pyo")) or path == "assets/build_manifest.json":
        return False
    return path in TRACKED_FILES or path.startswith(TRACKED_DIRS)


def parse_version(init_py: bytes) -> str | None:
    m = re.search(rb'__version__\s*=\s*["\']([^"\']+)["\']', init_py)
    return m.group(1).decode() if m else None


def _http_get(url: str, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("Update source not found - check the repository name in Settings "
                              "(it must be a public GitHub repository).")
        if e.code in (403, 429):
            raise UpdateError("GitHub is rate-limiting update checks right now; I'll try again later.")
        raise UpdateError(f"GitHub returned an error ({e.code}).")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError(f"Couldn't reach GitHub ({getattr(e, 'reason', e)}).")


# ---------------------------------------------------------------- sources
class GitHubSource:
    def __init__(self, repo: str, branch: str = "main", get: Callable[[str], bytes] = _http_get):
        repo = repo.strip().removeprefix("https://github.com/").strip("/")
        if repo.endswith(".git"):
            repo = repo[:-4]
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            raise UpdateError("The update source must look like 'owner/repository'.")
        self.repo, self.branch, self.get = repo, (branch or "main").strip(), get
        self.commit = ""

    def snapshot(self) -> tuple[str, dict[str, str]]:
        info = json.loads(self.get(f"https://api.github.com/repos/{self.repo}/commits/{self.branch}"))
        self.commit = info["sha"]
        tree = json.loads(self.get(f"https://api.github.com/repos/{self.repo}/git/trees/{self.commit}?recursive=1"))
        if tree.get("truncated"):
            raise UpdateError("The repository is too large to update file-by-file.")
        files = {e["path"]: e["sha"] for e in tree.get("tree", []) if e.get("type") == "blob" and tracked(e["path"])}
        return self.commit[:7], files

    def fetch(self, path: str) -> bytes:
        return self.get(f"https://raw.githubusercontent.com/{self.repo}/{self.commit}/{path}")


class ZipSource:
    def __init__(self, zip_path: str):
        try:
            self.zf = zipfile.ZipFile(zip_path)
        except (OSError, zipfile.BadZipFile) as e:
            raise UpdateError(f"That isn't a readable zip file ({e}).")
        names = [n for n in self.zf.namelist() if not n.endswith("/")]
        tops = {n.split("/", 1)[0] for n in names}
        self.prefix = ""
        if len(tops) == 1 and all("/" in n for n in names):
            self.prefix = tops.pop() + "/"
        self.names = {n[len(self.prefix):]: n for n in names}
        if "teto/__init__.py" not in self.names:
            raise UpdateError("That zip doesn't look like a Teto download.")

    def snapshot(self) -> tuple[str, dict[str, str]]:
        files = {p: git_blob_sha(self.zf.read(n)) for p, n in self.names.items() if tracked(p)}
        return "zip", files

    def fetch(self, path: str) -> bytes:
        return self.zf.read(self.names[path])


# ------------------------------------------------------------------ plan
@dataclass
class Plan:
    label: str
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    expected: dict[str, str] = field(default_factory=dict)
    needs_full_download: bool = False
    version: str | None = None

    @property
    def has_changes(self) -> bool:
        return bool(self.changed or self.removed)

    @property
    def requirements_changed(self) -> bool:
        return "requirements.txt" in self.changed


class Updater:
    def __init__(self, app_root: str, state_dir: str, frozen: bool = False):
        self.app_root = app_root
        self.state_dir = state_dir
        self.frozen = frozen
        self.overlay = os.path.join(state_dir, "app")

    # where updated files live
    def target_dir(self) -> str:
        return self.overlay if self.frozen else self.app_root

    def _local_bytes(self, path: str) -> bytes | None:
        candidates = [os.path.join(self.overlay, path)] if self.frozen else []
        candidates.append(os.path.join(self.app_root, path))
        for c in candidates:
            if os.path.isfile(c):
                with open(c, "rb") as f:
                    return f.read()
        return None

    def _local_sha(self, path: str, baseline: dict[str, str]) -> str | None:
        data = self._local_bytes(path)
        if data is not None:
            return git_blob_sha(data)
        return baseline.get(path)

    def _baseline(self) -> dict[str, str]:
        """Hashes of the code baked into Teto.exe (written at build time)."""
        for base in (self.overlay, self.app_root):
            p = os.path.join(base, "assets", "build_manifest.json")
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f).get("files", {})
            except (OSError, ValueError):
                continue
        return {}

    def local_files(self) -> list[str]:
        out = []
        for d in TRACKED_DIRS:
            root = os.path.join(self.target_dir(), d)
            for dirpath, _dirs, files in os.walk(root):
                for fn in files:
                    rel = os.path.relpath(os.path.join(dirpath, fn), self.target_dir()).replace(os.sep, "/")
                    if tracked(rel):
                        out.append(rel)
        return out

    def check(self, source) -> Plan:
        label, remote = source.snapshot()
        baseline = self._baseline() if self.frozen else {}
        plan = Plan(label=label, expected=remote)
        for path, sha in sorted(remote.items()):
            if self._local_sha(path, baseline) != sha:
                plan.changed.append(path)
        for path in self.local_files():
            if path.startswith("teto/") and path.endswith(".py") and path not in remote:
                plan.removed.append(path)
        if self.frozen:
            outside = [p for p in plan.changed if not p.startswith(FROZEN_DIRS)]
            plan.needs_full_download = any(p in ("requirements.txt", "main.py") for p in outside)
            plan.changed = [p for p in plan.changed if p.startswith(FROZEN_DIRS)]
        if "teto/__init__.py" in plan.changed:
            try:
                plan.version = parse_version(source.fetch("teto/__init__.py"))
            except UpdateError:
                plan.version = None
        return plan

    def apply(self, plan: Plan, source, progress: Callable[[str], None] = lambda s: None) -> dict:
        """Download + verify everything first, then swap files in. Returns a summary."""
        if plan.needs_full_download:
            raise UpdateError("This update adds new components, so it needs the full Teto download once.")
        staged: dict[str, bytes] = {}
        for i, path in enumerate(plan.changed, 1):
            progress(f"Downloading {i}/{len(plan.changed)}: {path}")
            data = source.fetch(path)
            if git_blob_sha(data) != plan.expected[path]:
                raise UpdateError(f"{path} didn't match its checksum - update cancelled, nothing was changed.")
            staged[path] = data

        target = self.target_dir()
        backup = os.path.join(self.state_dir, "update_backup")
        shutil.rmtree(backup, ignore_errors=True)
        os.makedirs(backup, exist_ok=True)
        manifest = {"changed": [], "created": [], "removed": []}
        try:
            for path, data in staged.items():
                dest = os.path.join(target, *path.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                if os.path.isfile(dest):
                    b = os.path.join(backup, *path.split("/"))
                    os.makedirs(os.path.dirname(b), exist_ok=True)
                    shutil.copy2(dest, b)
                    manifest["changed"].append(path)
                else:
                    manifest["created"].append(path)
                tmp = dest + ".teto-new"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, dest)
            for path in plan.removed:
                dest = os.path.join(target, *path.split("/"))
                if os.path.isfile(dest):
                    b = os.path.join(backup, *path.split("/"))
                    os.makedirs(os.path.dirname(b), exist_ok=True)
                    shutil.move(dest, b)
                    manifest["removed"].append(path)
        except OSError as e:
            self._restore(backup, manifest, target)
            raise UpdateError(f"Couldn't write the update ({e}); the old version was restored.")
        with open(os.path.join(backup, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({**manifest, "target": target}, f)

        pip_ok = True
        if plan.requirements_changed and not self.frozen:
            progress("Installing new components...")
            pip_ok = self._pip_install()
        self.write_marker(plan.label)
        return {"files": len(staged), "removed": len(manifest["removed"]), "pip_ok": pip_ok,
                "version": plan.version or plan.label}

    def _pip_install(self) -> bool:
        py = sys.executable
        if py.lower().endswith("pythonw.exe"):
            py = py[:-len("pythonw.exe")] + "python.exe"
        try:
            r = subprocess.run([py, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r",
                                os.path.join(self.app_root, "requirements.txt")], capture_output=True,
                               timeout=900, stdin=subprocess.DEVNULL,
                               creationflags=0x08000000 if sys.platform == "win32" else 0)
            ok = r.returncode == 0
        except Exception:
            ok = False
        if ok:
            installed = os.path.join(self.app_root, ".venv", "installed.txt")
            if os.path.isdir(os.path.dirname(installed)):
                shutil.copy2(os.path.join(self.app_root, "requirements.txt"), installed)
        return ok

    # ---------------------------------------------------- rollback safety
    def write_marker(self, label: str):
        with open(os.path.join(self.state_dir, MARKER), "w", encoding="utf-8") as f:
            json.dump({"label": label, "attempts": 0, "time": time.time()}, f)

    def clear_marker(self):
        try:
            os.remove(os.path.join(self.state_dir, MARKER))
        except OSError:
            pass

    def startup_check(self) -> str | None:
        """Called by main.py before importing the app. Counts start attempts of
        a fresh update and rolls it back after two failed starts."""
        path = os.path.join(self.state_dir, MARKER)
        try:
            with open(path, "r", encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            return None
        info["attempts"] = int(info.get("attempts", 0)) + 1
        if info["attempts"] > 2:
            self.rollback()
            self.clear_marker()
            return "rolled_back"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(info, f)
        return None

    def rollback(self) -> bool:
        backup = os.path.join(self.state_dir, "update_backup")
        try:
            with open(os.path.join(backup, "manifest.json"), "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, ValueError):
            return False
        self._restore(backup, manifest, manifest.get("target", self.target_dir()))
        return True

    @staticmethod
    def _restore(backup: str, manifest: dict, target: str):
        for path in manifest.get("changed", []) + manifest.get("removed", []):
            src = os.path.join(backup, *path.split("/"))
            dest = os.path.join(target, *path.split("/"))
            if os.path.isfile(src):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(src, dest)
        for path in manifest.get("created", []):
            try:
                os.remove(os.path.join(target, *path.split("/")))
            except OSError:
                pass


def write_build_manifest(app_root: str, out_path: str) -> None:
    """Build step for Teto.exe: remember the hashes of the baked-in code."""
    files = {}
    for d in TRACKED_DIRS:
        for dirpath, _dirs, fns in os.walk(os.path.join(app_root, d)):
            for fn in fns:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, app_root).replace(os.sep, "/")
                if tracked(rel) and rel != "assets/build_manifest.json":
                    with open(full, "rb") as f:
                        files[rel] = git_blob_sha(f.read())
    for fn in TRACKED_FILES:
        full = os.path.join(app_root, fn)
        if os.path.isfile(full):
            with open(full, "rb") as f:
                files[fn] = git_blob_sha(f.read())
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"files": files}, f, indent=0, sort_keys=True)
