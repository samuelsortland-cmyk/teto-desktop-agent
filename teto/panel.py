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
OK_D = "#2e9e5b"

MODELS = ["default", "opus", "sonnet", "haiku", "claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"]
WORK_STYLES = {"background": "Background - I keep my mouse & keyboard",
               "foreground": "Foreground - Teto may use them"}
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


# Chat window palette (light, Teto-red accents)
C_BG = "#ffffff"
C_SOFT = "#fbf6f8"
C_BOT = "#f4eef1"
C_SHADOW = "#ece2e7"
C_LINE = "#efe4e9"
C_INK = "#2a1822"
C_MUTED = "#9b8a93"
C_ACT = "#6f7fa8"
C_ERR_BG = "#ffe6ea"
C_ERR = "#b3263f"
C_FIELD = "#f3eef1"


def _ui_family(root) -> str:
    from tkinter import font as tkfont
    have = set(tkfont.families(root))
    for fam in ("Segoe UI", "Inter", "Helvetica Neue", "DejaVu Sans", "Arial"):
        if fam in have:
            return fam
    return "TkDefaultFont"


def _round_rect(c, x0, y0, x1, y1, r, **kw):
    r = max(1, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
           x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, splinesteps=24, **kw)


class Panel:
    """The chat window: header, conversation, quick replies and the message field."""

    MAX_MESSAGES = 400

    def __init__(self, root: tk.Tk, app, font):
        self.root = root
        self.app = app
        fam = font[0]
        self.k = max(1.0, root.winfo_fpixels("1i") / 96.0)   # high-DPI displays
        ui = _ui_family(root)
        self.font = (ui, 10)
        self.font_b = (ui, 10, "bold")
        self.font_s = (ui, 8)
        self.font_msg = (ui, 10)
        self.font_name = (fam, 13, "bold")

        w = self.win = tk.Toplevel(root)
        w.title("Teto - Desktop Agent")
        w.configure(bg=C_BG)
        self.pw, self.ph = int(400 * self.k), int(620 * self.k)
        w.geometry(f"{self.pw}x{self.ph}")
        w.minsize(int(330 * self.k), int(420 * self.k))
        w.protocol("WM_DELETE_WINDOW", self.hide)
        w.attributes("-topmost", True)
        w._font_b = self.font_b
        w.bind("<Escape>", lambda e: self.app.stop_all())
        self.shell_var = tk.BooleanVar(value=self.app.config.confirm_shell)

        self._scallop(w)
        self._build_header(w)

        # banners (sign in / update / Teto Link) slot in under the header
        self.signin = self._banner(w, "#ffe3e9")
        self.signin_lbl = tk.Label(self.signin, text="", bg="#ffe3e9", fg=C_INK, font=self.font_b,
                                   justify="left", anchor="w", wraplength=int(230 * self.k))
        self.signin_lbl.pack(side="left", fill="x", expand=True)
        self.signin_btn = self._pill_button(self.signin, "SIGN IN WITH CLAUDE", self.app.sign_in)
        self.signin_btn.pack(side="right")

        self.update_bar = self._banner(w, "#fff3d1")
        self.update_lbl = tk.Label(self.update_bar, text="", bg="#fff3d1", fg=C_INK, font=self.font_b, anchor="w")
        self.update_lbl.pack(side="left", fill="x", expand=True)
        self._pill_button(self.update_bar, "UPDATE", self.app.install_update).pack(side="right")

        self.link_bar = self._banner(w, "#dcf6ec")
        tk.Label(self.link_bar, text="Let me work in tabs you're NOT on\n(one-time, 30-sec setup)", bg="#dcf6ec",
                 fg=C_INK, font=self.font_b, anchor="w", justify="left").pack(side="left", fill="x", expand=True)
        self._pill_button(self.link_bar, "CONNECT EDGE", self.app.connect_edge_ui).pack(side="right")

        self._build_input(w)
        self._build_chat(w)

        self._messages: list[tuple[str, str]] = []
        self._replies: list[tuple[str, object, bool]] = []
        self._pending = None          # (kind, callback)
        self._y = 0
        self._width = 0

        self._place_default()
        self.visible = True
        self.win.after(300, lambda: platform_win.exclude_from_capture(self.win))
        self.log("teto", "Hiii~ I'm Teto! Tell me what to do on your PC and I'll handle it. ♪")
        self.log("system", 'Try: "open Notepad and write a haiku about bread"')
        self.entry.focus_set()

    # ------------------------------------------------------------ building
    def _scallop(self, parent):
        """Teto-red top edge with a little scalloped trim."""
        h = int(9 * self.k)
        c = tk.Canvas(parent, height=h, bg=C_BG, highlightthickness=0, bd=0)
        c.pack(fill="x")

        def redraw(_e=None):
            c.delete("all")
            width = c.winfo_width() or self.pw
            c.create_rectangle(0, 0, width, h // 2, fill=RED, outline="")
            step = int(12 * self.k)
            for x in range(0, width + step, step):
                c.create_oval(x - step // 2, -h // 2, x + step // 2, h, fill=RED, outline="")
        c.bind("<Configure>", redraw)

    def _build_header(self, w):
        head = tk.Frame(w, bg=C_BG, padx=12, pady=8)
        head.pack(fill="x")
        self._face = _teto_face_icon(self.root, max(28, int(34 * self.k)))
        if self._face is not None:
            tk.Label(head, image=self._face, bg=C_BG, bd=0).pack(side="left", padx=(0, 8))
        names = tk.Frame(head, bg=C_BG)
        names.pack(side="left")
        tk.Label(names, text="Teto", bg=C_BG, fg=C_INK, font=self.font_name).pack(anchor="w")
        self.status_lbl = tk.Label(names, text="● Online", bg=C_BG, fg=OK_D, font=self.font_s)
        self.status_lbl.pack(anchor="w")

        def icon(text, cmd, tip_color=C_MUTED, size=13):
            lbl = tk.Label(head, text=text, bg=C_BG, fg=tip_color, font=(self.font[0], size), cursor="hand2",
                           padx=5)
            lbl.bind("<Button-1>", lambda e: cmd())
            lbl.bind("<Enter>", lambda e: lbl.config(fg=RED))
            lbl.bind("<Leave>", lambda e: lbl.config(fg=tip_color))
            return lbl

        icon("✕", self.hide).pack(side="right")
        icon("↻", self.app.new_chat).pack(side="right")
        icon("⚙", self.app.open_settings, size=12).pack(side="right")
        self.stop_btn = icon("■", self.app.stop_all, tip_color=RED, size=12)
        self.queue_lbl = tk.Label(head, text="", bg=C_BG, fg=C_MUTED, font=self.font_s)
        self.queue_lbl.pack(side="right", padx=4)
        self._signin_anchor = tk.Frame(w, bg=C_LINE, height=1)
        self._signin_anchor.pack(fill="x")

    def _banner(self, parent, color):
        f = tk.Frame(parent, bg=color, padx=12, pady=8)
        f._font_b = self.font_b
        return f

    def _pill_button(self, parent, text, command, filled=True):
        b = tk.Button(parent, text=text, command=command, relief="flat", bd=0, cursor="hand2",
                      bg=RED if filled else C_BG, fg="white" if filled else RED, font=self.font_b,
                      activebackground=RED_D, activeforeground="white", padx=12, pady=4,
                      highlightthickness=0)
        return b

    def _build_chat(self, w):
        body = self.body = tk.Frame(w, bg=C_BG)
        body.pack(fill="both", expand=True)
        self.chat = tk.Canvas(body, bg=C_BG, highlightthickness=0, bd=0)
        self.thumb = tk.Canvas(body, width=int(8 * self.k), bg=C_BG, highlightthickness=0, bd=0)
        self.thumb.pack(side="right", fill="y", padx=(0, 3), pady=6)
        self.chat.pack(side="left", fill="both", expand=True)
        self.chat.configure(yscrollcommand=self._on_scroll)
        self.chat.bind("<Configure>", self._on_resize)
        for widget in (self.chat, self.thumb):
            widget.bind("<MouseWheel>", lambda e: self.chat.yview_scroll(int(-e.delta / 120) or
                                                                         (-1 if e.delta > 0 else 1), "units"))
            widget.bind("<Button-4>", lambda e: self.chat.yview_scroll(-2, "units"))
            widget.bind("<Button-5>", lambda e: self.chat.yview_scroll(2, "units"))
        self.thumb.bind("<B1-Motion>", self._drag_thumb)
        self.thumb.bind("<Button-1>", self._drag_thumb)
        self._scroll = (0.0, 1.0)

    def _build_input(self, w):
        bottom = tk.Frame(w, bg=C_BG, padx=12, pady=8)
        bottom.pack(fill="x", side="bottom")
        self.field = tk.Canvas(bottom, height=int(46 * self.k), bg=C_BG, highlightthickness=0, bd=0)
        self.field.pack(fill="x")
        self.entry = tk.Text(self.field, height=2, bg=C_FIELD, fg=C_INK, insertbackground=RED, font=self.font_msg,
                             bd=0, highlightthickness=0, wrap="word", padx=2, pady=2)
        self._entry_win = self.field.create_window(0, 0, window=self.entry, anchor="nw")
        self.entry.bind("<Return>", self._on_enter)
        self.entry.bind("<FocusIn>", lambda e: self._placeholder(False))
        self.entry.bind("<FocusOut>", lambda e: self._placeholder(True))
        self.field.bind("<Configure>", self._draw_field)
        self.field.tag_bind("send", "<Button-1>", lambda e: self._submit())
        self.field.tag_bind("send", "<Enter>", lambda e: self.field.itemconfig("sendfill", fill=RED_D))
        self.field.tag_bind("send", "<Leave>", lambda e: self.field.itemconfig("sendfill", fill=RED))
        tk.Label(bottom, text="Enter to send · Shift+Enter new line · Esc stops", bg=C_BG, fg=C_MUTED,
                 font=self.font_s).pack(anchor="w", pady=(4, 0))
        self._ph = False

    def _draw_field(self, _e=None):
        c = self.field
        c.delete("bg", "send")
        wid, h = c.winfo_width(), c.winfo_height()
        _round_rect(c, 1, 1, wid - 1, h - 1, h // 2, fill=C_FIELD, outline=C_LINE, tags="bg")
        c.tag_lower("bg")
        r = h // 2 - int(6 * self.k)
        cx, cy = wid - h // 2, h // 2
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=RED, outline="", tags=("send", "sendfill"))
        s = r * 0.55                                   # a little paper plane
        c.create_polygon(cx - s, cy - s * 0.8, cx + s, cy, cx - s, cy + s * 0.8, cx - s * 0.45, cy,
                         fill="white", outline="", tags="send")
        c.coords(self._entry_win, h // 2 - 4, int(6 * self.k))
        c.itemconfigure(self._entry_win, width=max(40, wid - h - h // 2), height=h - int(12 * self.k))

    def _placeholder(self, show: bool):
        if show and not self.entry.get("1.0", "end").strip():
            self.entry.insert("1.0", "Message Teto...")
            self.entry.config(fg=C_MUTED)
            self._ph = True
        elif not show and self._ph:
            self.entry.delete("1.0", "end")
            self.entry.config(fg=C_INK)
            self._ph = False

    # ------------------------------------------------------------ scrolling
    def _on_scroll(self, first, last):
        self._scroll = (float(first), float(last))
        t = self.thumb
        t.delete("all")
        if self._scroll[1] - self._scroll[0] >= 0.999:
            return
        h = t.winfo_height()
        wid = t.winfo_width()
        y0, y1 = h * self._scroll[0], max(h * self._scroll[0] + 24, h * self._scroll[1])
        _round_rect(t, 1, y0, wid - 1, y1, wid // 2, fill="#d9cbd2", outline="")

    def _drag_thumb(self, e):
        h = max(1, self.thumb.winfo_height())
        span = self._scroll[1] - self._scroll[0]
        self.chat.yview_moveto(max(0.0, min(1.0, e.y / h - span / 2)))

    def _near_bottom(self) -> bool:
        return self._scroll[1] >= 0.98

    def _scroll_end(self):
        self.chat.update_idletasks()
        self.chat.configure(scrollregion=(0, 0, self._width, self._y + 12))
        self.chat.yview_moveto(1.0)

    # ------------------------------------------------------------ drawing
    def _on_resize(self, e):
        if abs(e.width - self._width) > 2:
            self._width = e.width
            self._redraw()

    def _redraw(self):
        c = self.chat
        c.delete("all")
        self._y = 8
        self._draw_header_divider()
        for kind, text in self._messages:
            self._draw(kind, text)
        self._draw_replies()
        self._scroll_end()

    def _draw_header_divider(self):
        import datetime as _dt
        c, wid = self.chat, self._width or self.pw
        label = _dt.datetime.now().strftime("%B %d, %Y").replace(" 0", " ")
        t = c.create_text(wid // 2, self._y + 10, text=label, fill=C_MUTED, font=self.font_s)
        x0, _, x1, _ = c.bbox(t)
        c.create_line(16, self._y + 10, x0 - 10, self._y + 10, fill=C_LINE)
        c.create_line(x1 + 10, self._y + 10, wid - 16, self._y + 10, fill=C_LINE)
        c.create_text(16, self._y + 28, text="Teto is online", anchor="w", fill=C_MUTED, font=self.font_s)
        self._y += 44

    def _draw(self, kind: str, text: str):
        c = self.chat
        wid = self._width or self.pw
        maxw = int(wid * 0.74)
        pad_x, pad_y, gap = int(13 * self.k), int(9 * self.k), int(8 * self.k)
        if kind in ("action", "thought", "system"):
            color = {"action": C_ACT, "thought": C_MUTED, "system": C_MUTED}[kind]
            font = (self.font[0], 8, "italic") if kind == "thought" else self.font_s
            prefix = {"action": "›  ", "thought": "", "system": ""}[kind]
            if kind == "system":
                item = c.create_text(wid // 2, self._y, text=text, fill=color, font=font, width=wid - 60,
                                     anchor="n", justify="center")
            else:
                item = c.create_text(22, self._y, text=prefix + text, fill=color, font=font, width=wid - 50,
                                     anchor="nw")
            self._y = c.bbox(item)[3] + 6
            return
        right = kind == "user"
        fill, ink = {"user": (RED, "white"), "error": (C_ERR_BG, C_ERR), "ask": (C_BOT, C_INK)}.get(kind, (C_BOT, C_INK))
        font = self.font_b if kind == "ask" else self.font_msg
        item = c.create_text(0, self._y + pad_y, text=text, fill=ink, font=font, width=maxw - 2 * pad_x,
                             anchor="nw")
        x0, y0, x1, y1 = c.bbox(item)
        tw = x1 - x0
        left = wid - 18 - tw - 2 * pad_x if right else 16
        c.move(item, left + pad_x - x0, 0)
        bx0, bx1, by1 = left, left + tw + 2 * pad_x, y1 + pad_y
        if not right:
            _round_rect(c, bx0, self._y + 2, bx1, by1 + 2, 16, fill=C_SHADOW, outline="")
        _round_rect(c, bx0, self._y, bx1, by1, 16, fill=fill, outline="")
        c.tag_raise(item)
        self._y = by1 + gap

    def _draw_replies(self):
        if not self._replies:
            return
        c = self.chat
        wid = self._width or self.pw
        h = int(32 * self.k)
        pills = []
        for i, (label, cb, filled) in enumerate(self._replies):
            t = c.create_text(0, 0, text=label, font=self.font_b, anchor="nw")
            x0, y0, x1, y1 = c.bbox(t)
            c.delete(t)
            pills.append((label, cb, filled, (x1 - x0) + int(30 * self.k)))
        rows, row, used = [], [], 0                      # wrap pills into right-aligned rows
        for p in pills:
            if row and used + p[3] + 8 > wid - 40:
                rows.append(row)
                row, used = [], 0
            row.append(p)
            used += p[3] + 8
        if row:
            rows.append(row)
        for row in rows:
            x = wid - 18 - sum(p[3] + 8 for p in row) + 8
            for n, (label, cb, filled, pw) in enumerate(row):
                tag = f"reply{id(cb)}_{n}_{label}"
                bg = _round_rect(c, x, self._y, x + pw, self._y + h, h // 2, fill=RED if filled else C_BG,
                                 outline=RED, width=2, tags=(tag, "replies"))
                c.create_text(x + pw / 2, self._y + h / 2, text=label, fill="white" if filled else RED,
                              font=self.font_b, tags=(tag, "replies"))
                c.tag_bind(tag, "<Button-1>", lambda e, cb=cb: cb())
                c.tag_bind(tag, "<Enter>", lambda e, bg=bg, f=filled: (c.itemconfig(bg, fill=RED_D if f else "#ffe9ee"),
                                                                    c.configure(cursor="hand2")))
                c.tag_bind(tag, "<Leave>", lambda e, bg=bg, f=filled: (c.itemconfig(bg, fill=RED if f else C_BG),
                                                                    c.configure(cursor="")))
                x += pw + 8
            self._y += h + 8

    # ---------------------------------------------------------------- window
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

    # ------------------------------------------------------------------ log
    def log(self, kind: str, text: str):
        text = (text or "").strip()
        if not text:
            return
        if kind == "teto" and text.startswith("Teto ♪ "):
            text = text[len("Teto ♪ "):]
        self._messages.append((kind, text))
        if len(self._messages) > self.MAX_MESSAGES:
            self._messages = self._messages[-int(self.MAX_MESSAGES * 0.75):]
            self._redraw()
            return
        follow = self._near_bottom()
        if self._replies:                # keep quick replies under the newest message
            self._redraw()
            return
        self._draw(kind, text)
        self.chat.configure(scrollregion=(0, 0, self._width, self._y + 12))
        if follow or kind == "user":
            self.chat.yview_moveto(1.0)

    def set_status(self, state: str):
        busy = state in ("thinking", "working", "talking", "waiting")
        label = {"idle": "Online", "thinking": "Thinking...", "working": "Working...", "talking": "Working...",
                 "waiting": "Needs you!", "success": "Done ♪", "error": "Hit a snag"}.get(state, state)
        color = {"idle": OK_D, "success": OK_D, "error": C_ERR, "waiting": "#c98a00"}.get(state, RED)
        self.status_lbl.config(text=f"● {label}", fg=color)
        if busy and not self.stop_btn.winfo_ismapped():
            self.stop_btn.pack(side="right", before=self.queue_lbl)
        elif not busy and self.stop_btn.winfo_ismapped():
            self.stop_btn.pack_forget()

    def set_update(self, text: str | None):
        """Show 'update ready' with an UPDATE button, or hide it (None)."""
        if text is None:
            self.update_bar.pack_forget()
            return
        self.update_lbl.config(text=text)
        if not self.update_bar.winfo_ismapped():
            self.update_bar.pack(fill="x", after=self._signin_anchor)

    def set_link(self, show: bool):
        """Show the 'connect Teto Link' bar until the extension is connected."""
        if not show:
            self.link_bar.pack_forget()
        elif not self.link_bar.winfo_ismapped():
            self.link_bar.pack(fill="x", after=self._signin_anchor)

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

    # ---------------------------------------------------------------- input
    def _on_enter(self, e):
        if e.state & 0x0001:        # shift held -> newline
            return None
        self._submit()
        return "break"

    def _submit(self):
        if self._ph:
            return
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

    # --------------------------------------------------- questions / confirm
    def ask(self, question: str, choices: list[str], callback):
        """Show a question with quick-reply buttons; callback(answer) is called once."""
        self._clear_pending()
        self._pending = ("ask", callback)
        self.log("ask", question)
        self._replies = [(c, (lambda c=c: self._answer(c)), i == 0) for i, c in enumerate(choices)]
        self._redraw()
        self.show()

    def confirm(self, title: str, detail: str, callback):
        self._clear_pending()
        self._pending = ("confirm", callback)
        self.log("ask", f"{title}\n\n{detail[:600]}")
        self._replies = [("Allow", lambda: self._resolve(True), True), ("Deny", lambda: self._resolve(False), False)]
        self._redraw()
        self.show()

    def _answer(self, text: str):
        if self._pending and self._pending[0] == "ask":
            self._resolve(text)
            self.log("user", text)

    def _resolve(self, value):
        pending = self._pending
        self._clear_pending()
        if pending:
            if pending[0] == "confirm":
                self.log("user", "Allow" if value else "Deny")
            pending[1](value)

    def cancel_pending(self):
        """Stop pressed while a question is open: answer it with None/False."""
        pending = self._pending
        self._clear_pending()
        if pending:
            pending[1](None if pending[0] == "ask" else False)

    def _clear_pending(self):
        self._pending = None
        if self._replies:
            self._replies = []
            self._redraw()


class PillButton(tk.Canvas):
    """A rounded button drawn on a canvas (filled red, or outlined)."""

    def __init__(self, parent, text, command, font, filled=True, bg=None, k=1.0):
        self._bg = bg or parent.cget("bg")
        super().__init__(parent, bg=self._bg, highlightthickness=0, bd=0, cursor="hand2")
        self.text, self.command, self.font, self.filled, self.k = text, command, font, filled, k
        tmp = self.create_text(0, 0, text=text, font=font, anchor="nw")
        x0, y0, x1, y1 = self.bbox(tmp)
        self.delete(tmp)
        self.w, self.h = (x1 - x0) + int(28 * k), (y1 - y0) + int(14 * k)
        self.configure(width=self.w, height=self.h)
        self._draw(False)
        self.bind("<Enter>", lambda e: self._draw(True))
        self.bind("<Leave>", lambda e: self._draw(False))
        self.bind("<Button-1>", lambda e: self.command())

    def _draw(self, hover):
        self.delete("all")
        if self.filled:
            fill, ink, outline = (RED_D if hover else RED), "white", (RED_D if hover else RED)
        else:
            fill, ink, outline = ("#ffe9ee" if hover else self._bg), RED, RED
        _round_rect(self, 1, 1, self.w - 1, self.h - 1, self.h // 2, fill=fill, outline=outline, width=2)
        self.create_text(self.w / 2, self.h / 2, text=self.text, fill=ink, font=self.font)


class Toggle(tk.Frame):
    """A settings row: label (+ hint) on the left, an on/off switch on the right."""

    def __init__(self, parent, text, variable, font, font_s, hint="", k=1.0):
        bg = parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.var = variable
        words = tk.Frame(self, bg=bg)
        words.pack(side="left", fill="x", expand=True)
        tk.Label(words, text=text, bg=bg, fg=C_INK, font=font, anchor="w").pack(anchor="w")
        if hint:
            tk.Label(words, text=hint, bg=bg, fg=C_MUTED, font=font_s, anchor="w", justify="left").pack(anchor="w")
        self.sw = tk.Canvas(self, width=int(40 * k), height=int(22 * k), bg=bg, highlightthickness=0, bd=0,
                            cursor="hand2")
        self.sw.pack(side="right", padx=(10, 0))
        for wdg in (self, self.sw, words, *words.winfo_children()):
            wdg.bind("<Button-1>", self._flip)
        self.var.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _flip(self, _e=None):
        self.var.set(not self.var.get())

    def _draw(self):
        c, on = self.sw, bool(self.var.get())
        c.delete("all")
        w, h = int(c.cget("width")), int(c.cget("height"))
        _round_rect(c, 1, 1, w - 1, h - 1, h // 2, fill=RED if on else "#ddd2d7", outline="")
        r = h // 2 - 3
        cx = w - h // 2 if on else h // 2
        c.create_oval(cx - r, h // 2 - r, cx + r, h // 2 + r, fill="white", outline="")


class SettingsWindow:
    PAGES = [("brain", "Brain"), ("work", "Working"), ("personality", "Personality"),
             ("routines", "Routines"), ("updates", "Updates")]

    def __init__(self, root, app, font):
        self.app = app
        cfg = app.config
        self.k = k = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self.pw = int(660 * k)
        ui = _ui_family(root)
        f, fb, fs = (ui, 10), (ui, 10, "bold"), (ui, 8)
        self.f, self.fb, self.fs = f, fb, fs
        w = self.win = tk.Toplevel(root)
        w.title("Teto - Settings")
        w.configure(bg=C_BG)
        w.attributes("-topmost", True)
        w.resizable(False, False)
        w._font_b = fb
        self._style_ttk(root, f)

        # header: scallop, Teto's face, title, close
        Panel._scallop(self, w)
        head = tk.Frame(w, bg=C_BG, padx=16, pady=10)
        head.pack(fill="x")
        self._face = _teto_face_icon(root, max(28, int(34 * k)))
        if self._face is not None:
            tk.Label(head, image=self._face, bg=C_BG).pack(side="left", padx=(0, 10))
        titles = tk.Frame(head, bg=C_BG)
        titles.pack(side="left")
        tk.Label(titles, text="Settings", bg=C_BG, fg=C_INK, font=(font[0], 13, "bold")).pack(anchor="w")
        from . import __version__
        tk.Label(titles, text=f"Make Teto yours ♪  ·  v{__version__}", bg=C_BG, fg=C_MUTED, font=fs).pack(anchor="w")
        x = tk.Label(head, text="✕", bg=C_BG, fg=C_MUTED, font=(ui, 13), cursor="hand2")
        x.pack(side="right")
        x.bind("<Button-1>", lambda e: w.destroy())
        tk.Frame(w, bg=C_LINE, height=1).pack(fill="x")

        # footer
        foot = tk.Frame(w, bg=C_BG, padx=16, pady=12)
        foot.pack(fill="x", side="bottom")
        tk.Frame(w, bg=C_LINE, height=1).pack(fill="x", side="bottom")
        PillButton(foot, "Save", self._save, fb, True, k=k).pack(side="right")
        PillButton(foot, "Cancel", w.destroy, fb, False, k=k).pack(side="right", padx=(0, 8))
        self.err = tk.Label(foot, text="", bg=C_BG, fg=C_ERR, font=f, anchor="w")
        self.err.pack(side="left", fill="x", expand=True)

        # sidebar + pages
        main = tk.Frame(w, bg=C_BG)
        main.pack(fill="both", expand=True)
        self.nav = tk.Frame(main, bg=C_SOFT, padx=10, pady=12, width=int(150 * k))
        self.nav.pack(side="left", fill="y")
        self.nav.pack_propagate(False)
        self.pages_box = tk.Frame(main, bg=C_BG, padx=18, pady=14)
        self.pages_box.pack(side="left", fill="both", expand=True)
        self.pages: dict[str, tk.Frame] = {}
        self.nav_items: dict[str, tk.Canvas] = {}
        for key, label in self.PAGES:
            self.pages[key] = tk.Frame(self.pages_box, bg=C_BG)
            item = tk.Canvas(self.nav, height=int(34 * k), bg=C_SOFT, highlightthickness=0, bd=0, cursor="hand2")
            item.pack(fill="x", pady=2)
            item.bind("<Button-1>", lambda e, key=key: self.show_page(key))
            item.bind("<Configure>", lambda e, key=key: self._draw_nav(key))
            item.label = label
            self.nav_items[key] = item

        self._build_brain(self.pages["brain"], cfg)
        self._build_work(self.pages["work"], cfg)
        self._build_personality(self.pages["personality"], cfg)
        self._build_routines(self.pages["routines"], cfg)
        self._build_updates(self.pages["updates"], cfg)
        self.current = "brain"
        self.show_page("brain")

        w.geometry(f"{int(660 * k)}x{int(620 * k)}")
        w.update_idletasks()
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        w.geometry(f"+{(sw - int(660 * k)) // 2}+{max(0, (sh - int(620 * k)) // 2 - 20)}")
        w.after(300, lambda: platform_win.exclude_from_capture(w))

    # ------------------------------------------------------------ chrome
    def _style_ttk(self, root, f):
        st = ttk.Style(root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Teto.TCombobox", fieldbackground=C_FIELD, background=C_FIELD, foreground=C_INK,
                     arrowcolor=RED, bordercolor=C_FIELD, lightcolor=C_FIELD, darkcolor=C_FIELD, padding=6,
                     selectbackground=C_FIELD, selectforeground=C_INK)
        st.map("Teto.TCombobox", fieldbackground=[("readonly", C_FIELD)], bordercolor=[("focus", RED)],
               lightcolor=[("focus", RED)])
        root.option_add("*TCombobox*Listbox.background", C_BG)
        root.option_add("*TCombobox*Listbox.foreground", C_INK)
        root.option_add("*TCombobox*Listbox.selectBackground", RED)
        root.option_add("*TCombobox*Listbox.selectForeground", "white")
        root.option_add("*TCombobox*Listbox.font", f)

    def _draw_nav(self, key):
        c = self.nav_items[key]
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        on = key == getattr(self, "current", "brain")
        if on:
            _round_rect(c, 0, 1, w, h - 1, h // 2, fill=RED, outline="")
        c.create_text(14, h / 2, text=c.label, anchor="w", fill="white" if on else C_INK,
                      font=self.fb if on else self.f)

    def show_page(self, key):
        self.current = key
        for p in self.pages.values():
            p.pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        for k in self.nav_items:
            self._draw_nav(k)

    def _title(self, page, text, sub=""):
        tk.Label(page, text=text, bg=C_BG, fg=C_INK, font=(self.f[0], 13, "bold")).pack(anchor="w")
        if sub:
            tk.Label(page, text=sub, bg=C_BG, fg=C_MUTED, font=self.fs, justify="left").pack(anchor="w")
        tk.Frame(page, bg=C_BG, height=8).pack()

    def _card(self, page):
        card = tk.Frame(page, bg=C_SOFT, padx=14, pady=10, highlightthickness=1, highlightbackground=C_LINE)
        card.pack(fill="x", pady=(0, 10))
        card._font_b = self.fb
        return card

    def _field_row(self, card, label, widget_factory):
        row = tk.Frame(card, bg=C_SOFT)
        row.pack(fill="x", pady=4)
        tk.Label(row, text=label, bg=C_SOFT, fg=C_INK, font=self.f, anchor="w", width=16).pack(side="left")
        widget = widget_factory(row)
        widget.pack(side="left", fill="x", expand=True)
        return widget

    def _entry(self, parent, **kw):
        return tk.Entry(parent, bg=C_FIELD, fg=C_INK, insertbackground=RED, font=self.f, bd=0, relief="flat",
                        highlightthickness=1, highlightbackground=C_FIELD, highlightcolor=RED, **kw)

    def _spin(self, parent, lo, hi, value):
        s = tk.Spinbox(parent, from_=lo, to=hi, width=6, bg=C_FIELD, fg=C_INK, insertbackground=RED, font=self.f,
                       bd=0, relief="flat", highlightthickness=1, highlightbackground=C_FIELD, highlightcolor=RED,
                       buttonbackground=C_FIELD)
        s.delete(0, "end")
        s.insert(0, str(value))
        return s

    def _combo(self, parent, values, value, readonly=True, width=30):
        cb = ttk.Combobox(parent, values=values, state="readonly" if readonly else "normal", width=width,
                          style="Teto.TCombobox", font=self.f)
        cb.set(value)
        return cb

    def _toggle(self, card, text, var, hint=""):
        Toggle(card, text, var, self.f, self.fs, hint, self.k).pack(fill="x", pady=3)

    # ------------------------------------------------------------ pages
    def _build_brain(self, page, cfg):
        self._title(page, "Brain", "How Teto thinks and sees.")
        card = self._card(page)
        self.brain = self._field_row(card, "Brain", lambda p: self._combo(
            p, list(BRAINS.values()), BRAINS.get(cfg.brain, BRAINS["subscription"])))
        self.key = self._field_row(card, "API key (advanced)", lambda p: self._entry(p, show="•"))
        self.key.insert(0, cfg.api_key)
        self.model = self._field_row(card, "Model", lambda p: self._combo(p, MODELS, cfg.model, readonly=False))
        card = self._card(page)
        self.speed = self._field_row(card, "Speed", lambda p: self._combo(
            p, list(SPEEDS.values()), SPEEDS.get(cfg.speed, SPEEDS["fast"])))
        self.effort = self._field_row(card, "Effort (custom)", lambda p: self._combo(p, EFFORTS, cfg.effort))
        self.shot = self._field_row(card, "Screenshot size", lambda p: self._combo(
            p, ["1280", "1366", "1568", "1920", "2560"], str(cfg.screenshot_max_long_edge), readonly=False))
        self.monitor = self._field_row(card, "Monitor", lambda p: self._spin(p, 1, 8, cfg.monitor))
        row = tk.Frame(page, bg=C_BG)
        row.pack(fill="x", pady=(2, 0))
        tk.Label(row, text="Steps per task: unlimited - she keeps going until it's done ♪", bg=C_BG, fg=RED,
                 font=self.fs).pack(side="left")
        PillButton(row, "Sign out", self._sign_out, self.fs, False, k=self.k).pack(side="right")

    def _build_work(self, page, cfg):
        self._title(page, "Working", "How Teto shares your PC. She works IN the tabs you already have open\n"
                                      "while you do something else, and opens new tabs only if you ask.")
        card = self._card(page)
        self.style = self._field_row(card, "Sharing your PC", lambda p: self._combo(
            p, list(WORK_STYLES.values()), WORK_STYLES.get(cfg.work_style, WORK_STYLES["background"]), width=34))
        self.v_auton = tk.BooleanVar(value=cfg.autonomous)
        self.v_real = tk.BooleanVar(value=cfg.prefer_real_browser)
        self.v_see = tk.BooleanVar(value=cfg.auto_screenshots)
        self.v_showb = tk.BooleanVar(value=cfg.show_browser)
        self.v_shell = tk.BooleanVar(value=cfg.confirm_shell)
        self.v_keys = tk.BooleanVar(value=cfg.confirm_risky_keys)
        card = self._card(page)
        self._toggle(card, "Full permission", self.v_auton, "Just do it - no \"should I?\" questions")
        self._toggle(card, "See the page after every action", self.v_see)
        self._toggle(card, "New tabs (only if asked) use my signed-in Edge", self.v_real)
        self._toggle(card, "Show Teto's own browser window", self.v_showb)
        self._toggle(card, "Ask before shell commands", self.v_shell, "Ignored while Full permission is on")
        self._toggle(card, "Ask before permanent-delete shortcuts", self.v_keys)
        card = self._card(page)
        row = tk.Frame(card, bg=C_SOFT)
        row.pack(fill="x")
        ok = getattr(self.app, "link_connected", lambda: False)()
        words = tk.Frame(row, bg=C_SOFT)
        words.pack(side="left", fill="x", expand=True)
        tk.Label(words, text="Teto Link", bg=C_SOFT, fg=C_INK, font=self.fb).pack(anchor="w")
        self.link_lbl = tk.Label(words, text="● connected - works in background tabs" if ok else
                                 "● not connected - one-time, 30-sec setup", bg=C_SOFT,
                                 fg=OK_D if ok else C_MUTED, font=self.fs)
        self.link_lbl.pack(anchor="w")
        PillButton(row, "Connect my Edge", self._connect_edge, self.fs, not ok, bg=C_SOFT, k=self.k).pack(side="right")

    def _build_personality(self, page, cfg):
        self._title(page, "Personality", "How Teto lives on your desktop.")
        self.v_wander = tk.BooleanVar(value=cfg.wander)
        self.v_windows = tk.BooleanVar(value=cfg.stand_on_windows)
        self.v_remind = tk.BooleanVar(value=cfg.reminders)
        self.v_human = tk.BooleanVar(value=cfg.human_typing)
        self.v_typos = tk.BooleanVar(value=cfg.typos)
        card = self._card(page)
        self._toggle(card, "Wander around when idle", self.v_wander)
        self._toggle(card, "Jump onto / ride my windows", self.v_windows)
        self._toggle(card, "Helpful nudges & suggestions", self.v_remind, "Water, stretch and eye-rest reminders")
        self._toggle(card, "Human-like typing & mouse", self.v_human, "Off automatically with Full permission")
        self._toggle(card, "Occasional typos (auto-fixed)", self.v_typos)
        card = self._card(page)
        self.scale = self._field_row(card, "Pet size", lambda p: self._spin(p, 2, 10, cfg.pet_scale))
        self.wpm = self._field_row(card, "Typing speed (WPM)", lambda p: self._spin(p, 20, 250, cfg.typing_wpm))

    def _build_routines(self, page, cfg):
        self._title(page, "Routines", "Teto runs these on her own every day.")
        self.routines = [dict(r) for r in cfg.routines if isinstance(r, dict)]
        card = self._card(page)
        self.rlist = tk.Listbox(card, height=8, bg=C_BG, fg=C_INK, font=self.f, bd=0, highlightthickness=1,
                                highlightbackground=C_LINE, selectbackground=RED, selectforeground="white",
                                activestyle="none")
        self.rlist.pack(fill="x")
        add = tk.Frame(card, bg=C_SOFT)
        add.pack(fill="x", pady=(10, 0))
        self.r_time = self._entry(add, width=6)
        self.r_time.insert(0, "09:00")
        self.r_time.pack(side="left", ipady=4)
        self.r_task = self._entry(add)
        self.r_task.pack(side="left", padx=8, fill="x", expand=True, ipady=4)
        PillButton(add, "Remove", self._del_routine, self.fs, False, bg=C_SOFT, k=self.k).pack(side="right")
        PillButton(add, "Add", self._add_routine, self.fs, True, bg=C_SOFT, k=self.k).pack(side="right", padx=(0, 6))
        tk.Label(page, text="Time is 24-hour (HH:MM). Select a routine to remove it.", bg=C_BG, fg=C_MUTED,
                 font=self.fs).pack(anchor="w")
        self._refresh_routines()

    def _build_updates(self, page, cfg):
        from . import __version__
        self._title(page, "Updates", f"You have Teto {__version__}. Only changed files are downloaded -\n"
                                      "Python and Claude Code are never re-downloaded.")
        self.v_auto = tk.BooleanVar(value=cfg.auto_update)
        card = self._card(page)
        self._toggle(card, "Update by herself when idle", self.v_auto)
        self.repo = self._field_row(card, "GitHub repository", lambda p: self._entry(p))
        self.repo.insert(0, cfg.update_repo)
        row = tk.Frame(page, bg=C_BG)
        row.pack(fill="x")
        PillButton(row, "Check now", self._check_now, self.fs, True, k=self.k).pack(side="left")
        PillButton(row, "From zip...", self._from_zip, self.fs, False, k=self.k).pack(side="left", padx=8)

    # ------------------------------------------------------------ actions
    def _check_now(self):
        self.app.config.update_repo = self.repo.get().strip()
        self.app.config.save()
        self.app.check_updates(manual=True)
        self.err.config(text="Checking... see the chat window", fg=C_MUTED)

    def _from_zip(self):
        from tkinter import filedialog

        path = filedialog.askopenfilename(parent=self.win, title="Choose the new Teto zip",
                                          filetypes=[("Zip files", "*.zip")])
        if path:
            self.app.check_updates(manual=True, zip_path=path)
            self.err.config(text="Reading the zip... see the chat window", fg=C_MUTED)

    def _sign_out(self):
        self.app.sign_out()
        self.err.config(text="Signed out of Claude", fg=C_MUTED)

    def _refresh_routines(self):
        self.rlist.delete(0, "end")
        for r in self.routines:
            self.rlist.insert("end", f"  {r.get('time', '??:??')}   {r.get('task', '')}")

    def _add_routine(self):
        t, task = self.r_time.get().strip(), self.r_task.get().strip()
        if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", t):
            self.err.config(text="Time must be HH:MM (24h)", fg=C_ERR)
            return
        if not task:
            self.err.config(text="Type what Teto should do", fg=C_ERR)
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

    def _connect_edge(self):
        from tkinter import messagebox
        text = self.app.connect_edge()
        messagebox.showinfo("Connect my Edge", text, parent=self.win)

    def _save(self):
        cfg = self.app.config
        try:
            shot = int(self.shot.get())
            monitor = int(self.monitor.get())
            scale = int(self.scale.get())
        except ValueError:
            self.err.config(text="Numbers only, please", fg=C_ERR)
            return
        model = self.model.get().strip()
        if not model:
            self.show_page("brain")
            self.err.config(text="Choose a model", fg=C_ERR)
            return
        brain = next((k for k, v in BRAINS.items() if v == self.brain.get()), "subscription")
        if brain == "api" and not (self.key.get().strip() or os.environ.get("ANTHROPIC_API_KEY")):
            self.show_page("brain")
            self.err.config(text="Paste an API key, or use the Claude subscription brain", fg=C_ERR)
            return
        old_scale = cfg.pet_scale
        cfg.brain = brain
        cfg.api_key = self.key.get().strip()
        cfg.model = model
        cfg.effort = self.effort.get()
        cfg.speed = next((k for k, v in SPEEDS.items() if v == self.speed.get()), "fast")
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


class TetoMenu:
    """Teto's right-click menu, drawn to match the chat and settings windows:
    a rounded white card with her face, hover pills, a switch and Eagle Eyes."""

    KEY = "#ff00fe"           # transparent corners on Windows

    def __init__(self, root, items, status=lambda: "Online", font_family="TkDefaultFont", name_font=None):
        """items: list of dicts {label, command, icon?, kind: item|toggle|eagle|danger|sep, var?}."""
        self.root = root
        self.items = items
        self.status = status
        self.k = max(1.0, root.winfo_fpixels("1i") / 96.0)
        ui = _ui_family(root)
        self.f, self.fb, self.fs = (ui, 10), (ui, 10, "bold"), (ui, 8)
        self.fname = name_font or (ui, 12, "bold")
        self.win = None

    def show(self, x, y):
        self.close()
        k = self.k
        w = self.win = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        rounded = platform_win.IS_WINDOWS
        bg = self.KEY if rounded else C_LINE
        w.configure(bg=bg)
        if rounded:
            try:
                w.attributes("-transparentcolor", self.KEY)
            except tk.TclError:
                bg = C_LINE
        width = int(236 * k)
        row_h, sep_h, head_h, pad = int(32 * k), int(11 * k), int(58 * k), int(8 * k)
        height = head_h + pad * 2
        for it in self.items:
            height += sep_h if it["kind"] == "sep" else (int(46 * k) if it["kind"] == "eagle" else row_h)
        c = self.c = tk.Canvas(w, width=width, height=height, bg=bg, highlightthickness=0, bd=0)
        c.pack()
        # card + soft shadow
        _round_rect(c, 3, 4, width - 1, height - 1, 16, fill=C_SHADOW, outline="")
        _round_rect(c, 1, 1, width - 3, height - 4, 16, fill=C_BG, outline=C_LINE)
        # header: red scallop band, face, name, status
        _round_rect(c, 1, 1, width - 3, int(14 * k), 12, fill=RED, outline="")
        c.create_rectangle(2, int(7 * k), width - 4, int(10 * k), fill=RED, outline="")
        step = int(12 * k)
        for sx in range(step // 2, width - step // 2, step):
            c.create_oval(sx - step // 2, int(4 * k), sx + step // 2, int(14 * k), fill=RED, outline="")
        face = _teto_face_icon(self.root, max(24, int(28 * k)))
        tx = int(16 * k)
        if face is not None:
            c.create_image(tx, int(36 * k), image=face, anchor="w")
            tx += face.width() + int(8 * k)
        c.create_text(tx, int(29 * k), text="Teto", anchor="w", fill=C_INK, font=self.fname)
        st = self.status()
        busy = st not in ("Online", "Done ♪")
        c.create_text(tx, int(45 * k), text=f"● {st}", anchor="w", fill=RED if busy else OK_D, font=self.fs)
        c.create_line(int(12 * k), head_h, width - int(14 * k), head_h, fill=C_LINE)

        y0 = head_h + pad
        for n, it in enumerate(self.items):
            if it["kind"] == "sep":
                c.create_line(int(16 * k), y0 + sep_h // 2, width - int(18 * k), y0 + sep_h // 2, fill=C_LINE)
                y0 += sep_h
                continue
            h = int(46 * k) if it["kind"] == "eagle" else row_h
            self._item(c, n, it, int(8 * k), y0 + 1, width - int(11 * k), y0 + h - 1)
            y0 += h

        # place by the cursor, kept on screen
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = min(max(0, x), sw - width - 4)
        y = y - height if y + height > sh - 40 else y
        w.geometry(f"{width}x{height}+{int(x)}+{max(0, int(y))}")
        w.lift()
        w.bind("<Escape>", lambda e: self.close())
        self._fg0 = None
        w.after(10, self._grab)
        w.after(150, self._watch_focus)
        w.after(200, lambda: platform_win.exclude_from_capture(w))

    def _grab(self):
        if not self.win:
            return
        try:
            self.win.focus_force()
            self.win.grab_set()
        except tk.TclError:
            pass
        self.win.bind("<Button-1>", self._click_outside, add="+")
        self.win.bind("<Button-3>", self._click_outside, add="+")

    def _click_outside(self, e):
        w = self.win
        if not w:
            return
        x0, y0 = w.winfo_rootx(), w.winfo_rooty()
        if not (x0 <= e.x_root <= x0 + w.winfo_width() and y0 <= e.y_root <= y0 + w.winfo_height()):
            self.close()

    def _watch_focus(self):
        """Close when the user switches to another app (clicks elsewhere on the desktop)."""
        if not self.win:
            return
        fg = platform_win.foreground_window()
        try:
            mine = int(self.win.wm_frame(), 16)
        except (tk.TclError, ValueError):
            mine = 0
        if fg and self._fg0 is None:
            self._fg0 = fg
        elif fg and fg not in (self._fg0, mine):
            self.close()
            return
        self.win.after(150, self._watch_focus)

    def close(self):
        if self.win is not None:
            try:
                self.win.grab_release()
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None

    def _run(self, it):
        self.close()
        if it["kind"] == "toggle":
            it["var"].set(not it["var"].get())
        self.root.after(1, it["command"])

    def _item(self, c, n, it, x0, y0, x1, y1):
        tag = f"item{n}"
        k = self.k
        eagle, danger, toggle = it["kind"] == "eagle", it["kind"] == "danger", it["kind"] == "toggle"
        base_fill = "#fff0f3" if eagle else C_BG
        bg = _round_rect(c, x0, y0, x1, y1, (y1 - y0) // 2 if not eagle else 12, fill=base_fill,
                         outline=("#ffc9d4" if eagle else base_fill), tags=tag)
        ink = RED if (eagle or danger) else C_INK
        icon = it.get("icon", "")
        ix = x0 + int(16 * k)
        cy = (y0 + y1) / 2
        icon_item = c.create_text(ix, cy if not eagle else cy, text=icon, fill=RED if (eagle or danger) else C_MUTED,
                                  font=(self.f[0], 11), tags=tag)
        tx = x0 + int(34 * k)
        if eagle:
            label = c.create_text(tx, cy - 8 * k, text=it["label"], anchor="w", fill=RED, font=self.fb, tags=tag)
            sub = c.create_text(tx, cy + 9 * k, text=it.get("sub", ""), anchor="w", fill=C_MUTED, font=self.fs,
                                tags=tag)
        else:
            label = c.create_text(tx, cy, text=it["label"], anchor="w", fill=ink,
                                  font=self.fb if danger else self.f, tags=tag)
            sub = None
        sw_items = []
        if toggle:                                   # a little switch, like in Settings
            on = bool(it["var"].get())
            sw_w, sw_h = int(34 * k), int(18 * k)
            sx1 = x1 - int(10 * k)
            sx0 = sx1 - sw_w
            sw_items.append(_round_rect(c, sx0, cy - sw_h / 2, sx1, cy + sw_h / 2, sw_h // 2,
                                        fill=RED if on else "#ddd2d7", outline="", tags=tag))
            r = sw_h / 2 - 3
            kx = sx1 - sw_h / 2 if on else sx0 + sw_h / 2
            sw_items.append(c.create_oval(kx - r, cy - r, kx + r, cy + r, fill="white", outline="", tags=tag))
        elif it.get("hint"):
            c.create_text(x1 - int(10 * k), cy, text=it["hint"], anchor="e", fill=C_MUTED, font=self.fs, tags=tag)

        def enter(_e):
            c.itemconfig(bg, fill=RED if not eagle else "#ffe0e7", outline=RED if not eagle else RED)
            if not eagle:
                c.itemconfig(label, fill="white")
                c.itemconfig(icon_item, fill="white")
            c.configure(cursor="hand2")

        def leave(_e):
            c.itemconfig(bg, fill=base_fill, outline=("#ffc9d4" if eagle else base_fill))
            c.itemconfig(label, fill=ink)
            c.itemconfig(icon_item, fill=RED if (eagle or danger) else C_MUTED)
            c.configure(cursor="")

        c.tag_bind(tag, "<Enter>", enter)
        c.tag_bind(tag, "<Leave>", leave)
        c.tag_bind(tag, "<ButtonRelease-1>", lambda e: self._run(it))
