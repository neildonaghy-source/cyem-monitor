"""Log-in for internet access.

Requests that come in from the internet through Tailscale Funnel carry the `Tailscale-Funnel-Request` header, which
tailscaled sets and a client cannot remove. Those requests need a session from /login: a username and password checked
against the `users` table (scrypt). Requests from the tailnet arrive without that header and pass straight through, as
before, so tailnet devices and the Home Assistant panel need no log-in. The token-protected SDR endpoints are exempt.

Fails closed: with no accounts set up, nobody gets in from the internet.
Accounts: python -m app.cli user add|passwd|del|list|signout <name>   (passwords are typed, never passed as arguments)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .db import get_db

COOKIE = "cyem_session"
TTL = 30 * 24 * 3600                       # a session lasts 30 days, then sign in again
TOUCH_S = 300                              # refresh last_seen at most every 5 minutes
MIN_PASSWORD = 12                          # length only, no composition rules (NCSC: three random words)
IP_TRIES, IP_WINDOW = 5, 900               # 5 failed sign-ins per address per 15 minutes
USER_TRIES, USER_LOCK = 10, 900            # 10 consecutive failures lock the account for 15 minutes
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
MAXMEM = 64 * 1024 * 1024
EXEMPT_PREFIX = ("/api/sdr/ingest", "/api/sdr/heartbeat", "/login", "/static/style.css", "/manifest", "/sw.js", "/icon")
_attempts: dict[str, list[float]] = {}
_schema_for: set[str] = set()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  username     TEXT PRIMARY KEY,
  pw_hash      TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  last_login   TEXT,
  failed       INTEGER NOT NULL DEFAULT 0,
  locked_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  username   TEXT NOT NULL,
  created    REAL NOT NULL,
  expires    REAL NOT NULL,
  last_seen  REAL NOT NULL,
  ip         TEXT,
  agent      TEXT
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(username);
"""

LOGIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CyEM Monitor</title><style>body{background:#0b1016;color:#e6edf3;font:16px system-ui,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
form{background:#141b24;border:1px solid #3c8cff;border-radius:10px;padding:28px 32px;width:min(360px,90vw)}h1{font-size:18px;letter-spacing:.08em;margin:0 0 16px}
input{width:100%;box-sizing:border-box;padding:10px;border-radius:6px;border:1px solid #2a3542;background:#0b1016;color:#e6edf3;font-size:16px;margin-bottom:12px}
button{width:100%;padding:10px;border-radius:6px;border:0;background:#3c8cff;color:#fff;font-size:16px}p.bad{color:#ff6b6b;margin:0 0 12px}p.ok{color:#45d38a;margin:0 0 12px}</style></head>
<body><form method="post" action="/login"><h1>CyEM <span style="color:#3c8cff">MONITOR</span></h1>{msg}
<input type="text" name="username" placeholder="Username" autofocus autocomplete="username" autocapitalize="none" spellcheck="false">
<input type="password" name="password" placeholder="Password" autocomplete="current-password">
<input type="hidden" name="next" value="{next}"><button>Sign in</button></form></body></html>"""


# ------------------------------------------------------------------ storage and hashing

def _db():
    db = get_db()
    if db.path not in _schema_for:
        with db.tx() as c:
            c.executescript(SCHEMA)
        _schema_for.add(db.path)
    return db


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, dklen=32, maxmem=MAXMEM, **SCRYPT)
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${_b64(salt)}${_b64(dk)}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        alg, n, r, p, salt, dk = stored.split("$")
        if alg != "scrypt":
            return False
        want = base64.b64decode(dk)
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(want), maxmem=MAXMEM)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


_DUMMY = hash_password(secrets.token_urlsafe(16))    # same cost for unknown usernames, so timing gives nothing away


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(username: str) -> str:
    return (username or "").strip().lower()


def check_new_password(pw: str) -> str | None:
    if len(pw) < MIN_PASSWORD:
        return f"at least {MIN_PASSWORD} characters (three random words works well)"
    return None


def add_user(username: str, pw: str) -> None:
    u = _norm(username)
    if not u or not u.replace("-", "").replace("_", "").replace(".", "").isalnum() or len(u) > 40:
        raise ValueError("username: letters, digits, '.', '-' or '_' only, up to 40 characters")
    bad = check_new_password(pw)
    if bad:
        raise ValueError("password: " + bad)
    with _db().tx() as c:
        if c.execute("SELECT 1 FROM users WHERE username=?", (u,)).fetchone():
            raise ValueError(f"user {u} already exists")
        c.execute("INSERT INTO users (username, pw_hash, created_at) VALUES (?,?,?)", (u, hash_password(pw), _now_iso()))


def set_password(username: str, pw: str) -> None:
    bad = check_new_password(pw)
    if bad:
        raise ValueError("password: " + bad)
    u = _norm(username)
    with _db().tx() as c:
        if not c.execute("UPDATE users SET pw_hash=?, failed=0, locked_until=0 WHERE username=?", (hash_password(pw), u)).rowcount:
            raise ValueError(f"no user {u}")
        c.execute("DELETE FROM sessions WHERE username=?", (u,))          # a new password signs out every device


def delete_user(username: str) -> bool:
    u = _norm(username)
    with _db().tx() as c:
        c.execute("DELETE FROM sessions WHERE username=?", (u,))
        return bool(c.execute("DELETE FROM users WHERE username=?", (u,)).rowcount)


def sign_out_everywhere(username: str) -> int:
    with _db().tx() as c:
        return c.execute("DELETE FROM sessions WHERE username=?", (_norm(username),)).rowcount


def list_users() -> list[dict]:
    db = _db()
    now = time.time()
    rows = db.query("SELECT username, created_at, last_login, failed, locked_until FROM users ORDER BY username")
    return [{**dict(r), "locked": r["locked_until"] > now,
             "sessions": db.one("SELECT COUNT(*) AS n FROM sessions WHERE username=? AND expires>?", (r["username"], now))["n"]}
            for r in rows]


def authenticate(username: str, pw: str) -> tuple[bool, str]:
    """(ok, reason). Locks the account for USER_LOCK seconds after USER_TRIES consecutive failures."""
    u = _norm(username)
    db = _db()
    row = db.one("SELECT pw_hash, failed, locked_until FROM users WHERE username=?", (u,))
    now = time.time()
    if row is None:
        verify_password(pw, _DUMMY)
        return False, "bad"
    if row["locked_until"] > now:
        verify_password(pw, _DUMMY)
        return False, "locked"
    if verify_password(pw, row["pw_hash"]):
        with db.tx() as c:
            c.execute("UPDATE users SET failed=0, locked_until=0, last_login=? WHERE username=?", (_now_iso(), u))
        return True, "ok"
    failed = row["failed"] + 1
    with db.tx() as c:
        c.execute("UPDATE users SET failed=?, locked_until=? WHERE username=?",
                  (0 if failed >= USER_TRIES else failed, now + USER_LOCK if failed >= USER_TRIES else 0, u))
    return False, "locked" if failed >= USER_TRIES else "bad"


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(username: str, ip: str, agent: str) -> str:
    tok = secrets.token_urlsafe(32)
    now = time.time()
    with _db().tx() as c:
        c.execute("DELETE FROM sessions WHERE expires<?", (now,))
        c.execute("INSERT INTO sessions (token_hash, username, created, expires, last_seen, ip, agent) VALUES (?,?,?,?,?,?,?)",
                  (_th(tok), _norm(username), now, now + TTL, now, ip, (agent or "")[:200]))
    return tok


def session_user(token: str | None) -> str | None:
    if not token or len(token) > 100:
        return None
    db = _db()
    row = db.one("SELECT username, expires, last_seen FROM sessions WHERE token_hash=?", (_th(token),))
    now = time.time()
    if row is None or row["expires"] < now:
        return None
    if now - row["last_seen"] > TOUCH_S:
        with db.tx() as c:
            c.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (now, _th(token)))
    return row["username"]


def end_session(token: str | None) -> None:
    if token:
        with _db().tx() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (_th(token),))


# ------------------------------------------------------------------ request handling

def safe_next(nxt: str | None) -> str:
    """Where to go after sign-in: a path on this site only. '//host' and '/\\host' are protocol-relative to a
    browser (an open redirect), and control characters or a scheme are refused; anything else falls back to '/'."""
    nxt = nxt or "/"
    if not nxt.startswith("/") or nxt.startswith(("//", "/\\")) or any(ord(ch) < 32 or ch == "\\" for ch in nxt):
        return "/"
    return nxt


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def _page(msg: str, nxt: str) -> str:
    return LOGIN_HTML.replace("{msg}", msg).replace("{next}", _esc(safe_next(nxt)))


def _is_local_proxy(host: str) -> bool:
    try:
        a = ipaddress.ip_address(host)
    except ValueError:
        return False
    return a.is_loopback or a.is_private


def client_ip(request: Request) -> str:
    """The real client address for the sign-in rate limit.

    The first X-Forwarded-For entry is whatever the client sent, so keying on it let anyone
    reset the 5-tries limit by changing the header. Only trust X-Forwarded-For when the TCP peer
    is our own proxy chain (tailscaled -> docker-proxy, i.e. a loopback/private address), and then
    take the right-most entry: the one our proxy appended, which the client cannot forge.
    (Checked 2026-10-03: tailscaled currently *replaces* X-Forwarded-For with the real Funnel client
    address, so this is defence in depth against a future proxy that appends instead.)"""
    peer = request.client.host if request.client else ""
    xff = request.headers.get("x-forwarded-for", "")
    if xff and _is_local_proxy(peer):
        hops = [h.strip() for h in xff.split(",") if h.strip()]
        if hops:
            return hops[-1]
    return peer or "?"


def from_internet(request: Request) -> bool:
    return bool(request.headers.get("tailscale-funnel-request"))


class LoginGate(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not from_internet(request):
            return await call_next(request)                 # tailnet and the box itself: no log-in
        path = request.url.path
        if path.startswith(EXEMPT_PREFIX):
            return await call_next(request)
        tok = os.environ.get("SDR_INGEST_TOKEN")
        if tok and hmac.compare_digest((request.headers.get("authorization") or "").encode(), f"Bearer {tok}".encode()):
            return await call_next(request)
        user = session_user(request.cookies.get(COOKIE))
        if user:
            request.state.user = user
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"error": "sign in required"}, status_code=401)
        return RedirectResponse(f"/login?next={quote(path, safe='/')}", status_code=302)


async def login_get(request: Request):
    return HTMLResponse(_page("", request.query_params.get("next", "/")))


async def login_post(request: Request):
    ip = client_ip(request)
    now = time.time()
    _attempts[ip] = [t for t in _attempts.get(ip, []) if now - t < IP_WINDOW]
    form = await request.form()
    nxt = str(form.get("next") or "/")
    if len(_attempts[ip]) >= IP_TRIES:
        return HTMLResponse(_page('<p class="bad">Too many attempts; try again in 15 minutes.</p>', nxt), status_code=429)
    ok, why = authenticate(str(form.get("username", "")), str(form.get("password", "")))
    if ok:
        _attempts.pop(ip, None)
        r = RedirectResponse(safe_next(nxt), status_code=302)
        r.set_cookie(COOKIE, new_session(str(form.get("username")), ip, request.headers.get("user-agent", "")),
                     max_age=TTL, httponly=True, secure=True, samesite="lax", path="/")
        return r
    _attempts[ip].append(now)
    msg = ("This account is locked for 15 minutes after repeated failures." if why == "locked"
           else "Wrong username or password.")
    return HTMLResponse(_page(f'<p class="bad">{msg}</p>', nxt), status_code=401)


async def logout(request: Request):
    end_session(request.cookies.get(COOKIE))
    r = RedirectResponse("/login" if from_internet(request) else "/", status_code=302)
    r.delete_cookie(COOKIE, path="/")
    return r


async def me(request: Request):
    """Who is signed in. Tailnet requests report internet=false and no user (no log-in needed there)."""
    return {"internet": from_internet(request), "user": getattr(request.state, "user", None)}
