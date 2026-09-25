import math

import numpy as np

from app.coverage_core import Coverage
from app.ems_core import bw_penalty_db, overlap, raster_axes, sample


def test_overlap_and_bandwidth_penalty():
    assert overlap(49.4875e6, 49.5125e6, 30e6, 88e6)            # VHF channel inside an ES receiver band
    assert not overlap(380e6, 381e6, 30e6, 88e6)
    assert bw_penalty_db(25e3, 25e3) == 0 and bw_penalty_db(10e3, 25e3) == 0
    assert math.isclose(bw_penalty_db(10e6, 25e3), 26.02, abs_tol=0.01)   # barrage over 10 MHz vs 25 kHz channel


def _cov():
    az, n = 36, 101
    prx = np.tile(np.linspace(-40, -140, n), (az, 1)).astype(np.float32)   # falls 1 dB per step outward
    prx[:, 0] = np.nan
    return Coverage(51.0, -1.0, 100.0, az, prx)                              # 100 m steps, 10 km radius


def test_sample_matches_point_lookup_and_radius():
    cov = _cov()
    LA, LO = raster_axes(*cov.bounds(), px=200)
    lv = sample(cov, LA, LO)
    i, j = 60, 140
    ref = cov.level_dbm(float(LA[i, j]), float(LO[i, j]))
    assert ref is not None and abs(lv[i, j] - ref) <= 1.01
    assert np.isneginf(lv[0, 0])                                             # raster corner is outside the circle


def test_position_along_track():
    from app.emo_api import position_at, track_minutes
    e = {"lat": 51.0, "lon": -1.0, "track": [[51.0, -0.9]], "speed_kmh": 60}
    assert position_at(e, 0) == (51.0, -1.0)
    mins = track_minutes(e)                                                  # ~7 km at 60 km/h ~ 7 min
    assert 6.5 < mins < 7.5
    la, lo = position_at(e, mins / 2)
    assert math.isclose(lo, -0.95, abs_tol=0.002)
    assert position_at(e, 999) == (51.0, -0.9)                               # stops at the last waypoint
    assert position_at({"lat": 51.0, "lon": -1.0, "track": None, "speed_kmh": None}, 30) == (51.0, -1.0)


def test_df_fix_geometry():
    from app.emo_api import _intersect, df_fix
    from app.link_core import bearing_deg
    tgt = (51.20, -1.90)
    s1, s2 = (51.30, -1.90), (51.20, -2.05)                       # north and west of the target: ~90 deg cut
    b1, b2 = bearing_deg(*s1, *tgt), bearing_deg(*s2, *tgt)
    pt = _intersect(s1, b1, s2, b2)
    assert pt and abs(pt[0] - tgt[0]) < 0.002 and abs(pt[1] - tgt[1]) < 0.002
    f = df_fix(tgt, [{"sensor": "a", "site": s1, "bearing": b1, "sigma": 2}, {"sensor": "b", "site": s2, "bearing": b2, "sigma": 2}])
    assert 80 < f["cut_deg"] <= 90 and 300 < f["error_m"] < 700       # ~11 km ranges x 2 deg ~ 0.39 km each
    s3 = (51.30, -1.905)                                           # nearly the same line as s1: poor cut
    assert df_fix(tgt, [{"sensor": "a", "site": s1, "bearing": b1, "sigma": 2},
                        {"sensor": "c", "site": s3, "bearing": bearing_deg(*s3, *tgt), "sigma": 2}]) is None


def test_jam_penalty_hopping_and_processing_gain():
    from app.emo_api import jam_penalty
    spot = {"freq_mhz": 45.0, "bw_khz": 25}
    barrage = {"freq_mhz": 45.0, "bw_khz": 20000}
    single = {"freq_mhz": 45.0, "bw_khz": 25}
    hopper = {"freq_mhz": 59.0, "bw_khz": 25, "hop_bw_khz": 58000}
    assert jam_penalty(spot, single) == 0                                          # spot on a fixed channel
    assert math.isclose(jam_penalty(barrage, single), 29.03, abs_tol=0.01)          # 20 MHz over 25 kHz
    assert math.isclose(jam_penalty(spot, hopper), 33.65, abs_tol=0.01)             # hits 1 hop in 2320
    assert math.isclose(jam_penalty(barrage, hopper), 33.65, abs_tol=0.01)          # partial-band barrage: same dilution
    l16 = {"freq_mhz": 1087.5, "bw_khz": 3000, "hop_bw_khz": 255000, "pg_db": 5}
    assert math.isclose(jam_penalty({"freq_mhz": 1087.5, "bw_khz": 255000}, l16), 19.29 + 5, abs_tol=0.01)


def test_on_air_windows():
    from app.emo_api import on_air
    e = {"active": True, "schedule": [[0, 20], [45, 90]]}
    assert on_air(e, 10) and not on_air(e, 30) and on_air(e, 45) and not on_air(e, 90)
    assert on_air({"active": True, "schedule": None}, 500)
    assert not on_air({"active": False, "schedule": None}, 0)
