"""Area coverage API (omni / sector / P2MP hub). Saved sites own a planned emitter
(planned_emitters.site_id) and their coverage replaces the fixed radius in
spectrum deconfliction for that emitter."""
from __future__ import annotations

import asyncio
import time
import uuid

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import dem
from .coverage_core import Coverage, polar_prx, radial_points, sector_atten_db
from .db import Database, get_db, now_iso
from .spectrum_store import planned_upsert

router = APIRouter(prefix="/api/coverage", tags=["coverage"])

SITE_SQL = """
CREATE TABLE IF NOT EXISTS coverage_sites (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, h_agl REAL NOT NULL,
  freq_hz REAL NOT NULL, bw_hz REAL NOT NULL, ptx_dbm REAL NOT NULL, gtx_dbi REAL NOT NULL, ltx_db REAL NOT NULL,
  pattern TEXT NOT NULL, azimuth REAL, beamwidth REAL, radius_km REAL NOT NULL, rx_h_agl REAL NOT NULL,
  grx_dbi REAL NOT NULL, sens_dbm REAL NOT NULL, margin_db REAL NOT NULL, itf_dbm REAL NOT NULL, k REAL NOT NULL,
  start_at TEXT, end_at TEXT, notes TEXT, stats TEXT, grid TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


def ensure_coverage_schema(db: Database) -> None:
    with db.tx() as c:
        c.executescript(SITE_SQL)
        cols = {r[1] for r in c.execute("PRAGMA table_info(planned_emitters)").fetchall()}
        if "site_id" not in cols:
            c.execute("ALTER TABLE planned_emitters ADD COLUMN site_id TEXT")
        if "fine" not in {r[1] for r in c.execute("PRAGMA table_info(coverage_sites)").fetchall()}:
            c.execute("ALTER TABLE coverage_sites ADD COLUMN fine INTEGER DEFAULT 0")


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    lat: float = Field(ge=-85, le=85)
    lon: float = Field(ge=-180, le=180)
    h_agl: float = Field(default=15, ge=0, le=500)
    freq_mhz: float = Field(gt=20, le=100_000)
    bw_khz: float = Field(ge=0, le=2_000_000)
    ptx_dbm: float = Field(ge=-30, le=70)
    gtx_dbi: float = Field(default=2, ge=-10, le=40)
    ltx_db: float = Field(default=1, ge=0, le=30)
    pattern: str = Field(default="omni", pattern="^(omni|sector)$")
    azimuth: float | None = Field(default=None, ge=0, lt=360)
    beamwidth: float | None = Field(default=None, gt=1, le=180)
    radius_km: float = Field(default=20, gt=0.5, le=100)
    rx_h_agl: float = Field(default=1.5, ge=0, le=1000)          # up to low-level air (corridor planner)
    grx_dbi: float = Field(default=0, ge=-10, le=40)
    sens_dbm: float = Field(default=-110, ge=-160, le=0)
    margin_db: float = Field(default=10, ge=0, le=60)
    itf_dbm: float = Field(default=-120, ge=-160, le=0)
    fine: bool = False
    k: float = Field(default=4 / 3, gt=0.3, le=10)
    start_at: str | None = None
    end_at: str | None = None
    notes: str | None = Field(default=None, max_length=500)


N_AZ = 360


def _compute(S: SiteIn) -> tuple[Coverage, dict]:
    t0 = time.monotonic()
    R = S.radius_km * 1000
    n = int(min(1000 if S.fine else 600, max(60, R / 50))) + 1   # ~50 m steps; cap 600, or 1000 when fine
    dist = np.linspace(0, R, n)
    az = np.arange(N_AZ) * (360 / N_AZ)
    lats, lons = radial_points(S.lat, S.lon, az, dist)
    samp = dem.grid_sampler(float(lats.min()), float(lons.min()), float(lats.max()), float(lons.max()))
    heights = samp(lats, lons).astype(np.float64)
    eirp = np.full(N_AZ, S.ptx_dbm - S.ltx_db + S.gtx_dbi)
    if S.pattern == "sector":
        off = np.abs((az - (S.azimuth or 0) + 180) % 360 - 180)
        eirp = eirp - sector_atten_db(off, S.beamwidth or 65)
    prx = polar_prx(heights, dist, az, h_tx_agl=S.h_agl, h_rx_agl=S.rx_h_agl, f_hz=S.freq_mhz * 1e6,
                    eirp_dbm=eirp, grx_dbi=S.grx_dbi, k=S.k)
    cov = Coverage(S.lat, S.lon, float(dist[1]), N_AZ, prx)
    thr = S.sens_dbm + S.margin_db
    stats = {"area_km2": round(cov.area_km2(thr), 1), "max_range_km": round(cov.max_range_km(thr), 2),
             "marginal_area_km2": round(cov.area_km2(S.sens_dbm) - cov.area_km2(thr), 1),
             "interference_area_km2": round(cov.area_km2(S.itf_dbm), 1),
             "site_ground_m": round(float(heights[0, 0]), 1), "step_m": round(float(dist[1]), 1),
             "compute_s": round(time.monotonic() - t0, 2)}
    return cov, stats


def _result(S: SiteIn, cov: Coverage, stats: dict) -> dict:
    url, bounds = cov.render_png(S.sens_dbm, S.margin_db)
    return {"stats": stats, "overlay": url, "bounds": bounds,
            "bands": {"strong_dbm": S.sens_dbm + S.margin_db + 10, "adequate_dbm": S.sens_dbm + S.margin_db,
                      "marginal_dbm": S.sens_dbm, "interference_dbm": S.itf_dbm},
            "assumptions": "Copernicus 30 m surface model sampled at about 60 m, Deygout diffraction limited to 3 edges "
                           "(ITU-R P.526), earth radius factor k, generic antenna pattern, "
                           "receiver at the stated height everywhere. No clutter, buildings or multipath."}


# One limit for all terrain-heavy work (coverage here, EMO footprints and paths): each job holds about 200-300 MB at
# 100 km, and unlimited parallel jobs OOM-killed the container at 1 GB on 19 Nov 2026.
HEAVY = asyncio.Semaphore(3)


async def analyse_site(S: SiteIn) -> tuple[Coverage, dict]:
    try:
        async with HEAVY:
            return await asyncio.to_thread(_compute, S)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"coverage failed: {type(e).__name__}: {str(e)[:200]}") from e


@router.post("/analyse")
async def analyse(body: SiteIn):
    cov, stats = await analyse_site(body)
    return _result(body, cov, stats)


def _row(S: SiteIn) -> dict:
    d = S.model_dump()
    d["freq_hz"] = d.pop("freq_mhz") * 1e6
    d["bw_hz"] = d.pop("bw_khz") * 1e3
    return d


def _to_in(row: dict) -> SiteIn:
    d = {k: row[k] for k in SiteIn.model_fields if k in row}
    d["freq_mhz"] = row["freq_hz"] / 1e6
    d["bw_khz"] = row["bw_hz"] / 1e3
    return SiteIn(**d)


def _public(row: dict) -> dict:
    import json
    out = {k: v for k, v in row.items() if k != "grid"}
    out["stats"] = json.loads(row["stats"]) if row.get("stats") else None
    return out


async def _save(S: SiteIn, sid: str | None) -> dict:
    import json
    from .spectrum_api import PlannedIn
    db = get_db()
    cov, stats = await analyse_site(S)
    sid = sid or uuid.uuid4().hex[:10]
    d = _row(S)
    d["stats"] = json.dumps(stats)
    d["grid"] = cov.pack()
    now = now_iso()
    cols = list(d.keys())
    with db.tx() as c:
        c.execute(f"INSERT INTO coverage_sites (id, {','.join(cols)}, created_at, updated_at) VALUES (?,{','.join('?' * len(cols))},?,?) "
                  f"ON CONFLICT(id) DO UPDATE SET {','.join(f'{k}=excluded.{k}' for k in cols)}, updated_at=excluded.updated_at",
                  [sid, *d.values(), now, now])
        c.execute("DELETE FROM planned_emitters WHERE site_id=?", (sid,))
    pin = PlannedIn(name=f"{S.name} (site)"[:80], freq_mhz=S.freq_mhz, bw_khz=S.bw_khz, power_w=round(10 ** ((S.ptx_dbm - 30) / 10), 3),
                    lat=S.lat, lon=S.lon, start_at=S.start_at, end_at=S.end_at, notes=f"coverage site {sid}")
    em = planned_upsert(db, pin.to_row())
    with db.tx() as c:
        c.execute("UPDATE planned_emitters SET site_id=? WHERE id=?", (sid, em["id"]))
    return {"site": _public(db.one("SELECT * FROM coverage_sites WHERE id=?", (sid,))), **_result(S, cov, stats)}


@router.get("")
async def list_sites():
    return {"sites": [_public(r) for r in get_db().query("SELECT * FROM coverage_sites ORDER BY name")]}


@router.post("")
async def create_site(body: SiteIn):
    return await _save(body, None)


@router.put("/{sid}")
async def update_site(sid: str, body: SiteIn):
    if not get_db().one("SELECT id FROM coverage_sites WHERE id=?", (sid,)):
        raise HTTPException(404, "no such site")
    return await _save(body, sid)


@router.get("/{sid}/overlay")
async def overlay(sid: str):
    row = get_db().one("SELECT * FROM coverage_sites WHERE id=?", (sid,))
    if not row:
        raise HTTPException(404, "no such site")
    cov = Coverage.unpack(row["grid"])
    S = _to_in(row)
    url, bounds = cov.render_png(S.sens_dbm, S.margin_db)
    return {"site": _public(row), "overlay": url, "bounds": bounds}


@router.get("/{sid}/level")
async def level(sid: str, lat: float, lon: float):
    row = get_db().one("SELECT grid FROM coverage_sites WHERE id=?", (sid,))
    if not row:
        raise HTTPException(404, "no such site")
    lv = Coverage.unpack(row["grid"]).level_dbm(lat, lon)
    return {"level_dbm": round(lv, 1) if lv is not None else None}


@router.delete("/{sid}")
async def delete_site(sid: str):
    db = get_db()
    with db.tx() as c:
        n = c.execute("DELETE FROM coverage_sites WHERE id=?", (sid,)).rowcount
        c.execute("DELETE FROM planned_emitters WHERE site_id=?", (sid,))
    if not n:
        raise HTTPException(404, "no such site")
    return {"deleted": sid}


def coverage_for_emitters(db: Database) -> dict[str, tuple[Coverage, float]]:
    """planned emitter id -> (coverage, interference threshold dBm) for deconfliction."""
    out = {}
    for r in db.query("SELECT e.id AS eid, s.grid, s.itf_dbm FROM planned_emitters e JOIN coverage_sites s ON s.id = e.site_id"):
        try:
            out[r["eid"]] = (Coverage.unpack(r["grid"]), r["itf_dbm"])
        except Exception:  # noqa: BLE001
            continue
    return out
