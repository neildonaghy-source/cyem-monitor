"""Unit tests for app/coverage_core.py on synthetic terrain."""
import math

import numpy as np

from app.coverage_core import Coverage, polar_prx, radial_points, sector_atten_db
from app.link_core import fspl_db, haversine_m

AZ = np.arange(36) * 10.0
DIST = np.linspace(0, 10_000, 201)


def _flat(h=0.0):
    return np.full((len(AZ), len(DIST)), h)


def test_radial_points_distance_and_bearing():
    la, lo = radial_points(51.0, -1.0, np.array([0.0, 90.0]), np.array([0.0, 10_000.0]))
    assert math.isclose(haversine_m(51.0, -1.0, la[0, 1], lo[0, 1]), 10_000, rel_tol=1e-6)
    assert la[0, 1] > 51.0 and math.isclose(lo[0, 1], -1.0, abs_tol=1e-9)     # due north
    assert lo[1, 1] > -1.0                                                     # due east


def test_flat_open_terrain_matches_free_space():
    prx = polar_prx(_flat(), DIST, AZ, h_tx_agl=100, h_rx_agl=10, f_hz=150e6, eirp_dbm=np.full(len(AZ), 40.0))
    i = 100   # 5 km
    assert math.isclose(prx[0, i], 40 - fspl_db(DIST[i], 150e6), abs_tol=0.05)
    assert np.isnan(prx[0, 0])


def test_ridge_shadows_only_its_radial():
    h = _flat()
    h[0, 80:83] = 150.0                                   # ridge at ~4 km on radial 0 only
    prx = polar_prx(h, DIST, AZ, h_tx_agl=20, h_rx_agl=2, f_hz=450e6, eirp_dbm=np.full(len(AZ), 40.0))
    assert prx[0, 150] < prx[1, 150] - 15                  # behind the ridge vs open radial
    assert math.isclose(prx[0, 50], prx[1, 50], abs_tol=0.5)   # in front of the ridge unaffected


def test_sector_pattern():
    off = np.array([0.0, 32.5, 90.0, 180.0])
    a = sector_atten_db(off, 65)
    assert a[0] == 0 and math.isclose(a[1], 3.0, abs_tol=1e-9) and math.isclose(a[2], 23.006, abs_tol=0.01) and a[3] == 25


def test_pack_lookup_area_png():
    prx = polar_prx(_flat(), DIST, AZ, h_tx_agl=100, h_rx_agl=10, f_hz=150e6, eirp_dbm=np.full(len(AZ), 40.0))
    cov = Coverage(51.0, -1.0, float(DIST[1]), len(AZ), prx)
    back = Coverage.unpack(cov.pack())
    assert np.nanmax(np.abs(back.prx - prx)) <= 0.26
    la, lo = radial_points(51.0, -1.0, np.array([0.0]), np.array([5000.0]))
    assert math.isclose(back.level_dbm(float(la[0, 0]), float(lo[0, 0])), prx[0, 100], abs_tol=0.3)
    assert back.level_dbm(52.0, -1.0) is None                                  # outside radius
    assert math.isclose(cov.area_km2(-200), math.pi * 10 ** 2, rel_tol=0.05)   # everything covered
    url, bounds = cov.render_png(-110, 10, px=64)
    assert url.startswith("data:image/png;base64,") and bounds[0][0] < 51.0 < bounds[1][0]



def test_two_ridges_cost_more_than_one():
    one, two = _flat(), _flat()
    one[0, 80:83] = 150.0
    two[0, 80:83] = 150.0
    two[0, 120:123] = 150.0                                  # second ridge further out
    kw = dict(h_tx_agl=20, h_rx_agl=2, f_hz=450e6, eirp_dbm=np.full(len(AZ), 40.0))
    p1, p2 = polar_prx(one, DIST, AZ, **kw), polar_prx(two, DIST, AZ, **kw)
    assert p2[0, 180] < p1[0, 180] - 1.5                    # Bullington sees the second ridge
