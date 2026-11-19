"""corridor_core on small hand-checkable grids."""
import math

import numpy as np

from app import corridor_core as cc


def test_free_grid_gives_the_straight_line():
    cost = np.zeros((5, 9))
    ok = np.ones((5, 9), bool)
    r = cc.corridor(cost, ok, (2, 0), (2, 8))
    assert r["path"][0] == (2, 0) and r["path"][-1] == (2, 8) and len(r["path"]) == 9
    assert math.isclose(r["cost"], 8.0) and r["band"][2].all()


def test_path_goes_round_a_wall_and_a_risky_zone():
    ok = np.ones((7, 9), bool)
    ok[0:5, 4] = False                                          # a wall with a gap at the bottom
    cost = np.zeros((7, 9))
    cost[6, :] = 10.0                                           # but the bottom row is dangerous
    r = cc.corridor(cost, ok, (0, 0), (0, 8))
    rows = [c[0] for c in r["path"]]
    assert all(ok[c] for c in r["path"]) and max(rows) == 5     # through the gap at row 5, not along row 6
    assert not r["band"][0:5, 4].any()                          # never through the wall


def test_no_route_and_no_diagonal_squeeze():
    ok = np.ones((3, 3), bool)
    ok[0, 1] = ok[1, 0] = False                                 # (0,0) boxed in except diagonally
    r = cc.corridor(np.zeros((3, 3)), ok, (0, 0), (2, 2))
    assert r["path"] == [] and r["cost"] is None


def test_band_widens_with_margin():
    cost = np.zeros((9, 9))
    ok = np.ones((9, 9), bool)
    a = cc.corridor(cost, ok, (4, 0), (4, 8), margin=0.0)["band"].sum()
    b = cc.corridor(cost, ok, (4, 0), (4, 8), margin=0.3)["band"].sum()
    assert b > a >= 9


def test_straight_cost_counts_risk():
    cost = np.zeros((3, 5)); cost[1, 2] = 4.0
    assert cc.straight_cost(cost, (1, 0), (1, 4)) == 4 + 0.5 * 4 * 2


def test_legs_split_on_emcon_and_risk_and_absorb_slivers():
    path = [(0, j) for j in range(10)]
    state = np.zeros((1, 10), bool); state[0, 4:8] = True       # emitting on cells 4-7
    risk = np.zeros((1, 10)); risk[0, 6] = 0.7                  # one high-risk cell: too short for its own leg
    lg = cc.legs(path, state, risk)
    assert lg == [(0, 3), (4, 7), (8, 9)]


def test_phi():
    assert abs(float(cc.phi(0.0)) - 0.5) < 1e-9 and float(cc.phi(3.0)) > 0.998


# ---- through time (phase 5, part 2) -------------------------------------------------------------------------------
def test_one_layer_matches_the_one_step_search():
    rng = np.random.default_rng(3)
    cost = rng.random((8, 11)) * 3
    ok = np.ones((8, 11), bool); ok[2:7, 5] = False
    a = cc.corridor(cost, ok, (1, 0), (6, 10))
    b = cc.corridor_time(cost[None], ok, (1, 0), (6, 10), layer_len=5.0)
    assert math.isclose(a["cost"], b["cost"]) and [s[:2] for s in b["states"]] == a["path"]
    assert b["waits"] == [] and (b["band"] == a["band"]).all()


def _gate():
    """A wall with one gap at (1, 4); the gap is covered (cost 50) in the first layer only. Layers last 6 cells."""
    ok = np.ones((3, 9), bool); ok[:, 4] = False; ok[1, 4] = True
    costs = np.zeros((2, 3, 9)); costs[0, 1, 4] = 50.0
    return costs, ok


def test_waits_for_the_gap_to_open():
    costs, ok = _gate()
    r = cc.corridor_time(costs, ok, (1, 0), (1, 8), layer_len=6.0, wait_cost=0.2)
    gap = next(s for s in r["states"] if s[:2] == (1, 4))
    assert gap[2] == 1                                          # through the gap once it is clear
    assert r["waits"] and math.isclose(r["cost"], 8 + 3 * 0.2)  # holds at (1, 3) from t=3 to t=6
    assert r["times"] == sorted(r["times"]) and r["states"][-1][:2] == (1, 8)


def test_without_waiting_it_takes_the_gap_while_covered():
    """One label per cell and layer: with waiting off, the search does not mark time by moving to and fro."""
    costs, ok = _gate()
    r = cc.corridor_time(costs, ok, (1, 0), (1, 8), layer_len=6.0, wait=False)
    gap = next(s for s in r["states"] if s[:2] == (1, 4))
    assert gap[2] == 0 and r["waits"] == [] and math.isclose(r["cost"], 8 + 50.0)
    assert [s[2] for s in r["states"]] == [0] * 6 + [1] * 3   # crosses into the second layer at t=6


def test_time_route_refuses_what_cannot_be_reached():
    costs, ok = _gate(); ok[1, 4] = False
    r = cc.corridor_time(costs, ok, (1, 0), (1, 8), layer_len=6.0)
    assert r["states"] == [] and r["cost"] is None
