"""Teto Link: a tiny local bridge to the Teto Link extension in the user's Edge.

The extension (assets/teto-link) runs inside the user's own, already-open Edge
and long-polls this server for commands. That gives Teto direct access to the
user's existing tabs - including tabs that aren't showing and windows that are
covered or minimized - without opening new tabs or touching the mouse.

Only the extension can talk to it: requests must come from an extension origin
and carry the X-Teto-Link header (a web page can't send that without a CORS
preflight, which is refused).
"""

from __future__ import annotations

import itertools
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 47823
POLL_SECONDS = 20.0
_EXT_ORIGINS = ("chrome-extension://", "extension://", "moz-extension://")


class LinkError(Exception):
    pass


class LinkServer:
    def __init__(self, port: int = PORT):
        self.port = port
        self._cmds: "queue.Queue[dict]" = queue.Queue()
        self._waiting: dict[int, dict] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self.last_seen = 0.0
        self.version = ""
        self.ext_version = ""            # the extension version Teto ships; Edge reloads itself to match
        self._httpd = None

    # ------------------------------------------------------------ server
    def start(self) -> bool:
        if self._httpd is not None:
            return True
        link = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def _allowed(self) -> bool:
                origin = self.headers.get("Origin", "")
                return (self.headers.get("X-Teto-Link") == "1"
                        and (not origin or origin.startswith(_EXT_ORIGINS)))

            def _send(self, code: int, body: dict | None = None):
                data = json.dumps(body).encode() if body is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                if link.ext_version:
                    self.send_header("X-Teto-Ext-Version", link.ext_version)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if data:
                    self.wfile.write(data)

            def do_OPTIONS(self):            # CORS preflight from a web page: refuse
                self._send(403)

            def do_GET(self):
                if not self._allowed() or not self.path.startswith("/poll"):
                    return self._send(403)
                link.last_seen = time.monotonic()
                link.version = self.headers.get("X-Teto-Link-Version", link.version)
                end = time.monotonic() + POLL_SECONDS
                while True:
                    try:
                        cmd = link._cmds.get(timeout=max(0.05, end - time.monotonic()))
                    except queue.Empty:
                        return self._send(204)
                    if cmd.pop("_expires", 0) > time.monotonic():
                        break                        # stale commands (Teto gave up on them) are dropped
                link.last_seen = time.monotonic()
                self._send(200, cmd)

            def do_POST(self):
                if not self._allowed() or not self.path.startswith("/result"):
                    return self._send(403)
                link.last_seen = time.monotonic()
                try:
                    n = int(self.headers.get("Content-Length", "0") or 0)
                    msg = json.loads(self.rfile.read(min(n, 30_000_000)) or b"{}")
                except Exception:
                    return self._send(400)
                with link._lock:
                    slot = link._waiting.get(int(msg.get("id", 0) or 0))
                if slot is not None:
                    slot["msg"] = msg
                    slot["event"].set()
                self._send(200, {"ok": True})

        try:
            self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        except OSError:
            self._httpd = None
            return False
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, name="teto-link", daemon=True).start()
        return True

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    # ------------------------------------------------------------ client side
    def connected(self) -> bool:
        return self._httpd is not None and time.monotonic() - self.last_seen < POLL_SECONDS + 15

    def call(self, cmd: str, timeout: float = 20.0, **args):
        if not self.connected():
            raise LinkError("Teto Link isn't connected.")
        cid = next(self._ids)
        slot = {"event": threading.Event(), "msg": None}
        with self._lock:
            self._waiting[cid] = slot
        self._cmds.put({"id": cid, "cmd": cmd, "args": args, "_expires": time.monotonic() + timeout})
        try:
            if not slot["event"].wait(timeout):
                raise LinkError(f"Edge didn't answer {cmd!r} in time.")
        finally:
            with self._lock:
                self._waiting.pop(cid, None)
        msg = slot["msg"] or {}
        if not msg.get("ok"):
            raise LinkError(str(msg.get("error") or "unknown error"))
        return msg.get("result")


_shared: LinkServer | None = None


def shared() -> LinkServer:
    global _shared
    if _shared is None:
        _shared = LinkServer()
        _shared.start()
    return _shared
