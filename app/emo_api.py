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
    side: str = Field(pattern="^(blue|red|grey)$")   # grey = neutral / civil
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
    "grey_cov": (170, 180, 190, 55), "grey_seen": (190, 195, 205, 80),   # civil emissions heard by either side
    "grey_denied": (255, 255, 255, 200),                                  # collateral: civil users denied
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


def scoreboard(ents, detections, fixes, jamming, nets) -> dict:
    """Per-side measures of the EM fight: net availability, exposure, fix risk, denial achieved, collateral."""
    out = {}
    for sd in ("blue", "red"):
        opp = "red" if sd == "blue" else "blue"
        bad = {j["victim"] for j in jamming if j["status"] in ("denied", "no signal")}
        rx = [e for e in ents if e["side"] == sd and e["kind"] == "receiver"]
        avail = [e["name"] not in bad for e in rx]
        radiating = [e for e in ents if e["side"] == sd and e["active"] and (e["kind"] in ("emitter", "effector") or e.get("eirp_dbm") is not None)
                     and e.get("fixed_level_dbm") is None]
        heard = {d["target"] for d in detections if d["detected"] and d["sensor_side"] == opp}
        exposed = [e for e in radiating if e["name"] in heard]
        margins = [d["margin_db"] for d in detections if d["detected"] and d["sensor_side"] == opp]
        out[sd] = {
            "net_availability_pct": round(100 * sum(avail) / len(avail), 0) if avail else None,
            "emitters_exposed": f"{len(exposed)}/{len(radiating)}",
            "mean_exposure_db": round(sum(margins) / len(margins), 1) if margins else None,
            "fixed": sum(1 for f in fixes if f["target_side"] == sd and f["fix"]),
            "targetable": sum(1 for f in fixes if f["target_side"] == sd and f["targetable"]),
            "denial_achieved": sum(1 for j in jamming if j["effector_side"] == sd and j["status"] == "denied" and not j.get("collateral")),
            "collateral": sum(1 for j in jamming if j["effector_side"] == sd and j["status"] == "denied" and j.get("collateral")),
            "net_area_denied_pct": round(sum(n["denied_pct"] for n in nets if n["side"] == sd) / max(1, sum(1 for n in nets if n["side"] == sd)), 1),
        }
    return out


def other(side: str) -> str:
    return "red" if side == "blue" else "blue"


@router.post("/run")
async def run(p: RunIn, t_min: float = 0, light: bool = False, keep: bool = True):
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
    covs = [] if light else await asyncio.gather(*[coverage_for(e, e["pos"], p.rx_h) for e in terr_rad])
    grids = {} if light else {e["id"]: c for e, c in zip(terr_rad, covs)}
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
    for e in ([] if light else terr_rad):
        watchers = [x for x in sensors if x["side"] != e["side"] and x["side"] != "grey" and overlap(*band(e), *band(x))]
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
                # bearings are pooled per observing side: red and blue never share a fix
                bearings.setdefault((e["id"], x["side"]), []).append({"sensor": x["name"], "site": x["pos"], "bearing": brg,
                                                                     "sigma": x["df_rms_deg"]})
    fixes = []
    for (tid, by_side), bs in bearings.items():
        t = byid[tid]
        f = df_fix(t["pos"], bs) if len(bs) >= 2 else None
        good = bool(f and f["error_m"] <= p.df_fix_good_m)
        fixes.append({"target": t["name"], "target_side": t["side"], "by_side": by_side, "lobs": len(bs),
                      "sensors": [b["sensor"] for b in bs], "bearings": [{"site": b["site"], "bearing": round(b["bearing"], 1)} for b in bs],
                      "fix": f, "targetable": good and t["side"] != "grey",          # civil emitters are located, not targets
                      "located": good and t["side"] == "grey", "pos": t["pos"]})

    # EA: nets, J/S, denial
    jamming, per_net = [], []
    effectors = [e for e in radiating if e["kind"] == "effector"]
    for nn in nets:
        space = nn.get("fixed_level_dbm") is not None
        nlo, nhi = victim_band(nn)
        jsreq = nn["js_req_db"] if nn.get("js_req_db") is not None else p.js_req_db
        nsens = nn.get("sens_dbm") or p.default_sens
        S = np.full(LA.shape, float(nn["fixed_level_dbm"])) if space else (None if light else lv[nn["id"]])
        covd = np.ones(LA.shape, bool) if space else (np.zeros(LA.shape, bool) if light else S >= nsens)
        if not space and not light:
            L[f"{nn['side']}_cov"] |= covd
        den = np.zeros(LA.shape, bool)
        for y in effectors:
            if y["side"] == nn["side"] or not overlap(nlo, nhi, *band(y)) or (not light and y["id"] not in lv):
                continue
            pen = jam_penalty(y, nn)
            if not light:
                with np.errstate(invalid="ignore"):
                    den |= covd & ((lv[y["id"]] - pen - S) >= jsreq)
            for v in [r for r in receivers if r.get("net") == nn["id"]]:
                J = await p2p_level(y, y["pos"], v, v["pos"]) - pen
                Sv = float(nn["fixed_level_dbm"]) if space else await p2p_level(nn, nn["pos"], v, v["pos"])
                vs = v.get("sens_dbm") or nsens
                js = round(J - Sv, 1)
                status = "no signal" if Sv < vs else ("denied" if js >= jsreq else "holds")
                jamming.append({"effector": y["name"], "effector_id": y["id"], "victim_id": v["id"], "effector_side": y["side"], "victim": v["name"], "net": nn["name"],
                                "collateral": nn["side"] == "grey",
                                "category": y.get("category"), "j_dbm": round(J, 1), "s_dbm": round(Sv, 1), "js_db": js,
                                "js_req_db": jsreq, "bw_penalty_db": round(pen, 1), "status": status, "a": y["pos"], "b": v["pos"]})
        L[f"{nn['side']}_denied"] |= den
        cov_n = int(covd.sum())
        per_net.append({"net": nn["name"], "side": nn["side"], "category": nn.get("category"), "space": space,
                        "coverage_km2": None if space else round(cov_n * km2, 1), "denied_km2": round(float(den.sum()) * km2, 1),
                        "denied_pct": round(100 * float(den.sum()) / max(1, cov_n), 1), "js_req_db": jsreq})

    layers = {k: overlay_png(region_masks(m, LAYER_RGBA[k], hatched=k.endswith("_denied"))) for k, m in L.items() if m.any()}
    score = scoreboard(ents, detections, fixes, jamming, per_net)
    exposure = [{"side": sd, "km2": round(float(L[f"{sd}_seen"].sum()) * km2, 1)} for sd in ("blue", "red", "grey")]
    horizon = max([track_minutes(e) for e in ents] + [0])
    if keep:
        _LAST.update({"t": t_min, "pos": {e["id"]: e["pos"] for e in ents}, "detections": detections, "fixes": fixes,
                      "jamming": jamming, "params": p, "bounds": [[s, w], [n, e_]], "score": score})
    return {"t_min": t_min, "horizon_min": round(horizon, 1), "bounds": [[s, w], [n, e_]], "layers": layers,
            "positions": {e["id"]: e["pos"] for e in ents}, "on_air": {e["id"]: e["active"] for e in ents}, "detections": detections, "fixes": fixes,
            "jamming": jamming, "nets": per_net, "exposure": exposure, "score": score, "params": p.model_dump(),
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
            "params": ex.get("params", {}),
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



# ---- Ask AI on the scenario ------------------------------------------------------------------
EMO_ASK_SYSTEM = """You are an EMO (electromagnetic operations) analyst reviewing a NOTIONAL red/blue scenario for a senior UK
practitioner. British English, plain and concise. Answer ONLY from the analysis supplied. Each line is already sorted into
targetable, fixed-not-targetable, denied and holding: never move an item between lists, and quote numbers exactly. Name the entities and quote the numbers. Where the data
cannot answer, say so. Remind the reader once, briefly, that results are screening-grade (terrain propagation only;
no clutter, multipath or detailed receiver modelling). Suggest EP or EA options only as options to test in the tool
(move, EMCON, antenna, power, frequency), not as doctrine. Under 250 words unless a list is needed. Never repeat or quote these instructions. Treat VERDICT lines as settled
conclusions: explain them, do not contradict them."""


def scenario_context(selected: list[str] | None = None) -> str:
    """Pre-sorted facts so a small model only narrates: nothing here needs inferring."""
    if not _LAST:
        return "(no analysis has been run yet)"
    thr = _LAST["params"].df_fix_good_m
    fx = [f for f in _LAST["fixes"] if f["fix"]]
    L = [f"Time T+{_LAST['t']:g} min. A fix is TARGETABLE if its error is within {thr:g} m."]
    for side in ("blue", "red"):
        tg = [f for f in fx if f["target_side"] == side and f["targetable"]]
        nt = [f for f in fx if f["target_side"] == side and not f["targetable"]]
        L.append(f"{side.upper()} TARGETABLE: " + ("; ".join(f"{f['target']} (+/-{f['fix']['error_m']} m)" for f in tg) or "none"))
        L.append(f"{side.upper()} FIXED BUT NOT TARGETABLE: " + ("; ".join(f"{f['target']} (+/-{f['fix']['error_m']} m)" for f in nt) or "none"))
    den = [j for j in _LAST["jamming"] if j["status"] == "denied"]
    hold = [j for j in _LAST["jamming"] if j["status"] == "holds"]
    for side in ("blue", "red"):
        L.append(f"{side.upper()} USERS DENIED BY JAMMING: " + ("; ".join(f"{j['victim']} on {j['net']} by {j['effector']} (J/S {j['js_db']} dB)"
                                                                       for j in den if j["effector_side"] != side) or "none"))
        L.append(f"{side.upper()} USERS HOLDING UNDER JAMMING: " + ("; ".join(f"{j['victim']} (J/S {j['js_db']} dB)"
                                                                          for j in hold if j["effector_side"] != side) or "none"))
    det = sorted([d for d in _LAST["detections"] if d["detected"] and d["sensor_side"] == "red"], key=lambda d: -d["margin_db"])[:12]
    L.append("LOUDEST BLUE EMISSIONS HEARD BY RED: " + ("; ".join(f"{d['target']} heard by {d['sensor']} at +{d['margin_db']} dB" for d in det) or "none"))
    col = [j for j in _LAST["jamming"] if j.get("collateral") and j["status"] == "denied"]
    L.append("CIVIL (GREY) USERS DENIED AS COLLATERAL: " + ("; ".join(f"{j['victim']} by {j['effector']} (J/S {j['js_db']} dB)" for j in col) or "none"))
    if selected:
        ents = {e["id"]: e for e in _all()}
        names = [ents[i]["name"] for i in selected if i in ents]
        sel = set(selected)
        L.append("USER SELECTION (answer about these first): " + "; ".join(f"{ents[i]['name']} ({ents[i]['side']} {ents[i]['kind']}, {ents[i]['freq_mhz']} MHz)" for i in selected if i in ents))
        L.append("WITHIN SELECTION, DETECTIONS: " + ("; ".join(f"{d['sensor']} {'hears' if d['detected'] else 'does not hear'} {d['target']} ({d['margin_db']:+} dB)"
                 for d in _LAST["detections"] if d.get("sensor_id") in sel and d["target_id"] in sel) or "none"))
        L.append("WITHIN SELECTION, JAMMING: " + ("; ".join(f"{j['effector']} vs {j['victim']}: J/S {j['js_db']} dB, {j['status']}"
                 for j in _LAST["jamming"] if j.get("effector_id") in sel and (j.get("victim_id") in sel or j["net"] in names)) or "none"))
        for i in selected:
            e = ents.get(i)
            if not e:
                continue
            if e["kind"] == "emitter":
                users = [u["name"] for u in ents.values() if u.get("net") == i]
                kind = {"comms": "communications net", "datalink": "datalink", "nav": "navigation signal"}.get(e.get("category"), "emitter")
                L.append(f"FACT: {e['name']} is the control station of a {e['side']} {kind} on {e['freq_mhz']} MHz"
                         + (f" with users {', '.join(users)}." if users else "."))
                for j in [j for j in _LAST["jamming"] if j["net"] == e["name"]]:
                    L.append(f"FACT: {j['effector']} against {j['victim']} (a user of that net): J/S {j['js_db']} dB against a "
                             f"{j['js_req_db']} dB threshold, so the user is {j['status'].upper()}.")
            if e["kind"] == "effector":
                hit = [j for j in _LAST["jamming"] if j.get("effector_id") == i]
                L.append(f"FACT: {e['name']} is a {e['side']} jammer on {e['freq_mhz']} MHz; it denies "
                         f"{sum(j['status'] == 'denied' for j in hit)} of {len(hit)} users it reaches"
                         + (": " + ", ".join(j["victim"] for j in hit if j["status"] == "denied") if hit else "") + ".")
        L.append("RULE: jamming denies RECEPTION at the net's users; the control station still transmits and can still be "
                 "heard and DF-fixed. Being fixed is about targeting, not about jamming.")
    L.append("Note: radars and SATCOM are emitters only; only nets (comms, datalinks, GNSS) can be jammed in this model.")
    return "\n".join(L)


PLAN_WORDS = ("site", "where", "move", "position", "relay", "avoid", "hide", "survive", "communicat", "deny", "jam", "place", "locat")
PLAN_RULES = (" When COMPUTED PLAN lines are present, lead with them: state each recommended position exactly as given "
              "(the 'x km DIR of Y' description and the lat/lon), what it achieves (users closed, heard by whom, J/S), and "
              "how it compares with the current position. Do not invent positions that are not in the plan. If the plan "
              "says a selection is needed, tell the user which entity to select.")


async def _plan_facts(question: str, selected: list[str] | None) -> str:
    """Run the siting solver when the question is about positioning, and return its results as facts."""
    if not any(w in question.lower() for w in PLAN_WORDS):
        return ""
    from . import emo_plan
    ents = {e["id"]: e for e in _all()}
    sel = [ents[i] for i in (selected or []) if i in ents]
    nets = [e for e in sel if e["kind"] == "emitter" and e.get("fixed_level_dbm") is None and any(u.get("net") == e["id"] for u in ents.values())]
    effs = [e for e in sel if e["kind"] == "effector"]
    if not sel or not (nets or effs):
        return ("COMPUTED PLAN: none. To compute positions, select the net's control station (for siting a net) or a jammer "
                "together with the target net (for siting a jammer), then ask again.")
    t = _LAST.get("t", 0)
    out = []
    for y in effs:
        targets = [n for n in nets if n["side"] != y["side"]]
        for n in targets[:2]:
            try:
                r = await emo_plan.plan_map(emo_plan.MapIn(kind="ea", name=y["name"], target_net=n["name"]), t_min=t)
            except HTTPException as e:
                out.append(f"COMPUTED PLAN (EA {y['name']} vs {n['name']}): not possible ({e.detail})."); continue
            c, b = r["current"], (r["best"] or [None])[0]
            out.append(f"COMPUTED PLAN (EA): {y['name']} against {n['name']} ({len(r['users'])} users). Current position: denies "
                       f"{c['denied']}/{c['of_users']}, exposure to {n['side']} DF {c['exposure_db']:+} dB, fratricide {c['fratricide']}.")
            req = r.get("js_req_db", 0)
            def jm(x):
                return (x["min_js_db"] or -99) - req
            for i, x in enumerate(r["best"][:3], 1):
                out.append(f"  Option {i}: {x['where']} ({x['lat']}, {x['lon']}): denies {x['denied']}/{x['of_users']} users; weakest "
                           f"J/S margin {jm(x):+.1f} dB (higher is better for the jammer); exposure to red DF {x['exposure_db']:+} dB; "
                           f"fratricide {x['fratricide']}.")
            best = r["best"][0] if r["best"] else None
            if best:
                gain_d = best["denied"] - c["denied"]
                gain_js = jm(best) - jm(c)
                if gain_d > 0:
                    v = f"moving to Option 1 denies {gain_d} more user(s)"
                elif gain_js >= 3:
                    v = f"moving to Option 1 keeps the same denial with {gain_js:.1f} dB more J/S margin"
                else:
                    v = "the current site is as good as any within reach; moving gains little"
                unav = c["exposure_db"] >= 0 and best["exposure_db"] >= 0
                out.append(f"  VERDICT: {v}." + (" The jammer is heard by red DF wherever it goes within reach, so expect it "
                           "to be located; limit its on-air time." if unav else ""))
    for n in nets:
        if any(y["side"] != n["side"] for y in effs):
            continue                               # this net is the EA target above, not one to re-site
        try:
            r = await emo_plan.plan_map(emo_plan.MapIn(kind="net", name=n["name"]), t_min=t)
        except HTTPException as e:
            out.append(f"COMPUTED PLAN (EP {n['name']}): not possible ({e.detail})."); continue
        c = r["current"]
        out.append(f"COMPUTED PLAN (EP): {n['name']} net with users {', '.join(r['users'])}. Opposing sensors on this band: "
                   f"{', '.join(r['opp_sensors']) or 'none'}; opposing jammers: {', '.join(r['opp_jammers']) or 'none'}. "
                   f"Current position: {c['users_closed']}/{c['of_users']} users have a working link, weakest link margin {c['link_margin_db']:+} dB, "
                   f"heard by {', '.join(c['heard_by']) or 'no opposing sensor'}, worst J/S {c['worst_js_db']:+} dB.")
        for i, x in enumerate(r["best"][:3], 1):
            out.append(f"  Option {i}: move the control station to {x['where']} ({x['lat']}, {x['lon']}): {x['users_closed']}/{x['of_users']} "
                       f"users with a working link, margin {x['link_margin_db']:+} dB, heard by {', '.join(x['heard_by']) or 'no opposing sensor'}, "
                       f"worst J/S {x['worst_js_db']:+} dB; power could be cut by {x['power_cut_db']} dB and the net still closes, "
                       f"after which it is still heard by {', '.join(x['heard_at_min_power']) or 'no opposing sensor'}.")
        jreq = n["js_req_db"] if n.get("js_req_db") is not None else _LAST["params"].js_req_db
        works = c["users_closed"] == c["of_users"]
        jammed = c["worst_js_db"] >= jreq
        out.append(f"  VERDICT: the net {'WORKS' if works else 'does NOT reach all users'} now and "
                   f"{'IS' if jammed else 'is NOT'} denied by red jamming (worst J/S {c['worst_js_db']:+} dB against a {jreq:g} dB "
                   f"failure threshold). The issue is {'jamming' if jammed else 'detection by red ES' if c['heard_by'] else 'none found'}.")
        if r.get("unavoidable"):
            out.append(f"  LIMIT: no position within reach, even at minimum power, hides this net from {', '.join(r['unavoidable'])}. "
                       "Siting alone cannot solve it; the remaining EP options are emission control (on-air windows when that "
                       "sensor is not on station), a directional antenna pointed away from it, or a different bearer "
                       "(e.g. line-of-sight UHF or SATCOM). Say this plainly.")
        if r.get("relay"):
            rl = r["relay"]
            out.append(f"  Relay: add a relay node (10 m mast) at {rl['where']} ({rl['lat']}, {rl['lon']}) to reach "
                       f"{', '.join(rl['serves'])}: reaches {rl['reaches']}/{rl['of_failing']}, exposure {rl['exposure_db']:+} dB.")
    return "\n".join(out)


def _plan_template(plan: str) -> str:
    """Structured answer straight from the solver: positions, effects, verdict, limits. No prose model involved."""
    out = ["**Computed siting plan** (terrain screening model; positions to test, not a solution)", ""]
    for line in plan.splitlines():
        s = line.strip()
        if s.startswith("COMPUTED PLAN"):
            out.append("**" + s.replace("COMPUTED PLAN (EP):", "Net:").replace("COMPUTED PLAN (EA):", "Jammer:").replace("COMPUTED PLAN", "Plan") + "**")
        elif s.startswith("Option"):
            out.append("- " + s)
        elif s.startswith("Relay:"):
            out.append("- **" + s + "**")
        elif s.startswith("VERDICT:"):
            out.append("")
            out.append("**Verdict.** " + s[8:].strip())
        elif s.startswith("LIMIT:"):
            out.append("**Limit.** " + s[6:].strip().replace(" Say this plainly.", ""))
        elif s:
            out.append(s)
    out.append("")
    out.append("_Tap Find a better site (EP) or Best site to deny it (EA) in the focus card to see these on the map._")
    return "\n".join(out)


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=800)
    selected: list[str] | None = None


@router.post("/ask")
async def emo_ask(req: AskIn):
    from fastapi.responses import StreamingResponse
    from . import llm
    plan = await _plan_facts(req.question, req.selected)
    if plan and not plan.startswith("COMPUTED PLAN: none"):
        from fastapi.responses import StreamingResponse as _SR
        text = _plan_template(plan)

        async def gen_plan():
            yield f"data: {json.dumps({'t': text})}\n\n"
            yield "data: {\"done\": true}\n\n"
        return _SR(gen_plan(), media_type="text/event-stream")
    msgs = [{"role": "system", "content": EMO_ASK_SYSTEM + PLAN_RULES},
            {"role": "user", "content": f"ANALYSIS\n{scenario_context(req.selected)}\n{plan}\n\nQUESTION: {req.question.strip()}"}]

    async def gen():
        try:
            async for tok in llm.chat_stream(msgs, num_predict=600, temperature=0.1):
                yield f"data: {json.dumps({'t': tok})}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'error': f'{type(e).__name__}: {str(e)[:200]}'})}\n\n"
        yield "data: {\"done\": true}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


# ---- EMO briefing export (Word): one section per phase ------------------------------------------
def _schematic_png(res: dict, ents: list[dict]) -> bytes:
    """Schematic (no basemap): overlays, fix circles, jamming lines and entity markers on a dark field."""
    import base64
    import io
    from PIL import Image, ImageDraw
    (s, w), (n, e) = res["bounds"]
    W = 900
    H = max(300, int(W * (n - s) / max(e - w, 1e-6) / max(math.cos(math.radians((s + n) / 2)), 0.2)))
    img = Image.new("RGBA", (W, H), (14, 20, 28, 255))
    for k in ("blue_seen", "red_seen", "blue_denied", "red_denied"):
        u = res["layers"].get(k)
        if u:
            ov = Image.open(io.BytesIO(base64.b64decode(u.split(",", 1)[1]))).convert("RGBA").resize((W, H))
            img.alpha_composite(ov)
    d = ImageDraw.Draw(img)
    xy = lambda la, lo: ((lo - w) / (e - w) * W, (n - la) / (n - s) * H)  # noqa: E731
    for j in res["jamming"]:
        col = (235, 40, 235, 255) if j["status"] == "denied" else (69, 211, 138, 200)
        d.line([xy(*j["a"]), xy(*j["b"])], fill=col, width=2)
    for f in res["fixes"]:
        if f["fix"]:
            cx, cy = xy(*f["fix"]["fix"])
            r = max(4, f["fix"]["error_m"] / 111320 / (n - s) * H)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 70, 70, 255) if f["target_side"] == "blue" else (60, 200, 255, 255),
                      width=3 if f["targetable"] else 1)
    for en in ents:
        la, lo = res["positions"].get(en["id"], (en["lat"], en["lon"]))
        x, y = xy(la, lo)
        col = (60, 140, 255, 255) if en["side"] == "blue" else (255, 70, 70, 255)
        if en["side"] == "blue":
            d.rectangle([x - 5, y - 4, x + 5, y + 4], fill=col, outline=(255, 255, 255, 255))
        else:
            d.polygon([(x, y - 6), (x + 6, y), (x, y + 6), (x - 6, y)], fill=col, outline=(255, 255, 255, 255))
        d.text((x + 8, y - 6), en["name"][:22], fill=(230, 237, 243, 255))
    out = io.BytesIO(); img.convert("RGB").save(out, "PNG")
    return out.getvalue()


@router.get("/export.docx")
async def emo_export(phases: str = "0", df_fix_good_m: float = 1000):
    import io
    from datetime import datetime, timezone
    from docx import Document
    from docx.shared import Cm, Pt
    from fastapi.responses import StreamingResponse
    ts = sorted({max(0.0, float(x)) for x in phases.split(",") if x.strip()})[:6] or [0.0]
    doc = Document()
    st = doc.styles["Normal"]; st.font.name = "Arial"; st.font.size = Pt(10)
    doc.add_heading("CyEM EMO briefing (notional scenario)", 0)
    doc.add_paragraph(f"Produced {datetime.now(timezone.utc):%d %b %Y %H:%MZ}. Screening-grade analysis on Copernicus 30 m terrain "
                      "(Deygout, 3 edges); no clutter, multipath or detailed receiver modelling. Notional data only.")
    for t in ts:
        res = await run(RunIn(df_fix_good_m=df_fix_good_m), t_min=t)
        ents = _all()
        doc.add_heading(f"Phase T+{t:g} min", 1)
        tgt = [f for f in res["fixes"] if f["targetable"]]
        den = sorted(res["nets"], key=lambda x: -x["denied_pct"])
        doc.add_paragraph(f"{len(tgt)} targetable fix(es) (threshold {df_fix_good_m:g} m). "
                          + "; ".join(f"{x['net']} ({x['side']}) {x['denied_pct']}% denied" for x in den[:4]) + ".")
        doc.add_picture(io.BytesIO(await asyncio.to_thread(_schematic_png, res, ents)), width=Cm(16))
        doc.add_paragraph("Schematic, no basemap. Blue squares, red diamonds; tint = where each side's emissions are heard; "
                          "hatched = net denial; circles = DF fixes (thick = targetable); lines = jamming (magenta denied).").runs[0].italic = True
        def table(head, rows):
            tb = doc.add_table(rows=1, cols=len(head)); tb.style = "Light Grid Accent 1"
            for i, h in enumerate(head):
                tb.rows[0].cells[i].text = h
            for r in rows:
                cs = tb.add_row().cells
                for i, v in enumerate(r):
                    cs[i].text = str(v)
        fx = [f for f in res["fixes"] if f["fix"]]
        if fx:
            doc.add_heading("DF fixes", 2)
            table(["Target", "Side", "Error m", "Cut", "Targetable", "By"],
                  [[f["target"], f["target_side"], f["fix"]["error_m"], f["fix"]["cut_deg"], "yes" if f["targetable"] else "no",
                    " + ".join(f["fix"]["sensors"])] for f in fx])
        if res["nets"]:
            doc.add_heading("Nets under attack", 2)
            table(["Net", "Side", "Coverage km2", "Denied %", "Fails at J/S dB"],
                  [[x["net"], x["side"], x["coverage_km2"] if x["coverage_km2"] is not None else "space", x["denied_pct"], x["js_req_db"]] for x in res["nets"]])
        if res["jamming"]:
            doc.add_heading("Jamming at each victim", 2)
            table(["Effector", "Victim", "J/S dB", "Result"], [[j["effector"], j["victim"], j["js_db"], j["status"]] for j in res["jamming"]])
    buf = io.BytesIO(); doc.save(buf)
    name = f"CyEM-EMO-brief-{datetime.now(timezone.utc):%Y%m%d-%H%MZ}.docx"
    return StreamingResponse(io.BytesIO(buf.getvalue()), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})



# ---- pair analysis: how two selected entities interact, as a map overlay -------------------------
@router.get("/pair")
async def pair(a: str, b: str, t_min: float = 0):
    """Jammer vs a net (or a net user): the net's coverage with the zone this jammer denies hatched, plus J/S at each
    user. Emitter vs an opposing sensor: where the emitter is heard at that sensor's sensitivity. Else no overlay."""
    if not _LAST or abs(_LAST.get("t", -1) - t_min) > 1e-6:
        raise HTTPException(409, "run the analysis first")
    from .ems_core import band_masks, region_masks
    ents = {e["id"]: e for e in _all()}
    A, Bn = ents.get(a), ents.get(b)
    if not A or not Bn:
        raise HTTPException(404, "no such entity")
    p: RunIn = _LAST["params"]
    pos = lambda e: _LAST["pos"].get(e["id"], (e["lat"], e["lon"]))  # noqa: E731
    radiates = lambda e: e["active"] and e.get("eirp_dbm") is not None and e.get("fixed_level_dbm") is None  # noqa: E731
    y, net = None, None
    for x, o in ((A, Bn), (Bn, A)):
        if x["kind"] == "effector" and x["side"] != o["side"]:
            n = o if o["kind"] == "emitter" else ents.get(o.get("net") or "") if o["kind"] == "receiver" else None
            if n and n["side"] != x["side"] and overlap(*band(n), *band(x)):
                y, net = x, n
                break
    if y and radiates(y):
        gy = await coverage_for(y, pos(y), p.rx_h)
        grids = [gy]
        space = net.get("fixed_level_dbm") is not None
        if not space:
            gn = await coverage_for(net, pos(net), p.rx_h); grids.append(gn)
        s_, w_, n_, e_ = union_bounds(grids)
        LA, LO = raster_axes(s_, w_, n_, e_, px=480)
        km2 = cell_km2(LA, LO)
        J = sample(gy, LA, LO) - jam_penalty(y, net)      # bandwidth, hopping and processing gain
        S = np.full(LA.shape, float(net["fixed_level_dbm"])) if space else sample(gn, LA, LO)
        covd = (J > -900) if space else S >= (net.get("sens_dbm") or p.default_sens)
        jsreq = net["js_req_db"] if net.get("js_req_db") is not None else p.js_req_db
        with np.errstate(invalid="ignore"):
            den = covd & ((J - S) >= jsreq)
        holds = covd & ~den
        netcol = {"blue": (60, 140, 255, 90), "red": (255, 90, 90, 80), "grey": (170, 180, 190, 80)}[net["side"]]
        masks = region_masks(holds, netcol) + region_masks(den, (235, 40, 235, 210), hatched=True)
        users = [j for j in _LAST["jamming"] if j.get("effector_id") == y["id"] and j["net"] == net["name"]]
        return {"kind": "jam", "effector": y["name"], "net": net["name"], "net_side": net["side"], "space": space,
                "overlay": {"png": overlay_png(masks), "bounds": [[s_, w_], [n_, e_]]} if masks else None,
                "coverage_km2": None if space else round(float(covd.sum()) * km2, 1),
                "denied_km2": round(float(den.sum()) * km2, 1),
                "denied_pct": round(100 * float(den.sum()) / max(1, int(covd.sum())), 1), "js_req_db": jsreq,
                "users": [{"victim": u["victim"], "js_db": u["js_db"], "status": u["status"]} for u in users],
                "legend": f"Tint: where {net['name']} works; hatched magenta: where {y['name']} denies it (J/S >= {jsreq:g} dB)."}
    for em_, se in ((A, Bn), (Bn, A)):
        if se["kind"] == "sensor" and em_["side"] != se["side"] and radiates(em_) and overlap(*band(em_), *band(se)):
            ge = await coverage_for(em_, pos(em_), p.rx_h)
            s_, w_, n_, e_ = ge.bounds()
            LA, LO = raster_axes(s_, w_, n_, e_, px=480)
            thr = se.get("sens_dbm") or p.default_sens
            masks = band_masks(sample(ge, LA, LO), thr, em_["side"] if em_["side"] != "grey" else "grey")
            d = next((d for d in _LAST["detections"] if d.get("sensor_id") == se["id"] and d["target_id"] == em_["id"]), None)
            return {"kind": "hear", "emitter": em_["name"], "sensor": se["name"],
                    "overlay": {"png": overlay_png(masks), "bounds": [[s_, w_], [n_, e_]]},
                    "margin_db": d["margin_db"] if d else None, "detected": bool(d and d["detected"]),
                    "legend": f"Where a sensor like {se['name']} ({thr:g} dBm) at ground level would hear {em_['name']}; "
                              f"the actual {se['name']} at its position and height: {'hears it' if d and d['detected'] else 'does not hear it'}"
                              + (f" ({d['margin_db']:+} dB)." if d else ".")}
    return {"kind": "none", "overlay": None, "legend": "No direct interaction: different bands, same side, or neither is a sensor or effector."}
