import json
import os
import shutil
import socket
import threading
import time
import types
import urllib.error
import urllib.request

import pytest

from teto_cb.server import LinkError, Server

CB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMIUM = os.environ.get("TETO_BROWSER_PATH") or shutil.which("chromium") or "/opt/pw-browsers/chromium"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def req(port, path, token="", method="GET", body=None, origin=None, timeout=30):
    h = {"X-Teto-Token": token}
    if origin:
        h["Origin"] = origin
    if body is not None:
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, headers=h,
                               data=json.dumps(body).encode() if body is not None else None)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(r, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, None


# ------------------------------------------------------------------ server
def test_server_requires_the_token_and_relays_link_and_events(monkeypatch):
    import teto_cb.server as srv_mod
    monkeypatch.setattr(srv_mod, "POLL_SECONDS", 0.5)
    port = free_port()
    s = Server("t" * 48, port, host="127.0.0.1")
    s.handlers["echo"] = lambda b: {"ok": True, "got": b}
    assert s.start()
    try:
        assert req(port, "/ping")[0] == 403                                   # no token
        assert req(port, "/ping", "wrong")[0] == 403
        assert req(port, "/ping", "t" * 48, origin="https://evil.example")[0] == 403
        assert req(port, "/ping", "t" * 48, origin="chrome-extension://abc")[0] == 200
        assert req(port, "/api/echo", "t" * 48, "POST", {"a": 1})[1] == {"ok": True, "got": {"a": 1}}

        def extension():
            code, cmd = req(port, "/poll", "t" * 48)
            req(port, "/result", "t" * 48, "POST", {"id": cmd["id"], "ok": True, "result": cmd["args"]})
        assert req(port, "/poll", "t" * 48)[0] == 204                        # marks the extension connected
        t = threading.Thread(target=extension)
        t.start()
        assert s.call("tabs", x=2) == {"x": 2}
        t.join()
        with pytest.raises(LinkError):
            s.call("tabs", timeout=0.2)

        n = s.emit({"type": "log", "kind": "teto", "text": "hi"})
        code, data = req(port, f"/events?after={n - 1}&wait=0", "t" * 48)
        assert data["events"][0]["text"] == "hi" and data["last"] == n
        got = {}
        threading.Thread(target=lambda: got.update(req(port, f"/events?after={n}&wait=5", "t" * 48)[1])).start()
        time.sleep(0.3)
        s.emit({"type": "status", "state": "working"})                        # wakes the long-poll
        time.sleep(0.3)
        assert got["events"][0]["state"] == "working"
    finally:
        s.stop()


# ------------------------------------------------------------------ app
class FakeAgent:
    def __init__(self, app):
        self.app = app
        self.stop_event = threading.Event()
        self.tasks = []

    def run_task(self, text, fresh=False):
        self.tasks.append(text)
        self.app.status("working")
        if "ask" in text:
            a = self.app.ask("Which one?", ["A", "B"])
            self.app.log("teto", f"You picked {a}")
        else:
            self.app.log("teto", f"Done: {text}")
        self.app.status("success")
        return "done"

    def stop(self):
        self.stop_event.set()

    def new_conversation(self):
        pass

    def shutdown(self):
        pass


def make_app(tmp_path, **kw):
    from teto_cb.app import CbApp
    repo = tmp_path / "repo"
    shutil.copytree(os.path.join(CB, "extension"), repo / "chromebook" / "extension",
                    ignore=shutil.ignore_patterns("token.json"))
    holder = {}
    app = CbApp(str(repo), cfg_dir=str(tmp_path / "cfg"), port=free_port(),
                agent_factory=lambda: holder.setdefault("a", FakeAgent(holder["app"])), **kw)
    holder["app"] = app
    app.server.host = "127.0.0.1"
    return app, holder


def wait_for(cond, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_app_chat_ask_settings_and_token(tmp_path, monkeypatch):
    import teto.brain_cli as bc
    monkeypatch.setattr(bc, "auth_status", lambda: {"loggedIn": True})
    app, h = make_app(tmp_path)
    try:
        tok = json.loads((tmp_path / "repo/chromebook/extension/token.json").read_text())
        assert tok["token"] == app.token and tok["port"] == app.port and len(app.token) >= 32
        st = app.api_state({})                     # answers at once; sign-in status follows as an event
        assert st["settings"]["autonomous"] is True and st["version"]
        assert wait_for(lambda: any(e["type"] == "signin" and e["signed_in"] for e in app.server.history()))
        assert app.api_state({})["signed_in"] is True
        app.api_chat({"text": "summarize this page"})
        assert wait_for(lambda: any(e.get("text") == "Done: summarize this page" for e in app.server.history()))
        kinds = [(e["type"], e.get("kind") or e.get("state")) for e in app.server.history()]
        assert ("log", "user") in kinds and ("status", "working") in kinds

        app.api_chat({"text": "please ask me"})
        assert wait_for(lambda: any(e["type"] == "ask" for e in app.server.history()))
        q = next(e for e in app.server.history() if e["type"] == "ask")
        assert q["choices"] == ["A", "B"]
        assert app.api_answer({"id": q["id"], "answer": "B"})["ok"]
        assert wait_for(lambda: any(e.get("text") == "You picked B" for e in app.server.history()))

        r = app.api_settings({"set": {"speed": "max", "pet": False, "bogus": 1}})
        assert r["settings"]["speed"] == "max" and r["settings"]["pet"] is False and "bogus" not in r["settings"]
        saved = json.loads((tmp_path / "cfg/config.json").read_text())
        assert saved["speed"] == "max"

        app.api_eagle({"text": "jump over the gap"})
        assert wait_for(lambda: any("EAGLE EYES" in t for t in h["a"].tasks))
        app.api_new_chat({})
        assert any(e["type"] == "clear" for e in app.server.history())
    finally:
        app.server.stop()


def test_chromebook_brain_has_tab_tools_not_windows_tools(tmp_path):
    from teto.agent import AgentSettings
    from teto_cb.brain import ChromebookAgent, cb_prompt
    from teto_cb.tools import ChromeTools
    tools = ChromeTools(Server("x" * 40, free_port()))
    a = ChromebookAgent(types.SimpleNamespace(status=print, log=print, ask=None, confirm=None),
                        AgentSettings(autonomous=True, work_style="background"), tools)
    try:
        names = set(a.tool_specs)
        assert {"my_tab_read", "my_tab_click", "tab_screenshot", "tab_click_xy", "browser_open", "run_shell",
                "say", "ask_user"} <= names
        assert not names & {"screenshot", "click", "type_text", "press_key", "open_target", "zoom"}
        opts = a._options()
        assert "Chromebook" in opts.system_prompt and "Windows" not in opts.system_prompt
        assert all(t.split("__")[-1] in names for t in opts.allowed_tools)
        assert "full permission" in cb_prompt(True) and "Ask the user" in cb_prompt(False)
        a.tab_policy.note_task("do my quiz")                 # same no-new-tabs rule as on Windows
        res = a._handle_tool("browser_open", {"url": "https://google.com"})
        assert res["is_error"] and "did NOT ask" in res["content"][0]["text"]
    finally:
        a.shutdown()


def test_windows_updater_never_picks_up_chromebook_files():
    from teto.updater import tracked
    for p in ("chromebook/teto_cb/app.py", "chromebook/extension/manifest.json", "chromebook/install.sh"):
        assert not tracked(p)


# ------------------------------------------------------------------ the real extension, end to end
QUIZ = """<!doctype html><title>AP World History Unit 1 Practice Test</title>
<style>.opt{border:1px solid #ccc;padding:8px;margin:4px;cursor:pointer}</style>
<p id=q>1. The author's point of view regarding the passage is:</p>
<div class=opt onclick="pick(this)">Critical of the peasant class</div>
<div class=opt onclick="pick(this)">Sympathetic to the nobility</div>
<p id=res></p>
<canvas id=game width=300 height=150 style="border:1px solid"></canvas>
<script>function pick(el){document.getElementById('res').innerText='Correct: '+el.innerText}
document.getElementById('game').addEventListener('mousedown',e=>{document.title='hit '+e.offsetX+','+e.offsetY});
</script>"""


@pytest.mark.skipif(not os.path.exists(CHROMIUM), reason="no Chromium available")
def test_extension_end_to_end(tmp_path, monkeypatch):
    import http.server
    from playwright.sync_api import sync_playwright
    import teto.brain_cli as bc
    monkeypatch.setattr(bc, "auth_status", lambda: {"loggedIn": True})

    site = tmp_path / "site"
    site.mkdir()
    (site / "quiz.html").write_text(QUIZ)
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(site), **k)
    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    web.RequestHandlerClass.log_message = lambda *a: None
    threading.Thread(target=web.serve_forever, daemon=True).start()
    quiz_url = f"http://127.0.0.1:{web.server_address[1]}/quiz.html"

    app, h = make_app(tmp_path)
    ext = str(tmp_path / "repo/chromebook/extension")
    pw = sync_playwright().start()
    ctx = None
    try:
        ctx = pw.chromium.launch_persistent_context(
            str(tmp_path / "prof"), headless=False, executable_path=CHROMIUM, viewport={"width": 900, "height": 700},
            args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}", "--no-sandbox"])
        quiz = ctx.pages[0] if ctx.pages else ctx.new_page()
        quiz.goto(quiz_url)
        assert wait_for(app.server.connected, 20), "extension never connected"

        # Teto walks on the page (her own shadow-DOM element)
        quiz.wait_for_selector("#teto-pet-host", state="attached", timeout=10000)

        # work in the existing tab
        out = app.tools.run("my_tab_read", {"tab": "AP World"})
        text = out[0]["text"] if isinstance(out, list) else out
        assert "1. The author's point of view" in text
        ref = next(l.split("]")[0][1:] for l in text.splitlines() if l.startswith("[") and "Critical of the peasant" in l)
        out = app.tools.run("my_tab_click", {"ref": int(ref)})
        text = out[0]["text"] if isinstance(out, list) else out
        assert "Correct: Critical of the peasant class" in text

        # Eagle Eyes on a canvas: picture + real click lands where the model aimed
        shot = app.tools.run("tab_screenshot", {})
        assert shot[0]["type"] == "image"
        box = quiz.locator("#game").bounding_box()
        s = app.tools._shot
        app.tools.run("tab_click_xy", {"x": int((box["x"] + 50) / s["sx"]), "y": int((box["y"] + 40) / s["sy"])})
        assert wait_for(lambda: quiz.title().startswith("hit "), 5)
        hx, hy = map(int, quiz.title()[4:].split(","))
        assert abs(hx - 50) <= 4 and abs(hy - 40) <= 4
        assert quiz.locator("#teto-pet-host").evaluate("e => e.style.display") != "none"   # back after the picture

        # the side panel chat
        ext_id = ctx.service_workers[0].url.split("/")[2]
        panel = ctx.new_page()
        panel.goto(f"chrome-extension://{ext_id}/panel.html")
        panel.wait_for_selector("text=Online", timeout=10000)
        panel.fill("#input", "say hi to my bread")
        panel.press("#input", "Enter")
        panel.wait_for_selector("text=Done: say hi to my bread", timeout=10000)
        assert panel.locator(".msg.user", has_text="say hi to my bread").count() == 1
        panel.fill("#input", "ask me something")
        panel.press("#input", "Enter")
        panel.wait_for_selector("#replies >> text=B", timeout=10000)
        panel.click("#replies >> text=B")
        panel.wait_for_selector("text=You picked B", timeout=10000)
    finally:
        if ctx:
            ctx.close()
        pw.stop()
        app.server.stop()
        web.shutdown()
