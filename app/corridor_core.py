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


# ---- corridors through time (phase 5, part 2) ---------------------------------------------------------------------
def dijkstra_time(costs: np.ndarray, passable: np.ndarray, src: tuple[int, int], layer_len: float,
                  wait: bool = True, wait_cost: float = 1.0):
    """Least cost through space and time. costs is (K, H, W): the cost grid for each time layer; layer k holds from
    time k * layer_len to (k + 1) * layer_len, the last layer for ever. Time is counted in cell-lengths of travel (one
    orthogonal step takes 1.0, a diagonal step sqrt 2), so layer_len is the layer's duration over the time to cross one
    cell. A move is priced with the layer the unit leaves in and the layer it arrives in. With wait, the unit may hold
    in a cell until the next layer starts, at (wait_cost + the cell's cost in that layer) per unit of time held.
    Returns g (K, H, W), the arrival time tau (K, H, W) and the predecessor of each state (flat index, -1 for none).
    Labels keep the cheapest arrival per (cell, layer), the screening simplification that keeps this a plain Dijkstra."""
    K, H, W = costs.shape
    g = np.full((K, H, W), np.inf)
    tau = np.full((K, H, W), np.inf)
    pred = np.full(K * H * W, -1, dtype=np.int64)
    if not passable[src]:
        return g, tau, pred
    g[0][src] = 0.0
    tau[0][src] = 0.0
    heap = [(0.0, 0, src[0], src[1])]
    while heap:
        d, k, i, j = heapq.heappop(heap)
        if d > g[k, i, j]:
            continue
        t = tau[k, i, j]
        ci = costs[k, i, j]
        here = (k * H + i) * W + j
        for di, dj, ln in STEPS:
            a, b = i + di, j + dj
            if 0 <= a < H and 0 <= b < W and passable[a, b]:
                if di and dj and not (passable[i + di, j] or passable[i, j + dj]):
                    continue
                t2 = t + ln
                k2 = min(K - 1, int(t2 // layer_len))
                nd = d + ln * (1.0 + 0.5 * (ci + costs[k2, a, b]))
                if nd < g[k2, a, b]:
                    g[k2, a, b], tau[k2, a, b] = nd, t2
                    pred[(k2 * H + a) * W + b] = here
                    heapq.heappush(heap, (nd, k2, a, b))
        if wait and k < K - 1:
            t2 = (k + 1) * layer_len
            nd = d + (t2 - t) * (wait_cost + ci)
            if nd < g[k + 1, i, j]:
                g[k + 1, i, j], tau[k + 1, i, j] = nd, t2
                pred[((k + 1) * H + i) * W + j] = here
                heapq.heappush(heap, (nd, k + 1, i, j))
    return g, tau, pred


def corridor_time(costs: np.ndarray, passable: np.ndarray, start: tuple[int, int], goal: tuple[int, int],
                  layer_len: float, margin: float = 0.15, wait: bool = True, wait_cost: float = 1.0) -> dict:
    """Best route through space and time, as states (row, col, layer) with arrival times, and the band. The band uses
    each cell's cost in the layer the unit would first reach it (the time a planner would be there), so it reads like
    the one-step band; the route itself is the exact time-layered search."""
    K, H, W = costs.shape
    g, tau, pred = dijkstra_time(costs, passable, start, layer_len, wait, wait_cost)
    gk = g[:, goal[0], goal[1]]
    if not np.isfinite(gk).any():
        return {"states": [], "times": [], "cost": None, "band": np.zeros((H, W), bool), "waits": []}
    kbest = int(np.argmin(gk))
    states, s = [], (kbest * H + goal[0]) * W + goal[1]
    while s != -1:
        k, r = divmod(int(s), H * W)
        states.append((r // W, r % W, k))
        s = int(pred[s])
    states.reverse()
    times = [float(tau[k, i, j]) for i, j, k in states]
    waits = [n for n in range(1, len(states)) if states[n][:2] == states[n - 1][:2]]
    first = np.argmin(np.where(np.isfinite(g), g, np.inf), axis=0)              # layer of each cell's cheapest label
    first = np.where(np.isfinite(g).any(axis=0), first, K - 1)
    eff = np.take_along_axis(costs, first[None], axis=0)[0]
    band = corridor(eff, passable, start, goal, margin)["band"]
    for i, j, _ in states:
        band[i, j] = True
    return {"states": states, "times": times, "cost": float(gk[kbest]), "band": band, "waits": waits}
