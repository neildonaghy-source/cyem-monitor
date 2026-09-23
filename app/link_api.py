"""Point-to-point link planner API. Saved links create planned emitters at both ends
(tagged with link_id) so the spectrum deconfliction checks them automatically."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import dem
from .db import Database, get_db, now_iso
from .link_core import analyse, bearing_deg, gc_points, haversine_m, sample_count
from .spectrum_store import planned_upsert

router = APIRouter(prefix="/api/links", tags=["links"])

LINK_SQL = """
CREATE TABLE IF NOT EXISTS planned_links (
  id TEXT PRIMARY KEY, name TEXT NOT NULL,
  a_name TEXT, a_lat REAL NOT NULL, a_lon REAL NOT NULL, a_h REAL NOT NULL,
  b_name TEXT, b_lat REAL NOT NULL, b_lon REAL NOT NULL, b_h REAL NOT NULL,
  freq_hz REAL NOT NULL, rtn_freq_hz REAL, bw_hz REAL NOT NULL,
  ptx_dbm REAL NOT NULL, gtx_dbi REAL NOT NULL, grx_dbi REAL NOT NULL, ltx_db REAL NOT NULL, lrx_db REAL NOT NULL,
  sens_dbm REAL NOT NULL, rain_mm_h REAL NOT NULL, pol TEXT NOT NULL, k REAL NOT NULL,
  req_margin_db REAL NOT NULL, avail_target REAL NOT NULL, start_at TEXT, end_at TEXT, notes TEXT,
  last_verdict TEXT, last_margin_db REAL, last_distance_m REAL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""

PRESETS = [
    {"id": "vhf", "label": "VHF 150 MHz, 25 kHz, 5 W, Yagi", "freq_mhz": 150.0, "bw_khz": 25, "ptx_dbm": 37, "gtx_dbi": 9,
     "grx_dbi": 9, "ltx_db": 2, "lrx_db": 2, "sens_dbm": -110, "req_margin_db": 10, "avail_target": 99.9, "pol": "V"},
    {"id": "uhf", "label": "UHF 450 MHz, 12.5 kHz, 10 W, Yagi", "freq_mhz": 450.0, "bw_khz": 12.5, "ptx_dbm": 40, "gtx_dbi": 11,
     "grx_dbi": 11, "ltx_db": 3, "lrx_db": 3, "sens_dbm": -110, "req_margin_db": 10, "avail_target": 99.9, "pol": "V"},
    {"id": "shf", "label": "SHF 18 GHz microwave, 27.5 MHz, 0.6 m dishes", "freq_mhz": 18000.0, "bw_khz": 27500, "ptx_dbm": 18,
     "gtx_dbi": 38, "grx_dbi": 38, "ltx_db": 0.5, "lrx_db": 0.5, "sens_dbm": -75, "req_margin_db": 20, "avail_target": 99.99, "pol": "V"},
    {"id": "ehf", "label": "EHF 80 GHz E-band, 250 MHz, 0.3 m dishes", "freq_mhz": 80000.0, "bw_khz": 250000, "ptx_dbm": 15,
     "gtx_dbi": 45, "grx_dbi": 45, "ltx_db": 0.5, "lrx_db": 0.5, "sens_dbm": -60, "req_margin_db": 20, "avail_target": 99.99, "pol": "V"},
]


def ensure_link_schema(db: Database) -> None:
    with db.tx() as c:
        c.executescript(LINK_SQL)
        cols = {r[1] for r in c.execute("PRAGMA table_info(planned_emitters)").fetchall()}
        if "link_id" not in cols:
            c.execute("ALTER TABLE planned_emitters ADD COLUMN link_id TEXT")


class LinkIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    a_name: str | None = Field(default=None, max_length=60)
    a_lat: float = Field(ge=-85, le=85)
    a_lon: float = Field(ge=-180, le=180)
    a_h: float = Field(default=10, ge=0, le=500)
    b_name: str | None = Field(default=None, max_length=60)
    b_lat: float = Field(ge=-85, le=85)
    b_lon: float = Field(ge=-180, le=180)
    b_h: float = Field(default=10, ge=0, le=500)
    freq_mhz: float = Field(gt=20, le=100_000)
    rtn_freq_mhz: float | None = Field(default=None, gt=20, le=100_000)
    bw_khz: float = Field(ge=0, le=2_000_000)
    ptx_dbm: float = Field(ge=-30, le=70)
    gtx_dbi: float = Field(ge=-10, le=60)
    grx_dbi: float = Field(ge=-10, le=60)
    ltx_db: float = Field(default=0, ge=0, le=30)
    lrx_db: float = Field(default=0, ge=0, le=30)
    sens_dbm: float = Field(ge=-160, le=0)
    rain_mm_h: float = Field(default=25, ge=0, le=200)
    pol: str = Field(default="V", pattern="^[HVhv]$")
    k: float = Field(default=4 / 3, gt=0.3, le=10)
    req_margin_db: float = Field(default=10, ge=0, le=60)
    avail_target: float = Field(default=99.99, ge=90, le=99.9999)
    start_at: str | None = None
    end_at: str | None = None
    notes: str | None = Field(default=None, max_length=500)


async def run_analysis(L: LinkIn) -> dict:
    D = haversine_m(L.a_lat, L.a_lon, L.b_lat, L.b_lon)
    if D < 50:
        raise HTTPException(400, "ends are less than 50 m apart")
    if D > 300_000:
        raise HTTPException(400, "path over 300 km; outside the scope of this planner")
    n = sample_count(D)
    pts = gc_points(L.a_lat, L.a_lon, L.b_lat, L.b_lon, n)
    try:
        terr = await asyncio.to_thread(dem.heights, pts)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"terrain data unavailable: {type(e).__name__}: {str(e)[:200]}") from e
    dist = [D * i / (n - 1) for i in range(n)]
    res = analyse(dist, terr, h_a_agl=L.a_h, h_b_agl=L.b_h, f_hz=L.freq_mhz * 1e6, ptx_dbm=L.ptx_dbm,
                  gtx_dbi=L.gtx_dbi, grx_dbi=L.grx_dbi, ltx_db=L.ltx_db, lrx_db=L.lrx_db, sens_dbm=L.sens_dbm,
                  k=L.k, rain_mm_h=L.rain_mm_h, pol=L.pol.upper(), req_margin_db=L.req_margin_db,
                  avail_target_pct=L.avail_target)
    res["bearing_ab_deg"] = round(bearing_deg(L.a_lat, L.a_lon, L.b_lat, L.b_lon), 1)
    res["bearing_ba_deg"] = round(bearing_deg(L.b_lat, L.b_lon, L.a_lat, L.a_lon), 1)
    res["points"] = [[round(la, 5), round(lo, 5)] for la, lo in pts[:: max(1, n // 60)]] + [[L.b_lat, L.b_lon]]
    res["assumptions"] = ("Copernicus 30 m surface model (includes some canopy), effective earth radius k, "
                          "Deygout diffraction, symmetric equipment both ways, no clutter, multipath or ducting. "
                          "Rain coefficients from ITU-R P.838-3 as tabulated here: verify for design use.")
    return res


@router.get("/presets")
async def presets():
    return {"presets": PRESETS, "dem": dem.status()}


@router.post("/analyse")
async def analyse_only(body: LinkIn):
    return await run_analysis(body)


def _emitters_for(db: Database, lid: str, L: LinkIn) -> None:
    from .spectrum_api import PlannedIn
    with db.tx() as c:
        c.execute("DELETE FROM planned_emitters WHERE link_id=?", (lid,))
    pw = round(10 ** ((L.ptx_dbm - 30) / 10), 3)
    ends = [(f"{L.name} A>B", L.a_lat, L.a_lon, L.freq_mhz),
            (f"{L.name} B>A", L.b_lat, L.b_lon, L.rtn_freq_mhz or L.freq_mhz)]
    for name, la, lo, f in ends:
        pin = PlannedIn(name=name[:80], freq_mhz=f, bw_khz=L.bw_khz, power_w=pw, lat=la, lon=lo,
                        start_at=L.start_at, end_at=L.end_at, notes=f"link {lid}")
        row = planned_upsert(db, pin.to_row())
        with db.tx() as c:
            c.execute("UPDATE planned_emitters SET link_id=? WHERE id=?", (lid, row["id"]))


def _link_row(L: LinkIn) -> dict:
    d = L.model_dump()
    d["freq_hz"] = d.pop("freq_mhz") * 1e6
    r = d.pop("rtn_freq_mhz")
    d["rtn_freq_hz"] = r * 1e6 if r else None
    d["bw_hz"] = d.pop("bw_khz") * 1e3
    d["pol"] = d["pol"].upper()
    return d


def _to_in(row: dict) -> LinkIn:
    d = {k: row[k] for k in LinkIn.model_fields if k in row}
    d["freq_mhz"] = row["freq_hz"] / 1e6
    d["rtn_freq_mhz"] = row["rtn_freq_hz"] / 1e6 if row.get("rtn_freq_hz") else None
    d["bw_khz"] = row["bw_hz"] / 1e3
    return LinkIn(**d)


@router.get("")
async def list_links():
    return {"links": get_db().query("SELECT * FROM planned_links ORDER BY name")}


@router.get("/{lid}")
async def get_link(lid: str):
    row = get_db().one("SELECT * FROM planned_links WHERE id=?", (lid,))
    if not row:
        raise HTTPException(404, "no such link")
    return row


@router.get("/{lid}/analysis")
async def link_analysis(lid: str):
    row = await get_link(lid)
    return {"link": row, "analysis": await run_analysis(_to_in(row))}


async def _save(body: LinkIn, lid: str | None) -> dict:
    db = get_db()
    res = await run_analysis(body)
    lid = lid or uuid.uuid4().hex[:10]
    d = _link_row(body)
    now = now_iso()
    cols = list(d.keys()) + ["last_verdict", "last_margin_db", "last_distance_m"]
    vals = list(d.values()) + [res["verdict"], res["margin_db"], res["distance_m"]]
    with db.tx() as c:
        c.execute(f"INSERT INTO planned_links (id, {','.join(cols)}, created_at, updated_at) VALUES (?,{','.join('?' * len(cols))},?,?) "
                  f"ON CONFLICT(id) DO UPDATE SET {','.join(f'{k}=excluded.{k}' for k in cols)}, updated_at=excluded.updated_at",
                  [lid, *vals, now, now])
    _emitters_for(db, lid, body)
    return {"link": db.one("SELECT * FROM planned_links WHERE id=?", (lid,)), "analysis": res}


@router.post("")
async def create_link(body: LinkIn):
    return await _save(body, None)


@router.put("/{lid}")
async def update_link(lid: str, body: LinkIn):
    await get_link(lid)
    return await _save(body, lid)


@router.delete("/{lid}")
async def delete_link(lid: str):
    db = get_db()
    with db.tx() as c:
        n = c.execute("DELETE FROM planned_links WHERE id=?", (lid,)).rowcount
        c.execute("DELETE FROM planned_emitters WHERE link_id=?", (lid,))
    if not n:
        raise HTTPException(404, "no such link")
    return {"deleted": lid}
