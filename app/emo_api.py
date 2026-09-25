"""Electromagnetic Operations (EMO) red / blue scenario: ES, EA and EP interactions on terrain.

Symmetric model. Every entity is on side blue or red and is one of:
  emitter   anything that radiates: comms, radar, datalink, nav (GNSS, fixed space level), cuas, other
  receiver  a user of an own-side emitter's net (the victim for EA); with EIRP set it also transmits
  sensor    ES: intercept, DF (df_rms_deg set) or RWR, watching a band freq..f_hi
  effector  EA: jammer (comms, datalink, GNSS, C-UAS, other); it radiates, so it can be detected too
EP is represented by 'active' (EMCON: off-air emitters are neither seen nor provide coverage), siting,
antenna pattern and power.

ES   sensor(side Y) vs active emitters and effectors (side X != Y), frequency overlap, per-pair terrain
     path at both heights; detection margin; DF lines of bearing; fixes from the best two DF bearings.
EA   effector(side Y) vs nets of side X: J/S at each receiver (per-pair terrain paths), and on the map a
     denial zone inside the net's coverage where J - S - bandwidth loss >= the net's J/S threshold.
Maps (per side): own net coverage, exposure of own emissions to the other side's sensors, denial.
Radar: modelled as an emitter for ES only; radar detection and radar-jamming J/S are not modelled.
Screening grade: Deygout 3-edge on Copernicus 30 m, no processing gain, hopping, nulling, clutter,
multipath or time variability. Notional scenarios only.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
import uuid

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .coverage_api import SiteIn, _compute
from .db import Database, get_db, now_iso
from .ems_core import band_masks, cell_km2, overlap, overlay_png, raster_axes, region_masks, sample, union_bounds

router = APIRouter(prefix="/api/emo", tags=["emo"])

SQL = """
CREATE TABLE IF NOT EXISTS emo_entities (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, side TEXT NOT NULL, kind TEXT NOT NULL, category TEXT,
  lat REAL NOT NULL, lon REAL NOT NULL, h_agl REAL NOT NULL,
  freq_mhz REAL NOT NULL, bw_khz REAL NOT NULL, f_hi_mhz REAL,
  eirp_dbm REAL, fixed_level_dbm REAL, sens_dbm REAL, js_req_db REAL, df_rms_deg REAL,
  pattern TEXT NOT NULL DEFAULT 'omni', azimuth REAL, beamwidth REAL,
  net TEXT, active INTEGER NOT NULL DEFAULT 1, radius_km REAL NOT NULL DEFAULT 30,
  sidc TEXT, track TEXT, speed_kmh REAL, notes TEXT, updated_at TEXT NOT NULL,
  hop_bw_khz REAL, pg_db REAL, schedule TEXT
);
CREATE TABLE IF NOT EXISTS emo_scenarios (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL, entities TEXT NOT NULL);
"""
CATS = "^(comms|radar|datalink|nav|cuas|other|es|df|rwr)$"


def ensure_emo_schema(db: Database) -> None:
    with db.tx() as c:
        c.executescript(SQL)
        cols = {r[1] for r in c.execute("PRAGMA table_info(emo_entities)").fetchall()}
        for col, typ in (("hop_bw_khz", "REAL"), ("pg_db", "REAL"), ("schedule", "TEXT")):
            if col not in cols:
                c.execute(f"ALTER TABLE emo_entities ADD COLUMN {col} {typ}")


class EntityIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    side: str = Field(pattern="^(blue|red)$")
    kind: str = Field(pattern="^(emitter|receiver|sensor|effector)$")
    category: str | None = Field(default=None, pattern=CATS)
    lat: float = Field(ge=-85, le=85)
    lon: float = Field(ge=-180, le=180)
    h_agl: float = Field(default=2, ge=0, le=15000)
    freq_mhz: float = Field(gt=1, le=100_000)
    bw_khz: float = Field(default=25, ge=0, le=2_000_000)
    f_hi_mhz: float | None = Field(default=None, gt=1, le=100_000)
    eirp_dbm: float | None = Field(default=None, ge=-30, le=120)
    fixed_level_dbm: float | None = Field(default=None, ge=-180, le=0)
    sens_dbm: float | None = Field(default=None, ge=-170, le=0)
    js_req_db: float | None = Field(default=None, ge=-30, le=80)
    df_rms_deg: float | None = Field(default=None, gt=0, le=30)
    pattern: str = Field(default="omni", pattern="^(omni|sector)$")
    azimuth: float | None = Field(default=None, ge=0, lt=360)
    beamwidth: float | None = Field(default=None, gt=1, le=180)
    net: str | None = None
    active: bool = True
    radius_km: float | None = Field(default=None, gt=0.5, le=100)   # blank: automatic by band and height
    sidc: str | None = Field(default=None, max_length=30)
    track: list[list[float]] | None = None
    speed_kmh: float | None = Field(default=None, ge=0, le=2000)
    notes: str | None = Field(default=None, max_length=300)
    hop_bw_khz: float | None = Field(default=None, gt=0, le=2_000_000)   # frequency-hopping hopset width
    pg_db: float | None = Field(default=None, ge=0, le=60)               # other processing gain / anti-jam margin
    schedule: list[list[float]] | None = None                            # on-air windows [[start_min, end_min], ...]


class MoveIn(BaseModel):
    lat: float = Field(ge=-85, le=85)
    lon: float = Field(ge=-180, le=180)


class RunIn(BaseModel):
    rx_h: float = Field(default=2, ge=0, le=100)          # ground receiver / sensor height for the maps
    js_req_db: float = Field(default=0, ge=-30, le=80)     # default J/S at which a net fails
    default_sens: float = Field(default=-110, ge=-170, le=0)
    df_fix_good_m: float = Field(default=1000, gt=0)       # fix error below which a target is 'targetable'


def _decode(row: dict) -> dict:
    r = dict(row)
    r["track"] = json.loads(r["track"]) if r.get("track") else None
    r["active"] = bool(r.get("active", 1))
    r["schedule"] = json.loads(r["schedule"]) if r.get("schedule") else None
    return r


def auto_radius(freq_mhz: float, h_agl: float) -> float:
    """Default footprint radius: airborne 100 km, HF/VHF 80 km, UHF 60 km, 1 GHz and above 40 km."""
    if h_agl > 300:
        return 100.0
    return 80.0 if freq_mhz < 300 else 60.0 if freq_mhz < 1000 else 40.0


def _upsert(b: EntityIn, eid: str | None) -> dict:
    db = get_db()
    eid = eid or uuid.uuid4().hex[:8]
    d = b.model_dump()
    if d.get("radius_km") is None:
        d["radius_km"] = auto_radius(d["freq_mhz"], d["h_agl"])
    d["track"] = json.dumps(d["track"]) if d.get("track") else None
    d["schedule"] = json.dumps(d["schedule"]) if d.get("schedule") else None
    d["active"] = 1 if d["active"] else 0
    cols = list(d)
    with db.tx() as c:
        c.execute(f"INSERT INTO emo_entities (id, {','.join(cols)}, updated_at) VALUES (?,{','.join('?' * len(cols))},?) "
                  f"ON CONFLICT(id) DO UPDATE SET {','.join(f'{k}=excluded.{k}' for k in cols)}, updated_at=excluded.updated_at",
                  [eid, *d.values(), now_iso()])
    return _decode(db.one("SELECT * FROM emo_entities WHERE id=?", (eid,)))


def _check(b: EntityIn):
    if b.kind in ("emitter", "effector") and b.eirp_dbm is None and b.fixed_level_dbm is None:
        raise HTTPException(422, "emitters and effectors need EIRP (dBm)")


def _all() -> list[dict]:
    return [_decode(r) for r in get_db().query("SELECT * FROM emo_entities ORDER BY side, kind, name")]


@router.get("")
async def list_entities():
    return {"entities": _all()}


@router.post("")
async def create_entity(body: EntityIn):
    _check(body)
    return _upsert(body, None)


@router.put("/{eid}")
async def update_entity(eid: str, body: EntityIn):
    if not get_db().one("SELECT id FROM emo_entities WHERE id=?", (eid,)):
        raise HTTPException(404, "no such entity")
    _check(body)
    return _upsert(body, eid)


@router.post("/{eid}/move")
async def move_entity(eid: str, body: MoveIn):
    """Drag on the map: move the entity (and its track start) to a new position."""
    with get_db().tx() as c:
        n = c.execute("UPDATE emo_entities SET lat=?, lon=?, updated_at=? WHERE id=?", (body.lat, body.lon, now_iso(), eid)).rowcount
    if not n:
        raise HTTPException(404, "no such entity")
    return {"moved": eid}


@router.post("/{eid}/active")
async def set_active(eid: str, on: bool):
    """EMCON: take an emitter or effector off-air (or back on)."""
    with get_db().tx() as c:
        n = c.execute("UPDATE emo_entities SET active=?, updated_at=? WHERE id=?", (1 if on else 0, now_iso(), eid)).rowcount
    if not n:
        raise HTTPException(404, "no such entity")
    return {"id": eid, "active": on}


@router.delete("/{eid}")
async def delete_entity(eid: str):
    with get_db().tx() as c:
        n = c.execute("DELETE FROM emo_entities WHERE id=?", (eid,)).rowcount
        c.execute("UPDATE emo_entities SET net=NULL WHERE net=?", (eid,))
    if not n:
        raise HTTPException(404, "no such entity")
    return {"deleted": eid}


# ---- movement, bands, geometry ------------------------------------------------------------
def position_at(e: dict, t_min: float) -> tuple[float, float]:
    from .link_core import haversine_m
    pts = [(e["lat"], e["lon"])] + [tuple(p) for p in (e.get("track") or [])]
    if len(pts) < 2 or not e.get("speed_kmh") or t_min <= 0:
        return pts[0]
    left = e["speed_kmh"] * 1000 / 60 * t_min
    for (a_lat, a_lon), (b_lat, b_lon) in zip(pts, pts[1:]):
        seg = haversine_m(a_lat, a_lon, b_lat, b_lon)
        if left <= seg:
            f = left / seg if seg else 0
            return a_lat + (b_lat - a_lat) * f, a_lon + (b_lon - a_lon) * f
        left -= seg
    return pts[-1]


def track_minutes(e: dict) -> float:
    from .link_core import haversine_m
    pts = [(e["lat"], e["lon"])] + [tuple(p) for p in (e.get("track") or [])]
    if len(pts) < 2 or not e.get("speed_kmh"):
        return 0.0
    return sum(haversine_m(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:])) / (e["speed_kmh"] * 1000 / 60)


def on_air(e: dict, t_min: float) -> bool:
    """EMCON flag and, if set, the on-air windows."""
    if not e.get("active", True):
        return False
    sch = e.get("schedule")
    return not sch or any(a <= t_min < b for a, b in sch)


def victim_band(n: dict) -> tuple[float, float]:
    """Band a jammer must overlap to affect a net: its hopset if hopping, else its channel."""
    if n.get("hop_bw_khz"):
        f, half = n["freq_mhz"] * 1e6, n["hop_bw_khz"] * 1e3 / 2
        return f - half, f + half
    return band(n)


def jam_penalty(y: dict, n: dict) -> float:
    """dB by which jammer power is diluted against a net: 10 log(max(Bj, Bhop, Bch) / Bch) + processing gain.
    Spot jammer vs hopper: only 1/N of hops hit; barrage: power spread over its width."""
    ylo, yhi = band(y)
    bj = max(yhi - ylo, 1.0)
    bch = max((n.get("bw_khz") or 25) * 1e3, 1.0)
    bhop = (n.get("hop_bw_khz") or 0) * 1e3
    return 10 * math.log10(max(bj, bhop, bch) / bch) + (n.get("pg_db") or 0)


def band(e: dict) -> tuple[float, float]:
    f = e["freq_mhz"] * 1e6
    if e.get("kind") == "sensor" and e.get("f_hi_mhz"):
        return f, e["f_hi_mhz"] * 1e6
    half = (e.get("bw_khz") or 0) * 1e3 / 2
    return f - half, f + half


def pattern_loss(e: dict, lat: float, lon: float, tx_pos) -> float:
    """Sector antenna attenuation towards a point (0 for omni)."""
    if e.get("pattern") != "sector":
        return 0.0
    from .coverage_core import sector_atten_db
    from .link_core import bearing_deg
    brg = bearing_deg(tx_pos[0], tx_pos[1], lat, lon)
    off = abs((brg - (e.get("azimuth") or 0) + 180) % 360 - 180)
    return float(sector_atten_db(np.array([off]), e.get("beamwidth") or 65)[0])


def _p2p_sync(tx, tx_h, rx, rx_h, f_hz, eirp):
    from . import dem
    from .link_core import analyse, gc_points, haversine_m, sample_count
    D = haversine_m(tx[0], tx[1], rx[0], rx[1])
    if D < 30:
        return eirp - 40.0
    n = sample_count(D, step_m=60, max_n=600)
    pts = gc_points(tx[0], tx[1], rx[0], rx[1], n)
    terr = dem.heights(pts)
    dist = [D * i / (n - 1) for i in range(n)]
    r = analyse(dist, terr, h_a_agl=tx_h, h_b_agl=rx_h, f_hz=f_hz, ptx_dbm=eirp, gtx_dbi=0, grx_dbi=0,
                sens_dbm=-200, rain_mm_h=0)
    return r["prx_dbm"]


_P2P: dict[tuple, float] = {}
_HEAVY = asyncio.Semaphore(3)


async def p2p_level(e: dict, tx_pos, rx: dict, rx_pos) -> float:
    """Received level (dBm) from emitter/effector e at rx, terrain path at both heights, antenna pattern applied."""
    key = (e["id"], e["updated_at"], round(tx_pos[0], 4), round(tx_pos[1], 4), rx["id"], rx["updated_at"],
           round(rx_pos[0], 4), round(rx_pos[1], 4))
    if key not in _P2P:
        if len(_P2P) > 4000:
            _P2P.clear()
        async with _HEAVY:
            _P2P[key] = await asyncio.to_thread(_p2p_sync, tx_pos, e["h_agl"], rx_pos, rx["h_agl"], e["freq_mhz"] * 1e6, e["eirp_dbm"])
    return _P2P[key] - pattern_loss(e, rx_pos[0], rx_pos[1], tx_pos)


def _intersect(p1, b1, p2, b2):
    """Intersection of two bearings (deg) from p1, p2 on a local flat projection; None if near-parallel."""
    lat0 = math.radians((p1[0] + p2[0]) / 2)
    def xy(p):
        return (math.radians(p[1]) * math.cos(lat0) * 6371000.0, math.radians(p[0]) * 6371000.0)
    (x1, y1), (x2, y2) = xy(p1), xy(p2)
    d1 = (math.sin(math.radians(b1)), math.cos(math.radians(b1)))
    d2 = (math.sin(math.radians(b2)), math.cos(math.radians(b2)))
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-6:
        return None
    t = ((x2 - x1) * d2[1] - (y2 - y1) * d2[0]) / den
    if t <= 0:
        return None
    x, y = x1 + t * d1[0], y1 + t * d1[1]
    return math.degrees(y / 6371000.0), math.degrees(x / (6371000.0 * math.cos(lat0)))


def df_fix(target_pos, bearings: list[dict]) -> dict | None:
    """Best two-bearing fix: cut angle closest to 90 deg. Error ~ sqrt(e1^2 + e2^2) / sin(cut), e = range x sigma."""
    from .link_core import haversine_m
    best = None
    for i in range(len(bearings)):
        for j in range(i + 1, len(bearings)):
            a, b = bearings[i], bearings[j]
            cut = abs((a["bearing"] - b["bearing"] + 180) % 360 - 180)
            cut = min(cut, 180 - cut)
            if cut < 10:
                continue
            e1 = haversine_m(*a["site"], *target_pos) * math.radians(a["sigma"])
            e2 = haversine_m(*b["site"], *target_pos) * math.radians(b["sigma"])
            err = math.sqrt(e1 * e1 + e2 * e2) / math.sin(math.radians(cut))
            if best is None or err < best["error_m"]:
                pt = _intersect(a["site"], a["bearing"], b["site"], b["bearing"]) or target_pos
                best = {"sensors": [a["sensor"], b["sensor"]], "cut_deg": round(cut, 1), "error_m": round(err), "fix": pt}
    return best


# ---- analysis ---------------------------------------------------------------------------------
_COV: dict[tuple, object] = {}
_LAST: dict = {}
LAYER_RGBA = {
    "blue_cov": (60, 140, 255, 70), "red_cov": (255, 90, 90, 60),
    "blue_seen": (255, 70, 70, 110),    # blue emissions detectable by red ES
    "red_seen": (60, 200, 255, 110),    # red emissions detectable by blue ES
    "blue_denied": (235, 40, 235, 210), "red_denied": (255, 170, 30, 210),
}


async def coverage_for(e: dict, pos, rx_h: float):
    key = (e["id"], e["updated_at"], round(pos[0], 4), round(pos[1], 4), rx_h)
    if key not in _COV:
        s = SiteIn(name=e["name"], lat=pos[0], lon=pos[1], h_agl=min(e["h_agl"], 500), freq_mhz=e["freq_mhz"],
                   bw_khz=e["bw_khz"] or 0, ptx_dbm=min(e["eirp_dbm"], 70.0), gtx_dbi=0, ltx_db=0, pattern=e["pattern"],
                   azimuth=e.get("azimuth"), beamwidth=e.get("beamwidth"), radius_km=e["radius_km"], rx_h_agl=rx_h,
                   grx_dbi=0, sens_dbm=-110, margin_db=0, itf_dbm=-130)
        async with _HEAVY:
            cov, _ = await asyncio.to_thread(_compute, s)
        extra = e["eirp_dbm"] - min(e["eirp_dbm"], 70.0)   # Coverage caps power at 70 dBm; level scales with EIRP
        if extra:
            cov.prx = cov.prx + np.float32(extra)
        if len(_COV) > 80:
            _COV.clear()
        _COV[key] = cov
    return _COV[key]


def other(side: str) -> str:
    return "red" if side == "blue" else "blue"


@router.post("/run")
async def run(p: RunIn, t_min: float = 0):
    t0 = time.monotonic()
    ents = _all()
    if not ents:
        raise HTTPException(400, "no entities: load an example or add some")
    byid = {e["id"]: e for e in ents}
    for e in ents:
        e["pos"] = position_at(e, t_min)
        e["active"] = on_air(e, t_min)
    # everything that radiates: emitters, effectors, and net users that transmit (receivers with EIRP)
    radiating = [e for e in ents if e["active"] and (e["kind"] in ("emitter", "effector")
                                                  or (e["kind"] == "receiver" and e.get("eirp_dbm") is not None))]
    terr_rad = [e for e in radiating if e.get("fixed_level_dbm") is None and e.get("eirp_dbm") is not None]
    sensors = [e for e in ents if e["kind"] == "sensor"]
    receivers = [e for e in ents if e["kind"] == "receiver"]
    nets = [e for e in ents if e["kind"] == "emitter" and e["active"] and (any(r.get("net") == e["id"] for r in receivers)
                                                                           or e.get("fixed_level_dbm") is not None)]
    covs = await asyncio.gather(*[coverage_for(e, e["pos"], p.rx_h) for e in terr_rad])
    grids = {e["id"]: c for e, c in zip(terr_rad, covs)}
    # warm every terrain path the ES and EA loops will need, in parallel
    jobs = []
    for x in sensors:
        for e in radiating:
            if e["side"] != x["side"] and e.get("fixed_level_dbm") is None and overlap(*band(e), *band(x)):
                jobs.append(p2p_level(e, e["pos"], x, x["pos"]))
    for y in [e for e in radiating if e["kind"] == "effector"]:
        for nn in nets:
            if y["side"] != nn["side"] and overlap(*band(nn), *band(y)):
                for v in [r for r in receivers if r.get("net") == nn["id"]]:
                    jobs.append(p2p_level(y, y["pos"], v, v["pos"]))
                    if nn.get("fixed_level_dbm") is None:
                        jobs.append(p2p_level(nn, nn["pos"], v, v["pos"]))
    await asyncio.gather(*jobs)
    if grids:
        s, w, n, e_ = union_bounds(list(grids.values()))
    else:
        la = [x["pos"][0] for x in ents]; lo = [x["pos"][1] for x in ents]
        s, w, n, e_ = min(la) - 0.2, min(lo) - 0.3, max(la) + 0.2, max(lo) + 0.3
    LA, LO = raster_axes(s, w, n, e_)
    km2 = cell_km2(LA, LO)
    L = {k: np.zeros(LA.shape, bool) for k in LAYER_RGBA}
    lv = {k: sample(g, LA, LO) for k, g in grids.items()}

    # ES maps: where each side's emissions can be heard by the other side's (ground) sensors
    for e in terr_rad:
        watchers = [x for x in sensors if x["side"] == other(e["side"]) and overlap(*band(e), *band(x))]
        if watchers:
            sens = min(x.get("sens_dbm") or p.default_sens for x in watchers)
            L[f"{e['side']}_seen"] |= lv[e["id"]] >= sens

    # ES pairs, lines of bearing, fixes
    detections, bearings = [], {}
    from .link_core import bearing_deg
    for x in sensors:
        for e in radiating:
            if e["side"] == x["side"] or e.get("fixed_level_dbm") is not None or not overlap(*band(e), *band(x)):
                continue
            lvl = await p2p_level(e, e["pos"], x, x["pos"])
            margin = round(lvl - (x.get("sens_dbm") or p.default_sens), 1)
            det = margin >= 0
            d = {"sensor": x["name"], "sensor_id": x["id"], "sensor_side": x["side"], "target": e["name"], "target_id": e["id"],
                 "category": e.get("category"), "level_dbm": round(lvl, 1), "margin_db": margin, "detected": det,
                 "df": bool(x.get("df_rms_deg")), "a": x["pos"], "b": e["pos"]}
            detections.append(d)
            if det and x.get("df_rms_deg"):
                brg = bearing_deg(x["pos"][0], x["pos"][1], e["pos"][0], e["pos"][1])
                bearings.setdefault(e["id"], []).append({"sensor": x["name"], "site": x["pos"], "bearing": brg,
                                                        "sigma": x["df_rms_deg"]})
    fixes = []
    for tid, bs in bearings.items():
        t = byid[tid]
        f = df_fix(t["pos"], bs) if len(bs) >= 2 else None
        fixes.append({"target": t["name"], "target_side": t["side"], "lobs": len(bs),
                      "sensors": [b["sensor"] for b in bs], "bearings": [{"site": b["site"], "bearing": round(b["bearing"], 1)} for b in bs],
                      "fix": f, "targetable": bool(f and f["error_m"] <= p.df_fix_good_m), "pos": t["pos"]})

    # EA: nets, J/S, denial
    jamming, per_net = [], []
    effectors = [e for e in radiating if e["kind"] == "effector"]
    for nn in nets:
        space = nn.get("fixed_level_dbm") is not None
        nlo, nhi = victim_band(nn)
        jsreq = nn["js_req_db"] if nn.get("js_req_db") is not None else p.js_req_db
        nsens = nn.get("sens_dbm") or p.default_sens
        S = np.full(LA.shape, float(nn["fixed_level_dbm"])) if space else lv[nn["id"]]
        covd = np.ones(LA.shape, bool) if space else S >= nsens
        if not space:
            L[f"{nn['side']}_cov"] |= covd
        den = np.zeros(LA.shape, bool)
        for y in effectors:
            if y["side"] == nn["side"] or not overlap(nlo, nhi, *band(y)) or y["id"] not in lv:
                continue
            pen = jam_penalty(y, nn)
            with np.errstate(invalid="ignore"):
                den |= covd & ((lv[y["id"]] - pen - S) >= jsreq)
            for v in [r for r in receivers if r.get("net") == nn["id"]]:
                J = await p2p_level(y, y["pos"], v, v["pos"]) - pen
                Sv = float(nn["fixed_level_dbm"]) if space else await p2p_level(nn, nn["pos"], v, v["pos"])
                vs = v.get("sens_dbm") or nsens
                js = round(J - Sv, 1)
                status = "no signal" if Sv < vs else ("denied" if js >= jsreq else "holds")
                jamming.append({"effector": y["name"], "effector_id": y["id"], "victim_id": v["id"], "effector_side": y["side"], "victim": v["name"], "net": nn["name"],
                                "category": y.get("category"), "j_dbm": round(J, 1), "s_dbm": round(Sv, 1), "js_db": js,
                                "js_req_db": jsreq, "bw_penalty_db": round(pen, 1), "status": status, "a": y["pos"], "b": v["pos"]})
        L[f"{nn['side']}_denied"] |= den
        cov_n = int(covd.sum())
        per_net.append({"net": nn["name"], "side": nn["side"], "category": nn.get("category"), "space": space,
                        "coverage_km2": None if space else round(cov_n * km2, 1), "denied_km2": round(float(den.sum()) * km2, 1),
                        "denied_pct": round(100 * float(den.sum()) / max(1, cov_n), 1), "js_req_db": jsreq})

    layers = {k: overlay_png(region_masks(m, LAYER_RGBA[k], hatched=k.endswith("_denied"))) for k, m in L.items() if m.any()}
    exposure = [{"side": sd, "km2": round(float(L[f"{sd}_seen"].sum()) * km2, 1)} for sd in ("blue", "red")]
    horizon = max([track_minutes(e) for e in ents] + [0])
    _LAST.update({"t": t_min, "pos": {e["id"]: e["pos"] for e in ents}, "detections": detections, "fixes": fixes,
                  "jamming": jamming, "params": p})
    return {"t_min": t_min, "horizon_min": round(horizon, 1), "bounds": [[s, w], [n, e_]], "layers": layers,
            "positions": {e["id"]: e["pos"] for e in ents}, "on_air": {e["id"]: e["active"] for e in ents}, "detections": detections, "fixes": fixes,
            "jamming": jamming, "nets": per_net, "exposure": exposure, "params": p.model_dump(),
            "compute_s": round(time.monotonic() - t0, 1),
            "notes": "Screening only: Deygout 3-edge on Copernicus 30 m terrain; no processing gain, hopping, nulling, clutter, "
                     "multipath or time variability. Radar modelled as an emitter for ES only. DF fix error = range x DF "
                     "sigma per bearing, combined over the best cut angle. Notional scenario data."}


# ---- examples --------------------------------------------------------------------------------
@router.get("/examples")
async def examples():
    from .emo_examples import EXAMPLES
    return {"examples": [{"id": k, "title": v["title"], "about": v["about"], "centre": v["centre"], "zoom": v["zoom"],
                          "entities": len(v["entities"])} for k, v in EXAMPLES.items()]}


@router.post("/examples/{name}")
async def load_example(name: str):
    """Replace the current scenario with a notional example; entities are then editable."""
    from .emo_examples import EXAMPLES
    ex = EXAMPLES.get(name)
    if not ex:
        raise HTTPException(404, "no such example")
    with get_db().tx() as c:
        c.execute("DELETE FROM emo_entities")
    ids = {}
    for d in ex["entities"]:
        dd = {k: v for k, v in d.items() if k != "net"}
        dd["radius_km"] = max(dd.get("radius_km") or 0, auto_radius(dd["freq_mhz"], dd.get("h_agl", 2)))
        ids[d["name"]] = _upsert(EntityIn(**dd), None)["id"]
    with get_db().tx() as c:
        for d in ex["entities"]:
            if d.get("net"):
                c.execute("UPDATE emo_entities SET net=? WHERE id=?", (ids[d["net"]], ids[d["name"]]))
    _COV.clear(); _P2P.clear()
    return {"loaded": name, "title": ex["title"], "about": ex["about"], "centre": ex["centre"], "zoom": ex["zoom"],
            "entities": _all()}


# ---- focus on one entity ----------------------------------------------------------------
BANDS = {"blue": [(60, 200, 255, 55), (60, 200, 255, 95), (60, 200, 255, 140)],
         "red": [(255, 90, 90, 55), (255, 90, 90, 95), (255, 90, 90, 140)]}


@router.get("/focus/{eid}")
async def focus(eid: str, t_min: float = 0):
    """One entity's picture: its footprint (strength bands against the opposing sensors' sensitivity), who hears
    it, what it hears, what it jams or is jammed by. Uses the last run; run first if positions have changed."""
    if not _LAST or abs(_LAST.get("t", -1) - t_min) > 1e-6:
        raise HTTPException(409, "run the analysis first")
    ents = {e["id"]: e for e in _all()}
    e = ents.get(eid)
    if not e:
        raise HTTPException(404, "no such entity")
    for x in ents.values():
        x["active"] = on_air(x, _LAST["t"])
    p: RunIn = _LAST["params"]
    pos = _LAST["pos"].get(eid, (e["lat"], e["lon"]))
    radiates = e["active"] and e.get("eirp_dbm") is not None and e.get("fixed_level_dbm") is None and (
        e["kind"] in ("emitter", "effector") or e["kind"] == "receiver")
    out = {"id": eid, "name": e["name"], "side": e["side"], "kind": e["kind"], "category": e.get("category"),
           "active": e["active"], "overlay": None, "legend": None}
    if radiates:
        cov = await coverage_for(e, pos, p.rx_h)
        watchers = [x for x in ents.values() if x["kind"] == "sensor" and x["side"] != e["side"] and overlap(*band(e), *band(x))]
        thr = min([x.get("sens_dbm") or p.default_sens for x in watchers], default=p.default_sens)
        s_, w_, n_, e2 = cov.bounds()
        LA, LO = raster_axes(s_, w_, n_, e2, px=480)
        lv = sample(cov, LA, LO)
        masks = band_masks(lv, thr, e["side"])
        if e["kind"] == "effector":
            # the denial it causes on each victim net inside that net's coverage
            for nn in [x for x in ents.values() if x["kind"] == "emitter" and x["side"] != e["side"] and x["active"]
                       and overlap(*victim_band(x), *band(e)) and any(r.get("net") == x["id"] for r in ents.values())]:
                pen = jam_penalty(e, nn)
                jsreq = nn["js_req_db"] if nn.get("js_req_db") is not None else p.js_req_db
                if nn.get("fixed_level_dbm") is not None:
                    S = np.full(LA.shape, float(nn["fixed_level_dbm"])); covd = np.ones(LA.shape, bool)
                else:
                    S = sample(await coverage_for(nn, _LAST["pos"].get(nn["id"], (nn["lat"], nn["lon"])), p.rx_h), LA, LO)
                    covd = S >= (nn.get("sens_dbm") or p.default_sens)
                with np.errstate(invalid="ignore"):
                    masks += region_masks(covd & ((lv - pen - S) >= jsreq), (235, 40, 235, 210), hatched=True)
        out["overlay"] = {"png": overlay_png(masks), "bounds": [[s_, w_], [n_, e2]]}
        out["legend"] = {"threshold_dbm": round(thr, 1), "bands_db": [0, 10, 20],
                         "basis": "opposing sensors' best sensitivity" if watchers else "default sensitivity (no opposing sensor on this band)"}
    det, jam = _LAST["detections"], _LAST["jamming"]
    out["heard_by"] = sorted([d for d in det if d["target_id"] == eid], key=lambda d: -d["margin_db"])
    out["hears"] = sorted([d for d in det if d.get("sensor_id") == eid], key=lambda d: -d["margin_db"])
    out["jams"] = [j for j in jam if j.get("effector_id") == eid]
    out["jammed"] = [j for j in jam if j.get("victim_id") == eid or (e["kind"] == "emitter" and j["net"] == e["name"])]
    fx = [f for f in _LAST["fixes"] if f["target"] == e["name"]]
    out["fix"] = fx[0] if fx else None
    return out


# ---- saved scenarios --------------------------------------------------------------------------
class SaveIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.get("/scenarios")
async def list_scenarios():
    rows = get_db().query("SELECT id, name, created_at, entities FROM emo_scenarios ORDER BY created_at DESC")
    return {"scenarios": [{"id": r["id"], "name": r["name"], "created_at": r["created_at"],
                           "entities": len(json.loads(r["entities"]))} for r in rows]}


@router.post("/scenarios")
async def save_scenario(body: SaveIn):
    """Snapshot the current entities (with their ids and net links) under a name."""
    ents = [dict(r) for r in get_db().query("SELECT * FROM emo_entities")]
    if not ents:
        raise HTTPException(400, "nothing to save")
    sid = uuid.uuid4().hex[:8]
    with get_db().tx() as c:
        c.execute("INSERT INTO emo_scenarios (id, name, created_at, entities) VALUES (?,?,?,?)",
                  (sid, body.name.strip(), now_iso(), json.dumps(ents)))
    return {"id": sid, "name": body.name.strip(), "entities": len(ents)}


@router.post("/scenarios/{sid}/load")
async def load_scenario(sid: str):
    row = get_db().one("SELECT entities FROM emo_scenarios WHERE id=?", (sid,))
    if not row:
        raise HTTPException(404, "no such scenario")
    ents = json.loads(row["entities"])
    with get_db().tx() as c:
        c.execute("DELETE FROM emo_entities")
        for e in ents:
            e["updated_at"] = now_iso()
            cols = list(e)
            c.execute(f"INSERT INTO emo_entities ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [e[k] for k in cols])
    _COV.clear(); _P2P.clear(); _LAST.clear()
    return {"loaded": sid, "entities": _all()}


@router.delete("/scenarios/{sid}")
async def delete_scenario(sid: str):
    with get_db().tx() as c:
        n = c.execute("DELETE FROM emo_scenarios WHERE id=?", (sid,)).rowcount
    if not n:
        raise HTTPException(404, "no such scenario")
    return {"deleted": sid}
