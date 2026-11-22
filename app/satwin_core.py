"""Satcom and GNSS windows (phase 6 part 3): pure helpers, stdlib only, unit-tested.

Satcom: the look angle from a terminal to a geostationary slot, the terrain horizon on that bearing, and uplink
jamming. An opposing jammer that can itself see the satellite puts its power into the satellite's receiver alongside
the terminal's; J/S at the satellite is the EIRP difference, corrected for the two slant ranges and diluted by the
terminal's hopping or spreading (the same dilution rule as the run's jamming). Screening grade: the satellite's
receive antenna is taken as equal towards both (a wide beam); no downlink jamming, no satellite anti-jam nulling.
GNSS: the run's rules (J/S against the receiver's threshold; a spoofer between 3 and 30 dB deceives).
"""
from __future__ import annotations

import math

R_E = 6378.137            # km, equatorial radius (WGS84)
R_GEO = 42164.0           # km, geostationary orbit radius
R_MEAN = 6_371_008.8      # m


def _ecef(lat: float, lon: float, r: float) -> tuple[float, float, float]:
    la, lo = math.radians(lat), math.radians(lon)
    return r * math.cos(la) * math.cos(lo), r * math.cos(la) * math.sin(lo), r * math.sin(la)


def geo_look(lat: float, lon: float, sat_lon: float) -> tuple[float, float, float]:
    """(elevation deg, azimuth deg from true north, slant range km) from a ground point to a geostationary slot
    (spherical earth, terminal at sea level: within about 0.1 degree)."""
    gx, gy, gz = _ecef(lat, lon, R_E)
    sx, sy, sz = _ecef(0.0, sat_lon, R_GEO)
    dx, dy, dz = sx - gx, sy - gy, sz - gz
    la, lo = math.radians(lat), math.radians(lon)
    e = -math.sin(lo) * dx + math.cos(lo) * dy
    n = -math.sin(la) * math.cos(lo) * dx - math.sin(la) * math.sin(lo) * dy + math.cos(la) * dz
    u = math.cos(la) * math.cos(lo) * dx + math.cos(la) * math.sin(lo) * dy + math.sin(la) * dz
    rng = math.sqrt(dx * dx + dy * dy + dz * dz)
    return math.degrees(math.asin(u / rng)), (math.degrees(math.atan2(e, n)) + 360) % 360, rng


def slot_for_azimuth(lat: float, lon: float, az_deg: float, step: float = 0.05) -> float | None:
    """The geostationary slot (longitude) a terminal pointing at az_deg looks at, if one above the horizon lies on
    that bearing within 1 degree; None otherwise."""
    best, bd = None, 1.0
    s = lon - 80.0
    while s <= lon + 80.0:
        el, az, _ = geo_look(lat, lon, s)
        d = abs((az - az_deg + 180) % 360 - 180)
        if el > 0 and d < bd:
            best, bd = round(s, 2), d
        s += step
    return best


def horizon_deg(dists_m: list[float], heights_m: list[float], ground_m: float, ant_m: float, k: float = 4 / 3) -> float:
    """Highest terrain angle seen from the antenna along a profile (degrees above the horizontal), with earth
    curvature and refraction (k). -90 if no profile."""
    h0 = ground_m + ant_m
    best = -90.0
    for d, h in zip(dists_m, heights_m):
        if d <= 0:
            continue
        drop = d * d / (2 * k * R_MEAN)
        best = max(best, math.degrees(math.atan2(h - drop - h0, d)))
    return best


def uplink_js_db(j_eirp_dbm: float, own_eirp_dbm: float, own_range_km: float, j_range_km: float, dilution_db: float) -> float:
    """J/S at the satellite's receiver: EIRP difference, minus 20 log(j range / own range), less the dilution."""
    return j_eirp_dbm - own_eirp_dbm - 20 * math.log10(j_range_km / own_range_km) - dilution_db


def power_sum_db(values_db: list[float]) -> float | None:
    if not values_db:
        return None
    return 10 * math.log10(sum(10 ** (v / 10) for v in values_db))


def link_status(js_db: float | None, req_db: float) -> str:
    """As the run: denied at or over the threshold, degraded within 6 dB of it, else clear."""
    if js_db is None:
        return "clear"
    return "denied" if js_db >= req_db else "degraded" if js_db >= req_db - 6 else "clear"


def gnss_status(noise_js: float | None, spoof_js: float | None, req_db: float) -> str:
    """Worst of the noise jammers' and the spoofers' effect, by the run's rules."""
    st = link_status(noise_js, req_db) if noise_js is not None else "clear"
    if st == "denied":
        return "denied"
    if spoof_js is not None:
        if spoof_js > 30:
            return "denied"
        if spoof_js >= 3:
            return "deceived"
        if spoof_js >= -3 and st == "clear":
            st = "degraded"
    return st


def spans(flags: list[bool], times: list[float]) -> list[dict]:
    """Contiguous runs of True as {from_min, to_min, steps}; to_min is the last good step's time."""
    out, start = [], None
    for i, f in enumerate(list(flags) + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append({"from_min": times[start], "to_min": times[i - 1], "steps": i - start})
            start = None
    return out
