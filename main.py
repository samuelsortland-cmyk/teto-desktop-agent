"""Teto Desktop Agent - a pixel-art desktop pet that can use your computer.

Run:  python main.py

This file is kept tiny and stable on purpose: the self-updater replaces the
code in teto/, and this file (baked into Teto.exe) must keep working. It
also holds the update safety net, which runs before any updated code loads.
"""

import json
import os
import shutil
import sys


def _state_dir() -> str:
    if sys.platform == "win32":
        base = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "TetoAgent")
    else:
        base = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "teto-agent")
    os.makedirs(base, exist_ok=True)
    return base


def _safety_net(state: str) -> None:
    """If a fresh update failed to start twice, put the previous files back."""
    marker = os.path.join(state, "pending_update.json")
    if not os.path.isfile(marker):
        return
    try:
        with open(marker, "r", encoding="utf-8") as f:
            info = json.load(f)
        info["attempts"] = int(info.get("attempts", 0)) + 1
        if info["attempts"] <= 2:
            with open(marker, "w", encoding="utf-8") as f:
                json.dump(info, f)
            return
        backup = os.path.join(state, "update_backup")
        with open(os.path.join(backup, "manifest.json"), "r", encoding="utf-8") as f:
            manifest = json.load(f)
        target = manifest["target"]
        for path in manifest.get("changed", []) + manifest.get("removed", []):
            src = os.path.join(backup, *path.split("/"))
            if os.path.isfile(src):
                dest = os.path.join(target, *path.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(src, dest)
        for path in manifest.get("created", []):
            try:
                os.remove(os.path.join(target, *path.split("/")))
            except OSError:
                pass
        with open(os.path.join(state, "rolled_back.txt"), "w", encoding="utf-8") as f:
            f.write(str(info.get("label", "")))
    except Exception:
        pass
    try:
        os.remove(marker)
    except OSError:
        pass


def _use_overlay(state: str) -> None:
    """Teto.exe can't rewrite itself; updated code lives in an overlay folder."""
    overlay = os.path.join(state, "app")
    if getattr(sys, "frozen", False) and os.path.isfile(os.path.join(overlay, "teto", "__init__.py")):
        sys.path.insert(0, overlay)


if __name__ == "__main__":
    _state = _state_dir()
    _safety_net(_state)
    _use_overlay(_state)
    from teto import launcher

    sys.exit(launcher.main())
