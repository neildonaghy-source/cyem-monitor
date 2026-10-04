"""GDELT spread-out collector (2026-10-04): one theme per run round-robin,
per-theme 429 cooldown, partial success OK, explicit User-Agent."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.collectors import osint


class FakeDB:
    def __init__(self):
        self.snaps = {}
        self.items = []

    def get_snapshot(self, key):
        return self.snaps.get(key), None

    def set_snapshot(self, key, data):
        import json
        self.snaps[key] = json.loads(json.dumps(data, default=str))

    def upsert_items(self, items):
        self.items.extend(items)
        return len(items)


def _ok(ctx, t, total=2):
    return {"key": t["key"], "label": t["label"], "points": [], "total": total}, [{"id": t["key"]}]


def run(db, theme_fn, monkeypatch, per_run=1):
    monkeypatch.setattr(osint, "GDELT_THEMES_PER_RUN", per_run)
    monkeypatch.setattr(osint, "GDELT_THEME_GAP_S", (0, 0))
    monkeypatch.setattr(osint, "_theme", theme_fn)
    return asyncio.run(osint.collect_gdelt(SimpleNamespace(db=db)))


def test_collector_runs_every_30_min():
    from app.collectors.base import REGISTRY
    assert REGISTRY["gdelt"].interval_s == 30 * 60
    # 4 themes x 30 min: each theme refreshed every 2 h, as before
    assert len(osint.THEMES) * REGISTRY["gdelt"].interval_s == 2 * 3600


def test_one_theme_per_run_round_robin_and_persisted(monkeypatch):
    db, seen = FakeDB(), []

    async def fn(ctx, t):
        seen.append(t["key"])
        return _ok(ctx, t)

    for _ in range(len(osint.THEMES) + 1):
        run(db, fn, monkeypatch)
    keys = [t["key"] for t in osint.THEMES]
    assert seen == keys + keys[:1]
    # snapshot keeps every theme's latest result, not just this run's
    assert {t["key"] for t in db.snaps["gdelt"]["themes"]} == set(keys)
    assert db.snaps["gdelt_state"]["next"] == (len(keys) + 1) % len(keys)


def test_429_theme_cools_down_and_is_skipped(monkeypatch):
    db, seen = FakeDB(), []
    first = osint.THEMES[0]["key"]

    async def fn(ctx, t):
        seen.append(t["key"])
        if t["key"] == first:
            raise osint.GdeltRateLimited("GDELT rate limited (429) for " + first)
        return _ok(ctx, t)

    with pytest.raises(RuntimeError) as e:          # only theme tried this run failed
        run(db, fn, monkeypatch)
    from app.scheduler import retry_delay_s
    assert retry_delay_s(1800, False, str(e.value), 1) >= 2 * 3600   # 429 back-off kept
    st = db.snaps["gdelt_state"]["themes"][first]
    until = datetime.fromisoformat(st["cooldown_until"].replace("Z", "+00:00"))
    assert until - datetime.now(timezone.utc) > timedelta(hours=1, minutes=55)
    for _ in range(len(osint.THEMES)):              # a full lap: first theme skipped
        run(db, fn, monkeypatch)
    assert seen.count(first) == 1


def test_cooldown_escalates_and_caps():
    assert osint.cooldown_s(1) == 2 * 3600
    assert osint.cooldown_s(2) == 4 * 3600
    assert osint.cooldown_s(3) == 8 * 3600
    assert osint.cooldown_s(9) == 12 * 3600


def test_partial_success_is_ok_but_429_theme_still_backs_off(monkeypatch):
    db = FakeDB()
    bad = osint.THEMES[1]["key"]

    async def fn(ctx, t):
        if t["key"] == bad:
            raise osint.GdeltRateLimited("GDELT rate limited (429) for " + bad)
        return _ok(ctx, t, total=0)                  # success with 0 located articles still counts

    res = run(db, fn, monkeypatch, per_run=2)
    assert "errors:" in res.message and bad in res.message
    assert db.snaps["gdelt_state"]["themes"][bad]["cooldown_until"]
    assert not db.snaps["gdelt_state"]["themes"][osint.THEMES[0]["key"]]["cooldown_until"]


def test_all_themes_cooling_down_is_quiet_ok(monkeypatch):
    db = FakeDB()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    db.snaps["gdelt_state"] = {"next": 0, "themes": {t["key"]: {"cooldown_until": future} for t in osint.THEMES}}

    async def fn(ctx, t):
        raise AssertionError("must not request while cooling down")

    res = run(db, fn, monkeypatch)
    assert "cooling down" in res.message


def test_request_uses_user_agent_and_no_inrun_retry(monkeypatch):
    calls = []

    class R:
        status_code = 429

    class Http:
        async def get(self, url, **kw):
            calls.append(kw)
            return R()

    monkeypatch.setattr(osint, "GDELT_MIN_SPACING_S", 0)
    with pytest.raises(osint.GdeltRateLimited):
        asyncio.run(osint._theme(SimpleNamespace(http=Http()), osint.THEMES[0]))
    assert len(calls) == 1
    ua = calls[0]["headers"]["User-Agent"]
    assert ua.startswith("CyEM-Monitor/") and "github.com" in ua


def test_min_spacing_between_requests(monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(osint.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(osint, "_last_request_at", osint.time.monotonic())
    asyncio.run(osint._respect_spacing())
    assert slept and 4 < slept[0] <= 5
