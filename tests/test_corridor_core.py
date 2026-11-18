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
