"""Phase 6: dismounted (on foot) and civil (grey) corridors, on synthetic terrain; GNSS collateral by side."""
import asyncio

import pytest

from tests.test_emo_scenarios import emo  # noqa: F401  (fixture)
from tests.test_env_phase4b import T0, _stub_met


def _vignette(emo, name, met="standard"):
    from app import corridor_api
    from app.emo_examples import EXAMPLES
    v = EXAMPLES[name]["corridor"]

    async def go():
        await emo.load_example(name)
        await emo.run(emo.RunIn(met=met, met_time=T0), light=True)
        body = {k: v[k] for k in ("mover", "domain", "step_min", "alt_m", "speed_kmh") if k in v}
        return await corridor_api.plan_corridor(corridor_api.CorridorIn(**body, to_lat=v["to"][0], to_lon=v["to"][1], cell_m=1000))
    return asyncio.run(go())


def test_dismounted_patrol_on_foot_with_cold_batteries(emo, monkeypatch):
    _stub_met(monkeypatch)                                                    # 10 C: batteries at 80%
    r = _vignette(emo, "brecon-siting", met="forecast")
    s = r["summary"]
    assert r["domain"] == "foot" and s["speed_kmh"] == pytest.approx(4.0) and s["layers"] > 1
    assert any("batteries about 80%" in x for x in s["limit_reasons"])
    assert "slopes over 60%" in r["notes"] and r["legs"]


def test_civil_air_ambulance_counts_only_jamming_from_both_sides(emo):
    r = _vignette(emo, "suwalki-mdo")
    s = r["summary"]
    assert r["side"] == "grey" and r["domain"] == "air"
    assert s["max_p_detect"] == 0 and s["max_p_radar"] == 0 and s["sensors"] == [] and "Civil unit" in r["notes"]
    assert 0 < s["max_p_gnss"] < 100 and "collateral" in r and all("jammed_by" in lg for lg in r["legs"])
    assert set(s["gnss_jammers"]) == {"Red Pole-21 GNSS jammer (west)", "Red Pole-21 GNSS jammer (south-east)"}


def test_collateral_groups_jammers_by_side_and_leg():
    from app.corridor_api import _collateral
    ents = {1: {"name": "Red J", "side": "red"}, 2: {"name": "Blue J", "side": "blue"}}
    legs = [{"jammed_by": ["Red J"]}, {"jammed_by": ["Red J", "Blue J"]}, {"jammed_by": []}]
    assert _collateral(legs, ents) == {"red": [{"effector": "Red J", "legs": [1, 2]}], "blue": [{"effector": "Blue J", "legs": [2]}]}
