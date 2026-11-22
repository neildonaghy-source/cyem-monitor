"""Satcom and GNSS windows: pure helpers (phase 6 part 3)."""
import pytest

from app import satwin_core as s


def test_geo_look_known_values():
    el, az, rng = s.geo_look(0.0, 0.0, 0.0)                     # sub-satellite point
    assert el == pytest.approx(90.0, abs=0.01) and rng == pytest.approx(s.R_GEO - s.R_E, abs=1)
    el, az, _ = s.geo_look(51.5, 0.0, 0.0)                      # London to a slot due south: about 31 degrees
    assert el == pytest.approx(31.1, abs=0.3) and az == pytest.approx(180.0, abs=0.01)
    el, az, _ = s.geo_look(51.5, 0.0, 20.0)                     # a slot east of the meridian: bearing east of south
    assert 140 < az < 180 and el < 31
    el, _, _ = s.geo_look(68.1, 13.9, 13.9)                     # Lofoten: low elevation
    assert el == pytest.approx(13.8, abs=0.5)
    assert s.geo_look(85.0, 0.0, 0.0)[0] < 0                    # beyond the GEO arc's reach


def test_slot_for_azimuth_round_trip():
    _, az, _ = s.geo_look(51.2, -1.8, 9.0)
    assert s.slot_for_azimuth(51.2, -1.8, az) == pytest.approx(9.0, abs=0.1)
    assert s.slot_for_azimuth(51.2, -1.8, 0.0) is None            # north: no geostationary slot


def test_horizon_from_a_profile():
    assert s.horizon_deg([], [], 0, 2) == -90.0
    # a 300 m ridge 1 km away from a 2 m antenna at sea level: about 16.6 degrees
    assert s.horizon_deg([500, 1000, 2000], [0, 300, 0], 0.0, 2.0) == pytest.approx(16.5, abs=0.2)
    # flat ground: slightly below the horizontal because of curvature
    assert -0.5 < s.horizon_deg([5000, 20000], [0, 0], 0.0, 2.0) < 0


def test_uplink_js_and_status():
    assert s.uplink_js_db(80, 70, 38000, 38000, 0) == pytest.approx(10.0)
    assert s.uplink_js_db(80, 70, 38000, 40000, 0) == pytest.approx(10 - 20 * 0.0222, abs=0.01)
    assert s.uplink_js_db(80, 70, 38000, 38000, 15) == pytest.approx(-5.0)       # spreading or hopping
    assert [s.link_status(x, 0) for x in (None, -10, -3, 2)] == ["clear", "clear", "degraded", "denied"]
    assert s.power_sum_db([0, 0]) == pytest.approx(3.01, abs=0.01) and s.power_sum_db([]) is None


def test_gnss_status_noise_and_spoof():
    assert s.gnss_status(None, None, 35) == "clear"
    assert s.gnss_status(36, None, 35) == "denied" and s.gnss_status(31, None, 35) == "degraded"
    assert s.gnss_status(None, 10, 35) == "deceived" and s.gnss_status(None, 40, 35) == "denied"
    assert s.gnss_status(None, 0, 35) == "degraded" and s.gnss_status(10, 10, 35) == "deceived"


def test_spans():
    assert s.spans([True, True, False, True], [0, 10, 20, 30]) == [{"from_min": 0, "to_min": 10, "steps": 2},
                                                                   {"from_min": 30, "to_min": 30, "steps": 1}]
    assert s.spans([], []) == []
