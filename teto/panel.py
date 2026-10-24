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
        row("Steps per task", tk.Label(w, text="unlimited - she keeps going until it's done ♪", bg=BG,
                                       fg=PINK, font=f), 4)
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
                          ("New tabs (only if asked) use my signed-in Edge", self.v_real),
                          ("See the page after every action", self.v_see),
                          ("Show Teto's browser window", self.v_showb)):
            tk.Checkbutton(side, text=text, variable=var, **chk).pack(anchor="w")
        link_row = tk.Frame(side, bg=BG)
        link_row.pack(anchor="w", pady=(4, 0))
        ok = getattr(self.app, "link_connected", lambda: False)()
        self.link_lbl = tk.Label(link_row, text="Teto Link: connected ✓" if ok else "Teto Link: not connected",
                                 bg=BG, fg=(PINK if ok else GREY), font=f)
        self.link_lbl.pack(side="left")
        tk.Button(link_row, text="Connect my Edge", command=self._connect_edge, relief="flat", bg=PINK,
                  fg="white", activebackground=PINK, font=f, padx=8).pack(side="left", padx=(8, 0))
        tk.Label(side, text="Teto works IN the tabs you already have open (your quiz, form, email)\n"
                            "while you do something else. She opens new tabs only if you ask.", bg=BG, fg=GREY,
                 font=(fam, 8), justify="left").pack(anchor="w", pady=(2, 12))
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

    def _connect_edge(self):
        from tkinter import messagebox
        text = self.app.connect_edge()
        messagebox.showinfo("Connect my Edge", text, parent=self.win if hasattr(self, "win") else None)

    def _save(self):
        cfg = self.app.config
        try:
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
