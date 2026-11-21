"""
board.py - Connect 4 game state and rules

"""

EMPTY, HUMAN, AI = 0, 1, 2

_WINDOW_CACHE = {}


def _build_windows(rows, cols):
    """All 4-cell lines (horizontal, vertical, both diagonals) as ((r,c),...)."""
    windows = []
    for r in range(rows):
        for c in range(cols):
            for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
                er, ec = r + 3 * dr, c + 3 * dc
                if 0 <= er < rows and 0 <= ec < cols:
                    windows.append(tuple((r + i * dr, c + i * dc) for i in range(4)))
    return tuple(windows)


class Board:
    def __init__(self, rows=6, cols=7):
        if rows < 6 or cols < 7:
            raise ValueError("Board must be at least 6 rows x 7 columns")
        self.rows, self.cols = rows, cols
        self.grid = [[EMPTY] * cols for _ in range(rows)]
        self.heights = [0] * cols                      # discs per column
        if (rows, cols) not in _WINDOW_CACHE:
            _WINDOW_CACHE[(rows, cols)] = _build_windows(rows, cols)
        self.windows = _WINDOW_CACHE[(rows, cols)]

    # ---- state helpers -------------------------------------------------
    def copy(self):
        b = Board.__new__(Board)
        b.rows, b.cols = self.rows, self.cols
        b.grid = [row[:] for row in self.grid]
        b.heights = self.heights[:]
        b.windows = self.windows
        return b

    def next_row(self, col):
        """Row index where a disc dropped in `col` would land."""
        return self.rows - 1 - self.heights[col]

    def can_play(self, col):
        return 0 <= col < self.cols and self.heights[col] < self.rows

    def valid_moves(self):
        return [c for c in range(self.cols) if self.heights[c] < self.rows]

    def is_full(self):
        return sum(self.heights) == self.rows * self.cols

    def drop(self, col, piece):
        """Drop `piece` into `col`; returns the row it lands in."""
        row = self.next_row(col)
        self.grid[row][col] = piece
        self.heights[col] += 1
        return row

    # ---- scoring -------------------------------------------------------
    def count_fours(self, piece):
        g = self.grid
        return sum(1 for w in self.windows if all(g[r][c] == piece for r, c in w))

    def winning_cells(self, piece):
        g = self.grid
        cells = set()
        for w in self.windows:
            if all(g[r][c] == piece for r, c in w):
                cells.update(w)
        return cells
