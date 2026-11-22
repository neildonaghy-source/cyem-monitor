"""Spectrum by frequency and time for one net (phase 6 part 4), on flat synthetic terrain with a throw-away database."""
import asyncio

import pytest
from fastapi import HTTPException

from tests.test_emo_scenarios import _add, _flat, emo  # noqa: F401  (fixture)


def _plan(emo, name, before=None, **kw):
    from app import fqt_api
    from app.emo_examples import EXAMPLES
    v = {k: x for k, x in EXAMPLES[name]["spectrum"].items() if k != "note"}

    async def go():
        await emo.load_example(name)
        if before:
            before()
        await emo.run(emo.RunIn(), light=True)
        return await fqt_api.plan_spectrum(fqt_api.SpectrumIn(**{**v, **kw}))
    return asyncio.run(go())


def _wtr_row(emo, f_mhz, lat=51.21, lon=-1.79):
    from app import spectrum_store
    db = emo.get_db()
    spectrum_store.ensure_schema(db)
    with db.tx() as c:
        c.execute("INSERT INTO wtr (licence, freq_hz, bw_hz, station_type, company, product, lat, lon) VALUES (?,?,?,?,?,?,?,?)",
                  ("TEST1", f_mhz * 1e6, 12500, "T", "Test Radio Ltd", "Business Radio", lat, lon))


def test_battlegroup_net_moves_off_the_barrage_and_the_spot(emo, monkeypatch):
    _flat(monkeypatch)
    r = _plan(emo, "bg-vignette")
    assert r["band"] == [30.0, 88.0] and r["users"] and set(r["jammers"]) == {"Red VHF barrage", "Red VHF spot"}
    cur = r["current"]
    assert cur["f_mhz"] == 51.325 and cur["usable_steps"] < len(r["times"])          # the barrage and the spot reach it
    assert set(cur["jammers"]) == {"Red VHF barrage", "Red VHF spot"}
    for b in r["best"]:
        assert not (40 <= b["f_mhz"] <= 60) and b["usable_steps"] == len(r["times"])   # clear of the barrage
    inside = [c for c in r["channels"] if 41 < c["f_mhz"] < 59]
    assert inside and all(c["jammers"] == ["Red VHF barrage"] for c in inside if abs(c["f_mhz"] - 51.325) > 0.05)
    assert r["hopset"]["hop_khz"] == 58000 and r["hopset"]["usable_steps"] >= cur["usable_steps"]
    assert "usable throughout" in r["summary"] and r["wtr_checked"] is False


def test_deconfliction_own_civil_and_wtr(emo, monkeypatch):
    _flat(monkeypatch)
    _wtr_row(emo, 30.0125)

    def add_own():
        _add(emo, name="Blue other net", side="blue", lat=51.2, lon=-1.8, eirp_dbm=40, freq_mhz=30.0125, bw_khz=25)
        _add(emo, name="Civil PMR", side="grey", lat=51.2, lon=-1.8, eirp_dbm=30, freq_mhz=87.9875, bw_khz=25)
    r = _plan(emo, "bg-vignette", before=add_own)
    first, last = r["channels"][0], r["channels"][-1]
    assert first["f_mhz"] == 30.0125 and first["conflicts"]["own"] == ["Blue other net"]
    assert first["conflicts"]["wtr"]["count"] == 1 and first["conflicts"]["wtr"]["examples"][0]["product"] == "Business Radio"
    assert last["conflicts"]["civil"] == ["Civil PMR"]
    assert all(b["f_mhz"] not in (30.0125, 87.9875) for b in r["best"]) and r["wtr_checked"]


def test_hopping_division_net(emo, monkeypatch):
    _flat(monkeypatch)
    r = _plan(emo, "suwalki-mdo")
    assert r["current"]["hop_khz"] == 58000 and r["jammers"] == ["Red Borisoglebsk-2 VHF jammer"]
    assert all(not (35 <= b["f_mhz"] <= 55) for b in r["best"])


def test_errors(emo):
    from app import fqt_api

    async def go():
        await emo.load_example("bg-vignette")
        await emo.run(emo.RunIn(), light=True)
        out = []
        for kw in ({"net": "Nobody"}, {"net": "Blue A Coy"}, {"net": "Blue BG Main HQ", "lo_mhz": 60, "hi_mhz": 40}):
            try:
                await fqt_api.plan_spectrum(fqt_api.SpectrumIn(**kw))
                out.append(None)
            except HTTPException as e:
                out.append(e.status_code)
        return out
    assert asyncio.run(go()) == [404, 422, 422]
