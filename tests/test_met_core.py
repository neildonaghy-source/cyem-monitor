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
