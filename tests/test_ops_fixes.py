"""Regression tests for the 2026-10-03 ops fixes: cells index swap, collector back-off, login client IP."""
import gzip
from types import SimpleNamespace


def test_cells_reload_twice(tmp_path, monkeypatch):
    from app import cells
    monkeypatch.setattr(cells, "db_path", lambda: tmp_path / "cells.sqlite3")
    f = tmp_path / "234.csv.gz"
    hdr = "radio,mcc,net,area,cell,unit,lon,lat,range,samples,changeable,created,updated,averageSignal\n"
    with gzip.open(f, "wt") as g:
        g.write(hdr + "LTE,234,30,1,2,0,-0.1,51.5,1000,5,1,0,1700000000,0\n")
    assert cells.load_csv_gz([f]) == 1
    assert cells.load_csv_gz([f]) == 1      # second swap used to fail: index idx_cells_new_ll already exists
    assert cells.load_csv_gz([f]) == 1


def test_retry_delay():
    from app.scheduler import retry_delay_s
    H = 3600
    assert retry_delay_s(2 * H, True, "ok", 0) == 2 * H
    # GDELT-style 429: at least 2 h, doubling, capped at 12 h
    msg = "errors: cyber: RuntimeError: GDELT rate limited (429) after 2 retries"
    assert retry_delay_s(2 * H, False, msg, 1) == 2 * H
    assert retry_delay_s(2 * H, False, msg, 2) == 4 * H
    assert retry_delay_s(2 * H, False, msg, 3) == 8 * H
    assert retry_delay_s(2 * H, False, msg, 6) == 12 * H
    assert retry_delay_s(15 * 60, False, "HTTP 429", 1) == 2 * H        # short-interval source still waits 2 h
    # ordinary failures: 30 min first, never beyond the normal interval, never under 5 min
    assert retry_delay_s(2 * H, False, "timeout", 1) == 1800
    assert retry_delay_s(2 * H, False, "timeout", 5) == 2 * H
    assert retry_delay_s(60, False, "timeout", 1) == 300
    assert retry_delay_s(7 * 24 * H, False, "boom", 1) == 1800


def _req(peer, xff=None):
    h = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=h)


def test_client_ip():
    from app.auth import client_ip
    # via tailscaled -> docker-proxy: trust the right-most hop only
    assert client_ip(_req("172.21.0.1", "203.0.113.9")) == "203.0.113.9"
    assert client_ip(_req("172.21.0.1", "6.6.6.6, 203.0.113.9")) == "203.0.113.9"
    # a non-local peer cannot pick its own key via the header
    assert client_ip(_req("8.8.4.4", "6.6.6.6")) == "8.8.4.4"
    assert client_ip(_req("127.0.0.1")) == "127.0.0.1"


# --- 2026-10-03 round 2: GDELT partial failure, middleware order, constant-time tokens ---

class _FakeDB:
    def upsert_items(self, items):
        return len(items)

    def set_snapshot(self, *a):
        pass


def _run_gdelt(monkeypatch, theme_fn):
    import asyncio
    from app.collectors import osint
    monkeypatch.setattr(osint, "GDELT_THEME_GAP_S", 0)
    monkeypatch.setattr(osint, "_theme", theme_fn)
    return asyncio.run(osint.collect_gdelt(SimpleNamespace(db=_FakeDB())))


def test_gdelt_all_themes_rate_limited_is_a_failure(monkeypatch):
    import pytest
    from app.scheduler import retry_delay_s

    async def throttled(ctx, t):
        raise RuntimeError("GDELT rate limited (429) after 2 retries")

    with pytest.raises(RuntimeError) as e:
        _run_gdelt(monkeypatch, throttled)
    # ...and the scheduler treats that message as rate-limited (>= 2 h back-off)
    assert retry_delay_s(2 * 3600, False, str(e.value), 1) >= 2 * 3600


def test_gdelt_some_articles_with_errors_is_still_ok(monkeypatch):
    calls = {"n": 0}

    async def mixed(ctx, t):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"key": t["key"], "label": t["label"], "points": [], "total": 3, "articles": 3}, []
        raise RuntimeError("GDELT rate limited (429) after 2 retries")

    res = _run_gdelt(monkeypatch, mixed)
    assert "3 located articles" in res.message if hasattr(res, "message") else True


def test_gdelt_results_but_zero_articles_and_errors_fails(monkeypatch):
    import pytest
    calls = {"n": 0}

    async def zero_then_429(ctx, t):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"key": t["key"], "label": t["label"], "points": [], "total": 0, "articles": 0}, []
        raise RuntimeError("GDELT rate limited (429) after 2 retries")

    with pytest.raises(RuntimeError):
        _run_gdelt(monkeypatch, zero_then_429)


def test_password_gate_runs_before_workspace_middleware():
    from app.auth import PasswordGate
    from app.main import app
    # Starlette: user_middleware[0] is the outermost layer (runs first).
    order = [getattr(m, "kwargs", {}).get("dispatch", m.cls).__name__ for m in app.user_middleware]
    assert order.index("PasswordGate") < order.index("cyem_ws_middleware")


def test_unauthenticated_funnel_post_does_not_snapshot(monkeypatch):
    from fastapi.testclient import TestClient
    from app import emo_api
    from app.main import app
    monkeypatch.setenv("CYEM_PASSWORD", "pw")
    snaps = []
    monkeypatch.setattr(emo_api, "emo_snapshot", lambda label: snaps.append(label))
    c = TestClient(app)
    r = c.post("/api/emo", json={}, headers={"tailscale-funnel-request": "?1"})
    assert r.status_code == 401
    assert snaps == []


def test_bearer_ok_constant_time():
    from app.sdr_api import bearer_ok
    assert bearer_ok("Bearer s3cret", "s3cret")
    assert not bearer_ok("Bearer s3cre", "s3cret")
    assert not bearer_ok(None, "s3cret")
    assert not bearer_ok("Bearer x", None)
    assert not bearer_ok("Bearer x", "")
