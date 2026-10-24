"""Persistent settings stored as JSON in the user's app-data folder."""

from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import asdict, dataclass, field, fields


def app_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "TetoAgent")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        path = os.path.join(base, "teto-agent")
    os.makedirs(path, exist_ok=True)
    return path


DEFAULT_UPDATE_REPO = "samuelsortland-cmyk/teto-desktop-agent"


@dataclass
class Config:
    brain: str = "subscription"       # subscription (Claude Pro/Max sign-in) | api
    api_key: str = ""                 # only for brain == "api"; empty -> ANTHROPIC_API_KEY
    model: str = "default"            # default | opus | sonnet | haiku | a full model id
    effort: str = "medium"            # low | medium | high | xhigh | max (when speed == "custom")
    speed: str = "fast"               # fast | balanced | max | custom - trades thinking time vs. depth
    max_steps: int = 0                # 0 = no step limit (Teto keeps going until the task is done)
    monitor: int = 1                  # mss monitor index (1 = primary)
    screenshot_max_long_edge: int = 1568
    confirm_shell: bool = True        # ask before running shell commands
    confirm_risky_keys: bool = True   # ask before e.g. alt+F4 / ctrl+w / delete
    pet_scale: int = 6
    wander: bool = True
    sounds: bool = False
    hotkey_stop: str = "<ctrl>+<alt>+q"
    work_style: str = "background"     # background: never borrow your mouse/keyboard without asking
    autonomous: bool = True            # V3: full permission - act without asking (no confirm prompts)
    prefer_real_browser: bool = True   # V3: work in the user's own signed-in Edge/Chrome by default
    auto_screenshots: bool = True      # V3: every browser action comes back with a picture of the tab
    show_browser: bool = False         # show Teto's own browser window instead of running it invisibly
    browser_path: str = ""             # optional: a specific Chrome/Edge executable
    stand_on_windows: bool = True      # she can land on / ride your windows
    reminders: bool = True             # water/stretch/eye-rest nudges and suggestions
    human_typing: bool = True          # natural typing rhythm + mouse glide
    typing_wpm: int = 90
    typos: bool = True                 # occasional typo, instantly corrected
    update_repo: str = DEFAULT_UPDATE_REPO   # GitHub "owner/repo" to update from
    update_branch: str = "main"
    auto_update: bool = True           # install updates by herself when idle
    routines: list = field(default_factory=list)  # [{"time":"09:00","task":"...","enabled":true,"last_run":""}]

    @classmethod
    def path(cls) -> str:
        return os.path.join(app_dir(), "config.json")

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        try:
            with open(cls.path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            known = {f.name for f in fields(cls)}
            for k, v in data.items():
                if k in known:
                    setattr(cfg, k, v)
        except FileNotFoundError:
            pass
        except Exception as e:  # corrupt file: keep defaults, don't crash
            print(f"[config] could not read config: {e}", file=sys.stderr)
        cfg._sanitize()
        return cfg

    def _sanitize(self) -> None:
        if self.work_style not in ("background", "foreground"):
            self.work_style = "background"
        if self.brain not in ("subscription", "api"):
            self.brain = "subscription"
        if not isinstance(self.model, str) or not self.model.strip():
            self.model = "default"
        if self.effort not in ("low", "medium", "high", "xhigh", "max"):
            self.effort = "medium"
        if self.speed not in ("fast", "balanced", "max", "custom"):
            self.speed = "fast"
        self.max_steps = 0                # step limits are gone: she works until the job is done
        self.pet_scale = max(2, min(int(self.pet_scale or 6), 10))
        self.screenshot_max_long_edge = max(640, min(int(self.screenshot_max_long_edge or 1568), 2560))
        self.monitor = max(1, int(self.monitor or 1))
        self.typing_wpm = max(20, min(int(self.typing_wpm or 90), 250))
        self.update_repo = str(self.update_repo or "").strip() or DEFAULT_UPDATE_REPO
        self.update_branch = str(self.update_branch or "main").strip() or "main"
        if not isinstance(self.routines, list):
            self.routines = []
        for name in ("autonomous", "prefer_real_browser", "confirm_shell", "confirm_risky_keys",
                     "auto_screenshots", "show_browser", "human_typing", "typos", "auto_update"):
            v = getattr(self, name)
            if isinstance(v, str):
                v = v.strip().lower() in ("1", "true", "yes", "on")
            setattr(self, name, bool(v))

    # Speed profile -> (thinking effort, screenshot long-edge px). Smaller, lower-effort
    # requests come back from the model faster, which is what sets Teto's real pace.
    SPEED_PROFILES = {"fast": ("low", 1024), "balanced": ("medium", 1280), "max": ("high", 1568)}

    def effective_effort(self) -> str:
        if self.speed == "custom":
            return self.effort
        return self.SPEED_PROFILES.get(self.speed, self.SPEED_PROFILES["fast"])[0]

    def effective_screenshot_px(self) -> int:
        if self.speed == "custom":
            return self.screenshot_max_long_edge
        return self.SPEED_PROFILES.get(self.speed, self.SPEED_PROFILES["fast"])[1]

    _lock = threading.Lock()

    def save(self) -> None:
        self._sanitize()
        tmp = self.path() + ".tmp"
        with self._lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2)
            os.replace(tmp, self.path())
