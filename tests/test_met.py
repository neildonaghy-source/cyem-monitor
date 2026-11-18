"""met.py: Open-Meteo bodies (shaped like the live responses of 18 Nov 2026) into a met state; cache and fallback."""
import asyncio
from datetime import datetime, timezone

import pytest

HOUR = datetime(2026, 11, 18, 21, tzinfo=timezone.utc)


def _fc(elev=151.0, ps=966.7, t2=8.4, rh2=93, precip=2.4, vis=45520.0, levels=None, **extra):
    h = {"time": ["2026-11-18T20:00", "2026-11-18T21:00"],
         "temperature_2m": [8.5, t2], "relative_humidity_2m": [92, rh2], "dew_point_2m": [7.2, 7.3],
         "surface_pressure": [966.9, ps], "precipitation": [1.0, precip], "snowfall": [0.0, 0.0],
         "visibility": [40000.0, vis], "cloud_cover": [100, 100], "cloud_cover_low": [100, 100],
         "wind_speed_10m": [3.0, 3.2], "wind_direction_10m": [190, 186], "wind_gusts_10m": [5.5, 5.8],
         "freezing_level_height": [1600.0, 1580.0]}
    # 1000 hPa is below ground here (geopotential height -130 m, surface pressure 967 hPa): it must be skipped
    for p, z, t, rh in (levels or [(1000, -130.0, 10.7, 91), (975, 75.0, 8.9, 92), (950, 290.0, 7.4, 92),
                                   (925, 510.0, 6.0, 93), (900, 735.0, 4.6, 94), (850, 1205.0, 2.3, 91),
                                   (800, 1695.0, -0.2, 80), (700, 2740.0, -5.5, 60)]):
        h[f"temperature_{p}hPa"] = [t, t]
        h[f"relative_humidity_{p}hPa"] = [rh, rh]
        h[f"geopotential_height_{p}hPa"] = [z, z]
    h.update(extra)
    return {"latitude": 51.246, "longitude": -1.839, "elevation": elev, "hourly": h}


def test_build_state_from_a_land_forecast():
    from app.met import build_state
    st = build_state(_fc(), None, None, HOUR, 51.25, -1.85)
    assert st["source"] == "open-meteo" and st["valid_time"] == "2026-11-18T21:00Z"
    assert all(lv["h"] > 0 for lv in st["levels"][1:])                     # the level below ground was dropped
    assert 1.1 < st["k"] < 1.6 and st["refraction"] == "normal"
    assert st["rain_mm_h"] == 2.4 and st["fog_lwc_gm3"] == 0 and st["evap_duct"] is None
    assert st["cloud_base_m"] == 138 and st["freezing_level_m"] == 1580.0
    assert any("Rain 2.4 mm/h" in w for w in st["warnings"])


def test_fog_and_a_missing_hour():
    from app.met import build_state
    st = build_state(_fc(vis=150.0, precip=0.0), None, None, HOUR, 51.25, -1.85)
    assert 0.11 < st["fog_lwc_gm3"] < 0.13 and any(w.startswith("Fog") for w in st["warnings"])
    gone = build_state(_fc(), None, None, datetime(2026, 11, 19, 3, tzinfo=timezone.utc), 51.25, -1.85)
    assert gone["source"] == "standard" and "no forecast for that hour" in gone["notes"][0]


def test_evaporation_duct_uses_the_air_over_the_sea():
    from app.met import build_state
    marine = {"latitude": 50.625, "longitude": -1.208, "hourly": {"time": ["2026-11-18T21:00"], "sea_surface_temperature": [13.3],
                                                                  "wave_height": [1.46], "wave_period": [8.2], "wave_direction": [234]}}
    sea_air = {"latitude": 50.62, "longitude": -1.2, "hourly": {"time": ["2026-11-18T21:00"], "temperature_2m": [12.0],
                                                                "relative_humidity_2m": [80], "surface_pressure": [1001.0]}}
    st = build_state(_fc(), marine, sea_air, HOUR, 50.70, -1.20)
    ev = st["evap_duct"]
    assert st["sea"]["sst_c"] == 13.3 and st["sea"]["wave_m"] == 1.46
    assert 8 < ev["height_m"] < 16 and ev["stability"] == "unstable" and 2 < ev["cutoff_ghz"] < 4
    assert any("Evaporation duct" in w for w in st["warnings"])
    far = build_state(_fc(), marine, sea_air, HOUR, 51.25, -1.85)          # Salisbury Plain: the sea point is 70 km off
    assert far["evap_duct"] is None and far["sea"] is None


def test_super_refraction_and_a_surface_duct_are_reported():
    from app.met import build_state
    # warm, dry air over a cool moist surface layer: strong negative gradient, M falls across the inversion
    lv = [(975, 120.0, 14.0, 35), (950, 330.0, 13.0, 30), (925, 550.0, 11.0, 30), (900, 775.0, 9.0, 20),
          (850, 1250.0, 5.0, 20), (800, 1740.0, 1.0, 20), (700, 2790.0, -5.0, 20)]
    st = build_state(_fc(elev=10.0, ps=1000.0, t2=12.0, rh2=100, precip=0.0, levels=lv), None, None, HOUR, 50.8, -1.1)
    assert st["refraction"] in ("super-refraction", "trapping") and st["k"] > 2
    assert st["ducts"] and st["ducts"][0]["kind"] == "surface-based"
    assert any("duct" in w for w in st["warnings"])


def test_atmosphere_overrides_and_path_loss():
    from app.met import STANDARD_ATM, atmosphere, path_extra_db, standard
    assert STANDARD_ATM["k"] == 1.333 and STANDARD_ATM["sig"] == "k1.33r0.0f0.000"
    a = atmosphere(standard(), k=2.0, rain_mm_h=10.0, visibility_m=100.0)
    assert a["k"] == 2.0 and a["rain_mm_h"] == 10.0 and a["fog_lwc_gm3"] > 0.2 and a["sig"] != STANDARD_ATM["sig"]
    assert atmosphere(standard(), k=50)["k"] == 10.0
    assert path_extra_db(10_000, 400e6, a) < 0.1                            # UHF: rain and fog hardly matter
    x10 = path_extra_db(10_000, 10e9, atmosphere(standard(), rain_mm_h=10.0))
    assert 1.0 < x10 < 4.0                                                  # about 0.2 dB/km at 10 GHz, 10 km
    assert path_extra_db(10_000, 94e9, a) > 20                              # W band in rain and thick fog
    assert path_extra_db(0, 10e9, a) == 0.0


@pytest.fixture
def tmpdb(tmp_path, monkeypatch):
    from app import config, db as dbm, met
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(dbm, "_db", dbm.Database(str(tmp_path / "m.sqlite3")))
    met._schema_done.clear()
    yield met
    met._schema_done.clear()
    dbm.get_db()._conn.close()


def test_met_state_caches_and_falls_back(tmpdb, monkeypatch):
    met = tmpdb
    calls = []

    async def fake(url, params):
        calls.append(url)
        if "marine" in url:
            return {"latitude": 51.29, "longitude": -1.87, "hourly": {"time": ["2026-11-18T21:00"], "sea_surface_temperature": [None]}}
        return _fc()
    monkeypatch.setattr(met, "_fetch", fake)
    when = datetime(2026, 11, 18, 20, 50, tzinfo=timezone.utc)              # nearest hour: 21:00
    st = asyncio.run(met.met_state(51.25, -1.85, when))
    assert st["source"] == "open-meteo" and st["valid_time"] == "2026-11-18T21:00Z" and st["evap_duct"] is None
    n = len(calls)
    asyncio.run(met.met_state(51.26, -1.84, when))                          # same grid square and day: from the cache
    assert len(calls) == n

    async def down(url, params):
        raise met.MetUnavailable("Open-Meteo 503: busy")
    monkeypatch.setattr(met, "_fetch", down)
    st = asyncio.run(met.met_state(60.0, 5.0, when))
    assert st["source"] == "standard" and "Open-Meteo 503" in st["notes"][0] and st["k"] == 1.333


def test_api_and_cli(tmpdb, monkeypatch, capsys):
    from fastapi.testclient import TestClient
    from app.main import app
    from app import cli
    met = tmpdb

    async def fake(url, params):
        return {"hourly": {"time": []}} if "marine" in url else _fc()
    monkeypatch.setattr(met, "_fetch", fake)
    r = TestClient(app).get("/api/met", params={"lat": 51.25, "lon": -1.85, "time": "2026-11-18T21:00"})
    assert r.status_code == 200 and r.json()["source"] == "open-meteo" and r.json()["rain_mm_h"] == 2.4
    assert TestClient(app).get("/api/met", params={"lat": 51.25, "lon": -1.85, "time": "soon"}).status_code == 422
    assert cli.main(["met", "51.25", "-1.85", "2026-11-18T21:00"]) == 0
    out = capsys.readouterr().out
    assert '"source": "open-meteo"' in out and "profile (m above ground, N, M)" in out
