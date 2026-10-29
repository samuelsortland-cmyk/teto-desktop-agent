"""Teto for Chromebook: runs in the Chromebook's Linux side (no window).

Chrome's side panel is her chat window and she walks on your web pages; both
are the Teto for Chromebook extension, which talks to this program."""

from __future__ import annotations

import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass

from . import __version__
from .server import Server

DEFAULT_PORT = 47823


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(base, "teto-cb")
    os.makedirs(path, exist_ok=True)
    return path


@dataclass
class CbConfig:
    autonomous: bool = True          # full permission: never ask "should I?"
    speed: str = "fast"              # fast | balanced | max
    pet: bool = True                 # Teto walks on your web pages
    auto_screenshots: bool = True    # a picture of the tab after each action
    auto_update: bool = True
    model: str = "default"

    SPEEDS = {"fast": ("low", 1024), "balanced": ("medium", 1280), "max": ("high", 1568)}

    @classmethod
    def load(cls, path: str) -> "CbConfig":
        c = cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                for k, v in json.load(f).items():
                    if hasattr(c, k) and k != "SPEEDS":
                        setattr(c, k, v)
        except (OSError, ValueError):
            pass
        c.sanitize()
        return c

    def sanitize(self):
        for k in ("autonomous", "pet", "auto_screenshots", "auto_update"):
            setattr(self, k, bool(getattr(self, k)))
        if self.speed not in self.SPEEDS:
            self.speed = "fast"
        if not isinstance(self.model, str) or not self.model.strip():
            self.model = "default"

    def save(self, path: str):
        self.sanitize()
        data = {k: v for k, v in asdict(self).items()}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)

    def public(self) -> dict:
        return {k: v for k, v in asdict(self).items()}


class CbApp:
    def __init__(self, repo_dir: str, cfg_dir: str | None = None, port: int | None = None,
                 agent_factory=None, start_server: bool = True):
        self.repo_dir = repo_dir
        self.cfg_dir = cfg_dir or config_dir()
        os.makedirs(self.cfg_dir, exist_ok=True)
        self.cfg_path = os.path.join(self.cfg_dir, "config.json")
        self.config = CbConfig.load(self.cfg_path)
        self.ext_dir = os.path.join(repo_dir, "chromebook", "extension")
        self.port = port or int(os.environ.get("TETO_CB_PORT", DEFAULT_PORT))
        self.token = self._ensure_token()
        self.server = Server(self.token, self.port)
        self.server.ext_version = self._ext_version()
        for name in ("chat", "stop", "new_chat", "answer", "state", "settings", "signin", "signout", "update",
                     "eagle"):
            self.server.handlers[name] = getattr(self, "api_" + name)
        from .tools import ChromeTools
        self.tools = ChromeTools(self.server, self._tool_settings)
        self._agent_factory = agent_factory or self._make_agent
        self._agent = None
        self._tasks: "queue.Queue" = queue.Queue()
        self._pending: dict[int, dict] = {}
        self._pending_ids = iter(range(1, 10 ** 9))
        self._status = "idle"
        self.busy = False
        self.signed_in = None
        if start_server and not self.server.start():
            raise SystemExit(f"Port {self.port} is busy - is Teto already running?")
        threading.Thread(target=self._worker, name="teto-cb-worker", daemon=True).start()

    # ------------------------------------------------------------ setup
    def _ensure_token(self) -> str:
        """A secret shared with the extension: only it can talk to Teto."""
        path = os.path.join(self.cfg_dir, "token")
        try:
            with open(path, "r", encoding="utf-8") as f:
                token = f.read().strip()
        except OSError:
            token = ""
        if len(token) < 32:
            token = secrets.token_hex(24)
            with open(path, "w", encoding="utf-8") as f:
                f.write(token)
            os.chmod(path, 0o600)
        try:
            os.makedirs(self.ext_dir, exist_ok=True)
            with open(os.path.join(self.ext_dir, "token.json"), "w", encoding="utf-8") as f:
                json.dump({"token": token, "port": self.port}, f)
        except OSError:
            pass
        return token

    def _ext_version(self) -> str:
        try:
            with open(os.path.join(self.ext_dir, "manifest.json"), "r", encoding="utf-8") as f:
                return json.load(f).get("version", "")
        except (OSError, ValueError):
            return ""

    def _tool_settings(self) -> dict:
        return {"auto_screenshots": self.config.auto_screenshots,
                "screenshot_px": CbConfig.SPEEDS[self.config.speed][1]}

    def _make_agent(self):
        from teto.agent import AgentSettings
        from .brain import ChromebookAgent
        c = self.config
        effort = CbConfig.SPEEDS[c.speed][0]
        settings = AgentSettings(model="", effort=effort, max_steps=0, confirm_shell=not c.autonomous,
                                 cli_model="" if c.model == "default" else c.model, work_style="background",
                                 autonomous=c.autonomous)
        return ChromebookAgent(self, settings, self.tools)

    @property
    def agent(self):
        if self._agent is None:
            self._agent = self._agent_factory()
        return self._agent

    # ------------------------------------------------------------ UI protocol (called by the agent)
    def status(self, state: str) -> None:
        self._status = state
        self.server.emit({"type": "status", "state": state})

    def log(self, kind: str, text: str) -> None:
        self.server.emit({"type": "log", "kind": kind, "text": text})

    def _wait_answer(self, event: dict):
        pid = next(self._pending_ids)
        slot = {"event": threading.Event(), "answer": None}
        self._pending[pid] = slot
        self.server.emit({**event, "id": pid})
        stop = self.agent.stop_event if self._agent is not None else threading.Event()
        while not slot["event"].wait(0.25):
            if stop.is_set():
                break
        self._pending.pop(pid, None)
        self.server.emit({"type": "answered", "id": pid})
        return slot["answer"]

    def ask(self, question: str, choices: list[str]) -> str | None:
        return self._wait_answer({"type": "ask", "question": question, "choices": list(choices or [])})

    def confirm(self, title: str, detail: str) -> bool:
        return bool(self._wait_answer({"type": "confirm", "title": title, "detail": detail[:600]}))

    # ------------------------------------------------------------ work
    def _worker(self):
        while True:
            text, fresh = self._tasks.get()
            if text is None:
                return
            self.busy = True
            try:
                outcome = self.agent.run_task(text, fresh=fresh)
                self.server.emit({"type": "done", "outcome": outcome})
            except Exception as e:                 # never let one task kill Teto
                self.log("error", f"{type(e).__name__}: {e}")
                self.status("error")
            finally:
                self.busy = False
                if self._tasks.empty():
                    self.status("idle")

    def submit(self, text: str, fresh: bool = False):
        self._tasks.put((text, fresh))
        self.server.emit({"type": "queued", "n": self._tasks.qsize()})

    # ------------------------------------------------------------ API (side panel)
    def api_chat(self, body: dict) -> dict:
        text = str(body.get("text", "")).strip()
        if not text:
            return {"ok": False, "error": "empty message"}
        self.log("user", text)
        self.submit(text)
        return {"ok": True}

    def api_eagle(self, body: dict) -> dict:
        from .brain import EAGLE_PREFIX
        text = str(body.get("text", "")).strip()
        if not text:
            return {"ok": False, "error": "empty message"}
        self.log("user", "◉ Eagle Eyes: " + text)
        self.submit(EAGLE_PREFIX + text)
        return {"ok": True}

    def api_stop(self, body: dict) -> dict:
        while not self._tasks.empty():
            try:
                self._tasks.get_nowait()
            except queue.Empty:
                break
        for slot in list(self._pending.values()):
            slot["event"].set()
        if self._agent is not None:
            self._agent.stop()
        self.log("system", "Stopped.")
        return {"ok": True}

    def api_new_chat(self, body: dict) -> dict:
        self.api_stop({})
        if self._agent is not None:
            self._agent.new_conversation()
        self.server.emit({"type": "clear"})
        return {"ok": True}

    def api_answer(self, body: dict) -> dict:
        slot = self._pending.get(int(body.get("id", 0) or 0))
        if slot is None:
            return {"ok": False, "error": "that question is gone"}
        slot["answer"] = body.get("answer")
        slot["event"].set()
        return {"ok": True}

    def api_state(self, body: dict) -> dict:
        if self.signed_in is None and not getattr(self, "_checking", False):
            self._checking = True               # answer right away; the result arrives as an event

            def check():
                try:
                    self.server.emit({"type": "signin", "signed_in": self._check_signin()})
                finally:
                    self._checking = False
            threading.Thread(target=check, daemon=True).start()
        return {"ok": True, "version": __version__, "status": self._status, "busy": self.busy,
                "signed_in": self.signed_in, "settings": self.config.public(),
                "history": self.server.history(), "last": self.server._seq}

    def api_settings(self, body: dict) -> dict:
        changed = body.get("set") or {}
        if changed:
            for k, v in changed.items():
                if k in self.config.public():
                    setattr(self.config, k, v)
            self.config.save(self.cfg_path)
            if self._agent is not None and not self.busy:      # new settings: fresh brain next task
                try:
                    self._agent.shutdown()
                except Exception:
                    pass
                self._agent = None
            self.server.emit({"type": "settings", "settings": self.config.public()})
        return {"ok": True, "settings": self.config.public()}

    def _check_signin(self) -> bool:
        from teto.brain_cli import auth_status
        self.signed_in = bool(auth_status().get("loggedIn"))
        return self.signed_in

    def api_signin(self, body: dict) -> dict:
        from teto.brain_cli import start_login
        proc = start_login()          # opens claude.ai in Chrome; the callback comes back through localhost
        if proc is None:
            return {"ok": False, "error": "Claude Code wasn't found - run the Teto installer again."}

        def watch():
            for _ in range(240):
                time.sleep(2.5)
                if self._check_signin():
                    self.server.emit({"type": "signin", "signed_in": True})
                    self.log("teto", "Signed in! My brain is awake ♪")
                    return
        threading.Thread(target=watch, daemon=True).start()
        return {"ok": True}

    def api_signout(self, body: dict) -> dict:
        from teto.brain_cli import find_cli
        cli = find_cli()
        if cli:
            subprocess.run([cli, "auth", "logout"], capture_output=True, timeout=30)
        self.signed_in = False
        self.server.emit({"type": "signin", "signed_in": False})
        return {"ok": True}

    # ------------------------------------------------------------ updates (Chromebook copy only)
    def _git(self, *args, timeout=60) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", self.repo_dir, *args], capture_output=True, text=True, timeout=timeout)

    def update_available(self) -> bool:
        if self._git("fetch", "--quiet", "origin", "main").returncode != 0:
            return False
        head = self._git("rev-parse", "HEAD").stdout.strip()
        remote = self._git("rev-parse", "origin/main").stdout.strip()
        if not remote or head == remote:
            return False
        changed = self._git("diff", "--name-only", head, remote).stdout.split()
        return any(p.startswith(("chromebook/", "teto/")) for p in changed)

    def api_update(self, body: dict) -> dict:
        if not self.update_available():
            return {"ok": True, "updated": False}
        if self.busy and not body.get("force"):
            return {"ok": True, "updated": False, "later": True}
        return {"ok": True, "updated": self.install_update()}

    def install_update(self) -> bool:
        r = self._git("pull", "--ff-only", "--quiet", "origin", "main", timeout=180)
        if r.returncode != 0:
            self.log("error", "Update failed: " + (r.stderr.strip() or r.stdout.strip())[:300])
            return False
        pip = os.path.join(os.path.dirname(sys.executable), "pip")
        req = os.path.join(self.repo_dir, "chromebook", "requirements.txt")
        if os.path.exists(pip):
            subprocess.run([pip, "install", "-q", "-r", req], capture_output=True, timeout=900)
        self.log("system", "Teto updated herself - restarting ♪")
        threading.Timer(1.0, self.restart).start()
        return True

    def restart(self):
        os.execv(sys.executable, [sys.executable, "-m", "teto_cb"])

    def auto_update_loop(self, every: float = 3600):
        while True:
            time.sleep(every)
            if self.config.auto_update and not self.busy:
                try:
                    if self.update_available():
                        self.install_update()
                except Exception:
                    pass


def main():
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    app = CbApp(repo)
    print(f"Teto for Chromebook {__version__} is running on port {app.port}. "
          "Open Chrome and click the Teto icon to chat.", flush=True)
    threading.Thread(target=app.auto_update_loop, daemon=True).start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
