"""Weather for propagation and planning: Open-Meteo, cached per place and day, turned into a met state.

met_state(lat, lon, when) gives the k-factor and refraction class from the forecast profile in the lowest kilometre,
ducts in that profile, the evaporation duct when the place is at or near the sea, rain rate, visibility and fog
water, wind, cloud, freezing level, sea state, and current space weather. Recent and future hours come from the
forecast API (up to 16 days ahead), older ones from the historical forecast API (archived model runs, for exercise
replays). With no data it returns the standard atmosphere and says why. No key needed.
"""
from __future__ import annotations

import json
import math
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from . import met_core as mc
from .config import settings
from .db import get_db

LEVELS = (1000, 975, 950, 925, 900, 850, 800, 700)
SURFACE = ("temperature_2m", "relative_humidity_2m", "dew_point_2m", "surface_pressure", "precipitation", "snowfall",
           "visibility", "cloud_cover", "cloud_cover_low", "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
           "freezing_level_height")
PLEVEL = tuple(f"{v}_{p}hPa" for p in LEVELS for v in ("temperature", "relative_humidity", "geopotential_height"))
MARINE = ("wave_height", "wave_period", "wave_direction", "sea_surface_temperature")
FORECAST = "https://api.open-meteo.com/v1/forecast"
HISTORICAL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
SEA_NEAR_KM = 30.0            # use the sea point's duct only when the place is this close to it
GRID_DEG = 0.05               # cache places on a 0.05 degree grid (the models are 2 to 11 km)

STANDARD = {"source": "standard", "k": round(4 / 3, 3), "dn_per_km": mc.STANDARD_DN, "refraction": "normal",
            "rain_mm_h": 0.0, "visibility_m": None, "fog_lwc_gm3": 0.0, "temp_c": 15.0, "ducts": [], "evap_duct": None}


class MetUnavailable(Exception):
    pass


_schema_done: set[str] = set()


def _db():
    db = get_db()
    if db.path not in _schema_done:
        with db.tx() as c:
            c.execute("CREATE TABLE IF NOT EXISTS met_cache (key TEXT PRIMARY KEY, fetched REAL NOT NULL, body TEXT NOT NULL)")
        _schema_done.add(db.path)
    return db


def _grid(x: float) -> float:
    return round(round(x / GRID_DEG) * GRID_DEG, 2)


def valid_hour(when: datetime | None = None) -> datetime:
    """The forecast hour nearest to `when` (UTC)."""
    w = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return (w + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)


async def _fetch(url: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10), headers={"User-Agent": settings.user_agent}) as c:
        r = await c.get(url, params=params)
    if r.status_code != 200:
        try:
            why = r.json().get("reason") or r.text[:120]
        except ValueError:
            why = r.text[:120]
        raise MetUnavailable(f"Open-Meteo {r.status_code}: {why}")
    return r.json()


async def _day(kind: str, lat: float, lon: float, day: date) -> dict:
    """One day of hourly data for a grid place, from the cache when fresh enough."""
    key = f"{kind}:{lat:.2f}:{lon:.2f}:{day.isoformat()}"
    db = _db()
    row = db.one("SELECT fetched, body FROM met_cache WHERE key=?", (key,))
    today = datetime.now(timezone.utc).date()
    ttl = 3 * 3600 if day >= today - timedelta(days=1) else 7 * 86400
    if row and time.time() - row["fetched"] < ttl:
        return json.loads(row["body"])
    base = {"latitude": lat, "longitude": lon, "timezone": "UTC", "start_date": day.isoformat(), "end_date": day.isoformat()}
    try:
        if kind == "marine":
            body = await _fetch(MARINE_URL, {**base, "hourly": ",".join(MARINE)})
        else:
            hourly = ",".join(SURFACE + (PLEVEL if kind == "fc" else ()))
            first = FORECAST if day >= today - timedelta(days=2) else HISTORICAL
            body = await _fetch(first, {**base, "hourly": hourly, "wind_speed_unit": "ms"})
            if all(v is None for v in (body.get("hourly") or {}).get("surface_pressure", [None])):
                other = HISTORICAL if first == FORECAST else FORECAST       # the edges of each API's range
                body = await _fetch(other, {**base, "hourly": hourly, "wind_speed_unit": "ms"})
    except (httpx.HTTPError, ValueError, MetUnavailable) as e:
        if row:
            return json.loads(row["body"])                                  # stale beats nothing
        raise MetUnavailable(str(e) or e.__class__.__name__) from e
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO met_cache (key, fetched, body) VALUES (?,?,?)", (key, time.time(), json.dumps(body)))
        c.execute("DELETE FROM met_cache WHERE fetched < ?", (time.time() - 30 * 86400,))
    return body


def _at(body: dict, hour: datetime):
    hourly = body.get("hourly") or {}
    stamp = hour.strftime("%Y-%m-%dT%H:00")
    try:
        i = hourly.get("time", []).index(stamp)
    except ValueError:
        return lambda name: None
    return lambda name: (hourly.get(name) or [None] * (i + 1))[i]


def _km(lat1, lon1, lat2, lon2) -> float:
    p = math.pi / 180
    a = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 12742.0 * math.asin(min(1.0, math.sqrt(a)))


def standard(reason: str = "", hour: datetime | None = None) -> dict:
    s = {**STANDARD, "valid_time": hour.strftime("%Y-%m-%dT%H:00Z") if hour else None, "warnings": [], "notes": []}
    if reason:
        s["notes"].append(f"Standard atmosphere: {reason}.")
    return s


def build_state(fc: dict, marine: dict | None, sea_air: dict | None, hour: datetime, lat: float, lon: float) -> dict:
    """Met state from Open-Meteo bodies for one hour. Pure apart from its inputs; tested with recorded responses."""
    g = _at(fc, hour)
    ps, t2, rh2 = g("surface_pressure"), g("temperature_2m"), g("relative_humidity_2m")
    if None in (ps, t2, rh2):
        return standard("no forecast for that hour", hour)
    elev = fc.get("elevation") or 0.0
    pts = [{"h": 0.0, "p": ps, "t": t2, "rh": rh2}]
    for p in LEVELS:
        z, t, rh = g(f"geopotential_height_{p}hPa"), g(f"temperature_{p}hPa"), g(f"relative_humidity_{p}hPa")
        if None in (z, t, rh) or p >= ps or z - elev <= 10:
            continue                                                       # below ground or missing
        pts.append({"h": z - elev, "p": float(p), "t": t, "rh": rh})
    prof = mc.profile(pts) if len(pts) > 1 else {**STANDARD, "n_surface": None, "levels": []}
    precip, snow = g("precipitation") or 0.0, g("snowfall") or 0.0
    rain = round(max(0.0, precip - snow * 10.0 / 7.0), 1)                 # Open-Meteo: 7 cm of snow ~ 10 mm of water
    vis = g("visibility")
    fog = mc.fog_lwc_gm3(vis)
    st = {"source": "open-meteo", "valid_time": hour.strftime("%Y-%m-%dT%H:00Z"), "lat": round(lat, 3), "lon": round(lon, 3),
          "model_elevation_m": elev, "k": prof["k"], "dn_per_km": prof["dn_per_km"], "refraction": prof["refraction"],
          "n_surface": prof.get("n_surface"), "ducts": prof["ducts"], "levels": prof.get("levels", []),
          "rain_mm_h": rain, "snow_cm_h": snow, "visibility_m": vis, "fog_lwc_gm3": round(fog, 3), "temp_c": t2,
          "rh_pct": rh2, "pressure_hpa": ps, "dew_c": g("dew_point_2m"),
          "wind_ms": g("wind_speed_10m"), "wind_dir": g("wind_direction_10m"), "gust_ms": g("wind_gusts_10m"),
          "cloud_pct": g("cloud_cover"), "cloud_low_pct": g("cloud_cover_low"),
          "cloud_base_m": mc.cloud_base_m(t2, g("dew_point_2m")), "freezing_level_m": g("freezing_level_height"),
          "evap_duct": None, "sea": None, "warnings": [], "notes": []}
    if marine:
        m = _at(marine, hour)
        sst = m("sea_surface_temperature")
        near = _km(lat, lon, marine.get("latitude", lat), marine.get("longitude", lon))
        if sst is not None and near <= SEA_NEAR_KM:
            st["sea"] = {"sst_c": sst, "wave_m": m("wave_height"), "wave_period_s": m("wave_period"),
                         "wave_dir": m("wave_direction"), "distance_km": round(near, 1)}
            a = _at(sea_air, hour) if sea_air else g                         # air over the sea, not over the land
            ta, rha, pa = a("temperature_2m"), a("relative_humidity_2m"), a("surface_pressure")
            if None not in (ta, rha, pa):
                st["evap_duct"] = mc.evaporation_duct(sst, ta, rha, pa)
    _warn(st)
    return st


def _warn(st: dict) -> None:
    w, k = st["warnings"], st["k"]
    hor = lambda kk: mc.radio_horizon_km(10, 0, kk)
    if st["refraction"] == "super-refraction":
        w.append(f"Super-refraction (gradient {st['dn_per_km']:.0f} N/km, k {k:.2f}): a 10 m antenna's horizon is "
                 f"{hor(k):.0f} km against {hor(4 / 3):.0f} km standard, so ranges run longer.")
    elif st["refraction"] == "trapping":
        w.append(f"Trapping gradient in the lowest km ({st['dn_per_km']:.0f} N/km): k capped at {k:.0f}; expect "
                 "anomalous propagation well beyond the ranges shown.")
    elif st["refraction"] == "sub-refraction":
        w.append(f"Sub-refraction (k {k:.2f}): ranges shorter than standard.")
    for d in st["ducts"]:
        f = f"{d['cutoff_ghz'] * 1000:.0f} MHz" if d["cutoff_ghz"] and d["cutoff_ghz"] < 1 else f"{d['cutoff_ghz']} GHz"
        w.append(f"{d['kind'].capitalize()} duct {d['base_m']}-{d['top_m']} m traps above about {f}: emitters inside it "
                 "may be heard far beyond the ranges shown (ducts are flagged, not modelled).")
    ev = st.get("evap_duct")
    if ev and ev["height_m"] >= 4 and ev["cutoff_ghz"]:
        w.append(f"Evaporation duct about {ev['height_m']:.0f} m over the sea ({ev['stability']}): low antennas above "
                 f"about {ev['cutoff_ghz']:.1f} GHz (radar, datalinks) may be detected beyond the horizon."
                 + (" Air warmer than the sea: the duct may be higher and patchy." if ev["stability"] == "stable" else ""))
    if st["rain_mm_h"] >= 1:
        w.append(f"Rain {st['rain_mm_h']:.1f} mm/h (hourly mean): about {_rain_db_km(10, st['rain_mm_h']):.2f} dB/km "
                 f"at 10 GHz and {_rain_db_km(30, st['rain_mm_h']):.1f} dB/km at 30 GHz; little effect below 5 GHz.")
    if st["fog_lwc_gm3"] > 0:
        w.append(f"Fog (visibility {st['visibility_m']:.0f} m, about {st['fog_lwc_gm3']:.2f} g/m3): "
                 f"{mc.fog_db_per_km(30, st['fog_lwc_gm3'], st['temp_c']):.2f} dB/km at 30 GHz; negligible below 10 GHz.")


def _rain_db_km(f_ghz: float, r: float) -> float:
    from .link_core import rain_specific_db_km
    return rain_specific_db_km(f_ghz, r)


def space_weather() -> dict | None:
    sw, t = get_db().get_snapshot("spaceweather")
    if not sw:
        return None
    kp = ((sw.get("kp") or {}).get("value"))
    scales = (sw.get("scales") or {}).get("now") or {}
    return {"kp": kp, "scales": scales, "updated": t}


async def met_state(lat: float, lon: float, when: datetime | None = None) -> dict:
    """Met state for a place and time (nearest hour, UTC). Never raises: falls back to the standard atmosphere."""
    hour = valid_hour(when)
    la, lo = _grid(lat), _grid(lon)
    try:
        fc = await _day("fc", la, lo, hour.date())
    except MetUnavailable as e:
        return standard(f"forecast unavailable ({e})", hour)
    marine = sea_air = None
    try:
        marine = await _day("marine", la, lo, hour.date())
        if _km(lat, lon, marine.get("latitude", lat), marine.get("longitude", lon)) <= SEA_NEAR_KM \
                and _at(marine, hour)("sea_surface_temperature") is not None:
            sea_air = await _day("air", _grid(marine["latitude"]), _grid(marine["longitude"]), hour.date())
    except MetUnavailable:
        pass                                                               # no sea state: no evaporation duct
    st = build_state(fc, marine, sea_air, hour, lat, lon)
    if abs((hour - datetime.now(timezone.utc)).total_seconds()) <= 6 * 3600:
        sw = space_weather()
        if sw:
            st["space_weather"] = sw
            kp = sw.get("kp") or 0
            if kp >= 5:
                st["warnings"].append(f"Geomagnetic storm (Kp {kp:.0f}): GNSS accuracy and HF skywave degraded.")
    return st


def atmosphere(st: dict, k: float | None = None, rain_mm_h: float | None = None, visibility_m: float | None = None) -> dict:
    """What the propagation model uses from a met state, with any manual overrides, plus a cache signature."""
    kk = max(mc.K_MIN, min(mc.K_MAX, k if k is not None else st.get("k", 4 / 3)))
    rr = max(0.0, rain_mm_h if rain_mm_h is not None else st.get("rain_mm_h") or 0.0)
    vis = visibility_m if visibility_m is not None else st.get("visibility_m")
    fog = mc.fog_lwc_gm3(vis)
    t = st.get("temp_c") if st.get("temp_c") is not None else 15.0
    return {"k": round(kk, 3), "rain_mm_h": round(rr, 1), "fog_lwc_gm3": round(fog, 3), "temp_c": round(t, 1),
            "sig": f"k{kk:.2f}r{rr:.1f}f{fog:.3f}"}


STANDARD_ATM = atmosphere(STANDARD)


def path_extra_db(d_m: float, f_hz: float, atm: dict) -> float:
    """Rain and fog loss along a path (dB), on top of what link_core already counts (free space, terrain, gases).

    Rain: ITU-R P.838 at the forecast hourly rate over the whole path, shortened by the P.530 distance factor (a
    long path is not all in rain). Fog: ITU-R P.840 for the whole path at the forecast visibility."""
    from .link_core import rain_a001_db
    if d_m <= 0:
        return 0.0
    f_ghz, d_km = f_hz / 1e9, d_m / 1000.0
    loss = rain_a001_db(d_km, f_ghz, atm.get("rain_mm_h") or 0.0)
    lwc = atm.get("fog_lwc_gm3") or 0.0
    if lwc > 0:
        loss += mc.fog_db_per_km(f_ghz, lwc, atm.get("temp_c", 10.0)) * d_km
    return loss


# ---- API -------------------------------------------------------------------------------------------------------
from fastapi import APIRouter, HTTPException, Query  # noqa: E402

router = APIRouter(prefix="/api/met", tags=["met"])


@router.get("")
async def met_api(lat: float = Query(ge=-85, le=85), lon: float = Query(ge=-180, le=180), time: str | None = None):
    """The met state for a place and hour (UTC; ISO time, default now), as EMO runs use it."""
    when = None
    if time:
        try:
            when = datetime.fromisoformat(time.strip())
        except ValueError:
            raise HTTPException(422, "time: not an ISO date and time")
        when = when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when
    return await met_state(lat, lon, when)
