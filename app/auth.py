"""Password gate for public (Tailscale Funnel) access.

Tailnet requests arrive through `tailscale serve` with Tailscale identity headers and pass straight through. Anything
else (Funnel) needs a signed cookie obtained from /login with the shared password. Token-protected SDR endpoints are
exempt (the Pi is a tagged node with no identity headers). Disabled entirely when CYEM_PASSWORD is unset."""
from __future__ import annotations

import hashlib
import hmac
import os
import time

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

COOKIE = "cyem_auth"
TTL = 30 * 24 * 3600
EXEMPT_PREFIX = ("/api/sdr/ingest", "/api/sdr/heartbeat", "/login", "/static/style.css", "/manifest", "/sw.js", "/icon")
_attempts: dict[str, list[float]] = {}

LOGIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CyEM Monitor</title><style>body{background:#0b1016;color:#e6edf3;font:16px system-ui,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
form{background:#141b24;border:1px solid #3c8cff;border-radius:10px;padding:28px 32px;width:min(360px,90vw)}h1{font-size:18px;letter-spacing:.08em;margin:0 0 16px}
input{width:100%;box-sizing:border-box;padding:10px;border-radius:6px;border:1px solid #2a3542;background:#0b1016;color:#e6edf3;font-size:16px;margin-bottom:12px}
button{width:100%;padding:10px;border-radius:6px;border:0;background:#3c8cff;color:#fff;font-size:16px}p.bad{color:#ff6b6b;margin:0 0 12px}</style></head>
<body><form method="post" action="/login"><h1>CyEM <span style="color:#3c8cff">MONITOR</span></h1>{msg}<input type="password" name="password" placeholder="Password" autofocus autocomplete="current-password">
<input type="hidden" name="next" value="{next}"><button>Sign in</button></form></body></html>"""


def _page(msg: str, nxt: str) -> str:
    return LOGIN_HTML.replace("{msg}", msg).replace("{next}", nxt.replace('"', ""))


def _secret() -> bytes:
    return (os.environ.get("CYEM_SECRET") or os.environ.get("CYEM_PASSWORD") or "").encode()


def _token(exp: int) -> str:
    return f"{exp}.{hmac.new(_secret(), str(exp).encode(), hashlib.sha256).hexdigest()}"


def _valid(tok: str | None) -> bool:
    if not tok or "." not in tok:
        return False
    exp, sig = tok.split(".", 1)
    return exp.isdigit() and int(exp) > time.time() and hmac.compare_digest(sig, _token(int(exp)).split(".", 1)[1])


class PasswordGate(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        pw = os.environ.get("CYEM_PASSWORD")
        if not pw:
            return await call_next(request)
        path = request.url.path
        if request.headers.get("tailscale-user-login") or path.startswith(EXEMPT_PREFIX) or _valid(request.cookies.get(COOKIE)):
            return await call_next(request)
        tok = os.environ.get("SDR_INGEST_TOKEN")
        if tok and request.headers.get("authorization") == f"Bearer {tok}":
            return await call_next(request)
        if path.startswith("/api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "sign in required"}, status_code=401)
        return RedirectResponse(f"/login?next={path}", status_code=302)


async def login_get(request: Request):
    return HTMLResponse(_page("", request.query_params.get("next", "/")))


async def login_post(request: Request):
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    now = time.time()
    _attempts[ip] = [t for t in _attempts.get(ip, []) if now - t < 900]
    if len(_attempts[ip]) >= 5:
        return HTMLResponse(_page('<p class="bad">Too many attempts; try again in 15 minutes.</p>', "/"), status_code=429)
    form = await request.form()
    if hmac.compare_digest(str(form.get("password", "")), os.environ.get("CYEM_PASSWORD", "")):
        nxt = str(form.get("next") or "/")
        r = RedirectResponse(nxt if nxt.startswith("/") else "/", status_code=302)
        r.set_cookie(COOKIE, _token(int(now + TTL)), max_age=TTL, httponly=True, secure=True, samesite="lax")
        return r
    _attempts[ip].append(now)
    return HTMLResponse(_page('<p class="bad">Wrong password.</p>', str(form.get("next") or "/")), status_code=401)
