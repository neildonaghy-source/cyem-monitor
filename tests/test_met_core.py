"""met_core against ITU-R reference values and hand-worked cases (all numbers checked by hand on 18 Nov 2026)."""
import math

import pytest

from app import met_core as m


def test_saturation_vapour_and_surface_refractivity():
    assert m.sat_vapour_hpa(15.0) == pytest.approx(17.12, abs=0.02)          # 17.05 hPa x enhancement 1.004
    assert m.sat_vapour_hpa(0.0) == pytest.approx(6.14, abs=0.02)
    # mid-latitude surface: 1013 hPa, 15 C, 10 hPa water vapour -> about 318 N-units
    assert m.refractivity(1013.25, 15.0, 10.0) == pytest.approx(317.8, abs=0.3)
    assert m.refractivity(1013.25, 15.0, 0.0) == pytest.approx(272.9, abs=0.3)  # dry term only


def test_k_factor_and_refraction_classes():
    assert m.k_factor(-40) == pytest.approx(4 / 3, abs=0.01)                  # the standard atmosphere
    assert m.k_factor(0) == 1.0 and m.k_factor(60) == pytest.approx(0.723, abs=0.001)
    assert m.k_factor(-100) == pytest.approx(2.754, abs=0.001)
    assert m.k_factor(-157) == m.K_MAX == m.k_factor(-300)                   # trapping: capped, flagged elsewhere
    assert m.k_factor(500) == m.K_MIN
    assert [m.refraction_class(x) for x in (20, -40, -100, -200)] == ["sub-refraction", "normal", "super-refraction", "trapping"]


def test_radio_horizon_scales_with_k():
    assert m.radio_horizon_km(10) == pytest.approx(13.0, abs=0.1)            # 4.12 sqrt(h) km at k = 4/3
    assert m.radio_horizon_km(10, k=10) / m.radio_horizon_km(10) == pytest.approx(math.sqrt(7.5), abs=0.01)


def test_duct_cutoff():
    # 100 m surface duct with a 20 M-unit deficit: longest trapped wavelength 1.12 m, so about 267 MHz and up
    assert m.duct_cutoff_ghz(100, 20) == pytest.approx(0.267, abs=0.002)
    assert m.duct_cutoff_ghz(0, 20) is None and m.duct_cutoff_ghz(50, 0) is None


def _pt(h, p, t, rh):
    return {"h": h, "p": p, "t": t, "rh": rh}


def test_profile_standard_and_surface_duct():
    # near-standard: N falls about 40 per km
    std = m.profile([_pt(0, 1013, 15, 70), _pt(500, 955, 11.8, 66), _pt(1500, 845, 5.3, 60)])
    assert std["refraction"] == "normal" and 1.2 < std["k"] < 1.5 and std["ducts"] == []
    # moist, warm-topped boundary layer: N drops sharply across the inversion, M decreases, surface-based duct
    duct = m.profile([_pt(0, 1015, 12, 95), _pt(150, 997, 14, 40), _pt(1200, 880, 8, 35)])
    assert duct["ducts"] and duct["ducts"][0]["kind"] == "surface-based"
    d = duct["ducts"][0]
    assert d["base_m"] == 0 and d["top_m"] == 150 and d["deficit_m"] > 10 and d["cutoff_ghz"] < 1.0
    # the same inversion lifted off the ground: an elevated duct whose base is where M falls back to its top value
    up = m.profile([_pt(0, 1015, 12, 70), _pt(300, 980, 10, 90), _pt(450, 963, 13, 30), _pt(1500, 850, 6, 30)])
    e = [x for x in up["ducts"] if x["kind"] == "elevated"]
    assert e and 0 < e[0]["base_m"] < 300 and e[0]["top_m"] == 450


def test_evaporation_duct_neutral_case():
    # sea 15 C, air 15 C at 2 m, 80 %, 1013 hPa: about 11.6 m, trapping from about 2.7 GHz
    ev = m.evaporation_duct(15, 15, 80, 1013)
    assert ev["height_m"] == pytest.approx(11.6, abs=0.3)
    assert ev["cutoff_ghz"] == pytest.approx(2.7, abs=0.2) and ev["stability"] == "near neutral"
    assert m.evaporation_duct(15, 15, 100, 1013)["height_m"] < 2              # saturated air: almost no duct
    assert m.evaporation_duct(10, 14, 70, 1013)["stability"] == "stable"
    assert m.evaporation_duct(15, 15, 5, 1013)["height_m"] == 40.0           # very dry air: capped


def test_p840_liquid_water_coefficient():
    # double-Debye model, hand-worked: about 0.093 at 10 GHz and 0.77 at 30 GHz for water at 0 C
    assert m.cloud_kl(10, 0) == pytest.approx(0.093, abs=0.003)
    assert m.cloud_kl(30, 0) == pytest.approx(0.77, abs=0.02)
    assert m.cloud_kl(30, 20) < m.cloud_kl(30, 0)                           # warmer water absorbs less here
    assert m.fog_db_per_km(94, 0.5) > 2.0 > m.fog_db_per_km(10, 0.5)


def test_fog_from_visibility_matches_itu_typical_values():
    assert m.fog_lwc_gm3(300) == pytest.approx(0.05, abs=0.002)
    assert m.fog_lwc_gm3(50) == pytest.approx(0.5, abs=0.01)
    assert m.fog_lwc_gm3(1000) == 0.0 == m.fog_lwc_gm3(None) == m.fog_lwc_gm3(20000)


def test_cloud_base_from_dew_point_spread():
    assert m.cloud_base_m(8.4, 7.3) == 138 and m.cloud_base_m(None, 3) is None


# ---- phase 4 part 2: sea state, clutter, platform limits ---------------------------------------------------------
def test_douglas_sea_state():
    assert m.sea_state(None) is None
    assert [m.sea_state(h) for h in (0.0, 0.05, 0.3, 1.0, 2.0, 3.0, 5.0, 7.0, 12.0, 15.0)] == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_sea_clutter_grows_with_sea_state_and_band_and_fades_with_height():
    assert m.sea_clutter_db(1, 9400, 5) == 0 and m.sea_clutter_db(None, 9400, 5) == 0
    x3, x5 = m.sea_clutter_db(3, 9400, 5), m.sea_clutter_db(5, 9400, 5)
    assert 0 < x3 < x5 <= 20
    assert m.sea_clutter_db(5, 3000, 5) == pytest.approx(10.0) and m.sea_clutter_db(5, 1300, 5) < 10 < x5
    assert m.sea_clutter_db(5, 9400, 175) == pytest.approx(x5 / 2, abs=0.1) and m.sea_clutter_db(5, 9400, 400) == 0
    assert m.sea_clutter_db(9, 30000, 0) == 20.0 and m.sea_clutter_db(5, 150, 5) == 0


def _st(**kw):
    base = {"source": "open-meteo", "wind_ms": 4.0, "gust_ms": 7.0, "wind_dir": 270.0, "rain_mm_h": 0.0, "snow_cm_h": 0.0,
            "visibility_m": 20000.0, "cloud_base_m": 900.0, "cloud_low_pct": 20.0, "freezing_level_m": 2500.0, "rh_pct": 70.0, "sea": None}
    return {**base, **kw}


def test_platform_limits_go_marginal_no_go():
    assert m.platform_limits("air", {"source": "standard"})["status"] == "unknown"
    assert m.platform_limits("air", _st(), 120)["status"] == "go"
    r = m.platform_limits("air", _st(wind_ms=12.0), 120)
    assert r["status"] == "marginal" and r["cost"] == m.LIMIT_COST["marginal"] and "wind 12" in r["reasons"][0]
    assert m.platform_limits("air", _st(gust_ms=22.0), 120)["status"] == "no-go"
    assert m.platform_limits("air", _st(cloud_base_m=150.0, cloud_low_pct=80.0), 120)["status"] == "marginal"
    ice = m.platform_limits("air", _st(freezing_level_m=100.0, cloud_low_pct=80.0), 120)
    assert ice["status"] == "no-go" and any("icing" in x for x in ice["reasons"])
    assert m.platform_limits("air", _st(freezing_level_m=300.0, rain_mm_h=1.0), 120)["status"] == "marginal"
    assert m.platform_limits("air", _st(freezing_level_m=300.0), 120)["status"] == "go"        # no visible moisture


def test_headwind_slows_aircraft_and_sea_state_slows_boats():
    # wind from the west at 10 m/s against a westbound 100 km/h (27.8 m/s) UAS
    west = m.platform_limits("air", _st(wind_ms=10.0, wind_dir=270.0), 120, track_deg=270, speed_kmh=100)
    east = m.platform_limits("air", _st(wind_ms=10.0, wind_dir=270.0), 120, track_deg=90, speed_kmh=100)
    assert west["speed_factor"] == pytest.approx(1 - 10 / 27.78, abs=0.01) and east["speed_factor"] > 1
    assert m.headwind_ms(10, 0, 90) == pytest.approx(0, abs=1e-9)
    calm = m.platform_limits("sea", _st(sea={"wave_m": 0.3}))
    rough = m.platform_limits("sea", _st(sea={"wave_m": 2.0}))
    storm = m.platform_limits("sea", _st(sea={"wave_m": 3.0}, wind_ms=18.0))
    assert calm["status"] == "go" and calm["speed_factor"] == 1.0
    assert rough["status"] == "marginal" and rough["sea_state"] == 4 and rough["speed_factor"] == 0.75
    assert storm["status"] == "no-go" and storm["speed_factor"] == 0.5


def test_ground_is_slowed_never_stopped():
    r = m.platform_limits("ground", _st(snow_cm_h=4.0, visibility_m=100.0))
    assert r["status"] == "marginal" and r["speed_factor"] == 0.5
    assert m.platform_limits("ground", _st(rain_mm_h=9.0))["speed_factor"] == 0.7


def test_breaker_height_and_surf_limits():
    assert m.breaker_height_m(None) is None and m.breaker_height_m(0.0) == 0.0
    assert m.breaker_height_m(1.2) == 1.2                                   # no period: breaker taken as H0
    hb = m.breaker_height_m(1.0, 8.0)                                       # Komar and Gaudet: about 1.4 m
    assert 1.3 < hb < 1.5
    assert m.breaker_height_m(1.0, 30.0) == 1.5 and m.breaker_height_m(1.0, 0.5) == 0.5   # kept within 0.5 to 1.5 H0
    assert m.surf({"source": "standard"})["status"] == "unknown"
    assert m.surf(_st(sea={"wave_m": 0.4, "wave_period_s": 5.0}))["status"] == "go"
    mid = m.surf(_st(sea={"wave_m": 0.9, "wave_period_s": 7.0}))
    assert mid["status"] == "marginal" and mid["cost"] == m.LIMIT_COST["marginal"] and "surf about" in mid["reason"]
    assert m.surf(_st(sea={"wave_m": 1.5, "wave_period_s": 8.0}))["status"] == "no-go"


def test_landing_craft_limits_are_tighter_than_small_craft():
    st = _st(sea={"wave_m": 1.0})                                           # sea state 3
    sea, lc = m.platform_limits("sea", st), m.platform_limits("amphib", st)
    assert sea["status"] == "go" and lc["status"] == "marginal" and lc["speed_factor"] < sea["speed_factor"]
    assert m.platform_limits("amphib", _st(sea={"wave_m": 2.0}))["status"] == "no-go"
    assert m.platform_limits("amphib", _st(wind_ms=16.0, sea={"wave_m": 0.3}))["status"] == "no-go"
