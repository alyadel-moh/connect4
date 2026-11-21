import time
from board import AI, HUMAN
INF = float("inf")


def evaluate(board):
    return board.count_fours(AI) - board.count_fours(HUMAN)

class Node:
    __slots__ = ("move", "is_max", "depth", "value", "leaf",
                 "alpha", "beta", "pruned_cols", "children")

    def __init__(self, move, is_max, depth):
        self.move = move              # column that led here (None at root)
        self.is_max = is_max
        self.depth = depth
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

def _search(board,depth,is_max,alpha,beta,node,ctx):
    ctx.nodes += 1
    moves = board.valid_moves()

    if depth == 0 or not moves:
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

def choose_move(board, k, use_alpha_beta):
    ctx = _Ctx(use_alpha_beta)
    root = Node(None, True, 0)
    t0 = time.perf_counter()
    value = _search(board.copy(), k, True, -INF, INF, root, ctx)
    elapsed = time.perf_counter() - t0

    best_child = None                                  # first child with best value
    for ch in root.children:
        if best_child is None or ch.value > best_child.value:
            best_child = ch
    return SearchResult(best_child.move, root, ctx.nodes, elapsed, value) # type: ignore

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
        kind = "MAX" if n.is_max else "MIN"
        col = "ROOT" if n.move is None else f"col {n.move + 1}"
        if n.leaf:
            text = f"{col}  LEAF  heuristic = {_fmt(n.value)}"
        else:
            text = f"{col}  {kind}  value = {_fmt(n.value)}"
            if show_ab:
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
