"""The local server the Teto for Chromebook extension talks to.

One port, three jobs:
* Link  - the extension long-polls /poll for commands to run in the user's tabs
          and posts results to /result (same protocol as Teto Link on Windows).
* Events - the side panel and the on-page pet long-poll /events for what Teto
          says and does.
* API   - /api/<name> calls from the side panel (chat, stop, answer, settings...).

ChromeOS forwards localhost ports into the Linux container, so Chrome reaches
this at http://localhost:<port>. Every request must carry the install's secret
token (X-Teto-Token), which only the extension has (it's in its token.json).
"""

from __future__ import annotations

import hmac
import itertools
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

POLL_SECONDS = 20.0
_EXT_ORIGINS = ("chrome-extension://", "extension://")


class LinkError(Exception):
    pass


class Server:
    def __init__(self, token: str, port: int = 47823, host: str = "0.0.0.0"):
        self.token = token
        self.port = port
        self.host = host
        self.ext_version = ""
        self.handlers: dict[str, Callable[[dict], dict]] = {}
        # link
        self._cmds: "queue.Queue[dict]" = queue.Queue()
        self._waiting: dict[int, dict] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self.last_seen = 0.0
        # events
        self._events: list[dict] = []
        self._seq = 0
        self._cond = threading.Condition()
        self._httpd = None

    # ------------------------------------------------------------- serving
    def start(self) -> bool:
        if self._httpd is not None:
            return True
        srv = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_a):
                pass

            def _allowed(self) -> bool:
                origin = self.headers.get("Origin", "")
                if origin and not origin.startswith(_EXT_ORIGINS):
                    return False
                return hmac.compare_digest(self.headers.get("X-Teto-Token", ""), srv.token)

            def _send(self, code: int, body=None):
                data = json.dumps(body).encode() if body is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                if srv.ext_version:
                    self.send_header("X-Teto-Ext-Version", srv.ext_version)
                self.end_headers()
                if data:
                    self.wfile.write(data)

            def _body(self) -> dict:
                n = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(min(n, 30_000_000)) if n else b""
                data = json.loads(raw or b"{}")
                return data if isinstance(data, dict) else {}

            def do_OPTIONS(self):
                self._send(403)

            def do_GET(self):
                if not self._allowed():
                    return self._send(403)
                path, _, qs = self.path.partition("?")
                args = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                if path == "/poll":
                    srv.last_seen = time.monotonic()
                    cmd = srv._next_cmd()
                    return self._send(204) if cmd is None else self._send(200, cmd)
                if path == "/events":
                    try:
                        after = int(args.get("after", "0"))
                    except ValueError:
                        after = 0
                    events = srv.events_after(after, float(args.get("wait", POLL_SECONDS)))
                    return self._send(200, {"events": events, "last": srv._seq})
                if path == "/ping":
                    return self._send(200, {"ok": True})
                self._send(404)

            def do_POST(self):
                if not self._allowed():
                    return self._send(403)
                try:
                    body = self._body()
                except Exception:
                    return self._send(400)
                if self.path == "/result":
                    srv.last_seen = time.monotonic()
                    srv._resolve(body)
                    return self._send(200, {"ok": True})
                if self.path.startswith("/api/"):
                    fn = srv.handlers.get(self.path[5:])
                    if fn is None:
                        return self._send(404)
                    try:
                        return self._send(200, fn(body) or {"ok": True})
                    except Exception as e:                 # report, never crash the server
                        return self._send(200, {"ok": False, "error": f"{type(e).__name__}: {e}"})
                self._send(404)

        try:
            self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        except OSError:
            self._httpd = None
            return False
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, name="teto-cb-server", daemon=True).start()
        return True

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    # ------------------------------------------------------------- link
    def _next_cmd(self) -> dict | None:
        end = time.monotonic() + POLL_SECONDS
        while True:
            try:
                cmd = self._cmds.get(timeout=max(0.05, end - time.monotonic()))
            except queue.Empty:
                return None
            if cmd.pop("_expires", 0) > time.monotonic():
                return cmd                      # stale commands (nobody waits any more) are dropped

    def _resolve(self, msg: dict):
        with self._lock:
            slot = self._waiting.get(int(msg.get("id", 0) or 0))
        if slot is not None:
            slot["msg"] = msg
            slot["event"].set()

    def connected(self) -> bool:
        return self._httpd is not None and time.monotonic() - self.last_seen < POLL_SECONDS + 15

    def call(self, cmd: str, timeout: float = 20.0, **args):
        if not self.connected():
            raise LinkError("the Teto extension in Chrome isn't connected")
        cid = next(self._ids)
        slot = {"event": threading.Event(), "msg": None}
        with self._lock:
            self._waiting[cid] = slot
        self._cmds.put({"id": cid, "cmd": cmd, "args": args, "_expires": time.monotonic() + timeout})
        try:
            if not slot["event"].wait(timeout):
                raise LinkError(f"Chrome didn't answer {cmd!r} in time")
        finally:
            with self._lock:
                self._waiting.pop(cid, None)
        msg = slot["msg"] or {}
        if not msg.get("ok"):
            raise LinkError(str(msg.get("error") or "unknown error"))
        return msg.get("result")

    # ------------------------------------------------------------- events
    def emit(self, event: dict) -> int:
        with self._cond:
            self._seq += 1
            self._events.append({**event, "seq": self._seq, "t": time.time()})
            if len(self._events) > 600:
                self._events = self._events[-400:]
            self._cond.notify_all()
            return self._seq

    def events_after(self, after: int, wait: float = POLL_SECONDS) -> list[dict]:
        end = time.monotonic() + max(0.0, min(wait, 25.0))
        with self._cond:
            if after > self._seq:                 # server restarted: send everything we have
                after = 0
            while True:
                out = [e for e in self._events if e["seq"] > after]
                if out:
                    return out
                left = end - time.monotonic()
                if left <= 0:
                    return []
                self._cond.wait(left)

    def history(self, n: int = 200) -> list[dict]:
        with self._cond:
            return list(self._events[-n:])
