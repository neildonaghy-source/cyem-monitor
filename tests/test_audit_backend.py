"""Audit follow-ups of 19 Nov 2026: the EMO coverage cache (float32, least recently used), the scheduled brief's
retry and back-off, and the UKFAT coverage check."""
import asyncio
import json

import numpy as np


# ---- EMO coverage cache -----------------------------------------------------------------------------------
def _fake_compute(calls):
    from app.coverage_core import Coverage

    def compute(s):
        calls.append(s.lat)
        prx = np.linspace(-130.0, -40.0, 36 * 11, dtype=np.float64).reshape(36, 11) + s.lat   # float64 on purpose
        return Coverage(s.lat, s.lon, 100.0, 36, prx), {}
    return compute


def test_coverage_cache_is_float32_and_lru(monkeypatch):
    from app import emo_api
    calls = []
    monkeypatch.setattr(emo_api, "_compute", _fake_compute(calls))
    monkeypatch.setattr(emo_api, "_HEAVY", asyncio.Semaphore(3))
    monkeypatch.setattr(emo_api, "COV_MAX", 3)
    emo_api._COV.clear()
    e = {"id": "x", "name": "x", "updated_at": "", "h_agl": 10, "freq_mhz": 45.0, "bw_khz": 25, "eirp_dbm": 76.0,
         "pattern": "omni", "radius_km": 1.0}

    async def go(lat):
        return await emo_api.coverage_for(e, (lat, -1.0), 2.0)

    a = asyncio.run(go(51.0))
    assert a.prx.dtype == np.float32
    want = (np.linspace(-130.0, -40.0, 396).reshape(36, 11) + 51.0 + 6.0).astype(np.float32)   # +6 dB above the 70 dBm cap
    assert np.array_equal(a.prx, want)
    json.dumps({"v": a.level_dbm(51.0, -0.9995), "packed": a.pack()})   # what the API sends still serialises
    asyncio.run(go(52.0)); asyncio.run(go(53.0))
    assert asyncio.run(go(51.0)) is a and len(calls) == 3          # a hit, and 51 becomes most recently used
    asyncio.run(go(54.0))                                           # evicts 52, the least recently used
    assert len(emo_api._COV) == 3
    asyncio.run(go(51.0)); asyncio.run(go(53.0))
    assert len(calls) == 4
    asyncio.run(go(52.0))
    assert len(calls) == 5                                          # 52 had gone and was computed again
    emo_api._COV.clear()


# ---- scheduled brief retry ----------------------------------------------------------------------------------
def test_scheduled_brief_retries_with_backoff_then_stops():
    from app.scheduler import BRIEF_RETRY_DELAYS_S, scheduled_brief
    slept, tries = [], []

    async def sleep(s):
        slept.append(s)

    async def gen(db, kind):
        tries.append(kind)
        return {"ok": False, "error": "ConnectError"}
    r = asyncio.run(scheduled_brief(None, "2026-11-19T07", generate=gen, busy=lambda: False, sleep=sleep))
    assert not r["ok"] and len(tries) == 4 and slept == list(BRIEF_RETRY_DELAYS_S) == [600, 1200, 2400]


def test_scheduled_brief_stops_on_success_and_waits_for_a_brief_in_flight():
    from app.scheduler import BRIEF_BUSY_POLL_S, scheduled_brief
    slept, results = [], [{"ok": False, "error": "timeout"}, {"ok": True, "id": 7}]
    busy = [True, True, False]                       # a manual brief is generating when the first retry falls due

    async def sleep(s):
        slept.append(s)

    async def gen(db, kind):
        return results.pop(0)

    def is_busy():
        return busy.pop(0) if busy and len(slept) >= 1 else False
    r = asyncio.run(scheduled_brief(None, "slot", generate=gen, busy=is_busy, sleep=sleep))
    assert r == {"ok": True, "id": 7}
    assert slept == [600, BRIEF_BUSY_POLL_S, BRIEF_BUSY_POLL_S]


# ---- UKFAT ---------------------------------------------------------------------------------------------------
def test_ukfat_band_labels_with_digit_groups():
    from app.ukfat import _BAND, _norm_band
    assert _norm_band("15 800 – 16 360 kHz") == "15800 – 16360 kHz"
    assert _BAND.match(_norm_band("15 800 – 16 360 kHz"))
    assert _norm_band("16.36 – 17.41 MHz") == "16.36 – 17.41 MHz"
    assert _norm_band("16360 – 17410 kHz MOBILE 5.145 UK12 345").endswith("MOBILE 5.145 UK12 345")   # footnotes untouched


def test_ukfat_coverage_gaps():
    from app.ukfat import coverage_gaps
    ents = [{"lo_hz": 8.3e3, "hi_hz": 16.30e6}, {"lo_hz": 16.36e6, "hi_hz": 1e9}, {"lo_hz": 1e9, "hi_hz": 275e9}]
    assert coverage_gaps(ents) == [(16.30e6, 16.36e6)]
    assert coverage_gaps(ents[:1] + [{"lo_hz": 16.0e6, "hi_hz": 275e9}]) == []
