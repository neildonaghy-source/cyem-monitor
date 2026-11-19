"""Audit fixes of 19 Nov 2026: collector health and time limit, EMO cache keys."""
import asyncio

import pytest


class _DB:
    def __init__(self):
        self.runs = []

    def start_run(self, name):
        pass

    def finish_run(self, name, ok, message, count, duration_s):
        self.runs.append((name, ok, message))


@pytest.fixture
def reg(monkeypatch):
    from app.collectors import base
    saved = dict(base.REGISTRY)
    yield base
    base.REGISTRY.clear()
    base.REGISTRY.update(saved)


def test_collector_health_follows_its_result(reg):
    @reg.register("t_degraded", interval_s=60, domain="cyber", description="test")
    async def degraded(ctx):
        return reg.Result(0, "0 new; 40 feeds failing", ok=False)

    db = _DB()
    res = asyncio.run(reg.run_collector(reg.Context(db, None), "t_degraded"))
    assert res.ok is False and db.runs[-1][:2] == ("t_degraded", False)


def test_hung_collector_is_cut_off(reg, monkeypatch):
    monkeypatch.setattr(reg, "RUN_TIMEOUT_S", 0.2)

    @reg.register("t_hung", interval_s=60, domain="cyber", description="test")
    async def hung(ctx):
        await asyncio.sleep(30)

    db = _DB()
    res = asyncio.run(reg.run_collector(reg.Context(db, None), "t_hung"))
    assert res.ok is False and "timed out" in res.message and db.runs[-1][1] is False


def test_emo_caches_see_power_and_frequency(monkeypatch):
    """A planning candidate reuses its id; an EP tune changes power or frequency within the same second. Either must
    give a fresh path and footprint, not the cached one."""
    from app import emo_api
    calls = []

    def fake_p2p(tx_pos, h_tx, rx_pos, h_rx, f_hz, eirp, atm):
        calls.append((f_hz, eirp))
        return eirp - 100.0
    monkeypatch.setattr(emo_api, "_p2p_sync", fake_p2p)
    emo_api._P2P.clear()
    e = {"id": "cand-ctrl", "updated_at": "", "h_agl": 10, "freq_mhz": 45.0, "eirp_dbm": 47.0, "pattern": "omni"}
    rx = {"id": "rx", "updated_at": "", "h_agl": 2}

    async def go(ent):
        return await emo_api.p2p_level(ent, (51.0, -1.0), rx, (51.1, -1.0))
    a = asyncio.run(go(e))
    b = asyncio.run(go({**e, "eirp_dbm": 37.0}))                 # EP: power down 10 dB
    c = asyncio.run(go({**e, "freq_mhz": 60.0}))                 # EP: retune
    asyncio.run(go(e))                                           # unchanged: from the cache
    assert round(a - b, 6) == 10.0 and len(calls) == 3
    assert calls[2][0] == 60.0e6
