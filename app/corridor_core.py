"""EM manoeuvre corridors on a cost grid: least-cost path, the corridor band around it, and legs. numpy + heapq only.

A corridor is the set of cells through which a route costs no more than (1 + margin) times the best route. Cost per
cell is supplied by the caller (risk of detection, fix, radar track, loss of own C2, platform limits as impassable);
moving one cell costs its length times (1 + mean cell cost of the two cells), so a cell of zero risk costs only
distance. Dijkstra from both ends gives the best path and, by adding the two cost fields, the band.
"""
from __future__ import annotations

import heapq
import math

import numpy as np

STEPS = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
         (-1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)), (1, 1, math.sqrt(2))]


def phi(x: np.ndarray | float) -> np.ndarray:
    """Standard normal CDF (vectorised): the probability that a margin with unit spread is positive."""
    from math import erf
    v = np.vectorize(lambda z: 0.5 * (1 + erf(z / math.sqrt(2))))
    return v(np.asarray(x, dtype=float))


def dijkstra(cost: np.ndarray, passable: np.ndarray, src: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Least accumulated cost from src to every cell, and each cell's predecessor (flat index, -1 for none)."""
    H, W = cost.shape
    g = np.full((H, W), np.inf)
    pred = np.full(H * W, -1, dtype=np.int64)
    if not passable[src]:
        return g, pred
    g[src] = 0.0
    heap = [(0.0, src[0], src[1])]
    while heap:
        d, i, j = heapq.heappop(heap)
        if d > g[i, j]:
            continue
        ci = cost[i, j]
        for di, dj, ln in STEPS:
            a, b = i + di, j + dj
            if 0 <= a < H and 0 <= b < W and passable[a, b]:
                if di and dj and not (passable[i + di, j] or passable[i, j + dj]):
                    continue                                   # no squeezing diagonally between two blocked cells
                nd = d + ln * (1.0 + 0.5 * (ci + cost[a, b]))
                if nd < g[a, b]:
                    g[a, b] = nd
                    pred[a * W + b] = i * W + j
                    heapq.heappush(heap, (nd, a, b))
    return g, pred


def path_to(pred: np.ndarray, shape: tuple[int, int], src: tuple[int, int], dst: tuple[int, int]) -> list[tuple[int, int]]:
    H, W = shape
    out, k, s = [], dst[0] * W + dst[1], src[0] * W + src[1]
    while k != -1:
        out.append((k // W, k % W))
        if k == s:
            return out[::-1]
        k = int(pred[k])
    return []


def corridor(cost: np.ndarray, passable: np.ndarray, start: tuple[int, int], goal: tuple[int, int],
             margin: float = 0.15) -> dict:
    """Best path, its cost, and the band of cells on routes within (1 + margin) of it."""
    gs, pred = dijkstra(cost, passable, start)
    if not np.isfinite(gs[goal]):
        return {"path": [], "cost": None, "band": np.zeros(cost.shape, bool)}
    gg, _ = dijkstra(cost, passable, goal)
    best = float(gs[goal])
    through = gs + gg                                          # best route forced through each cell
    band = np.isfinite(through) & (through <= best * (1 + margin))
    return {"path": path_to(pred, cost.shape, start, goal), "cost": best, "band": band}


def straight_cost(cost: np.ndarray, start: tuple[int, int], goal: tuple[int, int]) -> float:
    """Cost of the direct line (for comparison), cell by cell along a Bresenham-style walk."""
    n = max(abs(goal[0] - start[0]), abs(goal[1] - start[1]), 1)
    cells = [(round(start[0] + (goal[0] - start[0]) * k / n), round(start[1] + (goal[1] - start[1]) * k / n)) for k in range(n + 1)]
    tot = 0.0
    for (i, j), (a, b) in zip(cells, cells[1:]):
        ln = math.sqrt(2) if (a != i and b != j) else 1.0
        tot += ln * (1.0 + 0.5 * (cost[i, j] + cost[a, b]))
    return float(tot)


def legs(path: list[tuple[int, int]], state: np.ndarray, risk: np.ndarray, min_cells: int = 2) -> list[tuple[int, int]]:
    """Split a path into legs where the EMCON state or the risk class (low < 0.1 <= medium < 0.5 <= high) changes.
    Returns (first, last) indices into the path; legs shorter than min_cells join the previous leg."""
    if not path:
        return []
    cls = lambda r: 0 if r < 0.1 else 1 if r < 0.5 else 2          # noqa: E731
    key = [(bool(state[c]), cls(float(risk[c]))) for c in path]
    out, a = [], 0
    for k in range(1, len(path) + 1):
        if k == len(path) or key[k] != key[a]:
            if out and k - a < min_cells:
                out[-1] = (out[-1][0], k - 1)
            else:
                out.append((a, k - 1))
            a = k
    merged = [out[0]]
    for lg in out[1:]:                                         # neighbours that ended up alike become one leg
        if key[lg[0]] == key[merged[-1][0]]:
            merged[-1] = (merged[-1][0], lg[1])
        else:
            merged.append(lg)
    return merged
