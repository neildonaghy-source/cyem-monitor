"""Phase 6 part 2: sub-surface exposure windows. Pure helpers, then the planner on synthetic sea with a throw-away
database (no network)."""
import asyncio

import numpy as np
import pytest

from app import exposure_core as xc
from tests.test_emo_scenarios import _add, _flat, emo  # noqa: F401  (fixture)


def test_combine_reach_and_dwell():
    assert np.isclose(xc.combine(0.5, 0.5), 0.75) and np.isclose(xc.combine(0.0, 0.0), 0.0)
    d = np.array([0.0, 4000.0, 6500.0])
    assert xc.reach_mask(d, 10, 0, 1000).tolist() == [True, False, False]
    assert xc.reach_mask(d, 10, 30, 1000).tolist() == [True, True, False]        # 5 km in 30 min, plus a cell
    assert xc.dwell_layers(10, 30) == 1 and xc.dwell_layers(45, 30) == 2 and xc.dwell_layers(10, 0) == 1


def test_windows_hold_the_same_cell_for_the_dwell_and_merge():
    risk = np.array([[[0.9, 0.1]], [[0.1, 0.5]], [[0.1, 0.1]], [[0.8, 0.8]]])   # K=4, one row, two cells
    use = np.ones_like(risk, bool)
    one = xc.windows(risk, use, [0, 30, 60, 90], 0.2, 1)
    assert [x["risk"] for x in one["layers"]] == [0.1, 0.1, 0.1, 0.8]
    assert [(w["t_from"], w["t_to"]) for w in one["windows"]] == [(0, 60)]
    two = xc.windows(risk, use, [0, 30, 60, 90], 0.2, 2)                         # mast up across two layers
    assert two["layers"][0]["risk"] == 0.5 and two["layers"][1]["cell"] == (0, 0) and two["layers"][1]["risk"] == 0.1
    assert [(w["t_from"], w["t_to"]) for w in two["windows"]] == [(30, 30)]
    none = xc.windows(risk, np.zeros_like(use), [0, 30, 60, 90], 0.2, 1)
    assert none["windows"] == [] and none["layers"][0]["cell"] is None


def _boat(emo, ctl_eirp=50):
    ctl = _add(emo, name="Blue MOC", side="blue", lat=51.3, lon=-1.0, eirp_dbm=ctl_eirp, h_agl=30, freq_mhz=250.0,
               sens_dbm=-110, js_req_db=0)
    ssk = _add(emo, name="Blue SSK", side="blue", kind="receiver", lat=51.0, lon=-1.0, eirp_dbm=40, h_agl=2, freq_mhz=250.0)
    with emo.get_db().tx() as cur:
        cur.execute("UPDATE emo_entities SET net=? WHERE id=?", (ctl["id"], ssk["id"]))


def test_mpa_gap_opens_a_window_and_the_radar_side_is_avoided(emo, monkeypatch):
    """Open sea. A red MPA (radar and ESM at 1000 m) is on station only T+0 to T+60; a red ship's radar sits 12 km east.
    The UHF mast finds no window while the MPA is up and one from T+60, on the side away from the ship."""
    from app import exposure_api
    _flat(monkeypatch, 0.0)
    _boat(emo)
    kw = dict(side="red", lat=51.0, lon=-1.0, h_agl=1000, schedule=[[0, 60]])
    _add(emo, name="Red MPA radar", kind="emitter", category="radar", freq_mhz=9500.0, bw_khz=20000, eirp_dbm=88, **kw)
    _add(emo, name="Red MPA ESM", kind="sensor", category="df", freq_mhz=2.0, f_hi_mhz=3000.0, sens_dbm=-110, df_rms_deg=5, **kw)
    _add(emo, name="Red ship radar", side="red", kind="emitter", category="radar", lat=51.0, lon=-0.83, h_agl=20,
         freq_mhz=9400.0, bw_khz=20000, eirp_dbm=85)

    async def go():
        await emo.run(emo.RunIn(), light=True)
        return await exposure_api.plan_exposure(exposure_api.ExposureIn(mover="Blue SSK", mast="uhf", radius_km=15, step_min=30,
                                                                        layers=4, cell_m=1000, speed_kmh=12))
    r = asyncio.run(go())
    L = r["layers"]
    assert [x["t"] for x in L] == [0, 30, 60, 90] and not L[0]["window"] and not L[1]["window"]
    assert L[2]["window"] and r["windows"] and r["windows"][0]["t_from"] == 60
    w = r["windows"][0]
    assert w["at"][1] < -0.95 and w["p_link"] >= 50 and w["risk_over_dwell"] <= 20      # west, away from the ship
    assert w["verified"]["p_link"] is not None and 0 <= w["verified"]["p_detect"] <= 100
    assert set(r["summary"]["radars"]) == {"Red MPA radar", "Red ship radar"} and "Red MPA ESM" in r["summary"]["sensors"]
    assert r["band"] and "Screening grade" in r["notes"] and "not applied" in r["notes"]
    assert L[0]["reach_km2"] < L[3]["reach_km2"]


def test_periscope_is_seen_only_by_radar_and_hf_follows_space_weather(emo, monkeypatch):
    from app import exposure_api
    _flat(monkeypatch, 0.0)
    _boat(emo)
    _add(emo, name="Red ESM", side="red", kind="sensor", category="df", lat=51.0, lon=-0.9, h_agl=20, freq_mhz=2.0,
         f_hi_mhz=3000.0, sens_dbm=-120, df_rms_deg=3)

    async def go(mast):
        await emo.run(emo.RunIn(), light=True)
        return await exposure_api.plan_exposure(exposure_api.ExposureIn(mover="Blue SSK", mast=mast, radius_km=8, step_min=0, cell_m=1000))
    peri, hf, uhf = asyncio.run(go("periscope")), asyncio.run(go("hf")), asyncio.run(go("uhf"))
    assert peri["summary"]["sensors"] == [] and peri["windows"] and peri["windows"][0]["p_esm"] == 0
    assert hf["layers"][0]["link"].startswith("HF ") and "skywave" in hf["notes"]
    assert uhf["summary"]["sensors"] == ["Red ESM"] and uhf["layers"][0]["best"]["p_esm"] >= peri["layers"][0]["best"]["p_esm"]


def test_refuses_land_only_areas_and_grey_units(emo, monkeypatch):
    from fastapi import HTTPException
    from app import exposure_api
    _flat(monkeypatch, 100.0)
    _boat(emo)
    _add(emo, name="Ferry", side="grey", kind="receiver", lat=51.0, lon=-1.0)

    async def go(name):
        await emo.run(emo.RunIn(), light=True)
        return await exposure_api.plan_exposure(exposure_api.ExposureIn(mover=name, step_min=0))
    for name, code in (("Blue SSK", 422), ("Ferry", 422), ("Nobody", 404)):
        with pytest.raises(HTTPException) as e:
            asyncio.run(go(name))
        assert e.value.status_code == code


def test_minches_vignette_plans(emo, monkeypatch):
    from app import exposure_api
    from app.emo_examples import EXAMPLES
    _flat(monkeypatch, 0.0)
    v = EXAMPLES["subsurface-minches"]["exposure"]

    async def go():
        r = await emo.load_example("subsurface-minches")
        assert r["exposure"] == v
        await emo.run(emo.RunIn(), light=True)
        body = {k: v[k] for k in ("mover", "mast", "dwell_min", "step_min", "layers", "radius_km", "eirp_dbm") if k in v}
        lo = await exposure_api.plan_exposure(exposure_api.ExposureIn(**body, cell_m=1000))
        full = await exposure_api.plan_exposure(exposure_api.ExposureIn(**{**body, "eirp_dbm": None}, cell_m=1000))
        return lo, full
    r, full = asyncio.run(go())
    assert len(r["layers"]) == v["layers"] and r["unit"] == "Blue SSK" and r["eirp_dbm"] == 26 and full["eirp_dbm"] == 40
    assert r["windows"] and r["windows"][0]["t_from"] == 60 and not full["windows"]        # the MPA's gap, at low power only
    assert {"Red MPA radar", "Red frigate radar"} <= set(r["summary"]["radars"]) | {"Red MPA radar"}
    assert "Red MPA radar" not in r["layers"][2]["radars"] and "Red MPA radar" in r["layers"][0]["radars"]   # T+60: off station


def test_hf_groundwave_rule():
    p = xc.hf_groundwave_p(np.array([0.0, 200.0, 250.0, 320.0, 400.0]))
    assert p[0] == 1.0 and p[1] == 1.0 and abs(p[2] - 0.5) < 1e-9 and p[3] == 0.0 and p[4] == 0.0
