"""Phase 6 part 1: amphibious ship to shore. A landing craft keeps to water until the beach, surf at the beach can make
it hold offshore, opposing comms jammers lower its C2, and the beach report says whether the party ashore needs the
craft as a relay. Synthetic terrain, a throw-away database, a stubbed forecast: no network."""
import asyncio
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from tests.test_emo_scenarios import _add, _flat, emo  # noqa: F401  (fixture)

T0 = "2026-11-22T12:00:00Z"
COAST = -1.0                                                  # land west of this longitude (20 m), sea east of it


def _coast(monkeypatch):
    from app import dem
    z = lambda la, lo: np.where(np.asarray(lo, float) < COAST, 20.0, 0.0)      # noqa: E731
    monkeypatch.setattr(dem, "heights", lambda pts: [float(z(a, b)) for a, b in pts])
    monkeypatch.setattr(dem, "grid_sampler", lambda s, w, n, e, res_deg=1 / 1800: (lambda la, lo: z(la, lo).astype(np.float32)))


def _landing(emo, jammer=True, party_lon=-1.012):
    ship = _add(emo, name="Blue ship", side="blue", lat=51.0, lon=-0.9, eirp_dbm=40, h_agl=20, freq_mhz=60.0,
                sens_dbm=-110, js_req_db=0)
    lc = _add(emo, name="Blue LC", side="blue", kind="receiver", lat=51.0, lon=-0.905, eirp_dbm=37, h_agl=3, freq_mhz=60.0)
    party = _add(emo, name="Blue party", side="blue", kind="receiver", lat=51.0, lon=party_lon, eirp_dbm=30, h_agl=2,
                 freq_mhz=60.0)
    with emo.get_db().tx() as cur:
        cur.execute("UPDATE emo_entities SET net=? WHERE id IN (?, ?)", (ship["id"], lc["id"], party["id"]))
    if jammer:
        _add(emo, name="Red VHF jammer", side="red", kind="effector", category="comms", lat=51.03, lon=-1.02, h_agl=10,
             freq_mhz=60.0, eirp_dbm=55)


def test_landing_craft_keeps_to_water_and_jamming_lowers_its_c2(emo, monkeypatch):
    from app import corridor_api
    from app.link_core import haversine_m
    _coast(monkeypatch)
    _landing(emo)

    async def go():
        await emo.run(emo.RunIn(), light=True)
        body = dict(mover="Blue LC", to_lat=51.0, to_lon=-1.004, domain="amphib", cell_m=500)
        on = await corridor_api.plan_corridor(corridor_api.CorridorIn(**body))
        with emo.get_db().tx() as cur:
            cur.execute("UPDATE emo_entities SET active=0 WHERE name='Red VHF jammer'")
        await emo.run(emo.RunIn(), light=True)
        off = await corridor_api.plan_corridor(corridor_api.CorridorIn(**body))
        return on, off
    on, off = asyncio.run(go())
    s, z = on["summary"], off["summary"]
    for lat, lon in on["path"]:                                # ashore only on the beach, near the landing point
        assert lon >= COAST or haversine_m(lat, lon, 51.0, -1.004) <= 1600
    assert s["c2_jammers"] == ["Red VHF jammer"] and s["max_p_jam"] > 0 and z["c2_jammers"] == []
    assert s["min_p_c2"] <= z["min_p_c2"] and s["c2"] == "hears Blue ship"
    assert all(0 <= lg["p_jam"] <= 100 for lg in on["legs"]) and on["legs"][-1]["verified"]["p_jam"] is not None
    b = s["beach"]
    assert b["control"] == "Blue ship" and [x["name"] for x in b["party"]] == ["Blue party"]
    assert b["surf"] == "unknown" and "surf not assessed" in b["text"] and "Amphibious" in on["notes"]
    assert 0 <= b["p_c2"] <= 100


def test_beach_party_out_of_reach_of_the_ship_needs_the_craft_as_relay(emo, monkeypatch):
    """A 1 mW net on flat land and sea: the party 2 km inland of the beach is 22 km from the ship (out of reach) but
    2 km from the craft on the beach."""
    from app import corridor_api
    _flat(monkeypatch, 0.0)
    ship = _add(emo, name="Blue ship", side="blue", lat=51.0, lon=-0.7, eirp_dbm=0, h_agl=5, freq_mhz=60.0, sens_dbm=-100)
    lc = _add(emo, name="Blue LC", side="blue", kind="receiver", lat=51.0, lon=-0.705, eirp_dbm=30, h_agl=3, freq_mhz=60.0)
    party = _add(emo, name="Blue party", side="blue", kind="receiver", lat=51.0, lon=-1.03, h_agl=2, freq_mhz=60.0, sens_dbm=-100)
    with emo.get_db().tx() as cur:
        cur.execute("UPDATE emo_entities SET net=? WHERE id IN (?, ?)", (ship["id"], lc["id"], party["id"]))

    async def go():
        await emo.run(emo.RunIn(), light=True)
        return await corridor_api.plan_corridor(corridor_api.CorridorIn(mover="Blue LC", to_lat=51.0, to_lon=-1.004,
                                                                        domain="amphib", cell_m=1000))
    b = asyncio.run(go())["summary"]["beach"]
    x = b["party"][0]
    assert x["direct_pct"] < 50 and x["via_craft_pct"] >= 50 and x["needs_relay"] and "relay through the craft" in b["text"]


def test_landing_craft_holds_offshore_for_the_surf(emo, monkeypatch):
    """A long swell for the first half hour (1.2 m at 10 s: sea state 3, marginal for the craft, but about 1.8 m of surf,
    no-go), then calm: with 20-minute layers the craft waits offshore and lands when the surf has dropped; with no
    holding it lands in the surf and is warned."""
    from app import corridor_api, met
    _flat(monkeypatch, 0.0)
    t0 = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)

    async def fake(lat, lon, when=None):
        rough = when is not None and when < t0 + timedelta(minutes=30)
        return {**met.standard(hour=met.valid_hour(when)), "source": "open-meteo", "lat": lat, "lon": lon, "wind_ms": 5.0,
                "gust_ms": 8.0, "wind_dir": 250.0, "rain_mm_h": 0.0, "snow_cm_h": 0.0, "visibility_m": 15000.0,
                "cloud_base_m": 800.0, "cloud_low_pct": 30.0, "freezing_level_m": 2000.0, "rh_pct": 75.0, "temp_c": 10.0,
                "sea": {"sst_c": 12.0, "wave_m": 1.2 if rough else 0.3, "wave_period_s": 10.0 if rough else 5.0,
                        "wave_dir": 240.0, "distance_km": 2.0}}
    monkeypatch.setattr(met, "met_state", fake)
    ship = _add(emo, name="Blue ship", side="blue", lat=51.0, lon=-0.96, eirp_dbm=40, h_agl=20, freq_mhz=60.0)
    lc = _add(emo, name="Blue LC", side="blue", kind="receiver", lat=51.0, lon=-0.965, eirp_dbm=37, h_agl=3, freq_mhz=60.0)
    with emo.get_db().tx() as cur:
        cur.execute("UPDATE emo_entities SET net=? WHERE id=?", (ship["id"], lc["id"]))

    async def go(wait):
        await emo.run(emo.RunIn(met="forecast", met_time=T0), light=True)
        return await corridor_api.plan_corridor(corridor_api.CorridorIn(mover="Blue LC", to_lat=51.0, to_lon=-1.004, domain="amphib",
                                                                        cell_m=500, step_min=20, layers=4, wait=wait))
    async def both():
        return await go(True), await go(False)
    held, rushed = asyncio.run(both())
    hb, rb = held["summary"]["beach"], rushed["summary"]["beach"]
    assert held["summary"]["hold_min"] > 0 and any(lg["hold"] for lg in held["legs"])
    assert hb["surf"] == "go" and hb["t"] >= 30
    assert rb["surf"] == "no-go" and "Surf at the beach" in rushed["summary"]["limits_warning"]


def test_studland_vignette_plans(emo, monkeypatch):
    from app import corridor_api
    from app.emo_examples import EXAMPLES
    _flat(monkeypatch, 0.0)
    v = EXAMPLES["amphib-studland"]["corridor"]
    assert v["domain"] == "amphib"

    async def go():
        await emo.load_example("amphib-studland")
        await emo.run(emo.RunIn(), light=True)
        return await corridor_api.plan_corridor(corridor_api.CorridorIn(mover=v["mover"], domain=v["domain"], step_min=v["step_min"],
                                                                        to_lat=v["to"][0], to_lon=v["to"][1], cell_m=500))
    out = asyncio.run(go())
    s = out["summary"]
    assert out["legs"] and s["layers"] > 1 and s["c2_jammers"] == ["Red VHF jammer (Swanage)"]
    assert set(s["sensors"]) == {"Red ES/DF (Ballard Down)", "Red DF (Hengistbury)"}
    assert [x["name"] for x in s["beach"]["party"]] == ["Blue beach party"] and s["beach"]["text"]


def test_amphib_is_a_valid_example_domain():
    from app import emo_examples
    ex = {"id": "x", "title": "x", "about": "x", "centre": [51.0, -1.0], "zoom": 10,
          "entities": [{"name": "A", "side": "blue", "kind": "emitter", "lat": 51.0, "lon": -1.0, "freq_mhz": 60.0}],
          "corridor": {"mover": "A", "to": [51.0, -1.1], "domain": "amphib"}}
    assert emo_examples.check(ex) == []
    ex["corridor"]["domain"] = "submarine"
    assert any("domain" in e for e in emo_examples.check(ex))


def test_beach_report_counts_the_jammer(emo, monkeypatch):
    """The exact beach figures include the comms jammer, so they agree with the grid's C2 on the last leg."""
    from app import corridor_api
    _flat(monkeypatch, 0.0)
    _landing(emo, jammer=True)

    async def go():
        await emo.run(emo.RunIn(), light=True)
        return await corridor_api.plan_corridor(corridor_api.CorridorIn(mover="Blue LC", to_lat=51.0, to_lon=-1.004,
                                                                        domain="amphib", cell_m=500))
    b = asyncio.run(go())["summary"]["beach"]
    assert b["p_jam"] is not None and b["p_jam"] > 0 and b["p_c2"] < 100 and "jamming denies it" in b["text"]
    assert b["party"][0]["direct_pct"] < 100
