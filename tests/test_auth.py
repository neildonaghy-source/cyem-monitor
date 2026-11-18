"""Internet log-in (app/auth.py): accounts, sessions, lockout, and the gate that applies only to Funnel requests."""
import time

import pytest

FUNNEL = {"tailscale-funnel-request": "?1"}


@pytest.fixture
def auth(tmp_path, monkeypatch):
    from app import auth as a, config, db as dbm
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(dbm, "_db", dbm.Database(str(tmp_path / "t.sqlite3")))
    a._schema_for.clear(); a._attempts.clear()
    yield a
    a._schema_for.clear(); a._attempts.clear()
    dbm.get_db()._conn.close()


@pytest.fixture
def client(auth):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.emo_api import ensure_emo_schema
    from app.db import get_db
    ensure_emo_schema(get_db())
    return TestClient(app, base_url="https://testserver")      # the session cookie is Secure


def test_password_hashing_and_rules(auth):
    h = auth.hash_password("correct horse battery")
    assert h.startswith("scrypt$") and auth.verify_password("correct horse battery", h)
    assert not auth.verify_password("correct horse batterY", h) and not auth.verify_password("x", "rubbish")
    with pytest.raises(ValueError, match="at least 12"):
        auth.add_user("neil", "short")
    with pytest.raises(ValueError, match="username"):
        auth.add_user("neil smith", "long enough password")
    auth.add_user("Neil", "long enough password")
    with pytest.raises(ValueError, match="already exists"):
        auth.add_user("neil", "another long password")
    assert [u["username"] for u in auth.list_users()] == ["neil"]


def test_lockout_after_repeated_failures(auth):
    auth.add_user("neil", "long enough password")
    for _ in range(auth.USER_TRIES - 1):
        assert auth.authenticate("neil", "wrong password!!") == (False, "bad")
    assert auth.authenticate("neil", "wrong password!!") == (False, "locked")
    assert auth.authenticate("neil", "long enough password") == (False, "locked")     # right password, still locked
    assert auth.list_users()[0]["locked"]
    auth.set_password("neil", "a new long password")                                  # an admin reset unlocks
    assert auth.authenticate("NEIL ", "a new long password") == (True, "ok")
    assert auth.authenticate("nobody", "whatever whatever") == (False, "bad")


def test_sessions_end_on_sign_out_password_change_and_expiry(auth):
    auth.add_user("neil", "long enough password")
    t1, t2 = auth.new_session("neil", "1.2.3.4", "ua"), auth.new_session("neil", "1.2.3.4", "ua")
    assert auth.session_user(t1) == auth.session_user(t2) == "neil"
    auth.end_session(t1)
    assert auth.session_user(t1) is None and auth.session_user(t2) == "neil"
    auth.set_password("neil", "a new long password")
    assert auth.session_user(t2) is None                                               # new password: all devices out
    t3 = auth.new_session("neil", "1.2.3.4", "ua")
    with auth._db().tx() as c:
        c.execute("UPDATE sessions SET expires=?", (time.time() - 1,))
    assert auth.session_user(t3) is None and auth.session_user("x" * 200) is None and auth.session_user(None) is None


def test_tailnet_needs_no_log_in(client):
    assert client.get("/api/me").json() == {"internet": False, "user": None}
    assert client.get("/api/emo").status_code == 200


def test_internet_fails_closed_and_logs_in(client, auth):
    assert client.get("/api/emo", headers=FUNNEL).status_code == 401
    r = client.get("/emo/x", headers=FUNNEL, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/login?next=/emo/x"
    form = {"username": "neil", "password": "long enough password", "next": "/"}
    assert client.post("/login", data=form, headers=FUNNEL, follow_redirects=False).status_code == 401   # no accounts yet
    auth.add_user("neil", "long enough password")
    r = client.post("/login", data={**form, "next": "//evil.example"}, headers=FUNNEL, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert "cyem_session=" in cookie and "HttpOnly" in cookie and "Secure" in cookie and "samesite=lax" in cookie.lower()
    assert client.get("/api/me", headers=FUNNEL).json() == {"internet": True, "user": "neil"}
    assert client.get("/api/emo", headers=FUNNEL).status_code == 200
    r = client.get("/logout", headers=FUNNEL, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/login"
    assert client.get("/api/emo", headers=FUNNEL).status_code == 401                  # session ended on the server


def test_address_rate_limit_and_sdr_token(client, auth, monkeypatch):
    auth.add_user("neil", "long enough password")
    bad = {"username": "neil", "password": "not the password", "next": "/"}
    for _ in range(auth.IP_TRIES):
        assert client.post("/login", data=bad, headers=FUNNEL).status_code == 401
    good = {"username": "neil", "password": "long enough password", "next": "/"}
    assert client.post("/login", data=good, headers=FUNNEL).status_code == 429       # this address must wait
    monkeypatch.setenv("SDR_INGEST_TOKEN", "s3cret")
    assert client.get("/api/emo", headers={**FUNNEL, "authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/api/emo", headers={**FUNNEL, "authorization": "Bearer nope"}).status_code == 401


def test_login_page_escapes_next(client):
    r = client.get('/login?next=/a"><script>alert(1)</script>', headers=FUNNEL)
    assert r.status_code == 200 and "<script>" not in r.text and 'name="username"' in r.text


def test_changes_from_another_site_are_refused_on_both_paths(client, auth):
    # /api/collect/<unknown> answers 404 once past the guard, so 404 means "allowed", 403 means "refused"
    post = lambda **h: client.post("/api/collect/no-such-collector", headers=h).status_code
    assert post() == 404                                                        # scripts and servers: no headers
    assert post(origin="https://testserver") == 404                             # a CyEM page
    assert post(**{"sec-fetch-site": "same-origin", "origin": "https://testserver"}) == 404
    assert post(**{"sec-fetch-site": "cross-site", "origin": "https://evil.example"}) == 403
    assert post(**{"sec-fetch-site": "same-site", "origin": "https://trade.tail013324.ts.net"}) == 403
    assert post(origin="https://evil.example") == 403                           # older browser: Origin alone
    assert post(origin="null") == 403                                           # sandboxed frame or data: page
    # behind a proxy that rewrites Host, X-Forwarded-Host carries the name the browser used
    assert post(host="127.0.0.1:3020", **{"x-forwarded-host": "cyem.example", "origin": "https://cyem.example"}) == 404
    # reading is never refused; the cross-site guard is for changes only
    assert client.get("/api/me", headers={"sec-fetch-site": "cross-site"}).status_code == 200
    # on the internet a forged sign-in is refused before the password is looked at
    auth.add_user("neil", "long enough password")
    form = {"username": "neil", "password": "long enough password", "next": "/"}
    r = client.post("/login", data=form, headers={**FUNNEL, "sec-fetch-site": "cross-site"}, follow_redirects=False)
    assert r.status_code == 403 and "set-cookie" not in r.headers
    r = client.post("/login", data=form, headers={**FUNNEL, "sec-fetch-site": "same-origin"}, follow_redirects=False)
    assert r.status_code == 302


def test_only_this_site_and_home_assistant_may_frame_it(client):
    from app.main import build_csp
    assert client.get("/").headers["content-security-policy"].endswith("frame-ancestors 'self'")    # default
    csp = build_csp("https://homeassistant.tail013324.ts.net, http://192.168.68.85:8123 'self' "
                    "https://*.example.org bad;script-src * 'unsafe-inline' javascript:alert(1)")
    fa = csp.split("frame-ancestors ", 1)[1]
    assert fa == "'self' https://homeassistant.tail013324.ts.net http://192.168.68.85:8123 https://*.example.org"
    assert csp.count(";") == build_csp().count(";")                            # nothing smuggled in as a directive
