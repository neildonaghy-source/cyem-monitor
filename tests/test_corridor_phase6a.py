"""Phase 6 part 1: amphibious ship to shore, dismounted (on foot) and civil (grey) corridors, on synthetic terrain."""
import asyncio

import numpy as np
import pytest
from fastapi import HTTPException

from tests.test_emo_scenarios import emo  # noqa: F401  (fixture)
from tests.test_env_phase4b import T0, _stub_met


def _coast(monkeypatch, lat0=68.06):
    """Sea south of lat0, 60 m plateau north of it."""
    from app import dem
    z = lambda la, lo: np.where(np.asarray(la, float) < lat0, 0.0, 60.0)                        # noqa: E731
    monkeypatch.setattr(dem, "heights", lambda pts: [float(z(a, b)) for a, b in pts])
    monkeypatch.setattr(dem, "grid_sampler", lambda s, w, n, e, res_deg=1 / 1800: (lambda la, lo: z(la, lo).astype(np.float32)))


def _vignette(emo, name, met="standard", **over):
    from app import corridor_api
    from app.emo_examples import EXAMPLES
    v = {**EXAMPLES[name]["corridor"], **over}

    async def go():
        await emo.load_example(name)
        await emo.run(emo.RunIn(met=met, met_time=T0), light=True)
        body = {k: v[k] for k in ("mover", "domain", "step_min", "alt_m", "speed_kmh", "ashore") if k in v}
        return await corridor_api.plan_corridor(corridor_api.CorridorIn(**body, to_lat=v["to"][0], to_lon=v["to"][1], cell_m=1000))
    return asyncio.run(go())


def test_dismounted_patrol_on_foot_with_cold_batteries(emo, monkeypatch):
    _stub_met(monkeypatch)                                                    # 10 C: batteries at 80%
    r = _vignette(emo, "brecon-siting", met="forecast")
    s = r["summary"]
    assert r["domain"] == "foot" and s["speed_kmh"] == pytest.approx(4.0) and s["layers"] > 1
    assert any("batteries about 80%" in x for x in s["limit_reasons"])
    assert "slopes over 60%" in r["notes"] and r["legs"]


def test_civil_air_ambulance_counts_only_gnss_from_both_sides(emo):
    r = _vignette(emo, "suwalki-mdo")
    s = r["summary"]
    assert r["side"] == "grey" and s["max_p_detect"] == 0 and s["max_p_radar"] == 0 and s["sensors"] == []
    assert "Civil unit" in r["notes"]
    assert r["domain"] == "air" and 0 < s["max_p_gnss"] < 100 and "collateral" in r
    assert set(s["gnss_jammers"]) == {"Red Pole-21 GNSS jammer (west)", "Red Pole-21 GNSS jammer (south-east)"}
    assert all("jammed_by" in lg for lg in r["legs"])


def test_collateral_groups_jammers_by_side_and_leg():
    from app.corridor_api import _collateral
    ents = {1: {"name": "Red J", "side": "red"}, 2: {"name": "Blue J", "side": "blue"}}
    legs = [{"jammed_by": ["Red J"]}, {"jammed_by": ["Red J", "Blue J"]}, {"jammed_by": []}]
    assert _collateral(legs, ents) == {"red": [{"effector": "Red J", "legs": [1, 2]}], "blue": [{"effector": "Blue J", "legs": [2]}]}


def test_amphibious_lands_on_the_coast_then_moves_ashore(emo, monkeypatch):
    _coast(monkeypatch)
    r = _vignette(emo, "littoral-a2ad")
    s = r["summary"]
    assert r["domain"] == "amphib" and len(r["bands"]) == 2 and s["landings_tried"]
    assert abs(s["landing"][0] - 68.06) < 0.02                                # on the coastline
    phases = [lg["phase"] for lg in r["legs"]]
    assert phases[0] == "sea" and phases[-1] == "ashore" and phases == sorted(phases, key=lambda x: x != "sea")
    first_ashore = next(lg for lg in r["legs"] if lg["phase"] == "ashore")
    assert first_ashore["t_from"] >= s["land_t"] - 0.1 and s["arrive_t"] > s["land_t"]
    assert s["km"] == pytest.approx(s["sea_km"] + s["ashore_km"], abs=0.2) and s["ashore_speed_kmh"] == pytest.approx(4.0)
    assert s["surf"] == "unknown" and "landing points" in r["notes"]


def test_amphibious_needs_sea_then_land(emo, monkeypatch):
    from app import corridor_api
    _coast(monkeypatch)

    async def go():
        await emo.load_example("littoral-a2ad")
        await emo.run(emo.RunIn(), light=True)
        out = []
        for kw in ({"to_lat": 67.9, "to_lon": 13.3},                                     # objective at sea
                   {"to_lat": 68.2, "to_lon": 13.9, "from_lat": 68.1, "from_lon": 13.5}):  # starting on land
            try:
                await corridor_api.plan_corridor(corridor_api.CorridorIn(mover="Blue landing craft (UHF)", domain="amphib", cell_m=1000, **kw))
                out.append(None)
            except HTTPException as e:
                out.append(e.detail)
        return out
    at_sea, on_land = asyncio.run(go())
    assert "ashore" in at_sea and "start at sea" in on_land


def test_amphibious_surf_from_the_forecast(emo, monkeypatch):
    _coast(monkeypatch)
    _stub_met(monkeypatch, wave_m=1.7, wind_ms=8.0)                          # sea state 4 and surf over 1.5 m
    s = _vignette(emo, "littoral-a2ad", met="forecast", step_min=0)["summary"]
    assert s["surf"] == "no-go" and s["limits"] == "no-go" and "surf" in s["limits_warning"]
