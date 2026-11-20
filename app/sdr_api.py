"""SDR nodes (e.g. Raspberry Pi + RTL-SDR on the tailnet): sweep ingest, peaks labelled against UKFAT, node position.
Reception and display of spectrum occupancy only; no demodulated content is stored.

Live mode (Nov 2026): a user asks for live listening on a node (POST /api/sdr/mode, normal auth); the node's agent polls
GET /api/sdr/mode with the ingest token, frees the dongle, starts OpenWebRX+ and reports state "live" by heartbeat.
The receiver is then reached only through CyEM (app/sdr_live.py). The request lapses on its own after `minutes`
(default 30, at most 120). Audio is streamed, never stored."""
from __future__ import annotations

import json
import math
import hmac
import os
import re
import struct
import time
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .db import Database, get_db, now_iso
from .sdr_core import find_peaks, summary

router = APIRouter(prefix="/api/sdr", tags=["sdr"])
SQL = """
CREATE TABLE IF NOT EXISTS sdr_nodes (node TEXT PRIMARY KEY, url TEXT, lat REAL, lon REAL, pos_at TEXT, last_seen TEXT, info TEXT);
CREATE TABLE IF NOT EXISTS sdr_sweeps (id INTEGER PRIMARY KEY AUTOINCREMENT, node TEXT NOT NULL, ts TEXT NOT NULL,
  f0_hz REAL NOT NULL, bin_hz REAL NOT NULL, n INTEGER NOT NULL, data BLOB NOT NULL, peaks TEXT, lat REAL, lon REAL);
CREATE INDEX IF NOT EXISTS sdr_sweeps_node_ts ON sdr_sweeps(node, ts);
CREATE TABLE IF NOT EXISTS sdr_mode (node TEXT PRIMARY KEY, mode TEXT NOT NULL, until REAL, set_at TEXT, set_by TEXT);
"""
KEEP = 300


def ensure_sdr_schema(db: Database) -> None:
    with db.tx() as c:
        c.executescript(SQL)


class SweepIn(BaseModel):
    node: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    url: str | None = Field(default=None, max_length=200)
    f0_hz: float = Field(gt=0)
    bin_hz: float = Field(gt=0)
    db: list[float] = Field(min_length=10, max_length=40000)
    info: dict | None = None


class PosIn(BaseModel):
    lat: float = Field(ge=-85, le=85)
    lon: float = Field(ge=-180, le=180)


def _label(f_hz: float) -> str:
    """UK allocation at this frequency, e.g. 'MARITIME MOBILE; FIXED (156-174 MHz)'."""
    try:
        from .ukfat import lookup
        b = lookup(f_hz, 1)
        if b:
            svc = []
            for r in b[0].get("rows", [])[:3]:
                n = (r.get("service_name") or r.get("service") or "").strip()
                if n and n not in svc:
                    svc.append(n)
            return f"{'; '.join(svc)} ({b[0].get('band', '')})"[:110]
    except Exception:  # noqa: BLE001
        pass
    return "not listed in Ofcom's UKFAT table"


_LAST_REJECT: dict = {}                                  # the panel's empty state says why sweeps are not arriving


def _check(authorization: str | None, node: str) -> None:
    tok = os.environ.get("SDR_INGEST_TOKEN")
    if not bearer_ok(authorization, tok):
        _LAST_REJECT.update(at=now_iso(), node=node,
                            reason="ingest is off on this server (SDR_INGEST_TOKEN not set)" if not tok else "wrong token")
        raise HTTPException(401, "bad token")


def bearer_ok(authorization: str | None, tok: str | None) -> bool:
    """Constant-time check of an `Authorization: Bearer <tok>` header."""
    if not tok:
        return False
    return hmac.compare_digest((authorization or "").encode(), f"Bearer {tok}".encode())


@router.post("/ingest")
async def ingest(s: SweepIn, authorization: str | None = Header(default=None)):
    _check(authorization, s.node)
    db = get_db()
    node = db.one("SELECT * FROM sdr_nodes WHERE node=?", (s.node,))
    peaks = find_peaks(s.f0_hz, s.bin_hz, s.db)
    for p in peaks:
        p["label"] = _label(p["f_hz"])
    blob = struct.pack(f"<{len(s.db)}h", *[max(-32768, min(32767, int(round(v * 10)))) for v in s.db])
    now = now_iso()
    info = {**(json.loads(node["info"] or "{}") if node else {}), **(s.info or {})}   # keeps state and live_capable
    with db.tx() as c:
        c.execute("INSERT INTO sdr_nodes (node, url, last_seen, info) VALUES (?,?,?,?) ON CONFLICT(node) DO UPDATE SET "
                  "url=COALESCE(excluded.url, url), last_seen=excluded.last_seen, info=excluded.info",
                  (s.node, s.url, now, json.dumps(info)))
        c.execute("INSERT INTO sdr_sweeps (node, ts, f0_hz, bin_hz, n, data, peaks, lat, lon) VALUES (?,?,?,?,?,?,?,?,?)",
                  (s.node, now, s.f0_hz, s.bin_hz, len(s.db), blob, json.dumps(peaks),
                   node["lat"] if node else None, node["lon"] if node else None))
        c.execute("DELETE FROM sdr_sweeps WHERE node=? AND id NOT IN (SELECT id FROM sdr_sweeps WHERE node=? ORDER BY id DESC LIMIT ?)",
                  (s.node, s.node, KEEP))
    return {"ok": True, "peaks": len(peaks), **summary(s.db)}


class HeartbeatIn(BaseModel):
    node: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    url: str | None = Field(default=None, max_length=200)
    state: str = Field(max_length=80)                 # e.g. "no dongle", "weather", "live", "sweeping"
    info: dict | None = None                          # only the keys in _HB_KEYS are kept


_HB_KEYS = {"live_capable": bool, "live_until": str, "live_error": str}


@router.post("/heartbeat")
async def heartbeat(h: HeartbeatIn, authorization: str | None = Header(default=None)):
    """Node check-in without a sweep, so the panel shows it online with its state."""
    _check(authorization, h.node)
    db = get_db()
    node = db.one("SELECT info FROM sdr_nodes WHERE node=?", (h.node,))
    info = json.loads(node["info"] or "{}") if node else {}
    info["state"] = h.state
    for k, v in (h.info or {}).items():
        t = _HB_KEYS.get(k)
        if t and (v is None or isinstance(v, t)):
            info[k] = v[:160] if isinstance(v, str) else v
    with db.tx() as c:
        c.execute("INSERT INTO sdr_nodes (node, url, last_seen, info) VALUES (?,?,?,?) ON CONFLICT(node) DO UPDATE SET "
                  "url=COALESCE(excluded.url, url), last_seen=excluded.last_seen, info=excluded.info",
                  (h.node, h.url, now_iso(), json.dumps(info)))
    return {"ok": True}


@router.get("/nodes")
async def nodes():
    rows = get_db().query("SELECT n.*, (SELECT COUNT(*) FROM sdr_sweeps s WHERE s.node=n.node) AS sweeps FROM sdr_nodes n ORDER BY last_seen DESC")
    db = get_db()
    for r in rows:
        r["info"] = json.loads(r["info"] or "{}")
        r["mode"] = mode_for(db, r["node"])
    return {"nodes": rows, "ingest_enabled": bool(os.environ.get("SDR_INGEST_TOKEN")),
            "last_reject": dict(_LAST_REJECT) or None}


# ---- live mode: requested here, carried out by the node's agent (pi/trade/cyem-sdr-mode) ----------
LIVE_DEFAULT_MIN, LIVE_MAX_MIN = 30, 120
_now = time.time                                       # tests move the clock


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None


def mode_for(db: Database, node: str) -> dict:
    """The requested mode now: 'live' until it lapses, otherwise 'auto' (shared sweeps and the weather receiver)."""
    r = db.one("SELECT mode, until, set_at, set_by FROM sdr_mode WHERE node=?", (node,))
    now = _now()
    if r and r["mode"] == "live" and (r["until"] or 0) > now:
        return {"node": node, "mode": "live", "until": _iso(r["until"]), "remaining_s": int(r["until"] - now),
                "set_at": r["set_at"], "set_by": r["set_by"]}
    return {"node": node, "mode": "auto", "until": None, "remaining_s": 0, "set_at": r["set_at"] if r else None,
            "set_by": r["set_by"] if r else None, "lapsed": bool(r and r["mode"] == "live")}


class ModeIn(BaseModel):
    node: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    mode: Literal["live", "auto"]
    minutes: int = Field(default=LIVE_DEFAULT_MIN, ge=1, le=LIVE_MAX_MIN)


@router.get("/mode")
async def get_mode(node: str, authorization: str | None = Header(default=None)):
    """For the node's agent (ingest token only): what it should be doing now."""
    _check(authorization, node)
    return mode_for(get_db(), node)


@router.post("/mode")
async def set_mode(m: ModeIn, request: Request):
    """A user asks for live listening, or ends it ('auto'). Normal app auth: tailnet, or a signed-in internet session."""
    db = get_db()
    n = db.one("SELECT info FROM sdr_nodes WHERE node=?", (m.node,))
    if not n:
        raise HTTPException(404, "unknown node")
    if m.mode == "live" and not json.loads(n["info"] or "{}").get("live_capable"):
        raise HTTPException(409, "this receiver does not offer live listening")
    until = _now() + m.minutes * 60 if m.mode == "live" else None
    who = getattr(request.state, "user", None) or "tailnet"
    with db.tx() as c:
        c.execute("INSERT INTO sdr_mode (node, mode, until, set_at, set_by) VALUES (?,?,?,?,?) ON CONFLICT(node) DO UPDATE SET "
                  "mode=excluded.mode, until=excluded.until, set_at=excluded.set_at, set_by=excluded.set_by",
                  (m.node, m.mode, until, now_iso(), who))
    return mode_for(db, m.node)


@router.get("/latest")
async def latest(node: str, points: int = 1200):
    r = get_db().one("SELECT * FROM sdr_sweeps WHERE node=? ORDER BY id DESC LIMIT 1", (node,))
    if not r:
        return {"node": node, "empty": True, "reason": "no sweeps from this node yet"}
    vals = [v / 10 for v in struct.unpack(f"<{r['n']}h", r["data"])]
    step = max(1, len(vals) // max(100, min(points, 4000)))
    dec = [max(vals[i:i + step]) for i in range(0, len(vals), step)]    # max-hold keeps narrow carriers visible
    return {"node": node, "ts": r["ts"], "f0_hz": r["f0_hz"], "bin_hz": r["bin_hz"] * step, "db": dec,
            "peaks": json.loads(r["peaks"] or "[]"), "lat": r["lat"], "lon": r["lon"]}


@router.post("/nodes/{node}/position")
async def set_position(node: str, p: PosIn):
    with get_db().tx() as c:
        n = c.execute("UPDATE sdr_nodes SET lat=?, lon=?, pos_at=? WHERE node=?", (p.lat, p.lon, now_iso(), node)).rowcount
    if not n:
        raise HTTPException(404, "unknown node")
    return {"node": node, "lat": p.lat, "lon": p.lon}


class LocateIn(BaseModel):
    q: str = Field(min_length=2, max_length=120)


_LL = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")
_PC = re.compile(r"^\s*([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\s*$", re.I)
_UA = {"User-Agent": "CyEM-Monitor/1.0 (personal, self-hosted)"}


def resolve_place(q: str) -> tuple[float, float, str]:
    """lat,lon | UK postcode | place name  ->  (lat, lon, label). Raises HTTPException(400)."""
    import httpx
    m = _LL.match(q)
    if m:
        la, lo = float(m.group(1)), float(m.group(2))
        if -85 <= la <= 85 and -180 <= lo <= 180:
            return la, lo, f"{la:.5f}, {lo:.5f}"
    m = _PC.match(q)
    if m:
        pc = f"{m.group(1)} {m.group(2)}".upper()
        try:
            r = httpx.get(f"https://api.postcodes.io/postcodes/{pc.replace(' ', '')}", timeout=8)
            j = r.json()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"postcode lookup not reachable: {e}")
        if r.status_code == 200 and j.get("result"):
            return float(j["result"]["latitude"]), float(j["result"]["longitude"]), pc
        raise HTTPException(400, f"postcode {pc} not found")
    try:
        r = httpx.get("https://nominatim.openstreetmap.org/search", params={"q": q, "format": "json", "limit": 1, "countrycodes": "gb"},
                      headers=_UA, timeout=8)
        j = r.json() if r.status_code == 200 else []
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"place lookup not reachable: {e}")
    if not j:
        raise HTTPException(400, "not recognised: use a UK postcode, a place name or lat, lon (or Pick on map)")
    return float(j[0]["lat"]), float(j[0]["lon"]), j[0].get("display_name", q)[:80]


@router.post("/nodes/{node}/locate")
async def locate(node: str, body: LocateIn):
    import asyncio
    la, lo, label = await asyncio.to_thread(resolve_place, body.q)
    with get_db().tx() as c:
        n = c.execute("UPDATE sdr_nodes SET lat=?, lon=?, pos_at=? WHERE node=?", (round(la, 5), round(lo, 5), now_iso(), node)).rowcount
    if not n:
        raise HTTPException(404, "unknown node")
    return {"node": node, "lat": round(la, 5), "lon": round(lo, 5), "label": label}


# ---- correlation: licensed / exempt / public / government / unexplained ------------------------
@router.get("/correlate")
async def correlate(node: str, radius_km: float = 40, max_peaks: int = 40):
    """Latest sweep's peaks classified against public data from the receiver's position. Who/what/where come from
    licence records and live layers, not from listening. 'Where' for licensed matches is the licensed site."""
    from .sdr_classify import bearing, band_for, haversine_km, verdict
    from .spectrum_core import bbox_for_radius, looks_personal
    db = get_db()
    r = db.one("SELECT * FROM sdr_sweeps WHERE node=? ORDER BY id DESC LIMIT 1", (node,))
    if not r:
        raise HTTPException(404, "no sweeps from this node yet")
    n = db.one("SELECT lat, lon FROM sdr_nodes WHERE node=?", (node,)) or {}
    lat, lon = n.get("lat"), n.get("lon")
    peaks = json.loads(r["peaks"] or "[]")[:max_peaks]
    tol = max(r["bin_hz"] / 2, 25e3)
    lic_rows = []
    if lat is not None:
        s, nn, w, e = bbox_for_radius(lat, lon, radius_km)
        lic_rows = db.query("SELECT licence, freq_hz, bw_hz, company, product, emission, lat, lon, ant_height_m FROM wtr "
                            "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?", (s, nn, w, e))
    # live context, counted once
    ctx = {}
    if lat is not None:
        try:
            snap, _ = db.get_snapshot("air")
            ctx["aircraft"] = sum(1 for a in (snap or {}).get("aircraft", []) if haversine_km(lat, lon, a["lat"], a["lon"]) <= 150)
        except Exception:  # noqa: BLE001
            pass
        try:
            snap, _ = db.get_snapshot("ais")
            ships = [v for v in (snap or {}).get("vessels", []) if haversine_km(lat, lon, v["lat"], v["lon"]) <= 40]
            ctx["ships"] = len(ships)
            ctx["ship_names"] = [v.get("name") or f"MMSI {v['mmsi']}" for v in sorted(ships, key=lambda v: haversine_km(lat, lon, v["lat"], v["lon"]))[:5]]
        except Exception:  # noqa: BLE001
            pass
        try:
            from .cells import cells as cells_q
            dlat, dlon = 5 / 111.0, 5 / (111.0 * max(0.2, math.cos(math.radians(lat))))
            got = await cells_q(lat - dlat, lon - dlon, lat + dlat, lon + dlon, limit=2000)
            items = got.get("cells", got.get("items", [])) if isinstance(got, dict) else got
            ctx["cells_5km"] = len(items)
        except Exception:  # noqa: BLE001
            pass
    out, counts, tiers = [], {}, {}
    for p in peaks:
        f = p["f_hz"]
        band = band_for(f)
        lic = []
        for L in lic_rows:
            if abs(L["freq_hz"] - f) <= tol + (L["bw_hz"] or 0) / 2:
                d = haversine_km(lat, lon, L["lat"], L["lon"])
                if d <= radius_km:
                    who = L["company"] or ""
                    who = "Licensee withheld (individual)" if (not who or any(looks_personal(x.strip()) for x in who.split(";"))) else who
                    lic.append({"who": who, "what": L["product"], "licence": L["licence"], "f_mhz": round(L["freq_hz"] / 1e6, 5),
                                "emission": L["emission"], "dist_km": round(d, 1), "bearing": round(bearing(lat, lon, L["lat"], L["lon"])),
                                "lat": L["lat"], "lon": L["lon"]})
        lic.sort(key=lambda x: x["dist_km"])
        seen, uniq = set(), []
        for x in lic:                                  # one line per site and licensee
            k = (x["who"], round(x["lat"], 3), round(x["lon"], 3))
            if k not in seen:
                seen.add(k); uniq.append(x)
        status, text = verdict(band, uniq)
        context = None
        fm = f / 1e6
        if 1085 <= fm <= 1095 and "aircraft" in ctx:
            context = f"ADS-B: {ctx['aircraft']} aircraft within 150 km"
        elif 117.975 <= fm <= 137 and "aircraft" in ctx:
            context = f"Airband: {ctx['aircraft']} aircraft within 150 km"
        elif 156 <= fm <= 162.05 and "ships" in ctx:
            context = f"Maritime: {ctx['ships']} ships within 40 km" + (f" ({', '.join(ctx['ship_names'])})" if ctx.get("ship_names") else "")
        elif band and band[1].startswith("Mobile network") and "cells_5km" in ctx:
            context = f"{ctx['cells_5km']} mobile cells within 5 km"
        counts[status] = counts.get(status, 0) + 1
        if status == "unexplained":
            tier, why = "unaccounted", "No nearby licence and no band that explains it"
        elif status == "government" or (status == "licensed" and len(uniq) > 3):
            tier, why = "unsure", ("Government band: not in public data" if status == "government"
                                   else f"{len(uniq)} licensed candidates in this slice: cannot say which")
        else:
            tier, why = "accounted", ("Licensed assignment nearby" if status == "licensed" else f"Expected: {text.lower()}")
        tiers[tier] = tiers.get(tier, 0) + 1
        out.append({**p, "tier": tier, "tier_why": why, "status": status, "status_text": text, "band": band[1] if band else None,
                    "licences": uniq[:5], "licence_count": len(uniq), "context": context})
    return {"node": node, "ts": r["ts"], "position": {"lat": lat, "lon": lon} if lat is not None else None,
            "radius_km": radius_km, "tolerance_khz": round(tol / 1e3, 1), "counts": counts, "tiers": tiers, "peaks": out,
            "notes": "Correlation with public records only; nothing is demodulated. A licensed match means an assignment exists "
                     "within the sweep bin near you, not that it is the source. Position of licensed matches is the licensed site. "
                     "Unexplained = no nearby licence and no exempt/public band: a lead to investigate, not proof of unlicensed use."}
