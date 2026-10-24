"""Chat panel, confirmation prompts and settings window (pixel-themed Tk)."""

from __future__ import annotations

import os
import re
import tkinter as tk
from tkinter import ttk

from . import platform_win

# Teto theme
BG = "#2a1822"
BG2 = "#3a2330"
PANEL = "#4a2d3c"
RED = "#e0435f"
RED_D = "#a8274a"
PINK = "#ff8fa3"
GREY = "#8c8a96"
TEXT = "#fff1f4"
DIM = "#b9a3ad"
ERR = "#ff6b6b"
OK = "#8fe3a1"

MODELS = ["default", "opus", "sonnet", "haiku", "claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"]
WORK_STYLES = {"background": "Background - don't use my mouse/keyboard (recommended)",
               "foreground": "Foreground - Teto may use my mouse & keyboard"}
SPEEDS = {"fast": "Fast - quickest, snappiest (recommended)", "balanced": "Balanced - a bit more careful",
          "max": "Max - slowest but most thorough", "custom": "Custom (use Effort below)"}
BRAINS = {"subscription": "Claude subscription (Pro/Max sign-in)", "api": "Anthropic API key (advanced)"}
EFFORTS = ["low", "medium", "high", "xhigh", "max"]


_FACE_CACHE: dict = {}


def _teto_face_icon(root, size: int):
    """A small Teto chibi face for the header (cached per size)."""
    if size in _FACE_CACHE:
        return _FACE_CACHE[size]
    try:
        from PIL import ImageTk

        from . import sprites
        img = sprites.render_pose(sprites.Pose(eyes="happy", mouth="smile"), 2)
        head = img.crop((sprites.OFF_X * 2, sprites.OFF_Y * 2,
                         (sprites.OFF_X + sprites.GRID_W) * 2, (sprites.OFF_Y + 16) * 2))
        box = head.getbbox() or (0, 0, head.width, head.height)
        head = head.crop(box)
        k = max(1, size // head.height)
        photo = ImageTk.PhotoImage(head.resize((head.width * k, head.height * k)))
    except Exception:
        photo = None
    _FACE_CACHE[size] = photo
    return photo


def pixel_button(parent, text, command, color=RED, fg=TEXT, width=None):
    b = tk.Button(parent, text=text, command=command, bg=color, fg=fg, activebackground=PINK,
                  activeforeground=BG, relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
                  highlightthickness=2, highlightbackground="#1a0e15", font=parent._font_b)
    if width:
        b.config(width=width)
    return b


class Panel:
    def __init__(self, root: tk.Tk, app, font):
        self.root = root
        self.app = app
        fam = font[0]
        self.font = (fam, 10)
        self.font_b = (fam, 10, "bold")
        self.font_h = (fam, 12, "bold")

        w = self.win = tk.Toplevel(root)
        w.title("Teto - Desktop Agent")
        w.configure(bg=BG)
        self.k = max(1.0, root.winfo_fpixels("1i") / 96.0)   # high-DPI displays
        self.pw, self.ph = int(440 * self.k), int(600 * self.k)
        w.geometry(f"{self.pw}x{self.ph}")
        w.minsize(int(360 * self.k), int(420 * self.k))
        w.protocol("WM_DELETE_WINDOW", self.hide)
        w.attributes("-topmost", True)
        w._font_b = self.font_b
        w.bind("<Escape>", lambda e: self.app.stop_all())

        # header - a little Teto face, her name, and a status lamp
        head = tk.Frame(w, bg=RED)
        head.pack(fill="x")
        head._font_b = self.font_b
        self._face = _teto_face_icon(root, max(28, int(34 * self.k)))
        if self._face is not None:
            tk.Label(head, image=self._face, bg=RED, bd=0).pack(side="left", padx=(8, 4), pady=4)
        titles = tk.Frame(head, bg=RED)
        titles.pack(side="left", pady=4)
        tk.Label(titles, text="Teto", bg=RED, fg=TEXT, font=(fam, 13, "bold")).pack(anchor="w")
        tk.Label(titles, text="your desktop buddy ♪", bg=RED, fg="#ffd6de",
                 font=(fam, 8)).pack(anchor="w")
        self.status_lbl = tk.Label(head, text="● idle", bg=RED, fg=TEXT, font=self.font_b, padx=10)
        self.status_lbl.pack(side="right")
        self._scallop(w)

        # toolbar
        bar = tk.Frame(w, bg=BG2, pady=6, padx=6)
        bar.pack(fill="x")
        bar._font_b = self.font_b
        self.stop_btn = pixel_button(bar, "■ STOP", self.app.stop_all, color="#c0392b")
        self.stop_btn.pack(side="left")
        pixel_button(bar, "NEW CHAT", self.app.new_chat, color=PANEL).pack(side="left", padx=6)
        pixel_button(bar, "SETTINGS", self.app.open_settings, color=PANEL).pack(side="left")
        self.queue_lbl = tk.Label(bar, text="", bg=BG2, fg=DIM, font=self.font)
        self.queue_lbl.pack(side="right")

        # "Sign in with Claude" banner (shown only when the subscription brain isn't signed in)
        self.signin = tk.Frame(w, bg=PINK, padx=8, pady=8)
        self.signin._font_b = self.font_b
        self.signin_lbl = tk.Label(self.signin, text="", bg=PINK, fg="#1a0e15", font=self.font_b,
                                   justify="left", anchor="w", wraplength=int(250 * self.k))
        self.signin_lbl.pack(side="left", fill="x", expand=True)
        self.signin_btn = pixel_button(self.signin, "SIGN IN WITH CLAUDE", self.app.sign_in, color=RED_D)
        self.signin_btn.pack(side="right")
        self._signin_anchor = bar

        self.update_bar = tk.Frame(w, bg="#ffd98a", padx=8, pady=6)
        self.update_bar._font_b = self.font_b
        self.update_lbl = tk.Label(self.update_bar, text="", bg="#ffd98a", fg="#1a0e15", font=self.font_b,
                                   anchor="w")
        self.update_lbl.pack(side="left", fill="x", expand=True)
        pixel_button(self.update_bar, "UPDATE", self.app.install_update, color=RED_D).pack(side="right")

        # log
        body = self.body = tk.Frame(w, bg=BG, padx=6, pady=6)
        self.log_txt = tk.Text(body, height=10, bg=BG, fg=TEXT, font=self.font, wrap="word", bd=0,
                               highlightthickness=2, highlightbackground=PANEL, padx=8, pady=8,
                               state="disabled", cursor="arrow", spacing1=2, spacing3=4)
        sb = tk.Scrollbar(body, command=self.log_txt.yview, bg=PANEL, troughcolor=BG, bd=0)
        self.log_txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_txt.pack(side="left", fill="both", expand=True)
        t = self.log_txt
        t.tag_config("user", foreground="#ffe08a", font=self.font_b, lmargin1=40, lmargin2=40)
        t.tag_config("teto", foreground=PINK, font=self.font_b)
        t.tag_config("thought", foreground=DIM, lmargin1=14, lmargin2=14)
        t.tag_config("action", foreground="#9fc3ff", lmargin1=14, lmargin2=14)
        t.tag_config("error", foreground=ERR)
        t.tag_config("system", foreground=GREY)
        t.tag_config("ask", foreground="#1a0e15", background=PINK, font=self.font_b)

        # question / confirmation area (hidden until needed)
        self.ask_frame = tk.Frame(w, bg=PANEL, padx=8, pady=8)
        self.ask_frame._font_b = self.font_b
        self.ask_lbl = tk.Label(self.ask_frame, text="", bg=PANEL, fg=TEXT, font=self.font_b,
                                justify="left", anchor="w", wraplength=380)
        self.ask_lbl.pack(fill="x")
        self.ask_btns = tk.Frame(self.ask_frame, bg=PANEL)
        self.ask_btns._font_b = self.font_b
        self.ask_btns.pack(fill="x", pady=(6, 0))
        self._pending = None          # (kind, callback)

        # input
        inp = tk.Frame(w, bg=BG2, padx=6, pady=6)
        inp.pack(fill="x", side="bottom")
        inp._font_b = self.font_b
        self.entry = tk.Text(inp, height=3, bg="#1a0e15", fg=TEXT, insertbackground=PINK, font=self.font,
                             bd=0, highlightthickness=2, highlightbackground=RED_D, highlightcolor=RED,
                             wrap="word", padx=6, pady=6)
        pixel_button(inp, "SEND ►", self._submit).pack(side="right", padx=(6, 0), fill="y")
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", self._on_enter)
        self.opts = tk.Frame(w, bg=BG2, padx=6)
        self.opts.pack(fill="x", side="bottom")
        self.shell_var = tk.BooleanVar(value=self.app.config.confirm_shell)
        tk.Checkbutton(self.opts, text="Ask before shell commands", variable=self.shell_var,
                       command=self._toggle_shell, bg=BG2, fg=DIM, selectcolor=BG, activebackground=BG2,
                       activeforeground=TEXT, font=self.font, bd=0).pack(side="left")
        tk.Label(self.opts, text="Stop: Esc · Ctrl+Alt+Q", bg=BG2, fg=GREY,
                 font=(self.font[0], 8)).pack(side="right")
        # packed last so the log shrinks first and the input never gets squeezed off-screen
        body.pack(fill="both", expand=True)

        self._place_default()
        self.visible = True
        self.win.after(300, lambda: platform_win.exclude_from_capture(self.win))
        self.log("teto", "Hiii~ I'm Teto! Tell me what to do on your PC and I'll handle it. ♪")
        self.log("system", "Try: \"open Notepad and write a haiku about bread\"")
        self.entry.focus_set()

    def _scallop(self, parent):
        """A decorative pixel-scallop divider with little drills and notes."""
        h = int(10 * self.k)
        c = tk.Canvas(parent, height=h, bg=RED, highlightthickness=0, bd=0)
        c.pack(fill="x")

        def redraw(_e=None):
            c.delete("all")
            w = c.winfo_width() or self.pw
            step = int(10 * self.k)
            for x in range(0, w + step, step):          # scalloped bottom edge
                c.create_oval(x - step // 2, -h, x + step // 2, h, fill=RED_D, outline="")
            for i, x in enumerate(range(step, w, step * 4)):   # drill-pink dots + notes
                col = PINK if i % 2 else "#ffd6de"
                c.create_rectangle(x, h // 2 - 1, x + 2, h // 2 + 1, fill=col, outline="")
        c.bind("<Configure>", redraw)
        self.root.after(60, redraw)

    # ------------------------------------------------------------- window
    def _place_default(self):
        """Bottom-right, but left of where the pet sits so they don't overlap."""
        self.win.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        left, top, right, bottom = platform_win.work_area(sw, sh)
        x = right - self.pw - int(360 * self.k)
        self.win.geometry(f"+{max(left, x)}+{max(top, bottom - self.ph - 40)}")

    def show(self):
        self.win.deiconify()
        self.win.lift()
        self.entry.focus_set()
        self.visible = True

    def hide(self):
        self.win.withdraw()
        self.visible = False

    def rect(self):
        if not self.visible:
            return None
        x, y = self.win.winfo_rootx(), self.win.winfo_rooty()
        return x, y - 32, x + self.win.winfo_width(), y + self.win.winfo_height()

    def dodge(self, px, py):
        r = self.rect()
        if not r:
            return
        x0, y0, x1, y1 = r
        if not (x0 - 10 <= px <= x1 + 10 and y0 - 10 <= py <= y1 + 10):
            return
        sw = self.root.winfo_screenwidth()
        w = x1 - x0
        nx = 10 if px > sw / 2 else sw - w - 10
        if nx <= px <= nx + w:          # screen too narrow to dodge: get out of the way
            self.win.iconify()
            self.visible = False
            return
        self.win.geometry(f"+{nx}+{max(0, y0 + 32)}")
        self.win.update_idletasks()

    # ---------------------------------------------------------------- log
    def log(self, kind: str, text: str):
        prefix = {"user": "", "teto": "Teto ♪ ", "thought": "· ", "action": "> ",
                  "error": "! ", "system": "~ "}.get(kind, "")
        t = self.log_txt
        t.configure(state="normal")
        t.insert("end", prefix + text.strip() + "\n", kind)
        # keep the log from growing without bound
        lines = int(t.index("end-1c").split(".")[0])
        if lines > 2000:
            t.delete("1.0", f"{lines - 1500}.0")
        t.configure(state="disabled")
        t.see("end")

    def set_status(self, state: str):
        colors = {"idle": TEXT, "thinking": "#ffe08a", "working": "#9fc3ff", "talking": TEXT,
                  "waiting": "#ffe08a", "success": OK, "error": "#ffd0d0"}
        label = {"waiting": "needs you!", "talking": "working"}.get(state, state)
        self.status_lbl.config(text=f"● {label}", fg=colors.get(state, TEXT))

    def set_update(self, text: str | None):
        """Show 'update ready' with an UPDATE button, or hide it (None)."""
        if text is None:
            self.update_bar.pack_forget()
            return
        self.update_lbl.config(text=text)
        if not self.update_bar.winfo_ismapped():
            self.update_bar.pack(fill="x", after=self._signin_anchor)

    def set_signin(self, state: str):
        """hidden | signed_out | waiting"""
        if state == "hidden":
            self.signin.pack_forget()
            return
        if state == "waiting":
            self.signin_lbl.config(text="Finish signing in in your browser...\n(I'll notice automatically)")
            self.signin_btn.config(text="OPEN AGAIN")
        else:
            self.signin_lbl.config(text="Sign in with your Claude account\n(Pro or Max) to wake my brain ♪")
            self.signin_btn.config(text="SIGN IN WITH CLAUDE")
        if not self.signin.winfo_ismapped():
            self.signin.pack(fill="x", after=self._signin_anchor)
        self.show()

    def set_queue(self, n: int):
        self.queue_lbl.config(text=f"{n} queued" if n else "")

    # -------------------------------------------------------------- input
    def _on_enter(self, e):
        if e.state & 0x0001:        # shift held -> newline
            return None
        self._submit()
        return "break"

    def _submit(self):
        text = self.entry.get("1.0", "end").strip()
        if not text:
            return
        self.entry.delete("1.0", "end")
        if self._pending and self._pending[0] == "ask":
            self._answer(text)
            return
        self.log("user", text)
        self.app.submit_task(text)

    def _toggle_shell(self):
        self.app.config.confirm_shell = bool(self.shell_var.get())
        self.app.config.save()
        self.app.apply_settings()

    # ------------------------------------------------- questions / confirm
    def ask(self, question: str, choices: list[str], callback):
        """Show a question; callback(answer) is called once with the answer."""
        self._clear_pending()
        self._pending = ("ask", callback)
        self.log("ask", f" ? {question} ")
        self.ask_lbl.config(text=question)
        for c in choices:
            pixel_button(self.ask_btns, c, lambda c=c: self._answer(c), color=RED).pack(side="left", padx=(0, 6))
        tk.Label(self.ask_btns, text="...or type your answer below", bg=PANEL, fg=DIM,
                 font=self.font).pack(side="left")
        self.ask_frame.pack(fill="x", before=self.body, side="bottom")
        self.show()

    def confirm(self, title: str, detail: str, callback):
        self._clear_pending()
        self._pending = ("confirm", callback)
        self.log("ask", f" ? {title} ")
        self.ask_lbl.config(text=f"{title}\n\n{detail[:600]}")
        pixel_button(self.ask_btns, "ALLOW", lambda: self._resolve(True), color="#2e8b57").pack(side="left")
        pixel_button(self.ask_btns, "DENY", lambda: self._resolve(False), color="#c0392b").pack(side="left", padx=6)
        self.ask_frame.pack(fill="x", before=self.body, side="bottom")
        self.show()

    def _answer(self, text: str):
        if self._pending and self._pending[0] == "ask":
            self.log("user", text)
            self._resolve(text)

    def _resolve(self, value):
        pending = self._pending
        self._clear_pending()
        if pending:
            pending[1](value)

    def cancel_pending(self):
        """Stop pressed while a question is open: answer it with None/False."""
        pending = self._pending
        self._clear_pending()
        if pending:
            pending[1](None if pending[0] == "ask" else False)

    def _clear_pending(self):
        self._pending = None
        for c in self.ask_btns.winfo_children():
            c.destroy()
        self.ask_frame.pack_forget()


class SettingsWindow:
    def __init__(self, root, app, font):
        self.app = app
        cfg = app.config
        fam = font[0]
        f, fb = (fam, 10), (fam, 10, "bold")
        w = self.win = tk.Toplevel(root)
        w.title("Teto - Settings")
        w.configure(bg=BG, padx=14, pady=12)
        w.attributes("-topmost", True)
        w.resizable(False, False)
        w._font_b = fb

        def row(label, widget, r):
            tk.Label(w, text=label, bg=BG, fg=TEXT, font=fb, anchor="w").grid(row=r, column=0, sticky="w", pady=4)
            widget.grid(row=r, column=1, sticky="we", pady=4, padx=(10, 0))

        ent = dict(bg="#1a0e15", fg=TEXT, insertbackground=PINK, font=f, bd=0, highlightthickness=2,
                   highlightbackground=RED_D, highlightcolor=RED)
        self.brain = ttk.Combobox(w, values=list(BRAINS.values()), state="readonly", width=36)
        self.brain.set(BRAINS.get(cfg.brain, BRAINS["subscription"]))
        row("Brain", self.brain, 0)
        self.key = tk.Entry(w, show="•", width=38, **ent)
        self.key.insert(0, cfg.api_key)
        row("API key (advanced only)", self.key, 1)
        self.model = ttk.Combobox(w, values=MODELS, width=30)
        self.model.set(cfg.model)
        row("Model", self.model, 2)
        self.speed = ttk.Combobox(w, values=list(SPEEDS.values()), state="readonly", width=30)
        self.speed.set(SPEEDS.get(cfg.speed, SPEEDS["fast"]))
        row("Speed", self.speed, 3)
        self.effort = ttk.Combobox(w, values=EFFORTS, state="readonly", width=30)
        self.effort.set(cfg.effort)
        self.steps = tk.Spinbox(w, from_=5, to=500, width=8, **ent)
        self.steps.delete(0, "end"); self.steps.insert(0, str(cfg.max_steps))
        row("Max steps per task", self.steps, 4)
        self.shot = ttk.Combobox(w, values=["1280", "1366", "1568", "1920", "2560"], width=30)
        self.shot.set(str(cfg.screenshot_max_long_edge))
        row("Screenshot size (px)", self.shot, 5)
        self.monitor = tk.Spinbox(w, from_=1, to=8, width=8, **ent)
        self.monitor.delete(0, "end"); self.monitor.insert(0, str(cfg.monitor))
        row("Monitor", self.monitor, 6)
        self.scale = tk.Spinbox(w, from_=2, to=10, width=8, **ent)
        self.scale.delete(0, "end"); self.scale.insert(0, str(cfg.pet_scale))
        row("Pet size", self.scale, 7)

        chk = dict(bg=BG, fg=TEXT, selectcolor=BG2, activebackground=BG, activeforeground=PINK, font=f, bd=0)
        self.v_shell = tk.BooleanVar(value=cfg.confirm_shell)
        self.v_keys = tk.BooleanVar(value=cfg.confirm_risky_keys)
        self.v_wander = tk.BooleanVar(value=cfg.wander)
        tk.Checkbutton(w, text="Ask before running shell commands", variable=self.v_shell, **chk).grid(
            row=8, column=0, columnspan=2, sticky="w")
        tk.Checkbutton(w, text="Ask before permanent-delete shortcuts", variable=self.v_keys, **chk).grid(
            row=9, column=0, columnspan=2, sticky="w")
        tk.Checkbutton(w, text="Let Teto wander around when idle", variable=self.v_wander, **chk).grid(
            row=10, column=0, columnspan=2, sticky="w")

        # right-hand column: personality + updates
        side = tk.Frame(w, bg=BG)
        side._font_b = fb
        side.grid(row=0, column=2, rowspan=14, sticky="n", padx=(22, 0))
        tk.Label(side, text="Sharing your PC", bg=BG, fg=PINK, font=fb).pack(anchor="w")
        self.style = ttk.Combobox(side, values=list(WORK_STYLES.values()), state="readonly", width=40)
        self.style.set(WORK_STYLES.get(cfg.work_style, WORK_STYLES["background"]))
        self.style.pack(anchor="w", pady=(2, 2))
        self.v_auton = tk.BooleanVar(value=cfg.autonomous)
        self.v_real = tk.BooleanVar(value=cfg.prefer_real_browser)
        self.v_see = tk.BooleanVar(value=cfg.auto_screenshots)
        self.v_showb = tk.BooleanVar(value=cfg.show_browser)
        for text, var in (("Full permission - just do it, never ask", self.v_auton),
                          ("Work in my signed-in Edge", self.v_real),
                          ("See the page after every action", self.v_see),
                          ("Show Teto's browser window", self.v_showb)):
            tk.Checkbutton(side, text=text, variable=var, **chk).pack(anchor="w")
        tk.Label(side, text="Background: Teto works in background tabs of your Edge (with your\n"
                            "logins) and talks to apps directly, so you can keep using your PC.", bg=BG, fg=GREY,
                 font=(fam, 8), justify="left").pack(anchor="w", pady=(0, 12))
        tk.Label(side, text="Personality", bg=BG, fg=PINK, font=fb).pack(anchor="w")
        self.v_windows = tk.BooleanVar(value=cfg.stand_on_windows)
        self.v_remind = tk.BooleanVar(value=cfg.reminders)
        self.v_human = tk.BooleanVar(value=cfg.human_typing)
        self.v_typos = tk.BooleanVar(value=cfg.typos)
        for text, var in (("Jump onto / ride my windows", self.v_windows),
                          ("Helpful nudges & suggestions", self.v_remind),
                          ("Human-like typing & mouse", self.v_human),
                          ("Occasional typos (auto-fixed)", self.v_typos)):
            tk.Checkbutton(side, text=text, variable=var, **chk).pack(anchor="w")
        wpm_row = tk.Frame(side, bg=BG)
        wpm_row.pack(anchor="w", pady=(4, 0))
        tk.Label(wpm_row, text="Typing speed (WPM)", bg=BG, fg=TEXT, font=f).pack(side="left")
        self.wpm = tk.Spinbox(wpm_row, from_=20, to=250, width=5, **ent)
        self.wpm.delete(0, "end"); self.wpm.insert(0, str(cfg.typing_wpm))
        self.wpm.pack(side="left", padx=6)

        tk.Label(side, text="Updates", bg=BG, fg=PINK, font=fb).pack(anchor="w", pady=(16, 0))
        from . import __version__
        tk.Label(side, text=f"You have Teto {__version__}", bg=BG, fg=DIM, font=f).pack(anchor="w")
        tk.Label(side, text="GitHub repository (owner/name):", bg=BG, fg=TEXT, font=f).pack(anchor="w", pady=(6, 0))
        self.repo = tk.Entry(side, width=30, **ent)
        self.repo.insert(0, cfg.update_repo)
        self.repo.pack(anchor="w", fill="x")
        self.v_auto = tk.BooleanVar(value=cfg.auto_update)
        tk.Checkbutton(side, text="Update by herself when idle", variable=self.v_auto, **chk).pack(anchor="w")
        ub = tk.Frame(side, bg=BG)
        ub._font_b = fb
        ub.pack(anchor="w", pady=(6, 0))
        pixel_button(ub, "CHECK NOW", self._check_now, color=PANEL).pack(side="left")
        pixel_button(ub, "FROM ZIP...", self._from_zip, color=PANEL).pack(side="left", padx=(6, 0))
        tk.Label(side, text="Only changed files are downloaded.\nPython & Claude Code are never re-downloaded.",
                 bg=BG, fg=GREY, font=(fam, 8), justify="left").pack(anchor="w", pady=(6, 0))

        # routines
        tk.Label(w, text="Routines (Teto runs these on her own every day)", bg=BG, fg=PINK, font=fb).grid(
            row=11, column=0, columnspan=2, sticky="w", pady=(12, 2))
        self.routines = [dict(r) for r in cfg.routines if isinstance(r, dict)]
        self.rlist = tk.Listbox(w, height=5, bg="#1a0e15", fg=TEXT, font=f, bd=0, highlightthickness=2,
                                highlightbackground=RED_D, selectbackground=RED)
        self.rlist.grid(row=12, column=0, columnspan=2, sticky="we")
        add = tk.Frame(w, bg=BG)
        add._font_b = fb
        add.grid(row=13, column=0, columnspan=2, sticky="we", pady=4)
        self.r_time = tk.Entry(add, width=6, **ent)
        self.r_time.insert(0, "09:00")
        self.r_time.pack(side="left")
        self.r_task = tk.Entry(add, width=30, **ent)
        self.r_task.insert(0, "")
        self.r_task.pack(side="left", padx=6, fill="x", expand=True)
        pixel_button(add, "+", self._add_routine, color=PANEL).pack(side="left")
        pixel_button(add, "−", self._del_routine, color=PANEL).pack(side="left", padx=(4, 0))
        self._refresh_routines()

        btns = tk.Frame(w, bg=BG)
        btns._font_b = fb
        btns.grid(row=14, column=0, columnspan=2, sticky="e", pady=(12, 0))
        pixel_button(btns, "SIGN OUT", self._sign_out, color=PANEL).pack(side="left")
        self.err = tk.Label(btns, text="", bg=BG, fg=ERR, font=f)
        self.err.pack(side="left", padx=8)
        pixel_button(btns, "CANCEL", w.destroy, color=PANEL).pack(side="left")
        pixel_button(btns, "SAVE", self._save).pack(side="left", padx=(6, 0))
        w.update_idletasks()
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        w.geometry(f"+{(sw - w.winfo_reqwidth()) // 2}+{max(0, (sh - w.winfo_reqheight()) // 2)}")
        w.after(300, lambda: platform_win.exclude_from_capture(w))

    def _check_now(self):
        self.app.config.update_repo = self.repo.get().strip()
        self.app.config.save()
        self.app.check_updates(manual=True)
        self.err.config(text="Checking... see the chat window", fg=DIM)

    def _from_zip(self):
        from tkinter import filedialog

        path = filedialog.askopenfilename(parent=self.win, title="Choose the new Teto zip",
                                          filetypes=[("Zip files", "*.zip")])
        if path:
            self.app.check_updates(manual=True, zip_path=path)
            self.err.config(text="Reading the zip... see the chat window", fg=DIM)

    def _sign_out(self):
        self.app.sign_out()
        self.err.config(text="Signed out of Claude", fg=DIM)

    def _refresh_routines(self):
        self.rlist.delete(0, "end")
        for r in self.routines:
            self.rlist.insert("end", f"{r.get('time', '??:??')}  {r.get('task', '')}")

    def _add_routine(self):
        t, task = self.r_time.get().strip(), self.r_task.get().strip()
        if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", t):
            self.err.config(text="Time must be HH:MM (24h)")
            return
        if not task:
            self.err.config(text="Type what Teto should do")
            return
        h, m = t.split(":")
        self.routines.append({"time": f"{int(h):02d}:{m}", "task": task, "enabled": True, "last_run": ""})
        self.r_task.delete(0, "end")
        self.err.config(text="")
        self._refresh_routines()

    def _del_routine(self):
        sel = self.rlist.curselection()
        if sel:
            del self.routines[sel[0]]
            self._refresh_routines()

    def _save(self):
        cfg = self.app.config
        try:
            steps = int(self.steps.get())
            shot = int(self.shot.get())
            monitor = int(self.monitor.get())
            scale = int(self.scale.get())
        except ValueError:
            self.err.config(text="Numbers only, please")
            return
        model = self.model.get().strip()
        if not model:
            self.err.config(text="Choose a model")
            return
        brain = next((k for k, v in BRAINS.items() if v == self.brain.get()), "subscription")
        if brain == "api" and not (self.key.get().strip() or os.environ.get("ANTHROPIC_API_KEY")):
            self.err.config(text="Paste an API key, or use the Claude subscription brain")
            return
        old_scale = cfg.pet_scale
        cfg.brain = brain
        cfg.api_key = self.key.get().strip()
        cfg.model = model
        cfg.effort = self.effort.get()
        cfg.speed = next((k for k, v in SPEEDS.items() if v == self.speed.get()), "fast")
        cfg.max_steps = steps
        cfg.screenshot_max_long_edge = shot
        cfg.monitor = monitor
        cfg.pet_scale = scale
        cfg.confirm_shell = bool(self.v_shell.get())
        cfg.confirm_risky_keys = bool(self.v_keys.get())
        cfg.wander = bool(self.v_wander.get())
        cfg.work_style = next((k for k, v in WORK_STYLES.items() if v == self.style.get()), "background")
        cfg.show_browser = bool(self.v_showb.get())
        cfg.autonomous = bool(self.v_auton.get())
        cfg.prefer_real_browser = bool(self.v_real.get())
        cfg.auto_screenshots = bool(self.v_see.get())
        cfg.stand_on_windows = bool(self.v_windows.get())
        cfg.reminders = bool(self.v_remind.get())
        cfg.human_typing = bool(self.v_human.get())
        cfg.typos = bool(self.v_typos.get())
        try:
            cfg.typing_wpm = int(self.wpm.get())
        except ValueError:
            pass
        cfg.update_repo = self.repo.get().strip()
        cfg.auto_update = bool(self.v_auto.get())
        cfg.routines = self.routines
        cfg.save()
        self.app.apply_settings(rebuild_pet=(old_scale != cfg.pet_scale))
        self.win.destroy()
