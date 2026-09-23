"""AIS vessel positions, UK waters and approaches, from aisstream.io (free key).

aisstream is a websocket stream; the collector samples it for WINDOW_S seconds every
5 minutes, keeps each vessel's latest position for KEEP_MIN minutes and remembers
static data (name, type, call sign, destination) across runs. Key: AISSTREAM_KEY in .env.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone

from ..db import iso
from .base import Context, Result, register

URL = "wss://stream.aisstream.io/v0/stream"
BBOX = [[48.5, -11.5], [61.5, 3.5]]          # UK waters and approaches
WINDOW_S = 45
KEEP_MIN = 30
_static: dict[int, dict] = {}                 # MMSI -> static data, kept across runs
_pos: dict[int, dict] = {}                    # MMSI -> latest position


def category(t: int | None) -> str:
    if t is None:
        return "unknown"
    if t == 35:
        return "military"
    if t == 55:
        return "law"
    if t == 51:
        return "sar"
    if t == 30:
        return "fishing"
    if t in (31, 32, 52, 50, 53, 54, 58):
        return "service"
    if t in (36, 37):
        return "leisure"
    if 60 <= t <= 69:
        return "passenger"
    if 70 <= t <= 79:
        return "cargo"
    if 80 <= t <= 89:
        return "tanker"
    return "other"


@register("ais", interval_s=300, domain="em",
          description="AIS vessel positions, UK waters (aisstream.io websocket sample)")
async def collect_ais(ctx: Context) -> Result:
    import websockets
    key = os.environ.get("AISSTREAM_KEY", "").strip()
    if not key:
        return Result(0, "no AISSTREAM_KEY set")
    sub = {"APIKey": key, "BoundingBoxes": [BBOX],
           "FilterMessageTypes": ["PositionReport", "StandardClassBPositionReport", "ShipStaticData"]}
    n_msg = 0
    t_end = time.monotonic() + WINDOW_S
    async with websockets.connect(URL, open_timeout=20, ping_interval=20, max_size=2 ** 20) as ws:
        await ws.send(json.dumps(sub))
        while time.monotonic() < t_end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(0.5, t_end - time.monotonic()))
            except asyncio.TimeoutError:
                break
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            if "error" in m:
                raise RuntimeError(f"aisstream: {m['error']}")
            md, mt = m.get("MetaData") or {}, m.get("MessageType")
            mmsi = md.get("MMSI")
            if not mmsi:
                continue
            n_msg += 1
            body = (m.get("Message") or {}).get(mt) or {}
            if mt == "ShipStaticData":
                _static[mmsi] = {"type": body.get("Type"), "callsign": (body.get("CallSign") or "").strip(),
                                 "dest": (body.get("Destination") or "").strip(), "name": (body.get("Name") or "").strip()}
                continue
            lat, lon = md.get("latitude"), md.get("longitude")
            if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
                continue
            _pos[mmsi] = {"mmsi": mmsi, "lat": round(lat, 5), "lon": round(lon, 5), "sog": body.get("Sog"), "cog": body.get("Cog"),
                          "hdg": body.get("TrueHeading"), "name": (md.get("ShipName") or "").strip(), "t": time.time(),
                          "cls": "B" if mt == "StandardClassBPositionReport" else "A"}
    cutoff = time.time() - KEEP_MIN * 60
    for k in [k for k, v in _pos.items() if v["t"] < cutoff]:
        del _pos[k]
    vessels = []
    for mmsi, v in _pos.items():
        s = _static.get(mmsi, {})
        vessels.append({**{k: v[k] for k in ("mmsi", "lat", "lon", "sog", "cog", "hdg", "cls")},
                        "name": s.get("name") or v["name"], "type": s.get("type"), "cat": category(s.get("type")),
                        "callsign": s.get("callsign"), "dest": s.get("dest"),
                        "seen": iso(datetime.fromtimestamp(v["t"], timezone.utc))})
    ctx.db.set_snapshot("ais", {"vessels": vessels, "count": len(vessels), "messages": n_msg, "window_s": WINDOW_S,
                                "keep_min": KEEP_MIN, "bbox": BBOX, "source": "aisstream.io"})
    return Result(len(vessels), f"{len(vessels)} vessels ({n_msg} messages in {WINDOW_S}s)")
