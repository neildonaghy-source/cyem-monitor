"""Unit tests for app/spectrum_core.py (stdlib only; run with pytest)."""
import math

from app.spectrum_core import (Emitter, bbox_for_radius, bw_from_emission, find_conflicts, freq_overlap_hz,
                               freq_overlaps, haversine_km, looks_personal, parse_wtr_row, severity, windows_intersect)

ROW = {
    "Licence Number": "1418767/1", "Frequency (Hz)": "163037500", "Station Type": "T", "Channel Width (Hz)": "12500",
    "Antenna ERP": "5", "Antenna ERP Unit": "W", "Antenna Height": "15", "Height Above Sea Level": "-",
    "Antenna AZIMUTH": "-", "Emission Code": "12K5G7W", "Licencee Surname": "SMITH", "Licencee First Name": "JOHN",
    "Licencee Company": "RADIO LINKS COMMUNICATIONS LIMITED", "Product Description": "BR Tech Assigned",
    "Latitude(Deg)": "56.29862893", "Longitude(Deg)": "-2.64607039", "NGR": "NO 60115 11987",
}


def test_parse_row_units_and_fields():
    r = parse_wtr_row(ROW)
    assert r["freq_hz"] == 163037500.0 and r["bw_hz"] == 12500.0 and r["bw_src"] == "wtr"
    assert r["erp"] == 5.0 and r["erp_unit"] == "W" and r["height_asl_m"] is None
    assert r["company"] == "RADIO LINKS COMMUNICATIONS LIMITED"
    assert math.isclose(r["lat"], 56.298629) and math.isclose(r["lon"], -2.64607)


def test_parse_row_drops_individual_names():
    r = parse_wtr_row(ROW)
    assert "SMITH" not in repr(r) and "JOHN" not in repr(r)


def test_parse_row_bw_fallback_to_emission():
    r = parse_wtr_row({**ROW, "Channel Width (Hz)": "-"})
    assert r["bw_hz"] == 12500.0 and r["bw_src"] == "emission"
    r = parse_wtr_row({**ROW, "Channel Width (Hz)": "", "Emission Code": "-"})
    assert r["bw_hz"] == 0.0 and r["bw_src"] == "none"


def test_parse_row_rejects_bad():
    assert parse_wtr_row({**ROW, "Frequency (Hz)": "x"}) is None
    assert parse_wtr_row({**ROW, "Latitude(Deg)": "123"}) is None


def test_parse_row_area_defined_keeps_no_position():
    r = parse_wtr_row({**ROW, "Latitude(Deg)": "-", "Longitude(Deg)": "-"})
    assert r is not None and r["lat"] is None and r["lon"] is None and r["freq_hz"] == 163037500.0
    assert parse_wtr_row({**ROW, "Latitude(Deg)": "123"}) is None


def test_emission_designators():
    assert bw_from_emission("12K5G7W") == 12500
    assert bw_from_emission("27M5D7W") == 27.5e6
    assert bw_from_emission("100HA1A") == 100
    assert bw_from_emission("6K00A3E") == 6000
    assert bw_from_emission("") is None and bw_from_emission("XYZ") is None


def test_overlap_boundaries():
    # 12.5 kHz channels: adjacent at 12.5 kHz spacing is exactly touching -> clear
    assert not freq_overlaps(100e6, 12.5e3, 100.0125e6, 12.5e3)
    assert freq_overlaps(100e6, 12.5e3, 100.012e6, 12.5e3)
    # the same pair becomes a conflict once a guard band is applied
    assert freq_overlaps(100e6, 12.5e3, 100.0125e6, 12.5e3, guard_hz=1e3)
    assert math.isclose(freq_overlap_hz(100e6, 25e3, 100e6, 25e3), 25e3)
    # wide channel swallowing a narrow one off-centre
    assert freq_overlaps(18.875e9, 27.5e6, 18.88e9, 1e6)


def test_haversine_and_bbox():
    d = haversine_km(51.5074, -0.1278, 50.8365, -0.7792)   # London to Chichester, ~87 km
    assert 80 < d < 95
    lo_lat, hi_lat, lo_lon, hi_lon = bbox_for_radius(51.0, -1.0, 50)
    for brg in range(0, 360, 15):
        lat = 51.0 + (50 / 111.2) * math.cos(math.radians(brg)) * 0.999
        lon = -1.0 + (50 / (111.2 * math.cos(math.radians(51)))) * math.sin(math.radians(brg)) * 0.999
        assert lo_lat <= lat <= hi_lat and lo_lon <= lon <= hi_lon


def test_windows():
    assert windows_intersect(None, None, "2026-01-01T00:00:00Z", None)
    assert windows_intersect("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "2026-01-01T12:00:00Z", "2026-01-03T00:00:00Z")
    assert not windows_intersect("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z")


def test_severity_bands():
    assert severity(500, 1000, 500, 1, 50) == "low"
    assert severity(20000, 0, -20000, 10, 50) == "high"
    assert severity(20000, 0, -20000, 30, 50) == "medium"


def _p(i, f, bw=12.5e3, lat=51.0, lon=-1.0, **kw):
    return Emitter(id=i, name=i, freq_hz=f, bw_hz=bw, lat=lat, lon=lon, **kw)


def test_find_conflicts_distance_and_ranking():
    planned = [_p("P1", 45.0e6)]
    near_co = _p("W1", 45.0e6, lat=51.05, kind="wtr")                   # ~5.6 km, co-channel
    far_co = _p("W2", 45.0e6, lat=51.40, kind="wtr")                    # ~44 km, co-channel
    too_far = _p("W3", 45.0e6, lat=52.0, kind="wtr")                    # ~111 km
    clear = _p("W4", 45.1e6, lat=51.0, kind="wtr")                      # 100 kHz away
    out = find_conflicts(planned, [clear, too_far, far_co, near_co], radius_km=50)
    assert [c["b"] for c in out] == ["W1", "W2"]
    assert out[0]["severity"] == "high" and out[1]["severity"] == "medium"


def test_planned_vs_planned_time_and_dedupe():
    a = _p("A", 150e6, start="2026-10-01T00:00:00Z", end="2026-10-02T00:00:00Z")
    b = _p("B", 150e6, start="2026-10-01T12:00:00Z", end="2026-10-03T00:00:00Z")
    c = _p("C", 150e6, start="2026-11-01T00:00:00Z", end="2026-11-02T00:00:00Z")
    out = find_conflicts([a, b, c], [a, b, c], radius_km=50)
    pairs = {tuple(sorted((r["a"], r["b"]))) for r in out}
    assert pairs == {("A", "B")} and len(out) == 1


def test_looks_personal_masks_individuals_not_organisations():
    for name in ["Daniel James", "DANIEL JAMES", "Mr Iftikhar Hussain", "A P Sheardown", "Mohammed Amin Pandor"]:
        assert looks_personal(name), name
    for org in ["Roadphone NRB", "Sefton MBC", "RADIO LINKS COMMUNICATIONS LIMITED", "Portsmouth City Council",
                "Standard Chartered Bank", "The Pirbright Institute", "Jamia Ghosia Mosque", "Edinburgh Trams Limited",
                "Rutherford Appleton Laboratory", "Brunel Education", None, ""]:
        assert not looks_personal(org), org


def test_parse_row_masks_personal_company():
    assert parse_wtr_row({**ROW, "Licencee Company": "Daniel James"})["company"] is None
