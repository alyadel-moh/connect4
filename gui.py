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
Keyboard: press 1..N to drop a disc in that column.
"""
import queue
import threading
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
    """Glossy game disc made of layered ovals."""
    dark, light = mix(color, "#000000", 0.30), mix(color, "#ffffff", 0.55)
    c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=dark, outline="", tags=tags)
    r2 = r * 0.88
    c.create_oval(cx - r2, cy - r2, cx + r2, cy + r2, fill=color, outline="", tags=tags)
    r3 = r * 0.58
    c.create_oval(cx - r3, cy - r3, cx + r3, cy + r3, fill=color, outline=dark,
                  width=max(1, int(r / 10)), tags=tags)
    c.create_oval(cx - r * 0.55, cy - r * 0.62, cx - r * 0.12, cy - r * 0.34,
                  fill=light, outline="", tags=tags)


# ----------------------------------------------------------------------------
# Custom widgets (canvas based so they can be rounded / animated)
# ----------------------------------------------------------------------------
class Button(tk.Canvas):
    def __init__(self, master, text, command, kind="primary", width=150, height=40, bg=BG):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._label, self._cmd, self.kind = text, command, kind
        self.bw, self.bh, self._hot = width, height, False
        self._draw()
        self.bind("<Enter>", lambda e: self._set_hot(True))
        self.bind("<Leave>", lambda e: self._set_hot(False))
        self.bind("<ButtonRelease-1>", self._release)

    def _set_hot(self, v):
        self._hot = v
        self._draw()

    def _release(self, e):
        if 0 <= e.x <= self.bw and 0 <= e.y <= self.bh and self._cmd:
            self._cmd()

    def _draw(self):
        self.delete("all")
        if self.kind == "primary":
            fill, outline, fg = (ACCENT_H if self._hot else ACCENT), "", "#ffffff"
        else:
            fill, outline, fg = ("#27356b" if self._hot else CARD2), BORDER, TEXT
        rrect(self, 1, 1, self.bw - 1, self.bh - 1, self.bh / 2.4, fill=fill, outline=outline)
        self.create_text(self.bw / 2, self.bh / 2, text=self._label, fill=fg, font=F(11, "bold"))


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
        self.animating, self._phase = False, 0
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
            if glow:
                self._pulse()
        if hover_color != "keep":
            self.hover_color = hover_color
        self._redraw()

    def _pulse(self):
        if not self._glow:
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
        W, cell = self.W, self.cell
        if not self.mini:
            rrect(c, self.M, self.T + 6, W - self.M, self.body_bottom + 6, 22,
                  fill="#050823", outline="")
        rrect(c, self.M, self.T, W - self.M, self.body_bottom, 8 if self.mini else 22,
              fill=BOARD, outline=BOARD_D, width=1 if self.mini else 3)
        if self.interactive and self.hover is not None and self.hover_color:
            x1 = self.gx + self.hover * cell + 3
            rrect(c, x1, self.T + 5, x1 + cell - 6, self.body_bottom - 5, 14,
                  fill=BOARD_L, outline="")
        b = self._board
        hr = cell * (0.46 if self.mini else 0.435)
        for r in range(self.rows):
            for col in range(self.cols):
                cx, cy = self._cx(col), self._cy(r)
                c.create_oval(cx - hr, cy - hr, cx + hr, cy + hr, fill=HOLE,
                              outline=HOLE_RIM, width=1 if self.mini else 2)
                v = b.grid[r][col] if b else 0
                if v:
                    draw_disc(c, cx, cy, self.R, RED if v == HUMAN else YELLOW)
                if (r, col) in self._glow:
                    c.create_oval(cx - self.R - 3, cy - self.R - 3, cx + self.R + 3,
                                  cy + self.R + 3, outline="#ffffff" if self._phase else "#a5b4fc",
                                  width=4 if self._phase else 2)
                if self._last == (r, col) and not self.mini:
                    k = self.R * 0.22
                    c.create_oval(cx - k, cy - k, cx + k, cy + k, outline="#ffffff", width=2)
        if self.interactive:
            for col in range(self.cols):
                on = col == self.hover
                c.create_text(self._cx(col), self.body_bottom + self.M + self.N / 2 + 1,
                              text=str(col + 1), fill=TEXT if on else MUTED,
                              font=F(10, "bold"))
            if self.hover is not None and self.hover_color:
                draw_disc(c, self._cx(self.hover), self.T * 0.5, self.R, self.hover_color)

    def animate_drop(self, col, row, color, done):
        """Bouncing drop from the top strip to (row, col); then done()."""
        self.animating = True
        self._redraw()
        cx, target = self._cx(col), self._cy(row)
        y, v, bounces = [self.T * 0.5], [3.0], [0]
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
    def __init__(self, master, name, color):
        super().__init__(master, bg=CARD, highlightbackground=BORDER,
                         highlightthickness=2, padx=12, pady=10)
        self.color = color
        icon = tk.Canvas(self, width=40, height=40, bg=CARD, highlightthickness=0)
        draw_disc(icon, 20, 20, 17, color)
        icon.grid(row=0, column=0, rowspan=2, padx=(0, 10))
        tk.Label(self, text=name, bg=CARD, fg=TEXT, font=F(12, "bold")).grid(row=0, column=1, sticky="w")
        tk.Label(self, text="connected fours", bg=CARD, fg=MUTED, font=F(9)).grid(row=1, column=1, sticky="w")
        self.score = tk.Label(self, text="0", bg=CARD, fg=TEXT, font=F(26, "bold"))
        self.score.grid(row=0, column=2, rowspan=2, padx=(14, 0))
        self.columnconfigure(1, weight=1)

    def set_score(self, n):
        self.score.config(text=str(n))

    def set_active(self, on):
        self.config(highlightbackground=self.color if on else BORDER)


class Tile(tk.Frame):
    def __init__(self, master, title):
        super().__init__(master, bg=CARD, highlightbackground=BORDER, highlightthickness=1,
                         padx=8, pady=7)
        tk.Label(self, text=title.upper(), bg=CARD, fg=MUTED, font=F(8, "bold")).pack(anchor="w")
        self.value = tk.Label(self, text="-", bg=CARD, fg=TEXT, font=F(13, "bold"))
        self.value.pack(anchor="w")

    def set(self, text, color=TEXT):
        self.value.config(text=text, fg=color)


def fmt_inf(x):
    return "-inf" if x == -INF else "+inf" if x == INF else f"{x:g}"


# ----------------------------------------------------------------------------
# Setup screen
# ----------------------------------------------------------------------------
class SetupView(tk.Frame):
    def __init__(self, master, on_start):
        super().__init__(master, bg=BG)
        self.on_start = on_start
        self.algo = tk.StringVar(value="alphabeta")
        self.k = tk.IntVar(value=4)
        self.rows = tk.IntVar(value=6)
        self.cols = tk.IntVar(value=7)
        self.first = tk.StringVar(value="human")
        self.print_tree = tk.BooleanVar(value=True)

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(expand=True, padx=50, pady=30)

        logo = tk.Canvas(wrap, width=240, height=64, bg=BG, highlightthickness=0)
        for i in range(4):
            draw_disc(logo, 30 + i * 60, 32, 26, RED if i % 2 == 0 else YELLOW)
        logo.pack()
        tk.Label(wrap, text="CONNECT 4", bg=BG, fg=TEXT, font=F(30, "bold")).pack(pady=(10, 0))
        tk.Label(wrap, text="Minimax AI  \u2022  Human vs Computer", bg=BG, fg=MUTED,
                 font=F(11)).pack(pady=(0, 20))

        box = card(wrap)
        box.pack(fill="x")
        self._row(box, "Algorithm", "How the computer searches",
                  lambda p: Segmented(p, [("Minimax", "minimax"), ("Alpha-Beta", "alphabeta")], self.algo))
        self._row(box, "Search depth (K)", "Levels explored before the cutoff",
                  lambda p: Stepper(p, self.k, 1, 10))
        self._row(box, "Board size", "Rows \u00d7 columns (min 6 \u00d7 7)", self._size_widget)
        self._row(box, "First move", "Who drops the first disc",
                  lambda p: Segmented(p, [("You", "human"), ("Computer", "ai")], self.first))
        self._row(box, "Print tree to console", "Readable minimax tree every AI turn",
                  lambda p: Toggle(p, self.print_tree), last=True)

        self.est = tk.Label(wrap, text="", bg=BG, fg=MUTED, font=F(10))
        self.est.pack(pady=(14, 4))
        Button(wrap, "Start game  \u25B6", self._start, width=280, height=50).pack(pady=(6, 8))
        tk.Label(wrap, text="Tip: press the number keys 1\u20137 to drop a disc", bg=BG,
                 fg=MUTED, font=F(9)).pack()

        for v in (self.algo, self.k, self.cols):
            v.trace_add("write", lambda *a: self._estimate())
        self._estimate()

    def _size_widget(self, parent):
        f = tk.Frame(parent, bg=CARD)
        Stepper(f, self.rows, 6, 12, width=112).pack(side="left")
        tk.Label(f, text="\u00d7", bg=CARD, fg=MUTED, font=F(12, "bold")).pack(side="left", padx=8)
        Stepper(f, self.cols, 7, 12, width=112).pack(side="left")
        return f

    def _row(self, parent, title, desc, factory, last=False):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=24, pady=12)
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

        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()
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

    def _build_left(self):
        cfg = self.cfg
        left = tk.Frame(self, bg=BG)
        left.grid(row=1, column=0, sticky="n", padx=(22, 14), pady=(0, 18))

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
        right.grid(row=1, column=1, sticky="nsew", padx=(0, 22), pady=(0, 18))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        players = tk.Frame(right, bg=BG)
        players.grid(row=0, column=0, sticky="ew")
        players.columnconfigure((0, 1), weight=1, uniform="p")
        self.p_human = PlayerCard(players, "You", RED)
        self.p_ai = PlayerCard(players, "Computer", YELLOW)
        self.p_human.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.p_ai.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        tiles = tk.Frame(right, bg=BG)
        tiles.grid(row=1, column=0, sticky="ew", pady=10)
        self.tiles = {}
        for i, name in enumerate(("Move", "Value", "Nodes", "Time", "Cutoffs")):
            tiles.columnconfigure(i, weight=1, uniform="t")
            t = Tile(tiles, name)
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
        self.after(320, self._tick_status)

    def _your_turn(self):
        self.busy = False
        self.set_status("Your turn", RED)
        self.p_human.set_active(True)
        self.p_ai.set_active(False)
        self.canvas.refresh(hover_color=RED)

    def _update_scores(self):
        self.p_human.set_score(self.board.count_fours(HUMAN))
        self.p_ai.set_score(self.board.count_fours(AI))

    # ---------------- input ----------------
    def on_key(self, e):
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
        self.p_ai.set_active(True)
        self.canvas.refresh(hover_color=None) # type: ignore
        snapshot = self.board.copy()
        self.tree_board = snapshot
        k, ab = self.cfg["k"], self.cfg["alpha_beta"]
        threading.Thread(target=lambda: self.q.put(choose_move(snapshot, k, ab)),
                         daemon=True).start()
        self.after(40, self._poll)

    def _poll(self):
        if not self.alive:
            return
        try:
            res = self.q.get_nowait()
        except queue.Empty:
            return self.after(40, self._poll)
        self.thinking = False
        self._show_stats(res)
        self.best_col = res.column
        self._fill_tree(res.root)
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
        self.canvas.refresh(self.board, last=self.last) # type: ignore
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
        self.p_human.set_active(h >= a)
        self.p_ai.set_active(a >= h)
        self.canvas.refresh(glow=glow, hover_color=None) # type: ignore
        ov = tk.Frame(self.canvas, bg=CARD, highlightbackground=color,
                      highlightthickness=3, padx=34, pady=22)
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
        self.bind("<Key>", lambda e: hasattr(self.view, "on_key") and self.view.on_key(e)) # type: ignore
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
