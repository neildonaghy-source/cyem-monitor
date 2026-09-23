"""Unit tests for app/link_core.py against textbook reference values."""
import math

from app.link_core import (analyse, deygout_loss_db, earth_bulge_m, fresnel_r1_m, fspl_db, gc_points, haversine_m,
                           knife_edge_loss_db, rain_a001_db, rain_a_p_db, rain_availability_pct, rain_specific_db_km,
                           sample_count)


def test_fspl_reference():
    assert math.isclose(fspl_db(1000, 1e9), 92.44, abs_tol=0.01)
    assert math.isclose(fspl_db(10_000, 18e9) - fspl_db(1000, 18e9), 20.0, abs_tol=1e-6)


def test_fresnel_and_bulge_rules_of_thumb():
    # F1 = 17.32 sqrt(d1 d2 / (f D)), km/GHz -> 8.66 m at mid-path of 10 km at 10 GHz
    assert math.isclose(fresnel_r1_m(5000, 5000, 10e9), 8.66, abs_tol=0.02)
    # bulge = d1 d2 / (12.74 k), km -> 36.8 m at mid-path of 50 km, k = 4/3
    assert math.isclose(earth_bulge_m(25_000, 25_000), 36.8, abs_tol=0.1)
    assert earth_bulge_m(0, 50_000) == 0


def test_knife_edge_values():
    assert knife_edge_loss_db(-1.0) == 0.0
    assert math.isclose(knife_edge_loss_db(0.0), 6.0, abs_tol=0.1)     # grazing: ~6 dB
    assert 13 < knife_edge_loss_db(1.0) < 14.5


def test_path_sampling():
    d = haversine_m(50.84, -0.78, 51.06, -1.31)
    assert 40_000 < d < 50_000
    pts = gc_points(50.84, -0.78, 51.06, -1.31, 5)
    assert pts[0] == (50.84, -0.78) or math.isclose(pts[0][0], 50.84, abs_tol=1e-9)
    assert math.isclose(pts[-1][1], -1.31, abs_tol=1e-9)
    assert sample_count(100) == 4 and sample_count(1e6) == 1500


def _flat(D=10_000, n=201, h=0.0):
    return [D * i / (n - 1) for i in range(n)], [h] * n


def test_clear_flat_path_budget():
    dist, terr = _flat()
    r = analyse(dist, terr, h_a_agl=30, h_b_agl=30, f_hz=1e9, ptx_dbm=30, gtx_dbi=10, grx_dbi=10, sens_dbm=-90)
    assert r["diffraction_db"] == 0.0
    assert math.isclose(r["fspl_db"], 112.44, abs_tol=0.01)
    assert math.isclose(r["prx_dbm"], 30 + 10 + 10 - 112.44 - r["gas_db"], abs_tol=0.02)
    assert r["verdict"] == "go" and r["min_f1_clearance"] > 1


def test_ridge_blocks_path():
    dist, terr = _flat()
    terr[100] = 60.0                       # 60 m ridge mid-path, masts 30 m
    r = analyse(dist, terr, h_a_agl=30, h_b_agl=30, f_hz=1e9, ptx_dbm=30, gtx_dbi=10, grx_dbi=10, sens_dbm=-90)
    assert r["min_f1_clearance"] < 0 and r["diffraction_db"] > 6
    assert "path obstructed" in " ".join(r["issues"])
    loss, edges = deygout_loss_db(dist, [t + earth_bulge_m(x, 10_000 - x) for x, t in zip(dist, terr)], 30, 30, 1e9)
    assert edges and edges[0]["i"] == 100 and math.isclose(loss, r["diffraction_db"], abs_tol=0.01)


def test_rain_model():
    g = rain_specific_db_km(20, 25, "V")
    assert 2.0 < g < 2.6
    assert rain_specific_db_km(1, 25) < 0.01
    a001 = rain_a001_db(10, 18, 25)
    assert 5 < a001 < 25
    assert math.isclose(rain_a_p_db(a001, 18, 0.01), a001, rel_tol=0.02)   # P.530 scaling is ~1 at 0.01%
    lo, hi = rain_availability_pct(5, a001, 18), rain_availability_pct(40, a001, 18)
    assert 99.0 <= lo < hi <= 99.999


def test_high_band_link_reports_availability():
    dist, terr = _flat(D=5000)
    r = analyse(dist, terr, h_a_agl=30, h_b_agl=30, f_hz=80e9, ptx_dbm=15, gtx_dbi=45, grx_dbi=45, sens_dbm=-60,
                rain_mm_h=25, avail_target_pct=99.99)
    assert r["rain_a001_db"] > 10 and r["availability_pct"] is not None
