import time
from board import AI, HUMAN

INF = float("inf")

# ---------------------------------------------------------------------------
# Heuristic
# ---------------------------------------------------------------------------
# weight by number of own discs in a window the opponent hasn't blocked
WINDOW_W = {0: 0, 1: 1, 2: 4, 3: 16, 4: 100}


def evaluate(board):
    g, score = board.grid, 0
    for w in board.windows:
        a = h = 0
        for r, c in w:
            v = g[r][c]
            if v == AI:
                a += 1
            elif v == HUMAN:
                h += 1
        if a and h:            # blocked for both players, worth nothing
            continue
        score += WINDOW_W[a] - WINDOW_W[h]
    mid = board.cols // 2      # small preference for the center column
    for r in range(board.rows):
        if g[r][mid] == AI:
            score += 3
        elif g[r][mid] == HUMAN:
            score -= 3
    return score


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
class Node:
    __slots__ = ("move", "is_max", "depth", "value", "leaf", "alpha", "beta",
                 "pruned_cols", "children", "kind", "prob")

    def __init__(self, move, is_max, depth, kind=None, prob=None):
        self.move = move              # column that led here (None at root)
        self.is_max = is_max          # whose turn it is at this node
        self.depth = depth            # level in the drawn tree
        self.kind = kind or ("max" if is_max else "min")   # max / min / chance
        self.prob = prob              # probability of the edge from a chance parent
        self.value = None
        self.leaf = False
        self.alpha = None             # alpha/beta on entry (pruning mode only)
        self.beta = None
        self.pruned_cols = []         # sibling columns skipped by a cutoff
        self.children = []


class SearchResult:
    def __init__(self, column, root, nodes, seconds, value):
        self.column, self.root = column, root
        self.nodes, self.seconds, self.value = nodes, seconds, value


class _Ctx:
    def __init__(self, prune):
        self.prune = prune
        self.nodes = 0


# ---------------------------------------------------------------------------
# Chance model
# ---------------------------------------------------------------------------
def outcomes(board, col):
    """[(landing_col, probability), ...] for a disc aimed at `col`."""
    nbrs = [c for c in (col - 1, col + 1) if board.can_play(c)]
    if not nbrs:
        return [(col, 1.0)]
    side = 0.2 if len(nbrs) == 2 else 0.4
    return [(col, 0.6)] + [(c, side) for c in nbrs]


# ---------------------------------------------------------------------------
# Minimax / Alpha-Beta
# ---------------------------------------------------------------------------
def _search(board, depth, is_max, alpha, beta, node, ctx):
    ctx.nodes += 1
    moves = board.valid_moves()

    if depth == 0 or not moves:                       # cutoff: score the board
        node.leaf = True
        node.value = evaluate(board)
        return node.value

    if ctx.prune:
        node.alpha, node.beta = alpha, beta

    piece = AI if is_max else HUMAN
    best = -INF if is_max else INF

    for i, col in enumerate(moves):
        child = Node(col, not is_max, node.depth + 1)
        node.children.append(child)
        nxt = board.copy()
        nxt.drop(col, piece)
        v = _search(nxt, depth - 1, not is_max, alpha, beta, child, ctx)
        if is_max:
            best = max(best, v)
            alpha = max(alpha, best)
        else:
            best = min(best, v)
            beta = min(beta, best)
        if ctx.prune and alpha >= beta:               # cutoff
            node.pruned_cols = moves[i + 1:]
            break
    node.value = best
    return best


# ---------------------------------------------------------------------------
# Expected minimax
# ---------------------------------------------------------------------------
def _search_expected(board, depth, is_max, node, ctx):
    ctx.nodes += 1
    moves = board.valid_moves()

    if depth == 0 or not moves:
        node.leaf = True
        node.value = evaluate(board)
        return node.value

    piece = AI if is_max else HUMAN
    best = -INF if is_max else INF

    for col in moves:
        if is_max:                                     # AI aims: the disc may slip
            chance = Node(col, True, node.depth + 1, kind="chance")
            node.children.append(chance)
            ctx.nodes += 1
            total = 0.0
            for land, p in outcomes(board, col):       # where it may really land
                child = Node(land, False, chance.depth + 1, prob=p)
                chance.children.append(child)
                nxt = board.copy()
                nxt.drop(land, AI)
                total += p * _search_expected(nxt, depth - 1, False, child, ctx)
            chance.value = total                       # weighted average
            best = max(best, total)
        else:                                          # human: lands exactly where clicked
            child = Node(col, True, node.depth + 1)
            node.children.append(child)
            nxt = board.copy()
            nxt.drop(col, HUMAN)
            best = min(best, _search_expected(nxt, depth - 1, True, child, ctx))

    node.value = best
    return best


# ---------------------------------------------------------------------------
# Entry point used by the GUI
# ---------------------------------------------------------------------------
def choose_move(board, k, use_alpha_beta, expected=False):
    ctx = _Ctx(use_alpha_beta and not expected)
    root = Node(None, True, 0)
    t0 = time.perf_counter()
    if expected:
        value = _search_expected(board.copy(), k, True, root, ctx)
    else:
        value = _search(board.copy(), k, True, -INF, INF, root, ctx)
    elapsed = time.perf_counter() - t0

    best_child = None                                  # first child with best value
    for ch in root.children:
        if best_child is None or ch.value > best_child.value:
            best_child = ch
    return SearchResult(best_child.move, root, ctx.nodes, elapsed, value)  # type: ignore


# ---------------------------------------------------------------------------
# Console tree printing
# ---------------------------------------------------------------------------
def _fmt(x):
    if x == INF:
        return "+inf"
    if x == -INF:
        return "-inf"
    return f"{x:g}"


def format_tree(root, show_ab):
    """Readable indented tree. Columns are shown 1-indexed."""
    lines = []

    def rec(n, prefix, is_last):
        branch = "" if n.move is None else ("`-- " if is_last else "|-- ")
        col = "ROOT" if n.move is None else f"col {n.move + 1}"
        if n.prob is not None:
            col += f" (p={n.prob:g})"
        if n.kind == "chance":
            text = f"{col}  CHANCE  expected = {_fmt(n.value)}"
        else:
            kind = "MAX" if n.is_max else "MIN"
            if n.leaf:
                text = f"{col}  LEAF  heuristic = {_fmt(n.value)}"
            else:
                text = f"{col}  {kind}  value = {_fmt(n.value)}"
                if show_ab and n.alpha is not None:
                    text += f"   [alpha={_fmt(n.alpha)}, beta={_fmt(n.beta)}]"
        lines.append(prefix + branch + text)
        child_prefix = prefix + ("" if n.move is None else ("    " if is_last else "|   "))
        for i, ch in enumerate(n.children):
            last = (i == len(n.children) - 1) and not n.pruned_cols
            rec(ch, child_prefix, last)
        if n.pruned_cols:
            cols = ", ".join(str(c + 1) for c in n.pruned_cols)
            lines.append(f"{child_prefix}`-- x PRUNED columns [{cols}] (alpha >= beta)")

    rec(root, "", True)
    return "\n".join(lines)