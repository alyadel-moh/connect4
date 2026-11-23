"""
gui.py - Modern Tkinter front-end for the Connect 4 minimax agent (Human vs Computer).

Run:  python gui.py

Structure
  Helpers / widgets : rrect, draw_disc, Button, Segmented, Stepper, Toggle
  BoardCanvas       : glossy board, hover column, bouncing drop animation,
                      last-move marker, pulsing winning discs, column numbers
  SetupView         : game configuration (algorithm, K, board size, first move)
  GameView          : board + player cards + AI insight tiles + minimax tree
                      explorer with a board preview of the selected node
The AI runs in a worker thread so the window never freezes.
Keyboard: press 1..N to drop a disc in that column, T opens the tree window.
"""
import queue
import random
import threading
import traceback
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from board import Board, HUMAN, AI
from minimax import choose_move, format_tree, INF

# ----------------------------------------------------------------------------
# Theme
# ----------------------------------------------------------------------------
BG, CARD, CARD2, BORDER = "#0b1020", "#141c3a", "#1b2650", "#2a376b"
TEXT, MUTED = "#eef2ff", "#8b97c7"
ACCENT, ACCENT_H = "#6366f1", "#818cf8"
CYAN, GREEN, ROSE, AMBER = "#22d3ee", "#34d399", "#fb7185", "#fbbf24"
RED, YELLOW = "#ff4d6d", "#ffd23f"
BOARD, BOARD_D, BOARD_L = "#2540d9", "#1a2fa8", "#3656ee"
HOLE, HOLE_RIM = "#0a1030", "#08102c"

FAMILY = "Segoe UI"


def F(size, weight="normal"):
    return (FAMILY, size, weight)


def pick_font(root):
    global FAMILY
    available = set(tkfont.families(root))
    for name in ("Segoe UI", "SF Pro Display", "Helvetica Neue", "Inter",
                 "Ubuntu", "Noto Sans", "DejaVu Sans", "Arial"):
        if name in available:
            FAMILY = name
            return


def mix(a, b, t):
    """Blend hex colour a towards b by factor t (0..1)."""
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(pa, pb))


def rrect(c, x1, y1, x2, y2, r, **kw):
    """Rounded rectangle on a canvas."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)



def draw_disc(c, cx, cy, r, color, tags=()):
    """Glossy game disc: rim, body, embossed inner ring and a specular highlight."""
    dark = mix(color, "#000000", 0.38)
    mid = mix(color, "#000000", 0.14)
    light = mix(color, "#ffffff", 0.45)
    c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=dark, outline="", tags=tags)
    r2 = r * 0.90
    c.create_oval(cx - r2, cy - r2, cx + r2, cy + r2, fill=mid, outline="", tags=tags)
    r3 = r * 0.80
    c.create_oval(cx - r3, cy - r3, cx + r3, cy + r3, fill=color, outline="", tags=tags)
    r4 = r * 0.56
    c.create_oval(cx - r4, cy - r4, cx + r4, cy + r4, fill=mix(color, "#ffffff", 0.08),
                  outline=mid, width=max(1, int(r / 9)), tags=tags)
    c.create_oval(cx - r * 0.58, cy - r * 0.68, cx - r * 0.06, cy - r * 0.32,
                  fill=light, outline="", tags=tags)
    c.create_oval(cx - r * 0.44, cy - r * 0.60, cx - r * 0.22, cy - r * 0.46,
                  fill="#ffffff", outline="", tags=tags)


def make_gradient(master, w, h, c1, c2):
    """Horizontal gradient as a PhotoImage (one row, tiled vertically)."""
    img = tk.PhotoImage(master=master, width=w, height=h)
    row = " ".join(mix(c1, c2, x / max(1, w - 1)) for x in range(w))
    img.put("{" + row + "}", to=(0, 0, w, h))
    return img


# ----------------------------------------------------------------------------
# Custom widgets (canvas based so they can be rounded / animated)
# ----------------------------------------------------------------------------

class Button(tk.Canvas):
    """Rounded button. kind='primary' (filled, glossy) or 'ghost' (outlined)."""

    def __init__(self, master, text, command, kind="primary", width=150, height=40, bg=BG):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._label, self._cmd, self.kind = text, command, kind
        self.bw, self.bh, self._hot, self._down = width, height, False, False
        self._draw()
        self.bind("<Enter>", lambda e: self._set(hot=True))
        self.bind("<Leave>", lambda e: self._set(hot=False, down=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(down=True))
        self.bind("<ButtonRelease-1>", self._release)

    def _set(self, hot=None, down=None):
        if hot is not None:
            self._hot = hot
        if down is not None:
            self._down = down
        self._draw()

    def _release(self, e):
        self._set(down=False)
        if 0 <= e.x <= self.bw and 0 <= e.y <= self.bh and self._cmd:
            self._cmd()

    def _draw(self):
        self.delete("all")
        r, off = self.bh / 2.4, (2 if self._down else 0)
        if self.kind == "primary":
            base = ACCENT_H if self._hot else ACCENT
            rrect(self, 1, 4, self.bw - 1, self.bh - 1, r, fill=mix(base, "#000000", 0.40), outline="")
            rrect(self, 1, 1 + off, self.bw - 1, self.bh - 4 + off, r, fill=base, outline="")
            rrect(self, 5, 3 + off, self.bw - 5, self.bh * 0.46 + off, 7,
                  fill=mix(base, "#ffffff", 0.16), outline="")
            fg = "#ffffff"
        else:
            fill = "#27356b" if self._hot else CARD2
            rrect(self, 1, 1 + off, self.bw - 1, self.bh - 1, r, fill=fill, outline=BORDER)
            fg = TEXT
        self.create_text(self.bw / 2, (self.bh - 3) / 2 + 1 + off, text=self._label, fill=fg,
                         font=F(11, "bold"))


class Segmented(tk.Canvas):
    """Pill-shaped option switcher bound to a StringVar."""

    def __init__(self, master, options, variable, width=270, height=40, bg=CARD):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.options, self.var, self.sw, self.sh = options, variable, width, height
        self._draw()
        self.bind("<Button-1>", self._click)
        variable.trace_add("write", lambda *a: self._draw())

    def _click(self, e):
        i = min(len(self.options) - 1, max(0, int(e.x // (self.sw / len(self.options)))))
        self.var.set(self.options[i][1])

    def _draw(self):
        self.delete("all")
        rrect(self, 1, 1, self.sw - 1, self.sh - 1, self.sh / 2, fill="#0f1733", outline=BORDER)
        seg = self.sw / len(self.options)
        for i, (label, value) in enumerate(self.options):
            on = self.var.get() == value
            if on:
                rrect(self, i * seg + 4, 4, (i + 1) * seg - 4, self.sh - 4,
                      (self.sh - 8) / 2, fill=ACCENT, outline="")
            self.create_text(i * seg + seg / 2, self.sh / 2, text=label,
                             fill="#ffffff" if on else MUTED, font=F(10, "bold"))


class Stepper(tk.Canvas):
    """[-]  value  [+] control bound to an IntVar."""

    def __init__(self, master, variable, lo, hi, width=124, height=40, bg=CARD):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.var, self.lo, self.hi, self.sw, self.sh = variable, lo, hi, width, height
        self._draw()
        self.bind("<Button-1>", self._click)
        variable.trace_add("write", lambda *a: self._draw())

    def _click(self, e):
        if e.x < 40:
            self.var.set(max(self.lo, self.var.get() - 1))
        elif e.x > self.sw - 40:
            self.var.set(min(self.hi, self.var.get() + 1))

    def _draw(self):
        self.delete("all")
        rrect(self, 1, 1, self.sw - 1, self.sh - 1, self.sh / 2, fill="#0f1733", outline=BORDER)
        cy = self.sh / 2
        for cx, sym in ((20, "\u2212"), (self.sw - 20, "+")):
            self.create_oval(cx - 13, cy - 13, cx + 13, cy + 13, fill=CARD2, outline="")
            self.create_text(cx, cy - 1, text=sym, fill=TEXT, font=F(13, "bold"))
        self.create_text(self.sw / 2, cy, text=str(self.var.get()), fill=TEXT, font=F(12, "bold"))


class Toggle(tk.Canvas):
    def __init__(self, master, variable, bg=CARD):
        super().__init__(master, width=54, height=30, bg=bg, highlightthickness=0,
                         bd=0, cursor="hand2")
        self.var = variable
        self._draw()
        self.bind("<Button-1>", lambda e: self.var.set(not self.var.get()))
        variable.trace_add("write", lambda *a: self._draw())

    def _draw(self):
        self.delete("all")
        on = self.var.get()
        rrect(self, 1, 1, 53, 29, 14, fill=ACCENT if on else "#2a3566", outline="")
        x = 39 if on else 15
        self.create_oval(x - 11, 4, x + 11, 26, fill="#ffffff", outline="")


class GradientBar(tk.Canvas):
    """Thin horizontal gradient accent line that stretches to its container."""

    def __init__(self, master, c1=ACCENT, c2=CYAN, height=3, bg=BG):
        super().__init__(master, width=1, height=height, bg=bg, highlightthickness=0, bd=0)
        self._c1, self._c2, self._h, self._img = c1, c2, height, None
        self.bind("<Configure>", self._fit)

    def _fit(self, e):
        self._img = make_gradient(self, max(2, e.width), self._h, self._c1, self._c2)
        self.delete("all")
        self.create_image(0, 0, image=self._img, anchor="nw")


# ----------------------------------------------------------------------------
# Board canvas
# ----------------------------------------------------------------------------
class BoardCanvas(tk.Canvas):
    """Draws a Board. Interactive: hover column, click, drop animation, numbers."""

    def __init__(self, master, rows, cols, cell, on_click=None, mini=False, bg=BG):
        self.rows, self.cols, self.cell, self.mini = rows, cols, cell, mini
        self.interactive = on_click is not None and not mini
        self.M = 3 if mini else 10                 # outer margin (shadow room)
        self.P = 4 if mini else 12                 # inner padding of the board body
        self.T = int(cell * 0.95) if self.interactive else 0   # hover strip height
        self.N = 26 if self.interactive else 0                  # column numbers strip
        self.R = cell * (0.44 if mini else 0.40)               # disc radius
        self.W = cols * cell + 2 * (self.M + self.P)
        self.gx, self.gy = self.M + self.P, self.T + self.P
        self.body_bottom = self.gy + rows * cell + self.P
        super().__init__(master, width=self.W, height=self.body_bottom + self.M + self.N,
                         bg=bg, highlightthickness=0, bd=0)
        self.on_click = on_click
        self._board, self._last, self._glow = None, None, set()
        self.hover, self.hover_color = None, None
        self.animating, self._phase, self._pulsing = False, 0, False
        if self.interactive:
            self.bind("<Motion>", lambda e: self._set_hover(self._col_at(e.x)))
            self.bind("<Leave>", lambda e: self._set_hover(None))
            self.bind("<Button-1>", self._click)
            self.configure(cursor="hand2")

    # ---- geometry ----
    def _col_at(self, x):
        col = int((x - self.gx) // self.cell)
        return col if 0 <= col < self.cols else None

    def _cx(self, col):
        return self.gx + col * self.cell + self.cell / 2

    def _cy(self, row):
        return self.gy + row * self.cell + self.cell / 2

    def _click(self, e):
        col = self._col_at(e.x)
        if col is not None and self.on_click:
            self.on_click(col)

    def _set_hover(self, col):
        if col != self.hover and not self.animating:
            self.hover = col
            self._redraw()

    # ---- public API ----
    def refresh(self, board=None, last="keep", glow=None, hover_color="keep"):
        if board is not None:
            self._board = board
        if last != "keep":
            self._last = last
        if glow is not None:
            self._glow = glow
            if glow and not self._pulsing:
                self._pulsing = True
                self._pulse()
        if hover_color != "keep":
            self.hover_color = hover_color
        self._redraw()

    def _pulse(self):
        if not self._glow:
            self._pulsing = False
            return
        try:
            self._phase ^= 1
            self._redraw()
            self.after(450, self._pulse)
        except tk.TclError:
            pass

    def _redraw(self):
        c = self
        c.delete("all")
        W, cell, mini = self.W, self.cell, self.mini
        top, bottom, M = self.T, self.body_bottom, self.M
        if not mini:                                           # drop shadow
            rrect(c, M, top + 8, W - M, bottom + 8, 24, fill="#04061a", outline="")
        rrect(c, M, top, W - M, bottom, 8 if mini else 24, fill=BOARD_D, outline="")       # rim
        rrect(c, M + 3, top + 3, W - M - 3, bottom - 3, 6 if mini else 21, fill=BOARD, outline="")
        if not mini:                                           # top sheen
            rrect(c, M + 12, top + 5, W - M - 12, top + 10, 3, fill=BOARD_L, outline="")
        if self.interactive and self.hover is not None and self.hover_color:
            x1 = self.gx + self.hover * cell + 3
            rrect(c, x1, top + 12, x1 + cell - 6, bottom - 12, 14, fill=BOARD_L, outline="#5b78ff")
        b = self._board
        hr = cell * (0.46 if mini else 0.435)
        for r in range(self.rows):
            for col in range(self.cols):
                cx, cy = self._cx(col), self._cy(r)
                if not mini:                                   # hole: rim + cavity + lower lip light
                    c.create_oval(cx - hr - 2, cy - hr - 2, cx + hr + 2, cy + hr + 2,
                                  fill=BOARD_D, outline="")
                c.create_oval(cx - hr, cy - hr, cx + hr, cy + hr, fill=HOLE,
                              outline=HOLE_RIM, width=1 if mini else 2)
                if not mini:
                    c.create_arc(cx - hr - 1, cy - hr - 1, cx + hr + 1, cy + hr + 1, start=210,
                                 extent=120, style="arc", outline=BOARD_L, width=2)
                v = b.grid[r][col] if b else 0
                if v:
                    draw_disc(c, cx, cy, self.R, RED if v == HUMAN else YELLOW)
                if (r, col) in self._glow:
                    c.create_oval(cx - self.R - 4, cy - self.R - 4, cx + self.R + 4,
                                  cy + self.R + 4, outline="#ffffff" if self._phase else "#a5b4fc",
                                  width=4 if self._phase else 2)
                if self._last == (r, col) and not mini:
                    k = self.R * 0.22
                    c.create_oval(cx - k, cy - k, cx + k, cy + k, outline="#ffffff", width=2)
        if self.interactive:
            for col in range(self.cols):
                on = col == self.hover
                c.create_text(self._cx(col), bottom + M + self.N / 2 + 1,
                              text=str(col + 1), fill=TEXT if on else MUTED, font=F(10, "bold"))
            if self.hover is not None and self.hover_color:
                draw_disc(c, self._cx(self.hover), self.T * 0.5, self.R, self.hover_color)

    def animate_drop(self, col, row, color, done):
        """Bouncing drop from the top strip to (row, col); then done()."""
        self.animating = True
        self._redraw()
        cx, target = self._cx(col), self._cy(row)
        y, v, bounces = [self.T * 0.5 if self.T else -self.R], [3.0], [0]
        draw_disc(self, cx, y[0], self.R, color, ("fall",))

        def finish():
            self.animating = False
            self.delete("fall")
            done()

        def step():
            try:
                v[0] += 2.6
                ny = y[0] + v[0]
                if ny >= target:
                    self.move("fall", 0, target - y[0])
                    y[0] = target
                    if bounces[0] < 2 and v[0] > 7:
                        v[0] = -v[0] * 0.28
                        bounces[0] += 1
                    else:
                        return finish()
                else:
                    self.move("fall", 0, ny - y[0])
                    y[0] = ny
                self.after(14, step)
            except tk.TclError:
                pass
        step()


# ----------------------------------------------------------------------------
# Small composite widgets
# ----------------------------------------------------------------------------
def card(master, **kw):
    return tk.Frame(master, bg=CARD, highlightbackground=BORDER, highlightthickness=1, **kw)



class PlayerCard(tk.Frame):
    """Score card; its border lights up in the player's colour when it is their turn."""

    def __init__(self, master, name, color):
        super().__init__(master, bg=CARD, highlightbackground=BORDER,
                         highlightthickness=2, padx=14, pady=10)
        self.color = color
        icon = tk.Canvas(self, width=44, height=44, bg=CARD, highlightthickness=0)
        draw_disc(icon, 22, 22, 19, color)
        icon.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        tk.Label(self, text=name, bg=CARD, fg=TEXT, font=F(13, "bold")).grid(row=0, column=1, sticky="w")
        tk.Label(self, text="connected fours", bg=CARD, fg=MUTED, font=F(9)).grid(row=1, column=1, sticky="w")
        self.score = tk.Label(self, text="0", bg=CARD, fg=TEXT, font=F(30, "bold"))
        self.score.grid(row=0, column=2, rowspan=2, padx=(14, 0))
        self.badge = tk.Label(self, text="", bg=CARD, fg=color, font=F(8, "bold"), anchor="w")
        self.badge.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.columnconfigure(1, weight=1)

    def set_score(self, n):
        self.score.config(text=str(n))

    def set_active(self, on, label=""):
        self.config(highlightbackground=self.color if on else BORDER)
        self.badge.config(text=label if on else "")



class Tile(tk.Frame):
    """Small stat tile with a coloured accent line."""

    def __init__(self, master, title, accent=ACCENT):
        super().__init__(master, bg=CARD, highlightbackground=BORDER, highlightthickness=1,
                         padx=8, pady=7)
        tk.Frame(self, bg=accent, height=3).pack(fill="x", pady=(0, 6))
        tk.Label(self, text=title.upper(), bg=CARD, fg=MUTED, font=F(8, "bold")).pack(anchor="w")
        self.value = tk.Label(self, text="-", bg=CARD, fg=TEXT, font=F(14, "bold"))
        self.value.pack(anchor="w")

    def set(self, text, color=TEXT):
        self.value.config(text=text, fg=color)


def fmt_inf(x):
    return "-inf" if x == -INF else "+inf" if x == INF else f"{x:g}"


# ----------------------------------------------------------------------------
# Setup screen
# ----------------------------------------------------------------------------

class SetupView(tk.Frame):
    """Landing screen: animated demo board on the left, game settings on the right."""
    PRESETS = {"easy": 2, "medium": 4, "hard": 6}

    def __init__(self, master, on_start):
        super().__init__(master, bg=BG)
        self.on_start = on_start
        self.algo = tk.StringVar(value="alphabeta")
        self.k = tk.IntVar(value=4)
        self.preset = tk.StringVar(value="medium")
        self.rows = tk.IntVar(value=6)
        self.cols = tk.IntVar(value=7)
        self.first = tk.StringVar(value="human")
        self.print_tree = tk.BooleanVar(value=True)

        GradientBar(self, ACCENT, CYAN, height=4).pack(fill="x")
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(expand=True, padx=48, pady=24)

        # ---- hero (left) ----
        hero = tk.Frame(wrap, bg=BG)
        hero.grid(row=0, column=0, padx=(0, 56), sticky="n")
        logo = tk.Canvas(hero, width=250, height=64, bg=BG, highlightthickness=0)
        for i in range(4):
            draw_disc(logo, 32 + i * 62, 32, 27, RED if i % 2 == 0 else YELLOW)
        logo.pack(anchor="w")
        tk.Label(hero, text="CONNECT 4", bg=BG, fg=TEXT, font=F(34, "bold")).pack(anchor="w", pady=(12, 0))
        tk.Label(hero, text="Beat the minimax AI", bg=BG, fg=CYAN, font=F(13, "bold")).pack(anchor="w")
        tk.Label(hero, text="Every move builds a search tree.\nExplore it node by node after each turn.",
                 bg=BG, fg=MUTED, font=F(10), justify="left").pack(anchor="w", pady=(6, 18))
        self.demo = BoardCanvas(hero, 6, 7, 46)
        self.demo.pack(anchor="w")

        # ---- settings (right) ----
        right = tk.Frame(wrap, bg=BG)
        right.grid(row=0, column=1, sticky="n")
        tk.Label(right, text="Game settings", bg=BG, fg=TEXT, font=F(17, "bold")).pack(anchor="w", pady=(0, 12))
        box = card(right)
        box.pack(fill="x")
        self._row(box, "Algorithm", "How the computer searches",
                  lambda p: Segmented(p, [("Minimax", "minimax"), ("Alpha-Beta", "alphabeta")], self.algo))
        self._row(box, "Difficulty", "Quick presets for the depth K",
                  lambda p: Segmented(p, [("Easy", "easy"), ("Medium", "medium"), ("Hard", "hard")], self.preset))
        self._row(box, "Search depth (K)", "Levels explored before the cutoff",
                  lambda p: Stepper(p, self.k, 1, 10))
        self._row(box, "Board size", "Rows \u00d7 columns (min 6 \u00d7 7)", self._size_widget)
        self._row(box, "First move", "Who drops the first disc",
                  lambda p: Segmented(p, [("You", "human"), ("Computer", "ai")], self.first))
        self._row(box, "Print tree to console", "Readable minimax tree every AI turn",
                  lambda p: Toggle(p, self.print_tree), last=True)

        self.est = tk.Label(right, text="", bg=BG, fg=MUTED, font=F(10))
        self.est.pack(pady=(14, 4))
        Button(right, "Start game  \u25B6", self._start, width=300, height=52).pack(pady=(6, 8))
        tk.Label(right, text="Tip: press 1\u20137 to drop a disc, T opens the tree window", bg=BG,
                 fg=MUTED, font=F(9)).pack()

        for v in (self.algo, self.k, self.cols):
            v.trace_add("write", lambda *a: self._estimate())
        self.preset.trace_add("write", lambda *a: self._on_preset())
        self.k.trace_add("write", lambda *a: self._on_k())
        self._estimate()
        self._demo_start()

    # ---- settings helpers ----
    def _on_preset(self):
        k = self.PRESETS.get(self.preset.get())
        if k and self.k.get() != k:
            self.k.set(k)

    def _on_k(self):
        name = {v: n for n, v in self.PRESETS.items()}.get(self.k.get(), "custom")
        if self.preset.get() != name:
            self.preset.set(name)

    def _size_widget(self, parent):
        f = tk.Frame(parent, bg=CARD)
        Stepper(f, self.rows, 6, 12, width=112).pack(side="left")
        tk.Label(f, text="\u00d7", bg=CARD, fg=MUTED, font=F(12, "bold")).pack(side="left", padx=8)
        Stepper(f, self.cols, 7, 12, width=112).pack(side="left")
        return f

    def _row(self, parent, title, desc, factory, last=False):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=24, pady=11)
        left = tk.Frame(row, bg=CARD)
        left.pack(side="left")
        tk.Label(left, text=title, bg=CARD, fg=TEXT, font=F(11, "bold")).pack(anchor="w")
        tk.Label(left, text=desc, bg=CARD, fg=MUTED, font=F(9)).pack(anchor="w")
        factory(row).pack(side="right", padx=(30, 0))
        if not last:
            tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=24)

    def _estimate(self):
        try:
            leaves = self.cols.get() ** self.k.get()
        except tk.TclError:
            return
        if self.algo.get() == "minimax":
            heavy = leaves > 3_000_000
            self.est.config(
                text=f"Up to {leaves:,} leaf boards" + ("  -  heavy, may be slow!" if heavy else ""),
                fg=AMBER if heavy else MUTED)
        else:
            self.est.config(text=f"Up to {leaves:,} leaf boards  -  pruning usually visits far fewer",
                            fg=MUTED)

    def _start(self):
        self.on_start(dict(alpha_beta=self.algo.get() == "alphabeta", k=self.k.get(),
                           rows=self.rows.get(), cols=self.cols.get(),
                           ai_first=self.first.get() == "ai", print_tree=self.print_tree.get()))

    # ---- looping demo game on the hero board ----
    def _demo_start(self):
        if not self.winfo_exists():
            return
        self._demo_board, self._demo_turn = Board(6, 7), HUMAN
        self.demo.refresh(self._demo_board, last=None, glow=set())
        self.after(700, self._demo_step)

    def _demo_step(self):
        if not self.winfo_exists():
            return
        b = self._demo_board
        fours = b.count_fours(HUMAN) + b.count_fours(AI)
        if fours or sum(b.heights) >= 26:                    # show the result, then restart
            if fours:
                self.demo.refresh(glow=b.winning_cells(HUMAN) | b.winning_cells(AI))
            self.after(2200, self._demo_start)
            return
        moves = b.valid_moves()
        col = random.choices(moves, weights=[(1, 2, 3, 4, 3, 2, 1)[m] for m in moves])[0]
        row, piece = b.next_row(col), self._demo_turn

        def done():
            b.drop(col, piece)
            self.demo.refresh(b, last=(row, col))
            self._demo_turn = AI if piece == HUMAN else HUMAN
            self.after(260, self._demo_step)
        self.demo.animate_drop(col, row, RED if piece == HUMAN else YELLOW, done)


# ----------------------------------------------------------------------------
# Graphical minimax tree window
# ----------------------------------------------------------------------------
class TreeViewer(tk.Toplevel):
    """Node-link diagram of the last AI search.
    Click a node to expand / collapse it, drag to pan, mouse wheel to scroll.
    The chosen (principal) path is drawn in gold; cut-off branches are dashed."""
    COLW, ROWH, BW = 158, 64, 122
    MAX_NODES = 1500

    def __init__(self, master, alpha_beta, rows, cols):
        super().__init__(master)
        self.title("Minimax tree")
        self.configure(bg=BG)
        self.geometry("1180x720")
        self.minsize(720, 480)
        self.ab, self.rows, self.cols = alpha_beta, rows, cols
        self.BH = 50 if alpha_beta else 40
        self.root_node, self.best_col, self.base_board = None, None, None
        self.expanded, self.hits, self.node_pos = set(), [], {}
        self.selected, self.visible, self._size, self._press = None, 0, (1, 1), (0, 0)

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=14, pady=(12, 6))
        Button(bar, "Expand level", self.expand_level, width=120, height=34).pack(side="left")
        Button(bar, "Collapse", self.collapse_all, kind="ghost", width=100, height=34).pack(side="left", padx=8)
        Button(bar, "Reset", self.reset_view, kind="ghost", width=80, height=34).pack(side="left")
        self.note = tk.Label(bar, text="", bg=BG, fg=MUTED, font=F(9))
        self.note.pack(side="left", padx=14)
        for text, color in (("pruned", "#64748b"), ("chosen path", YELLOW), ("leaf", MUTED),
                            ("MIN", ROSE), ("MAX", CYAN)):
            tk.Label(bar, text="\u25A0 " + text, bg=BG, fg=color, font=F(9, "bold")).pack(side="right", padx=6)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=14)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self.cv = tk.Canvas(body, bg=CARD, highlightthickness=1, highlightbackground=BORDER,
                            xscrollincrement=24, yscrollincrement=24)
        hb = ttk.Scrollbar(body, orient="horizontal", command=self.cv.xview)
        vb = ttk.Scrollbar(body, orient="vertical", command=self.cv.yview)
        self.cv.configure(xscrollcommand=hb.set, yscrollcommand=vb.set)
        self.cv.grid(row=0, column=0, sticky="nsew")
        vb.grid(row=0, column=1, sticky="ns")
        hb.grid(row=1, column=0, sticky="ew")
        self.cv.bind("<ButtonPress-1>", self._down)
        self.cv.bind("<B1-Motion>", lambda e: self.cv.scan_dragto(e.x, e.y, gain=1))
        self.cv.bind("<ButtonRelease-1>", self._up)
        self.cv.bind("<MouseWheel>", lambda e: self.cv.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.cv.bind("<Shift-MouseWheel>", lambda e: self.cv.xview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.cv.bind("<Button-4>", lambda e: self.cv.yview_scroll(-1, "units"))
        self.cv.bind("<Button-5>", lambda e: self.cv.yview_scroll(1, "units"))

        info = tk.Frame(self, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        info.pack(fill="x", padx=14, pady=12)
        self.preview = BoardCanvas(info, rows, cols, 16, mini=True, bg=CARD)
        self.preview.pack(side="left", padx=12, pady=10)
        txt = tk.Frame(info, bg=CARD)
        txt.pack(side="left", padx=6, anchor="n", pady=12)
        self.sel_title = tk.Label(txt, text="No node selected", bg=CARD, fg=TEXT, font=F(12, "bold"))
        self.sel_title.pack(anchor="w")
        self.sel_path = tk.Label(txt, text="Click a node to see its board here.", bg=CARD, fg=MUTED, font=F(10))
        self.sel_path.pack(anchor="w", pady=(2, 0))
        self.sel_ab = tk.Label(txt, text="", bg=CARD, fg=MUTED, font=F(10))
        self.sel_ab.pack(anchor="w")
        self._redraw()

    # ---- data ----
    def set_data(self, root, best_col, base_board):
        self.root_node, self.best_col, self.base_board = root, best_col, base_board
        self.reset_view()

    def reset_view(self):
        if self.root_node is None:
            return
        self.expanded = {self.root_node} | set(self.root_node.children)
        self.selected = None
        self._redraw()
        self.cv.xview_moveto(0)
        self.cv.yview_moveto(0)
        self._show_info(self.root_node, [])

    def collapse_all(self):
        if self.root_node is None:
            return
        self.expanded = {self.root_node}
        self._redraw()
        self.cv.xview_moveto(0)
        self.cv.yview_moveto(0)

    def expand_level(self):
        if self.root_node is None:
            return
        frontier = [e["n"] for e in self._layout()
                    if e["n"] is not None and e["n"].children and e["n"] not in self.expanded]
        if self.visible + sum(len(n.children) for n in frontier) > self.MAX_NODES:
            self.note.config(text=f"Too many nodes to expand a whole level (limit {self.MAX_NODES:,}). "
                                  "Expand single nodes instead.")
            return
        self.expanded.update(frontier)
        self._redraw()

    # ---- layout ----
    def _pv(self, n, is_root):
        """Child on the principal (chosen) path."""
        for ch in n.children:
            if (ch.move == self.best_col) if is_root else (ch.value == n.value):
                return ch
        return None

    def _layout(self):
        entries, slot = [], [0]

        def place(n, depth, path, best, parent):
            e = {"n": n, "d": depth, "path": path, "best": best, "parent": parent, "y": 0, "stub": None}
            entries.append(e)
            kids = n.children if n in self.expanded else []
            if kids:
                pv = self._pv(n, depth == 0) if best else None
                ys = []
                for ch in kids:
                    ys.append(place(ch, depth + 1, path + [ch.move], best and ch is pv, e)["y"])
                if n.pruned_cols:
                    se = {"n": None, "d": depth + 1, "path": path, "best": False, "parent": e,
                          "y": slot[0] * self.ROWH, "stub": n.pruned_cols}
                    slot[0] += 1
                    entries.append(se)
                    ys.append(se["y"])
                e["y"] = (ys[0] + ys[-1]) / 2
            else:
                e["y"] = slot[0] * self.ROWH
                slot[0] += 1
            return e

        place(self.root_node, 0, [], True, None)
        return entries

    # ---- drawing ----
    def _redraw(self):
        cv = self.cv
        cv.delete("all")
        self.hits, self.node_pos = [], {}
        if self.root_node is None:
            cv.configure(scrollregion=(0, 0, 10, 10))
            cv.create_text(300, 120, text="The tree appears after the computer's first move.",
                           fill=MUTED, font=F(12))
            return
        entries = self._layout()
        self.visible = len(entries)
        X0, Y0, BW, BH = 24, 40, self.BW, self.BH

        def pos(e):
            return X0 + e["d"] * self.COLW, Y0 + e["y"]

        for e in entries:                                     # edges first
            if e["parent"] is None:
                continue
            px, py = pos(e["parent"])
            cx, cy = pos(e)
            x1, mid = px + BW, (px + BW + cx) / 2
            kw = {"dash": (4, 3)} if e["stub"] else {}
            cv.create_line(x1, py, mid, py, mid, cy, cx, cy, smooth=True,
                           fill=YELLOW if e["best"] else "#3b4a86",
                           width=3 if e["best"] else 1, **kw)

        for e in entries:                                     # then boxes
            x, y = pos(e)
            x1, y1, x2, y2 = x, y - BH / 2, x + BW, y + BH / 2
            n = e["n"]
            if n is None:                                     # pruned stub
                rrect(cv, x1, y1 + 6, x2, y2 - 6, 10, fill=BG, outline="#64748b", dash=(3, 3))
                cv.create_text(x1 + BW / 2, y - 7, text="\u2702 pruned", fill="#64748b", font=F(8, "bold"))
                cv.create_text(x1 + BW / 2, y + 7, text=",".join(str(c + 1) for c in e["stub"]),
                               fill="#64748b", font=F(8))
                continue
            root = n.move is None
            color = ACCENT if root else MUTED if n.leaf else CYAN if n.is_max else ROSE
            rrect(cv, x1, y1, x2, y2, 10, fill="#1f2a5c" if n is self.selected else BG,
                  outline=YELLOW if e["best"] else color, width=3 if e["best"] else 2)
            head = "ROOT \u00b7 MAX" if root else \
                f"col {n.move + 1} \u00b7 {'LEAF' if n.leaf else 'MAX' if n.is_max else 'MIN'}"
            cv.create_text(x1 + 10, y1 + 12, text=head, anchor="w", fill=color, font=F(9, "bold"))
            cv.create_text(x1 + 10, y1 + 27, text=f"value  {fmt_inf(n.value)}", anchor="w",
                           fill=TEXT, font=F(10, "bold"))
            if self.ab and not n.leaf and n.alpha is not None:
                cv.create_text(x1 + 10, y1 + 41, anchor="w", fill=MUTED, font=F(8),
                               text=f"\u03b1 {fmt_inf(n.alpha)}  \u03b2 {fmt_inf(n.beta)}")
            if n.children:                                    # expand / collapse badge
                cv.create_oval(x2 - 11, y - 11, x2 + 11, y + 11, fill=ACCENT, outline=BG, width=2)
                cv.create_text(x2, y, fill="#ffffff", font=F(8, "bold"),
                               text="\u2212" if n in self.expanded else f"+{len(n.children)}")
            self.hits.append((x1, y1, x2 + 11, y2, n, e["path"]))
            self.node_pos[n] = (x1, y1)

        W = X0 + max(e["d"] for e in entries) * self.COLW + BW + 40
        H = Y0 + max(e["y"] for e in entries) + BH + 40
        self._size = (W, H)
        cv.configure(scrollregion=(0, 0, W, H))
        self.note.config(text=f"{self.visible:,} nodes shown  \u2022  click a node to expand / collapse"
                              "  \u2022  drag to pan")

    # ---- interaction ----
    def _down(self, e):
        self._press = (e.x, e.y)
        self.cv.scan_mark(e.x, e.y)

    def _up(self, e):
        if abs(e.x - self._press[0]) < 4 and abs(e.y - self._press[1]) < 4:
            self._click(self.cv.canvasx(e.x), self.cv.canvasy(e.y))

    def _click(self, x, y):
        for x1, y1, x2, y2, n, path in self.hits:
            if not (x1 <= x <= x2 and y1 <= y <= y2):
                continue
            old = self.node_pos.get(n)
            left, top = self.cv.canvasx(0), self.cv.canvasy(0)
            self.selected = n
            if n.children:
                if n in self.expanded:
                    self.expanded.discard(n)
                elif self.visible + len(n.children) > self.MAX_NODES:
                    self.note.config(text=f"Too many nodes shown (limit {self.MAX_NODES:,}). Collapse something first.")
                else:
                    self.expanded.add(n)
            self._redraw()
            new = self.node_pos.get(n)
            if old and new:                                   # keep the clicked node under the cursor
                W, H = self._size
                self.cv.xview_moveto(max(0, (left + new[0] - old[0]) / W))
                self.cv.yview_moveto(max(0, (top + new[1] - old[1]) / H))
            self._show_info(n, path)
            return

    def _show_info(self, n, path):
        b = self.base_board.copy()
        for i, col in enumerate(path):                        # replay moves from the root
            b.drop(col, AI if i % 2 == 0 else HUMAN)
        self.preview.refresh(b)
        if n.move is None:
            self.sel_title.config(text=f"Root  (current position)   value {fmt_inf(n.value)}")
            self.sel_path.config(text="Computer to move.")
        else:
            kind = "LEAF" if n.leaf else "MAX" if n.is_max else "MIN"
            self.sel_title.config(text=f"col {n.move + 1} \u00b7 {kind}   value {fmt_inf(n.value)}")
            self.sel_path.config(text="Moves: " + "  \u2192  ".join(str(c + 1) for c in path))
        self.sel_ab.config(text=f"\u03b1 = {fmt_inf(n.alpha)}    \u03b2 = {fmt_inf(n.beta)}"
                           if n.alpha is not None else "")


# ----------------------------------------------------------------------------
# Game screen
# ----------------------------------------------------------------------------
class GameView(tk.Frame):
    def __init__(self, master, cfg, on_menu, on_restart):
        super().__init__(master, bg=BG)
        self.cfg, self.on_menu, self.on_restart = cfg, on_menu, on_restart
        self.board = Board(cfg["rows"], cfg["cols"])
        self.alive, self.busy, self.over, self.thinking = True, False, False, False
        self.q = queue.Queue()
        self.node_map, self.tree_board = {}, self.board.copy()
        self.best_col, self.star_done, self.last, self._dots = None, False, None, 0
        self.viewer, self.last_data = None, None

        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)
        self._build_header()
        GradientBar(self, ACCENT, CYAN, height=3).grid(row=1, column=0, columnspan=2, sticky="ew")
        self._build_left()
        self._build_right()

        self._update_scores()
        self._tick_status()
        if cfg["ai_first"]:
            self.start_ai()
        else:
            self._your_turn()

    def destroy(self):
        self.alive = False
        if self.viewer is not None and self.viewer.winfo_exists():
            self.viewer.destroy()
        super().destroy()

    # ---------------- layout ----------------
    def _build_header(self):
        h = tk.Frame(self, bg=BG)
        h.grid(row=0, column=0, columnspan=2, sticky="ew", padx=22, pady=(16, 10))
        logo = tk.Canvas(h, width=64, height=30, bg=BG, highlightthickness=0)
        draw_disc(logo, 15, 15, 13, RED)
        draw_disc(logo, 47, 15, 13, YELLOW)
        logo.pack(side="left")
        tk.Label(h, text="CONNECT 4", bg=BG, fg=TEXT, font=F(17, "bold")).pack(side="left", padx=(8, 18))
        cfg = self.cfg
        for text in ("Alpha-Beta" if cfg["alpha_beta"] else "Minimax", f"K = {cfg['k']}",
                     f"{cfg['rows']} \u00d7 {cfg['cols']}"):
            tk.Label(h, text=text, bg=CARD2, fg=TEXT, font=F(9, "bold"),
                     padx=10, pady=4).pack(side="left", padx=4)
        Button(h, "Menu", self.on_menu, kind="ghost", width=90, height=36).pack(side="right")
        Button(h, "New game", self.on_restart, kind="ghost", width=110, height=36).pack(side="right", padx=8)
        Button(h, "Tree view", self.open_viewer, width=110, height=36).pack(side="right")

    def _build_left(self):
        cfg = self.cfg
        left = tk.Frame(self, bg=BG)
        left.grid(row=2, column=0, sticky="n", padx=(22, 14), pady=(16, 18))

        pill = tk.Frame(left, bg=CARD, highlightbackground=BORDER, highlightthickness=1, padx=14, pady=7)
        pill.pack(anchor="w", pady=(0, 10))
        self.dot = tk.Canvas(pill, width=14, height=14, bg=CARD, highlightthickness=0)
        self.dot_item = self.dot.create_oval(2, 2, 12, 12, fill=RED, outline="")
        self.dot.pack(side="left", padx=(0, 8))
        self.status = tk.Label(pill, text="", bg=CARD, fg=TEXT, font=F(11, "bold"))
        self.status.pack(side="left")

        cell = max(34, min(78, 620 // cfg["cols"], 560 // (cfg["rows"] + 1)))
        self.canvas = BoardCanvas(left, cfg["rows"], cfg["cols"], cell, self.human_click)
        self.canvas.pack()
        self.canvas.refresh(self.board, hover_color=RED)

    def _build_right(self):
        cfg = self.cfg
        right = tk.Frame(self, bg=BG)
        right.grid(row=2, column=1, sticky="nsew", padx=(0, 22), pady=(16, 18))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        players = tk.Frame(right, bg=BG)
        players.grid(row=0, column=0, sticky="ew")
        players.columnconfigure((0, 1), weight=1, uniform="p")
        self.p_human = PlayerCard(players, "You", RED)
        self.p_ai = PlayerCard(players, "Computer", YELLOW)
        self.p_human.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.p_ai.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.share = tk.Canvas(players, height=8, bg=BG, highlightthickness=0)     # score share bar
        self.share.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.share.bind("<Configure>", lambda e: self._draw_share())
        self._h_score = self._a_score = 0

        tiles = tk.Frame(right, bg=BG)
        tiles.grid(row=1, column=0, sticky="ew", pady=10)
        self.tiles = {}
        accents = (YELLOW, ACCENT_H, CYAN, AMBER, GREEN)
        for i, name in enumerate(("Move", "Value", "Nodes", "Time", "Cutoffs")):
            tiles.columnconfigure(i, weight=1, uniform="t")
            t = Tile(tiles, name, accents[i])
            t.grid(row=0, column=i, sticky="ew", padx=3)
            self.tiles[name] = t

        box = card(right)
        box.grid(row=2, column=0, sticky="nsew")
        top = tk.Frame(box, bg=CARD)
        top.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(top, text="Minimax tree", bg=CARD, fg=TEXT, font=F(12, "bold")).pack(side="left")
        tk.Label(top, text="last AI turn \u2022 expand nodes \u2022 click to preview", bg=CARD,
                 fg=MUTED, font=F(9)).pack(side="left", padx=10)

        body = tk.Frame(box, bg=CARD)
        body.pack(fill="both", expand=True, padx=(14, 8))
        cols = ("value", "ab") if cfg["alpha_beta"] else ("value",)
        self.tree = ttk.Treeview(body, columns=("value", "ab"), displaycolumns=cols,
                                 height=9, selectmode="browse")
        self.tree.heading("#0", text="Node", anchor="w")
        self.tree.heading("value", text="Value")
        self.tree.heading("ab", text="\u03b1 / \u03b2")
        self.tree.column("#0", width=210, minwidth=140)
        self.tree.column("value", width=70, anchor="e")
        self.tree.column("ab", width=110, anchor="center")
        for tag, color in (("max", CYAN), ("min", ROSE), ("leaf", MUTED), ("prune", "#64748b")):
            self.tree.tag_configure(tag, foreground=color)
        self.tree.tag_configure("best", foreground=YELLOW, font=F(10, "bold"))
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewOpen>>", lambda e: self._expand_item(self.tree.focus()))
        self.tree.bind("<<TreeviewSelect>>", self._select)

        bottom = tk.Frame(box, bg=CARD)
        bottom.pack(fill="x", padx=14, pady=12)
        self.preview = BoardCanvas(bottom, cfg["rows"], cfg["cols"], 16, mini=True, bg=CARD)
        self.preview.pack(side="left")
        self.preview.refresh(self.board)
        info = tk.Frame(bottom, bg=CARD)
        info.pack(side="left", padx=14, anchor="n")
        self.sel_title = tk.Label(info, text="No node selected", bg=CARD, fg=TEXT,
                                  font=F(11, "bold"), anchor="w")
        self.sel_title.pack(anchor="w")
        self.sel_path = tk.Label(info, text="The board of a node appears here.", bg=CARD,
                                 fg=MUTED, font=F(9), anchor="w", justify="left", wraplength=260)
        self.sel_path.pack(anchor="w", pady=(2, 0))

    def open_viewer(self):
        """Open (or focus) the graphical minimax tree window."""
        if self.viewer is not None and self.viewer.winfo_exists():
            self.viewer.lift()
            self.viewer.focus_force()
            return
        self.viewer = TreeViewer(self.winfo_toplevel(), self.cfg["alpha_beta"],
                                 self.cfg["rows"], self.cfg["cols"])
        if self.last_data:
            self.viewer.set_data(*self.last_data)

    # ---------------- status ----------------
    def set_status(self, text, color, thinking=False):
        self.status.config(text=text)
        self.dot.itemconfig(self.dot_item, fill=color)
        self.thinking = thinking
        self._base_status = text

    def _tick_status(self):
        if not self.alive:
            return
        if self.thinking:
            self._dots = (self._dots + 1) % 4
            self.status.config(text=self._base_status + "." * self._dots)
            self.dot.itemconfig(self.dot_item, fill=YELLOW if self._dots % 2 else mix(YELLOW, CARD, 0.6))
        self.after(320, self._tick_status)

    def _your_turn(self):
        self.busy = False
        self.set_status("Your turn", RED)
        self.p_human.set_active(True, "YOUR TURN")
        self.p_ai.set_active(False)
        self.canvas.refresh(hover_color=RED)

    def _update_scores(self):
        self._h_score = self.board.count_fours(HUMAN)
        self._a_score = self.board.count_fours(AI)
        self.p_human.set_score(self._h_score)
        self.p_ai.set_score(self._a_score)
        self._draw_share()

    def _draw_share(self):
        """Red/yellow bar showing who holds the larger share of connected fours."""
        c = self.share
        c.delete("all")
        w, h = max(c.winfo_width(), 20), 8
        a, b = self._h_score, self._a_score
        rrect(c, 0, 0, w, h, 4, fill=mix(YELLOW, BG, 0.70) if not a + b else YELLOW, outline="")
        if a + b == 0:
            rrect(c, 0, 0, w / 2 + 4, h, 4, fill=mix(RED, BG, 0.70), outline="")
        elif a:
            rrect(c, 0, 0, max(h, w * a / (a + b)), h, 4, fill=RED, outline="")

    # ---------------- input ----------------
    def on_key(self, e):
        if e.char and e.char.lower() == "t":
            return self.open_viewer()
        if e.char and e.char.isdigit():
            idx = int(e.char) - 1
            if 0 <= idx < self.cfg["cols"]:
                self.human_click(idx)

    def human_click(self, col):
        if self.busy or self.over or not self.board.can_play(col):
            return
        self.busy = True
        self.canvas.hover_color = None
        row = self.board.next_row(col)

        def done():
            if not self.alive:
                return
            self.board.drop(col, HUMAN)
            self.last = (row, col)
            self._after_move(HUMAN)
        self.canvas.animate_drop(col, row, RED, done)

    # ---------------- AI turn ----------------
    def start_ai(self):
        self.busy = True
        self.set_status("Computer is thinking", YELLOW, thinking=True)
        self.p_human.set_active(False)
        self.p_ai.set_active(True, "THINKING")
        self.canvas.refresh(hover_color=None)
        snapshot = self.board.copy()
        self.tree_board = snapshot
        k, ab = self.cfg["k"], self.cfg["alpha_beta"]

        def work():
            try:
                self.q.put(choose_move(snapshot, k, ab))
            except Exception as ex:                   # never leave the GUI hanging
                traceback.print_exc()
                self.q.put(ex)
        threading.Thread(target=work, daemon=True).start()
        self.after(40, self._poll)

    def _poll(self):
        if not self.alive:
            return
        try:
            res = self.q.get_nowait()
        except queue.Empty:
            return self.after(40, self._poll)
        self.thinking = False
        if isinstance(res, Exception):
            self.over = True
            self.set_status(f"AI error: {type(res).__name__} (see console)", ROSE)
            return
        self._show_stats(res)
        self.best_col = res.column
        self._fill_tree(res.root)
        self.last_data = (res.root, res.column, self.tree_board)
        if self.viewer is not None and self.viewer.winfo_exists():
            self.viewer.set_data(*self.last_data)
        if self.cfg["print_tree"]:
            name = "Alpha-Beta" if self.cfg["alpha_beta"] else "Minimax"
            print(f"\n===== AI turn | {name} | K={self.cfg['k']} | nodes={res.nodes} "
                  f"| {res.seconds * 1000:.1f} ms =====")
            print(format_tree(res.root, self.cfg["alpha_beta"]))
        self.set_status("Computer plays", YELLOW)
        row = self.board.next_row(res.column)

        def done():
            if not self.alive:
                return
            self.board.drop(res.column, AI)
            self.last = (row, res.column)
            self._after_move(AI)
        self.canvas.animate_drop(res.column, row, YELLOW, done)

    def _show_stats(self, res):
        t = self.tiles
        t["Move"].set(f"col {res.column + 1}", YELLOW)
        t["Value"].set(f"{res.value:g}")
        t["Nodes"].set(f"{res.nodes:,}", CYAN)
        t["Time"].set(f"{res.seconds * 1000:.1f} ms" if res.seconds < 1 else f"{res.seconds:.2f} s")
        if self.cfg["alpha_beta"]:
            n, stack = 0, [res.root]
            while stack:
                x = stack.pop()
                n += 1 if x.pruned_cols else 0
                stack.extend(x.children)
            t["Cutoffs"].set(f"{n:,}", GREEN)
        else:
            t["Cutoffs"].set("n/a", MUTED)

    def _after_move(self, who):
        self._update_scores()
        self.canvas.refresh(self.board, last=self.last)
        if self.board.is_full():
            return self._finish()
        if who == HUMAN:
            self.start_ai()
        else:
            self._your_turn()

    # ---------------- game over ----------------
    def _finish(self):
        self.over = True
        h, a = self.board.count_fours(HUMAN), self.board.count_fours(AI)
        if h > a:
            title, color, glow = "You win!", GREEN, self.board.winning_cells(HUMAN)
        elif a > h:
            title, color, glow = "Computer wins", ROSE, self.board.winning_cells(AI)
        else:
            title, color, glow = "It's a draw", AMBER, set()
        self.set_status("Game over", color)
        self.p_human.set_active(h >= a, "WINNER" if h > a else "DRAW")
        self.p_ai.set_active(a >= h, "WINNER" if a > h else "DRAW")
        self.canvas.refresh(glow=glow, hover_color=None)
        ov = tk.Frame(self.canvas, bg=CARD, highlightbackground=color,
                      highlightthickness=3, padx=34, pady=22)
        GradientBar(ov, color, ACCENT, height=4, bg=CARD).pack(fill="x", pady=(0, 14))
        tk.Label(ov, text=title, bg=CARD, fg=color, font=F(24, "bold")).pack()
        tk.Label(ov, text=f"You {h}   \u2022   Computer {a}", bg=CARD, fg=TEXT,
                 font=F(12)).pack(pady=(4, 16))
        Button(ov, "Play again", self.on_restart, width=200, height=42, bg=CARD).pack(pady=4)
        Button(ov, "Back to menu", self.on_menu, kind="ghost", width=200, height=42, bg=CARD).pack(pady=4)
        ov.place(relx=0.5, rely=0.5, anchor="center")

    # ---------------- tree explorer ----------------
    @staticmethod
    def _label(n):
        if n.move is None:
            return "ROOT  (MAX)"
        return f"col {n.move + 1}  ({'LEAF' if n.leaf else 'MAX' if n.is_max else 'MIN'})"

    def _insert(self, parent, n, path):
        text = self._label(n)
        if n.move is None:
            tag = "max"
        elif parent == self.root_iid and n.move == self.best_col and not self.star_done:
            self.star_done, tag, text = True, "best", "\u2605 " + text
        else:
            tag = "leaf" if n.leaf else "max" if n.is_max else "min"
        ab = f"{fmt_inf(n.alpha)} / {fmt_inf(n.beta)}" if n.alpha is not None else ""
        iid = self.tree.insert(parent, "end", text=text, values=(f"{n.value:g}", ab), tags=(tag,))
        self.node_map[iid] = (n, path)
        if n.children or n.pruned_cols:
            self.tree.insert(iid, "end", text="...")          # lazy placeholder
        return iid

    def _fill_tree(self, root):
        self.tree.delete(*self.tree.get_children())
        self.node_map.clear()
        self.root_iid, self.star_done = "", False
        self.root_iid = self._insert("", root, [])
        self.tree.item(self.root_iid, open=True)
        self._expand_item(self.root_iid)

    def _expand_item(self, iid):
        kids = self.tree.get_children(iid)
        if len(kids) == 1 and self.tree.item(kids[0], "text") == "...":
            self.tree.delete(kids[0])
            n, path = self.node_map[iid]
            for ch in n.children:
                self._insert(iid, ch, path + [ch.move])
            if n.pruned_cols:
                cols = ", ".join(str(c + 1) for c in n.pruned_cols)
                self.tree.insert(iid, "end", text=f"\u2702 pruned cols [{cols}]",
                                 values=("", "\u03b1 \u2265 \u03b2"), tags=("prune",))

    def _select(self, _e):
        iid = self.tree.focus()
        if iid not in self.node_map:
            return
        node, path = self.node_map[iid]
        b = self.tree_board.copy()
        for i, col in enumerate(path):                  # replay moves from the root
            b.drop(col, AI if i % 2 == 0 else HUMAN)
        self.preview.refresh(b)
        self.sel_title.config(text=f"{self._label(node)}   value {node.value:g}")
        self.sel_path.config(text=("Moves: " + "  \u2192  ".join(str(c + 1) for c in path))
                             if path else "Current position (root).")


# ----------------------------------------------------------------------------
# Application shell
# ----------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        pick_font(self)
        self.title("Connect 4  \u2022  Minimax AI")
        self.configure(bg=BG)
        self.minsize(900, 560)
        self._style()
        self.view = None
        self.bind("<Key>", lambda e: hasattr(self.view, "on_key") and self.view.on_key(e))
        self.show_setup()

    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        s.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT,
                    rowheight=25, borderwidth=0, font=F(10))
        s.configure("Treeview.Heading", background=CARD2, foreground=MUTED, relief="flat",
                    font=F(9, "bold"), padding=5)
        s.map("Treeview.Heading", background=[("active", "#27356b")])
        s.map("Treeview", background=[("selected", "#2b3a7a")], foreground=[("selected", "#ffffff")])
        s.configure("Horizontal.TScrollbar", background=CARD2, troughcolor=CARD, bordercolor=CARD,
                    arrowcolor=MUTED, lightcolor=CARD2, darkcolor=CARD2)
        s.configure("Vertical.TScrollbar", background=CARD2, troughcolor=CARD, bordercolor=CARD,
                    arrowcolor=MUTED, lightcolor=CARD2, darkcolor=CARD2)

    def _swap(self, view):
        if self.view is not None:
            self.view.destroy()
        self.view = view
        view.pack(fill="both", expand=True)

    def show_setup(self):
        self._swap(SetupView(self, self.show_game))

    def show_game(self, cfg):
        self._swap(GameView(self, cfg, self.show_setup, lambda: self.show_game(cfg)))


if __name__ == "__main__":
    App().mainloop()
