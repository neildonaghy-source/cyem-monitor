"""SatNOGS satellite transmitters (downlink frequencies) and pass prediction over a site.

Transmitters come from the SatNOGS DB (CC BY-SA 4.0), refreshed weekly by the
'satnogs' collector. Passes use CelesTrak TLEs fetched on demand and SGP4."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from .db import get_db

router = APIRouter(prefix="/api/sat", tags=["satellites"])
DOPPLER_HZ = 50e3
_TLE: dict[int, tuple[float, str, str, str]] = {}


def transmitters_near(f_hz: float, limit: int = 12) -> list[dict]:
    snap, _ = get_db().get_snapshot("satnogs")
    if not snap:
        return []
    out = []
    for t in snap.get("tx", []):
        lo, hi = t["lo"], t.get("hi") or t["lo"]
        if lo - DOPPLER_HZ <= f_hz <= hi + DOPPLER_HZ:
            out.append({**t, "offset_khz": round((min(abs(f_hz - lo), abs(f_hz - hi)) if not lo <= f_hz <= hi else 0) / 1e3, 1)})
    out.sort(key=lambda t: (t["offset_khz"], t["sat"]))
    return out[:limit]


def _gmst(jd_ut1: float) -> float:
    t = (jd_ut1 - 2451545.0) / 36525.0
    g = 67310.54841 + (876600 * 3600 + 8640184.812866) * t + 0.093104 * t * t - 6.2e-6 * t ** 3
    return math.radians((g % 86400) / 240.0)


def _look(lat, lon, alt_km, r_teme, jd):
    th = _gmst(jd)
    x, y, z = r_teme
    xe, ye = x * math.cos(th) + y * math.sin(th), -x * math.sin(th) + y * math.cos(th)
    a, f = 6378.137, 1 / 298.257223563
    e2 = f * (2 - f)
    la, lo = math.radians(lat), math.radians(lon)
    n = a / math.sqrt(1 - e2 * math.sin(la) ** 2)
    ox, oy, oz = (n + alt_km) * math.cos(la) * math.cos(lo), (n + alt_km) * math.cos(la) * math.sin(lo), (n * (1 - e2) + alt_km) * math.sin(la)
    dx, dy, dz = xe - ox, ye - oy, z - oz
    east = -math.sin(lo) * dx + math.cos(lo) * dy
    north = -math.sin(la) * math.cos(lo) * dx - math.sin(la) * math.sin(lo) * dy + math.cos(la) * dz
    up = math.cos(la) * math.cos(lo) * dx + math.cos(la) * math.sin(lo) * dy + math.sin(la) * dz
    rng = math.sqrt(dx * dx + dy * dy + dz * dz)
    return math.degrees(math.asin(up / rng)), (math.degrees(math.atan2(east, north)) + 360) % 360


async def _tle(norad: int):
    import time
    from .collectors.base import make_http
    c = _TLE.get(norad)
    if c and time.time() - c[0] < 12 * 3600:
        return c[1:]
    async with make_http() as http:
        r = await http.get(f"https://celestrak.org/NORAD/elements/gp.php?CATNR={norad}&FORMAT=tle", timeout=30)
    lines = [ln.strip() for ln in r.text.splitlines() if ln.strip()]
    if r.status_code != 200 or len(lines) < 3 or not lines[1].startswith("1 "):
        raise HTTPException(404, f"no TLE for NORAD {norad}")
    _TLE[norad] = (time.time(), lines[0], lines[1], lines[2])
    return lines[0], lines[1], lines[2]


def passes(l1: str, l2: str, lat: float, lon: float, hours: int = 24, min_el: float = 10.0) -> list[dict]:
    from sgp4.api import Satrec, jday
    s = Satrec.twoline2rv(l1, l2)
    t0 = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    out, cur = [], None
    for k in range(hours * 60 + 1):
        t = t0 + timedelta(minutes=k)
        jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, 0)
        e, r, _ = s.sgp4(jd, fr)
        if e:
            continue
        el, az = _look(lat, lon, 0.0, r, jd + fr)
        if el >= min_el:
            if not cur:
                cur = {"start": t, "max_el": el, "az_start": az, "t_max": t}
            if el > cur["max_el"]:
                cur["max_el"], cur["t_max"] = el, t
            cur["end"], cur["az_end"] = t, az
        elif cur:
            out.append(cur); cur = None
    if cur:
        out.append(cur)
    return [{"start": p["start"].isoformat().replace("+00:00", "Z"), "end": p["end"].isoformat().replace("+00:00", "Z"),
             "max_el": round(p["max_el"], 1), "t_max": p["t_max"].isoformat().replace("+00:00", "Z"),
             "az_start": round(p["az_start"]), "az_end": round(p["az_end"]),
             "duration_min": int((p["end"] - p["start"]).total_seconds() // 60) + 1} for p in out]


@router.get("/passes")
async def sat_passes(norad: int, lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180),
                     hours: int = Query(default=24, ge=1, le=72), min_el: float = Query(default=10, ge=0, le=80)):
    import asyncio
    name, l1, l2 = await _tle(norad)
    ps = await asyncio.to_thread(passes, l1, l2, lat, lon, hours, min_el)
    return {"norad": norad, "name": name, "site": [lat, lon], "hours": hours, "min_el": min_el, "passes": ps}


@router.get("/transmitters")
async def sat_tx(freq_mhz: float = Query(gt=0)):
    return {"freq_mhz": freq_mhz, "transmitters": transmitters_near(freq_mhz * 1e6, 30)}
