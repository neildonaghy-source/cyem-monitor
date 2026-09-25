"""SDR nodes (e.g. Raspberry Pi + RTL-SDR on the tailnet): sweep ingest, peaks labelled against UKFAT, node position.
Reception and display of spectrum occupancy only; no demodulated content is stored."""
from __future__ import annotations

import json
import os
import struct

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .db import Database, get_db, now_iso
from .sdr_core import find_peaks, summary

router = APIRouter(prefix="/api/sdr", tags=["sdr"])
SQL = """
CREATE TABLE IF NOT EXISTS sdr_nodes (node TEXT PRIMARY KEY, url TEXT, lat REAL, lon REAL, pos_at TEXT, last_seen TEXT, info TEXT);
CREATE TABLE IF NOT EXISTS sdr_sweeps (id INTEGER PRIMARY KEY AUTOINCREMENT, node TEXT NOT NULL, ts TEXT NOT NULL,
  f0_hz REAL NOT NULL, bin_hz REAL NOT NULL, n INTEGER NOT NULL, data BLOB NOT NULL, peaks TEXT, lat REAL, lon REAL);
CREATE INDEX IF NOT EXISTS sdr_sweeps_node_ts ON sdr_sweeps(node, ts);
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
    return "not in parsed UKFAT (parser gap)"


@router.post("/ingest")
async def ingest(s: SweepIn, authorization: str | None = Header(default=None)):
    tok = os.environ.get("SDR_INGEST_TOKEN")
    if not tok or authorization != f"Bearer {tok}":
        raise HTTPException(401, "bad token")
    db = get_db()
    node = db.one("SELECT * FROM sdr_nodes WHERE node=?", (s.node,))
    peaks = find_peaks(s.f0_hz, s.bin_hz, s.db)
    for p in peaks:
        p["label"] = _label(p["f_hz"])
    blob = struct.pack(f"<{len(s.db)}h", *[max(-32768, min(32767, int(round(v * 10)))) for v in s.db])
    now = now_iso()
    with db.tx() as c:
        c.execute("INSERT INTO sdr_nodes (node, url, last_seen, info) VALUES (?,?,?,?) ON CONFLICT(node) DO UPDATE SET "
                  "url=COALESCE(excluded.url, url), last_seen=excluded.last_seen, info=excluded.info",
                  (s.node, s.url, now, json.dumps(s.info or {})))
        c.execute("INSERT INTO sdr_sweeps (node, ts, f0_hz, bin_hz, n, data, peaks, lat, lon) VALUES (?,?,?,?,?,?,?,?,?)",
                  (s.node, now, s.f0_hz, s.bin_hz, len(s.db), blob, json.dumps(peaks),
                   node["lat"] if node else None, node["lon"] if node else None))
        c.execute("DELETE FROM sdr_sweeps WHERE node=? AND id NOT IN (SELECT id FROM sdr_sweeps WHERE node=? ORDER BY id DESC LIMIT ?)",
                  (s.node, s.node, KEEP))
    return {"ok": True, "peaks": len(peaks), **summary(s.db)}


@router.get("/nodes")
async def nodes():
    rows = get_db().query("SELECT n.*, (SELECT COUNT(*) FROM sdr_sweeps s WHERE s.node=n.node) AS sweeps FROM sdr_nodes n ORDER BY last_seen DESC")
    for r in rows:
        r["info"] = json.loads(r["info"] or "{}")
    return {"nodes": rows}


@router.get("/latest")
async def latest(node: str, points: int = 1200):
    r = get_db().one("SELECT * FROM sdr_sweeps WHERE node=? ORDER BY id DESC LIMIT 1", (node,))
    if not r:
        raise HTTPException(404, "no sweeps from this node yet")
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
