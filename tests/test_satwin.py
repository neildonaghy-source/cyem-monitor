"""Satcom and GNSS windows through a scenario (phase 6 part 3), on synthetic terrain with a throw-away database."""
import asyncio

import numpy as np
import pytest

from tests.test_emo_scenarios import _flat, emo  # noqa: F401  (fixture)
from tests.test_env_phase4b import T0, _stub_met, _sw


def _plan(emo, name, met="standard", **kw):
    from app import satwin_api
    from app.emo_examples import EXAMPLES
    v = {k: x for k, x in (EXAMPLES[name].get("windows") or {}).items() if k != "note"}

    async def go():
        await emo.load_example(name)
        await emo.run(emo.RunIn(met=met, met_time=T0), light=True)
        return await satwin_api.plan_windows(satwin_api.WindowsIn(**{**v, **kw}))
    return asyncio.run(go())


def test_satcom_window_opens_while_the_uplink_jammer_is_off(emo, monkeypatch):
    _flat(monkeypatch, 20.0)                                               # flat: the satellite clears the horizon
    r = _plan(emo, "littoral-a2ad")
    sat = r["satcom"]
    assert sat["terminal"] == "Blue raid SATCOM" and sat["slot_from"] == "where the antenna points" and sat["pointing"] is None
    assert sat["jammers_considered"] == ["Red satcom uplink jammer"]
    st = {row["t"]: row["status"] for row in sat["rows"]}
    assert st[0] == "denied" and st[50] == "clear" and st[80] == "denied"
    assert sat["windows"] == [{"from_min": 40.0, "to_min": 60.0, "steps": 3}]
    assert all(10 < row["el"] < 16 and row["visible"] for row in sat["rows"])


def test_terrain_blocks_the_satellite(emo, monkeypatch):
    from app import dem
    # a 2 km ridge 3 km south of the raid HQ (68.10 N 13.855 E)
    z = lambda la, lo: np.where((np.asarray(la, float) < 68.08) & (np.asarray(la, float) > 68.06), 2000.0, 20.0)   # noqa: E731
    monkeypatch.setattr(dem, "heights", lambda pts: [float(z(a, b)) for a, b in pts])
    monkeypatch.setattr(dem, "grid_sampler", lambda s, w, n, e, res_deg=1 / 1800: (lambda la, lo: z(la, lo).astype(np.float32)))
    sat = _plan(emo, "littoral-a2ad")["satcom"]
    assert all(row["status"] == "blocked" and row["horizon"] > row["el"] for row in sat["rows"]) and sat["windows"] == []


def test_gnss_windows_follow_the_moving_jammer(emo, monkeypatch):
    _flat(monkeypatch)
    r = _plan(emo, "a303-gnss")
    users = {u["user"]: u for u in r["gnss"]["users"]}
    assert set(users) == {"Blue GNSS user (airfield)", "Blue GNSS user (Larkhill)"} and "satcom" not in r
    assert set(r["gnss"]["effectors"]) == {"Red GNSS jammer (vehicle)", "Red GNSS spoofer (van)"}
    for u in users.values():
        sts = [row["status"] for row in u["rows"]]
        assert "denied" in sts or "deceived" in sts                         # the jammer passes close by
        assert all(row["req_db"] == 35 and row["space_db"] == 0 for row in u["rows"])
    air = users["Blue GNSS user (airfield)"]["rows"]
    assert air[0]["noise_js_db"] < air[-1]["noise_js_db"]                   # the jammer drives towards the airfield


def test_space_weather_lowers_the_gnss_threshold(emo, monkeypatch):
    _flat(monkeypatch)
    _stub_met(monkeypatch)
    _sw(emo, g=3)
    r = _plan(emo, "a303-gnss", met="forecast")
    rows = r["gnss"]["users"][0]["rows"]
    assert all(row["space_db"] == 3.0 and row["req_db"] == 32 for row in rows) and "space weather for each step" in r["notes"]


def test_errors(emo):
    from app import satwin_api
    from fastapi import HTTPException

    async def go():
        await emo.load_example("littoral-a2ad")
        await emo.run(emo.RunIn(), light=True)
        out = []
        for name in ("Nobody", "Blue LPD ES"):
            try:
                await satwin_api.plan_windows(satwin_api.WindowsIn(terminal=name))
            except HTTPException as e:
                out.append(e.status_code)
        return out
    assert asyncio.run(go()) == [404, 422]
