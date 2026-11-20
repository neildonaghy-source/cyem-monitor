"""Live receiver through CyEM: /sdr/live/{path} is a reverse proxy (HTTP and WebSocket) to OpenWebRX+ on trade.

Users reach CyEM from the tailnet, from the native apps (a tagged node that may reach only the EVO on 443) and from the
internet through Funnel (log-in), so the receiver is never reached directly. The proxy answers only while the node has
been asked for live mode (sdr_api.mode_for) and reports state "live" by heartbeat; otherwise 503 (HTTP) or close 1013
(WebSocket). Listen-only: GET/HEAD and the audio/waterfall WebSocket; OpenWebRX's settings and log-in pages are not
passed through (Neil reaches those on trade directly). Nothing is stored: bytes are relayed and dropped.

Auth: HTTP requests go through LoginGate like the rest of the app. Starlette's HTTP middleware does not see WebSockets,
so the WebSocket handler applies the same rules itself: a Funnel request needs a session, and a browser's Origin must
be this site (a page elsewhere could otherwise open the audio stream from a tailnet browser).

Config: SDR_LIVE_UPSTREAM (default http://100.124.48.91:8073, trade's tailnet address), SDR_LIVE_NODE (trade-sdr)."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from starlette.background import BackgroundTask

from .db import get_db
from .sdr_api import mode_for

router = APIRouter(include_in_schema=False)
PREFIX = "/sdr/live"
STALE_S = 180                       # the agent heartbeats every 60 s while live
WATCH_S = 10                        # open WebSockets are closed within this long of live ending
BLOCKED = ("settings", "login", "logout", "pwchange", "imageupload")   # admin and upload pages stay on trade

# OpenWebRX's page uses inline onclick handlers, so script-src needs 'unsafe-inline' here (and only here). The sandbox
# keeps the origin (cookies and the WebSocket work) but leaves out allow-downloads, so its in-browser record button
# cannot save a file. frame-ancestors 'self': only the CyEM page frames it.
LIVE_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https:; connect-src 'self'; font-src 'self' data:; media-src 'self' blob:; "
            "worker-src 'self' blob:; frame-src 'none'; object-src 'none'; base-uri 'self'; form-action 'none'; "
            "frame-ancestors 'self'; sandbox allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-modals")
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding",
       "upgrade", "host", "cookie", "authorization", "content-length"}
DROP_RESP = {"connection", "keep-alive", "transfer-encoding", "set-cookie", "content-security-policy", "x-frame-options",
             "strict-transport-security"}
_client = None


def upstream() -> str:
    return os.environ.get("SDR_LIVE_UPSTREAM", "http://100.124.48.91:8073").rstrip("/")


def live_node() -> str:
    return os.environ.get("SDR_LIVE_NODE", "trade-sdr")


def live_status() -> tuple[bool, str]:
    """(ready, reason). Ready only while live is requested and the node says it is live and has checked in lately."""
    db = get_db()
    node = live_node()
    if mode_for(db, node)["mode"] != "live":
        return False, "live listening is not switched on (use Listen live in the SDR panel)"
    r = db.one("SELECT info, last_seen FROM sdr_nodes WHERE node=?", (node,))
    info = json.loads((r or {}).get("info") or "{}")
    if info.get("state") != "live":
        return False, "the receiver is still switching to live"
    try:
        age = (datetime.now(timezone.utc) - datetime.strptime(r["last_seen"], "%Y-%m-%dT%H:%M:%SZ")
               .replace(tzinfo=timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        age = 1e9
    if age > STALE_S:
        return False, "the receiver has not checked in for a few minutes"
    return True, ""


def _path_ok(path: str) -> bool:
    p = path.lstrip("/").lower()
    return ".." not in p and "\\" not in p and not p.startswith(BLOCKED)


def _http():
    global _client
    if _client is None:
        import httpx
        _client = httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5), follow_redirects=False)
    return _client


@router.get(PREFIX)
async def live_root():
    return RedirectResponse(PREFIX + "/", status_code=307)


@router.api_route(PREFIX + "/{path:path}", methods=["GET", "HEAD"])
async def live_http(path: str, request: Request):
    ok, why = live_status()
    if not ok:
        return JSONResponse({"error": why}, status_code=503, headers={"Cache-Control": "no-store"})
    if not _path_ok(path):
        return JSONResponse({"error": "not available through CyEM"}, status_code=404)
    url = f"{upstream()}/{path}" + (f"?{request.url.query}" if request.url.query else "")
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP and not k.lower().startswith(("x-forwarded", "tailscale-"))}
    client = _http()
    try:
        r = await client.send(client.build_request(request.method, url, headers=headers), stream=True)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"receiver not reachable: {type(e).__name__}"}, status_code=502)
    out = {k: v for k, v in r.headers.items() if k.lower() not in DROP_RESP}
    loc = out.get("location")
    if loc and loc.startswith("/") and not loc.startswith("//"):
        out["location"] = PREFIX + loc
    out["content-security-policy"] = LIVE_CSP
    out.setdefault("cache-control", "no-store")
    return StreamingResponse(r.aiter_raw(), status_code=r.status_code, headers=out, background=BackgroundTask(r.aclose))


def ws_allowed(ws: WebSocket) -> tuple[bool, str]:
    """The LoginGate rules for a WebSocket: same-site Origin on both paths, and a session for Funnel requests."""
    from .auth import COOKIE, session_user
    h = ws.headers
    origin = h.get("origin")
    if origin is not None:
        hosts = {(h.get("host") or "").lower(), (h.get("x-forwarded-host") or "").lower()} - {""}
        if origin == "null" or urlsplit(origin).netloc.lower() not in hosts:
            return False, "another site"
    if h.get("tailscale-funnel-request") and not session_user(ws.cookies.get(COOKIE)):
        return False, "sign in required"
    return True, ""


@router.websocket(PREFIX + "/{path:path}")
async def live_ws(ws: WebSocket, path: str):
    ok, _ = ws_allowed(ws)
    if not ok:
        return await ws.close(code=1008)
    ready, _ = live_status()
    if not ready or not _path_ok(path):
        return await ws.close(code=1013)                     # try again later
    try:
        from websockets.asyncio.client import connect
    except ImportError:                                      # websockets < 13
        from websockets import connect                       # type: ignore[no-redef]
    target = upstream().replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/" + path
    try:
        up = await connect(target, open_timeout=10, max_size=None, ping_interval=20)
    except Exception:  # noqa: BLE001
        return await ws.close(code=1011)
    await ws.accept()

    async def to_up():
        while True:
            m = await ws.receive()
            if m["type"] == "websocket.disconnect":
                return
            if m.get("text") is not None:
                await up.send(m["text"])
            elif m.get("bytes") is not None:
                await up.send(m["bytes"])

    async def to_client():
        async for m in up:
            if isinstance(m, str):
                await ws.send_text(m)
            else:
                await ws.send_bytes(m)

    async def watch():
        while True:
            await asyncio.sleep(WATCH_S)
            if not live_status()[0]:
                return

    tasks = [asyncio.create_task(t()) for t in (to_up, to_client, watch)]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await up.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
