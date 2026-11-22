"""Phase 4 part 2: space weather in runs and the timeline, and met, platform limits, sea clutter and space weather in
corridors. Synthetic terrain, a throw-away database, a stubbed forecast: no network."""
import asyncio

import pytest

from tests.test_emo_scenarios import _flat, emo  # noqa: F401  (fixture)

T0 = "2026-11-22T12:00:00Z"


def _sw(emo_api, g=3, r=0):
    emo_api.get_db().set_snapshot("spaceweather", {
        "fetched_at": T0, "kp": {"value": 7.0, "time": T0},
        "scales": {"now": {"G": {"level": str(g)}, "R": {"level": str(r)}, "S": {"level": "0"}}, "predicted": {}}})


def _stub_met(monkeypatch, wave_m=2.0, wind_ms=12.0):
    from app import met

    async def fake(lat, lon, when=None):
        hour = met.valid_hour(when)
        return {**met.standard(hour=hour), "source": "open-meteo", "lat": lat, "lon": lon, "wind_ms": wind_ms, "gust_ms": wind_ms + 3,
                "wind_dir": 250.0, "rain_mm_h": 0.0, "snow_cm_h": 0.0, "visibility_m": 15000.0, "cloud_base_m": 800.0,
                "cloud_low_pct": 30.0, "freezing_level_m": 2000.0, "rh_pct": 75.0, "temp_c": 10.0,
                "sea": {"sst_c": 12.0, "wave_m": wave_m, "wave_period_s": 6.0, "wave_dir": 240.0, "distance_km": 2.0}}
    monkeypatch.setattr(met, "met_state", fake)


def test_space_weather_lowers_gnss_margin_only_with_the_forecast(emo, monkeypatch):
    _stub_met(monkeypatch)
    _sw(emo, g=3)

    async def go():
        await emo.load_example("a303-gnss")
        std = await emo.run(emo.RunIn(met_time=T0), light=True)
        fc = await emo.run(emo.RunIn(met="forecast", met_time=T0), light=True)
        return std, fc
    std, fc = asyncio.run(go())
    nav = lambda r: next(n for n in r["nets"] if n["category"] == "nav" and n["side"] == "blue")          # noqa: E731
    assert std["space"]["gnss"]["loss_db"] == 0 and "not applied" in std["space"]["text"] and nav(std)["js_req_db"] == 35
    assert fc["space"]["source"] == "now" and fc["space"]["gnss"]["loss_db"] == 3.0
    assert nav(fc)["js_req_db"] == 32 and nav(fc)["space_weather_db"] == 3.0
    vhf = [n for n in fc["nets"] if n["category"] != "nav"]
    assert all(n["space_weather_db"] == 0 for n in vhf)
    gj = lambda r: [j for j in r["jamming"] if j["net"] == nav(r)["net"]]                                # noqa: E731
    assert all(j["js_req_db"] == 32 for j in gj(fc))
    assert sum(j["status"] == "denied" for j in gj(fc)) >= sum(j["status"] == "denied" for j in gj(std))
    assert "SPACE WEATHER: Space weather (now): G3" in emo.scenario_context()


def test_timeline_reports_space_weather_per_step(emo, monkeypatch):
    from app import emo_plan
    _stub_met(monkeypatch)
    _sw(emo, g=0, r=2)

    async def go():
        await emo.load_example("a303-gnss")
        p = emo.RunIn(met="forecast", met_time="2026-11-22T15:00:00Z")
        await emo.run(p, light=True)
        return await emo_plan.timeline(emo_plan.TimelineIn(step_min=60, max_steps=3))
    tl = asyncio.run(go())
    sp = [b["space"] for b in tl["board"]]
    assert sp[0]["hf"] == "degraded" and sp[0]["sunlit"]                  # R2 in daylight at 15:00 UTC
    assert all(s["source"] == "now" for s in sp) and all(s["gnss_loss_db"] == 0 for s in sp)
    assert "space weather" in tl["notes"]


def test_corridor_takes_limits_clutter_and_space_weather_from_the_forecast(emo, monkeypatch):
    from app import corridor_api
    _flat(monkeypatch, 0.0)                                                # open sea
    _stub_met(monkeypatch, wave_m=2.0, wind_ms=12.0)                       # sea state 4, fresh breeze: marginal
    _sw(emo, g=3)
    v = None

    async def go(met):
        nonlocal v
        await emo.load_example("solent-maritime")
        from app.emo_examples import EXAMPLES
        v = EXAMPLES["solent-maritime"]["corridor"]
        await emo.run(emo.RunIn(met=met, met_time=T0), light=True)
        body = {k: v[k] for k in ("mover", "domain", "step_min") if k in v}
        return await corridor_api.plan_corridor(corridor_api.CorridorIn(**body, to_lat=v["to"][0], to_lon=v["to"][1], cell_m=1000))
    async def both():
        return await go("forecast"), await go("standard")
    fc, std = asyncio.run(both())
    s, z = fc["summary"], std["summary"]
    assert s["limits"] == "marginal" and any("sea state 4" in r for r in s["limit_reasons"])
    assert s["speed_factor"] == 0.75 and s["speed_kmh"] == pytest.approx(25 * 0.75, abs=0.06)
    assert s["max_sea_clutter_db"] > 0 and s["gnss_space_db"] == 3.0
    assert all(lg["limits"] == "marginal" for lg in fc["legs"]) and all(lg["sea_clutter_db"] > 0 for lg in fc["legs"])
    assert s["max_p_radar"] <= z["max_p_radar"]                            # clutter hides the boat from the red radar
    assert s["minutes"] > z["minutes"] and "forecast" in fc["notes"]
    assert z["limits"] == "unknown" and z["max_sea_clutter_db"] == 0 and z["speed_factor"] == 1.0
    assert "not applied" in std["notes"]


def test_no_go_layer_is_reported(emo, monkeypatch):
    from app import corridor_api
    _flat(monkeypatch)
    _stub_met(monkeypatch, wind_ms=18.0)                                    # gusts 21 m/s: no-go for a small UAS

    async def go():
        await emo.load_example("uas-gnss")
        from app.emo_examples import EXAMPLES
        v = EXAMPLES["uas-gnss"]["corridor"]
        await emo.run(emo.RunIn(met="forecast", met_time=T0), light=True)
        body = {k: v[k] for k in ("mover", "domain", "step_min", "alt_m", "speed_kmh") if k in v}
        return await corridor_api.plan_corridor(corridor_api.CorridorIn(**body, to_lat=v["to"][0], to_lon=v["to"][1], cell_m=1000))
    s = asyncio.run(go())["summary"]
    assert s["limits"] == "no-go" and "gusts 21" in s["limits_warning"]
    # wind from 250 against a westbound track: the ground speed is lower than the air speed
    assert s["speed_factor"] < 1 and s["speed_kmh"] < 100
