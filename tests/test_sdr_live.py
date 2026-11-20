"""SDR live listening: the mode API (app/sdr_api.py), the /sdr/live/ proxy (app/sdr_live.py) and trade's agent
(pi/trade/cyem-sdr-mode) with fake systemctl/docker, lock and clocks."""
import importlib.machinery
import importlib.util
import pathlib

import httpx
import pytest

FUNNEL = {"tailscale-funnel-request": "?1"}
TOK = {"authorization": "Bearer s3cret"}
ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import auth as a, config, db as dbm, sdr_api
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(dbm, "_db", dbm.Database(str(tmp_path / "t.sqlite3")))
    monkeypatch.setenv("SDR_INGEST_TOKEN", "s3cret")
    a._schema_for.clear(); a._attempts.clear()
    sdr_api.ensure_sdr_schema(dbm.get_db())
    from app.emo_api import ensure_emo_schema
    ensure_emo_schema(dbm.get_db())
    from fastapi.testclient import TestClient
    from app.main import app
    yield TestClient(app, base_url="https://testserver")
    a._schema_for.clear(); a._attempts.clear()
    dbm.get_db()._conn.close()


def beat(client, state, capable=True, node="trade-sdr"):
    r = client.post("/api/sdr/heartbeat", json={"node": node, "state": state, "info": {"live_capable": capable, "junk": "x" * 9}},
                    headers=TOK)
    assert r.status_code == 200


def test_mode_set_expiry_and_token_only_get(client, monkeypatch):
    from app import sdr_api
    assert client.post("/api/sdr/mode", json={"node": "trade-sdr", "mode": "live"}).status_code == 404
    beat(client, "weather", capable=False, node="pi-sdr")
    assert client.post("/api/sdr/mode", json={"node": "pi-sdr", "mode": "live"}).status_code == 409
    beat(client, "weather")
    n = next(x for x in client.get("/api/sdr/nodes").json()["nodes"] if x["node"] == "trade-sdr")
    assert n["info"]["live_capable"] is True and "junk" not in n["info"] and n["mode"]["mode"] == "auto"
    assert client.post("/api/sdr/mode", json={"node": "trade-sdr", "mode": "live", "minutes": 121}).status_code == 422
    r = client.post("/api/sdr/mode", json={"node": "trade-sdr", "mode": "live"}).json()
    assert r["mode"] == "live" and 1790 <= r["remaining_s"] <= 1800 and r["set_by"] == "tailnet"
    assert client.get("/api/sdr/mode?node=trade-sdr").status_code == 401                       # the agent's view needs the token
    assert client.get("/api/sdr/mode?node=trade-sdr", headers={"authorization": "Bearer no"}).status_code == 401
    assert client.get("/api/sdr/mode?node=trade-sdr", headers=TOK).json()["mode"] == "live"
    t0 = sdr_api._now()
    monkeypatch.setattr(sdr_api, "_now", lambda: t0 + 31 * 60)                                 # lapses on its own
    m = client.get("/api/sdr/mode?node=trade-sdr", headers=TOK).json()
    assert m["mode"] == "auto" and m["lapsed"] is True
    monkeypatch.setattr(sdr_api, "_now", lambda: t0)
    assert client.post("/api/sdr/mode", json={"node": "trade-sdr", "mode": "auto"}).json()["mode"] == "auto"


def test_mode_post_follows_internet_login_and_cross_site_rules(client):
    from app import auth
    beat(client, "weather")
    body = {"node": "trade-sdr", "mode": "live", "minutes": 15}
    assert client.post("/api/sdr/mode", json=body, headers=FUNNEL).status_code == 401
    assert client.post("/api/sdr/mode", json=body, headers={"sec-fetch-site": "cross-site"}).status_code == 403
    auth.add_user("neil", "long enough password")
    assert client.post("/login", data={"username": "neil", "password": "long enough password", "next": "/"},
                       headers=FUNNEL, follow_redirects=False).status_code == 302
    r = client.post("/api/sdr/mode", json=body, headers=FUNNEL)
    assert r.status_code == 200 and r.json()["set_by"] == "neil"


def test_ingest_keeps_live_flag(client):
    beat(client, "weather")
    r = client.post("/api/sdr/ingest", headers=TOK, json={"node": "trade-sdr", "f0_hz": 24e6, "bin_hz": 250e3, "db": [-40.0] * 20,
                                                          "info": {"gain": "30"}})
    assert r.status_code == 200
    info = client.get("/api/sdr/nodes").json()["nodes"][0]["info"]
    assert info["live_capable"] is True and info["gain"] == "30" and info["state"] == "weather"


def test_proxy_refuses_unless_live_and_relays_when_live(client, monkeypatch):
    from app import sdr_live
    assert client.get("/sdr/live/").status_code == 503                                       # no node, not requested
    beat(client, "weather")
    assert client.get("/sdr/live/").status_code == 503
    client.post("/api/sdr/mode", json={"node": "trade-sdr", "mode": "live"})
    r = client.get("/sdr/live/")
    assert r.status_code == 503 and "switching" in r.json()["error"]                          # requested, node not live yet
    beat(client, "live")
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["cookie"] = str(req.url), req.headers.get("cookie")
        return httpx.Response(200, stream=httpx.ByteStream(b"<html>owrx</html>"), headers={"content-type": "text/html", "set-cookie": "a=b",
                                                                          "content-security-policy": "default-src *"})
    monkeypatch.setattr(sdr_live, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("SDR_LIVE_UPSTREAM", "http://owrx.test:8073")
    client.cookies.set("cyem_session", "secret")
    r = client.get("/sdr/live/static/x.js?v=1")
    client.cookies.clear()
    assert r.status_code == 200 and r.text == "<html>owrx</html>"
    assert seen == {"url": "http://owrx.test:8073/static/x.js?v=1", "cookie": None}           # CyEM's cookie stays here
    assert r.headers["content-security-policy"] == sdr_live.LIVE_CSP and "set-cookie" not in r.headers
    assert "allow-downloads" not in sdr_live.LIVE_CSP and "frame-ancestors 'self'" in sdr_live.LIVE_CSP
    assert client.get("/sdr/live/settings").status_code == 404                                 # admin pages stay on trade
    assert client.get("/sdr/live", follow_redirects=False).headers["location"] == "/sdr/live/"
    r = client.get("/sdr/live/", headers=FUNNEL, follow_redirects=False)                       # internet: sign in first
    assert r.status_code == 302 and r.headers["location"].startswith("/login")
    client.post("/api/sdr/mode", json={"node": "trade-sdr", "mode": "auto"})                  # Stop: refused at once
    assert client.get("/sdr/live/").status_code == 503
    # the dashboard's own CSP still frames 'self' and keeps script-src 'self' only
    csp = client.get("/").headers["content-security-policy"]
    assert "frame-src 'self'" in csp and "script-src 'self';" in csp


def test_proxy_websocket_refusals(client):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/sdr/live/ws/"):
            pass
    assert e.value.code == 1013                                                                # not live
    beat(client, "live")
    client.post("/api/sdr/mode", json={"node": "trade-sdr", "mode": "live"})
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/sdr/live/ws/", headers=FUNNEL):
            pass
    assert e.value.code == 1008                                                                # internet without a session
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/sdr/live/ws/", headers={"origin": "https://evil.example"}):
            pass
    assert e.value.code == 1008                                                                # another site's page


# ---------------------------------------------------------------- trade agent
def load_agent():
    path = str(ROOT / "pi" / "trade" / "cyem-sdr-mode")
    loader = importlib.machinery.SourceFileLoader("cyem_sdr_mode", path)
    spec = importlib.util.spec_from_loader("cyem_sdr_mode", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class FakeHttp:
    def __init__(self):
        self.m, self.beats = {"mode": "auto", "remaining_s": 0, "set_at": None}, []

    def mode(self):
        return self.m

    def beat(self, state, info):
        self.beats.append((state, info))


class FakeLock:
    def __init__(self):
        self.fd, self.other = None, False

    def acquire(self):
        if self.other:
            return False
        self.fd = 1
        return True

    def release(self):
        self.fd = None

    def held_by_other(self):
        return self.fd is None and self.other


@pytest.fixture
def rig():
    mod = load_agent()
    t = {"now": 1000.0}
    cmds, fail = [], set()

    def run(cmd):
        cmds.append(" ".join(cmd))
        return 1 if " ".join(cmd) in fail else 0
    http, lock = FakeHttp(), FakeLock()
    a = mod.Agent(http, run=run, lock=lock, clock=lambda: t["now"], wall=lambda: 1.7e9 + t["now"], sleep=lambda s: None)
    return mod, a, http, lock, cmds, t, fail


def test_agent_live_then_stop(rig):
    mod, a, http, lock, cmds, t, _ = rig
    assert a.tick() == "weather" and cmds == [] and http.beats[-1][1]["live_capable"] is True
    http.m = {"mode": "live", "remaining_s": 1800, "set_at": "s1"}
    assert a.tick() == "live" and lock.fd is not None
    assert cmds == ["systemctl stop ecowitt-receiver.service", "docker start cyem-openwebrx"]
    assert http.beats[-1][0] == "live" and http.beats[-1][1]["live_until"]
    http.m = {"mode": "auto", "remaining_s": 0, "set_at": "s2"}
    assert a.tick() == "weather" and lock.fd is None
    assert cmds[-2:] == ["docker stop cyem-openwebrx", "systemctl start ecowitt-receiver.service"]


def test_agent_waits_for_a_sweep_and_expires_locally(rig):
    mod, a, http, lock, cmds, t, _ = rig
    lock.other = True
    http.m = {"mode": "live", "remaining_s": 600, "set_at": "s1"}
    assert a.tick() == "sweeping" and cmds == []                                     # the sweep keeps the dongle
    lock.other = False
    assert a.tick() == "live"
    http.m = None                                                                    # CyEM unreachable: keep to the local deadline
    a.http.mode = lambda: None
    t["now"] += 300
    assert a.tick() == "live"
    t["now"] += 301
    assert a.tick() == "weather" and cmds[-1] == "systemctl start ecowitt-receiver.service"


def test_agent_hard_cap_and_failed_start_are_not_retried(rig):
    mod, a, http, lock, cmds, t, fail = rig
    http.m = {"mode": "live", "remaining_s": 10 * 3600, "set_at": "s1"}             # a server that forgot its own cap
    assert a.tick() == "live"
    t["now"] += mod.HARD_CAP_S + 1
    assert a.tick() == "weather" and "120-minute" in a.error
    assert a.tick() == "weather"                                                     # same request: not restarted
    fail.add("docker start cyem-openwebrx")
    http.m = {"mode": "live", "remaining_s": 900, "set_at": "s2"}
    n = len(cmds)
    assert a.tick() == "weather" and lock.fd is None and "docker start failed" in a.error
    assert cmds[n:] == ["systemctl stop ecowitt-receiver.service", "docker start cyem-openwebrx",
                        "docker stop cyem-openwebrx", "systemctl start ecowitt-receiver.service"]
    n = len(cmds)
    assert a.tick() == "weather" and cmds[n:] == []                                  # not retried until a new request
    a.restore()
    assert cmds[n:] == []                                                            # restore when idle does nothing
