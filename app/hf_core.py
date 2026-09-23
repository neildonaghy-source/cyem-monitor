"""HF skywave now-cast from live ionosonde data (pure maths, stdlib only, unit-tested).

Model (screening grade):
  - great-circle path; hops sized so each stays above MIN_ELEV at the reflection height
  - control point at the middle of each hop
  - foF2, MUF(3000) and hmF2 at each control point by inverse-distance weighting of
    nearby fresh ionosondes
  - hop MUF: the station's own MUF(3000) scaled by the secant law,
        MUF(d) = MUF(3000) * sec(i_d) / sec(i_3000),  sin i = R cos e / (R + h)
  - path MUF = lowest control-point MUF; FOT (optimum working) = 0.85 x MUF
  - lower limit from D-RAP (space-weather absorption only; normal daytime D-layer
    absorption is not modelled)
"""
from __future__ import annotations

import math

R_KM = 6371.0
MIN_ELEV_DEG = 3.0
FOT_FACTOR = 0.85


def gc_km(la1, lo1, la2, lo2):
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_KM * math.asin(min(1.0, math.sqrt(a)))


def gc_point(la1, lo1, la2, lo2, f):
    p1, l1, p2, l2 = map(math.radians, (la1, lo1, la2, lo2))
    d = 2 * math.asin(min(1.0, math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2)))
    if d == 0:
        return la1, lo1
    a, b = math.sin((1 - f) * d) / math.sin(d), math.sin(f * d) / math.sin(d)
    x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
    y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
    z = a * math.sin(p1) + b * math.sin(p2)
    return math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))


def max_hop_km(h_km: float, min_elev: float = MIN_ELEV_DEG) -> float:
    e = math.radians(min_elev)
    theta = math.pi / 2 - e - math.asin(R_KM * math.cos(e) / (R_KM + h_km))
    return 2 * R_KM * theta


def elevation_deg(hop_km: float, h_km: float) -> float:
    """Take-off elevation for a single hop of ground length hop_km off a layer at h_km."""
    theta = hop_km / (2 * R_KM)
    return math.degrees(math.atan2(math.cos(theta) - R_KM / (R_KM + h_km), math.sin(theta)))


def sec_incidence(hop_km: float, h_km: float) -> float:
    e = math.radians(elevation_deg(hop_km, h_km))
    s = R_KM * math.cos(e) / (R_KM + h_km)
    return 1 / math.sqrt(max(1e-9, 1 - s * s))


def hop_muf(mufd_3000: float, hop_km: float, h_km: float) -> float:
    return mufd_3000 * sec_incidence(hop_km, h_km) / sec_incidence(3000.0, h_km)


def idw(stations: list[dict], lat: float, lon: float, key: str, max_km: float = 2000.0, power: float = 2.0):
    """Inverse-distance weighted value of `key` at a point. Returns (value, [(name, km), ...])."""
    num = den = 0.0
    used = []
    for s in stations:
        v = s.get(key)
        if v is None:
            continue
        d = gc_km(lat, lon, s["lat"], s["lon"])
        if d > max_km:
            continue
        w = 1.0 / max(d, 25.0) ** power
        num += w * v
        den += w
        used.append((s.get("name") or s.get("code"), round(d)))
    if not den:
        return None, []
    used.sort(key=lambda t: t[1])
    return num / den, used[:4]


def plan(la1, lo1, la2, lo2, stations: list[dict], freqs_mhz: list[float], luf_fn=None, default_h: float = 300.0) -> dict:
    D = gc_km(la1, lo1, la2, lo2)
    mid = gc_point(la1, lo1, la2, lo2, 0.5)
    h_mid, _ = idw(stations, mid[0], mid[1], "hmf2", 3000)
    h = h_mid or default_h
    hops = max(1, math.ceil(D / max_hop_km(h)))
    hop_len = D / hops
    cps = []
    for k in range(hops):
        la, lo = gc_point(la1, lo1, la2, lo2, (2 * k + 1) / (2 * hops))
        fof2, src = idw(stations, la, lo, "fof2")
        mufd, _ = idw(stations, la, lo, "mufd")
        hmf2, _ = idw(stations, la, lo, "hmf2")
        hh = hmf2 or h
        muf = hop_muf(mufd, hop_len, hh) if mufd else None
        luf = luf_fn(la, lo) if luf_fn else None
        cps.append({"lat": round(la, 3), "lon": round(lo, 3), "fof2": round(fof2, 2) if fof2 else None,
                    "mufd": round(mufd, 2) if mufd else None, "hmf2": round(hh), "muf": round(muf, 2) if muf else None,
                    "luf_sw": luf, "sources": src})
    mufs = [c["muf"] for c in cps if c["muf"]]
    path_muf = min(mufs) if mufs else None
    fot = round(FOT_FACTOR * path_muf, 2) if path_muf else None
    lufs = [c["luf_sw"] for c in cps if c["luf_sw"]]
    luf = max(lufs) if lufs else None
    rated = []
    for f in freqs_mhz:
        if path_muf is None:
            st = "no data"
        elif f > path_muf:
            st = "above MUF"
        elif luf and f <= luf:
            st = "absorbed"
        elif f > fot:
            st = "marginal"
        else:
            st = "good"
        rated.append({"mhz": f, "status": st})
    return {"distance_km": round(D), "hops": hops, "hop_km": round(hop_len), "elev_deg": round(elevation_deg(hop_len, h), 1),
            "mode": "NVIS" if D < 500 else "skywave", "reflect_h_km": round(h), "control_points": cps,
            "muf": path_muf, "fot": fot, "luf_space_weather": luf, "frequencies": rated,
            "coverage_ok": all(c["muf"] for c in cps)}
