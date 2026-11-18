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

# GDELT tests moved to tests/test_gdelt_spread.py (round-robin rewrite, 2026-10-04)


def test_password_gate_runs_before_workspace_middleware():
    from app.auth import LoginGate
    from app.main import app
    # Starlette: user_middleware[0] is the outermost layer (runs first).
    order = [getattr(m, "kwargs", {}).get("dispatch", m.cls).__name__ for m in app.user_middleware]
    assert order.index("LoginGate") < order.index("cyem_ws_middleware")


def test_unauthenticated_funnel_post_does_not_snapshot(monkeypatch):
    from fastapi.testclient import TestClient
    from app import emo_api
    from app.main import app
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
