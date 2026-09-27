"""Point-to-point link engineering: pure maths, standard library only (unit-tested).

Models, all screening-grade:
  - Great-circle path, terrain profile supplied by the caller (see dem.py).
  - Effective earth radius k*R (default k = 4/3) applied as earth bulge.
  - First Fresnel zone radius and clearance ratio along the path.
  - Diffraction: ITU-R P.526 knife-edge J(v), Deygout construction limited to 3 edges
    (principal plus one each side), as P.526 advises: more edges over-estimate the loss.
  - Free-space loss.
  - Gaseous absorption: coarse sea-level table (7.5 g/m3 water vapour), approximate.
  - Rain: ITU-R P.838-3 k/alpha (tabulated from memory, log-log interpolated: verify
    against the published table) and ITU-R P.530 path reduction and percentage scaling.
Not modelled: clutter, multipath/ducting fading, antenna patterns, polarisation mismatch.
"""
from __future__ import annotations

import math

EARTH_R_M = 6_371_008.8
C = 299_792_458.0


# ---- path geometry ------------------------------------------------------------
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_M * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def gc_points(lat1: float, lon1: float, lat2: float, lon2: float, n: int) -> list[tuple[float, float]]:
    """n >= 2 points along the great circle, endpoints included."""
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    d = 2 * math.asin(min(1.0, math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2)))
    if d == 0:
        return [(lat1, lon1)] * n
    out = []
    for i in range(n):
        f = i / (n - 1)
        a, b = math.sin((1 - f) * d) / math.sin(d), math.sin(f * d) / math.sin(d)
        x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
        y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
        z = a * math.sin(p1) + b * math.sin(p2)
        out.append((math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))))
    return out


def sample_count(dist_m: float, step_m: float = 30.0, max_n: int = 1500) -> int:
    return max(3, min(max_n, int(dist_m / step_m) + 1))


# ---- clearance -----------------------------------------------------------------
def earth_bulge_m(d1: float, d2: float, k: float = 4 / 3) -> float:
    return d1 * d2 / (2 * k * EARTH_R_M)


def fresnel_r1_m(d1: float, d2: float, f_hz: float) -> float:
    lam = C / f_hz
    return math.sqrt(lam * d1 * d2 / (d1 + d2)) if d1 > 0 and d2 > 0 else 0.0


def knife_edge_loss_db(v: float) -> float:
    """ITU-R P.526 approximation J(v); 0 for v <= -0.78."""
    if v <= -0.78:
        return 0.0
    return 6.9 + 20 * math.log10(math.sqrt((v - 0.1) ** 2 + 1) + v - 0.1)


def deygout_loss_db(dist: list[float], elev: list[float], h_start: float, h_end: float, f_hz: float,
                    s: int = 0, e: int | None = None, depth: int = 1) -> tuple[float, list[dict]]:
    """Diffraction loss over the profile by the Deygout construction.
    dist/elev: along-path distance (m) and terrain height including earth bulge (m ASL).
    h_start/h_end: absolute heights (m ASL) of the ray end points for this sub-path.
    Returns (loss dB, list of edges used)."""
    if e is None:
        e = len(dist) - 1
    if e - s < 2:
        return 0.0, []
    lam = C / f_hz
    ds, de = dist[s], dist[e]
    best_v, best_i = -1e9, None
    for i in range(s + 1, e):
        d1, d2 = dist[i] - ds, de - dist[i]
        if d1 <= 0 or d2 <= 0:
            continue
        los = h_start + (h_end - h_start) * d1 / (de - ds)
        v = (elev[i] - los) * math.sqrt(2 / lam * (1 / d1 + 1 / d2))
        if v > best_v:
            best_v, best_i = v, i
    if best_i is None or best_v <= -0.78:
        return 0.0, []
    loss = knife_edge_loss_db(best_v)
    edges = [{"i": best_i, "dist_m": round(dist[best_i], 1), "v": round(best_v, 3), "loss_db": round(loss, 2)}]
    if depth > 0:
        l1, e1 = deygout_loss_db(dist, elev, h_start, elev[best_i], f_hz, s, best_i, depth - 1)
        l2, e2 = deygout_loss_db(dist, elev, elev[best_i], h_end, f_hz, best_i, e, depth - 1)
        loss += l1 + l2
        edges += e1 + e2
    return loss, edges


def fspl_db(dist_m: float, f_hz: float) -> float:
    return 20 * math.log10(max(dist_m, 1.0) / 1000) + 20 * math.log10(f_hz / 1e6) + 32.44


# ---- atmosphere -------------------------------------------------------------------
# Approximate total specific gaseous attenuation at sea level, 15 C, 7.5 g/m3 (dB/km).
# Coarse reading of the ITU-R P.676 curve; good to a factor of ~1.5 away from line centres.
GAS_TABLE = [(1, 0.006), (5, 0.008), (10, 0.013), (15, 0.03), (20, 0.10), (22.2, 0.19), (25, 0.13),
             (30, 0.10), (35, 0.11), (40, 0.14), (45, 0.20), (50, 0.45), (54, 3.0), (57, 12.0), (60, 15.0),
             (63, 10.0), (66, 1.5), (70, 0.45), (75, 0.35), (80, 0.35), (86, 0.38), (90, 0.40), (100, 0.45)]

# ITU-R P.838-3 coefficients (f GHz: kH, aH, kV, aV). Tabulated from memory of the published
# table; screening use only, verify before relying on them.
RAIN_TABLE = [(1, 0.0000259, 0.9691, 0.0000308, 0.8592), (2, 0.0000847, 1.0664, 0.0000998, 0.9490),
              (4, 0.0001071, 1.6009, 0.0002461, 1.2476), (6, 0.0007056, 1.5900, 0.0004878, 1.5728),
              (7, 0.001915, 1.4810, 0.001425, 1.4745), (8, 0.004115, 1.3905, 0.003450, 1.3797),
              (10, 0.01217, 1.2571, 0.01129, 1.2156), (12, 0.02386, 1.1825, 0.02455, 1.1216),
              (15, 0.04481, 1.1233, 0.05008, 1.0440), (20, 0.09164, 1.0568, 0.09611, 0.9847),
              (25, 0.1571, 0.9991, 0.1533, 0.9491), (30, 0.2403, 0.9485, 0.2291, 0.9129),
              (35, 0.3374, 0.9047, 0.3224, 0.8761), (40, 0.4431, 0.8673, 0.4274, 0.8421),
              (50, 0.6600, 0.8084, 0.6472, 0.7871), (60, 0.8606, 0.7656, 0.8515, 0.7486),
              (70, 1.0315, 0.7345, 1.0253, 0.7215), (80, 1.1704, 0.7115, 1.1668, 0.7021),
              (90, 1.2807, 0.6944, 1.2795, 0.6876), (100, 1.3671, 0.6815, 1.3680, 0.6765)]


def _interp_loglog(table, x, col):
    if x <= table[0][0]:
        return table[0][col]
    if x >= table[-1][0]:
        return table[-1][col]
    for a, b in zip(table, table[1:]):
        if a[0] <= x <= b[0]:
            t = (math.log(x) - math.log(a[0])) / (math.log(b[0]) - math.log(a[0]))
            return math.exp(math.log(a[col]) + t * (math.log(b[col]) - math.log(a[col])))
    return table[-1][col]


def _interp_lin_logx(table, x, col):
    """Linear in value against log frequency (for exponents alpha)."""
    if x <= table[0][0]:
        return table[0][col]
    if x >= table[-1][0]:
        return table[-1][col]
    for a, b in zip(table, table[1:]):
        if a[0] <= x <= b[0]:
            t = (math.log(x) - math.log(a[0])) / (math.log(b[0]) - math.log(a[0]))
            return a[col] + t * (b[col] - a[col])
    return table[-1][col]


def gas_specific_db_km(f_ghz: float) -> float:
    return _interp_loglog(GAS_TABLE, f_ghz, 1) if f_ghz >= 1 else 0.0


def rain_specific_db_km(f_ghz: float, rain_mm_h: float, pol: str = "V") -> float:
    """gamma_R = k R^alpha (ITU-R P.838). pol: 'H' or 'V'."""
    if rain_mm_h <= 0 or f_ghz < 1:
        return 0.0
    kc, ac = (1, 2) if pol.upper() == "H" else (3, 4)
    k = _interp_loglog(RAIN_TABLE, f_ghz, kc)
    a = _interp_lin_logx(RAIN_TABLE, f_ghz, ac)
    return k * rain_mm_h ** a


def rain_path_reduction(d_km: float, f_ghz: float, r001: float, alpha: float) -> float:
    """ITU-R P.530 distance factor r (capped at 2.5)."""
    if d_km <= 0:
        return 1.0
    den = 0.477 * d_km ** 0.633 * r001 ** (0.073 * alpha) * f_ghz ** 0.123 - 10.579 * (1 - math.exp(-0.024 * d_km))
    return 2.5 if den <= 0 else min(2.5, 1 / den)


def rain_a001_db(d_km: float, f_ghz: float, r001: float, pol: str = "V") -> float:
    """Rain attenuation exceeded 0.01% of an average year (ITU-R P.530)."""
    if r001 <= 0 or f_ghz < 1:
        return 0.0
    ac = 2 if pol.upper() == "H" else 4
    alpha = _interp_lin_logx(RAIN_TABLE, f_ghz, ac)
    return rain_specific_db_km(f_ghz, r001, pol) * d_km * rain_path_reduction(d_km, f_ghz, r001, alpha)


def _p530_coeffs(f_ghz: float) -> tuple[float, float, float]:
    c0 = 0.12 + 0.4 * math.log10((f_ghz / 10) ** 0.8) if f_ghz >= 10 else 0.12
    c1 = 0.07 ** c0 * 0.12 ** (1 - c0)
    c2 = 0.855 * c0 + 0.546 * (1 - c0)
    c3 = 0.139 * c0 + 0.043 * (1 - c0)
    return c1, c2, c3


def rain_a_p_db(a001: float, f_ghz: float, p_pct: float) -> float:
    """Attenuation exceeded p% of the year, 0.001 <= p <= 1 (ITU-R P.530 scaling)."""
    c1, c2, c3 = _p530_coeffs(f_ghz)
    return a001 * c1 * p_pct ** -(c2 + c3 * math.log10(p_pct))


def rain_availability_pct(margin_db: float, a001: float, f_ghz: float) -> float | None:
    """Annual availability (%) against rain for a given fade margin. None when rain is
    negligible. Clamped to the P.530 validity range (99.0 to 99.999%)."""
    if a001 <= 0.01:
        return None
    if margin_db <= rain_a_p_db(a001, f_ghz, 1.0):
        return 99.0
    if margin_db >= rain_a_p_db(a001, f_ghz, 0.001):
        return 99.999
    lo, hi = 0.001, 1.0            # A_p decreases as p increases
    for _ in range(60):
        mid = math.sqrt(lo * hi)
        if rain_a_p_db(a001, f_ghz, mid) > margin_db:
            lo = mid
        else:
            hi = mid
    return 100 - math.sqrt(lo * hi)


# ---- full analysis --------------------------------------------------------------
def analyse(dist: list[float], terrain: list[float], *, h_a_agl: float, h_b_agl: float, f_hz: float,
            ptx_dbm: float, gtx_dbi: float, grx_dbi: float, ltx_db: float = 0.0, lrx_db: float = 0.0,
            sens_dbm: float = -100.0, k: float = 4 / 3, rain_mm_h: float = 25.0, pol: str = "V",
            req_margin_db: float = 10.0, avail_target_pct: float = 99.99, misc_db: float = 0.0) -> dict:
    """Link budget and clearance for a sampled profile. dist in m from A, terrain in m ASL."""
    n = len(dist)
    D = dist[-1]
    ha, hb = terrain[0] + h_a_agl, terrain[-1] + h_b_agl
    bulged = [terrain[i] + earth_bulge_m(dist[i], D - dist[i], k) for i in range(n)]
    los, r1, clr = [], [], []
    worst = (1e9, None)
    for i in range(n):
        l = ha + (hb - ha) * (dist[i] / D if D else 0)
        f1 = fresnel_r1_m(dist[i], D - dist[i], f_hz)
        los.append(l); r1.append(f1)
        if 0 < i < n - 1 and f1 > 0:
            c = (l - bulged[i]) / f1
            clr.append(c)
            if c < worst[0]:
                worst = (c, i)
    min_clear = worst[0] if worst[1] is not None else None
    diff_db, edges = deygout_loss_db(dist, bulged, ha, hb, f_hz)
    f_ghz = f_hz / 1e9
    fs = fspl_db(D, f_hz)
    gas = gas_specific_db_km(f_ghz) * D / 1000
    eirp = ptx_dbm - ltx_db + gtx_dbi
    prx = eirp - fs - diff_db - gas - misc_db + grx_dbi - lrx_db
    margin = prx - sens_dbm
    a001 = rain_a001_db(D / 1000, f_ghz, rain_mm_h, pol) if f_ghz >= 5 else 0.0
    avail = rain_availability_pct(margin, a001, f_ghz) if a001 else None
    issues = []
    if margin < 0:
        issues.append("received level below sensitivity")
    elif margin < req_margin_db:
        issues.append(f"fade margin below the {req_margin_db:g} dB required")
    if min_clear is not None and min_clear < 0:
        issues.append("path obstructed (terrain inside the line of sight)")
    elif min_clear is not None and min_clear < 0.6:
        issues.append("less than 60% first Fresnel zone clearance")
    if avail is not None and avail < avail_target_pct:
        issues.append(f"rain availability {avail:.3f}% below the {avail_target_pct:g}% target")
    # diffraction is already in the budget, so obstruction only drives no-go through the margin
    verdict = "no-go" if margin < 0 else "marginal" if issues else "go"
    return {
        "distance_m": round(D, 1), "f_hz": f_hz, "ha_asl": round(ha, 1), "hb_asl": round(hb, 1),
        "fspl_db": round(fs, 2), "diffraction_db": round(diff_db, 2), "gas_db": round(gas, 2), "misc_db": misc_db,
        "eirp_dbm": round(eirp, 2), "prx_dbm": round(prx, 2), "sens_dbm": sens_dbm, "margin_db": round(margin, 2),
        "min_f1_clearance": round(min_clear, 3) if min_clear is not None else None,
        "worst_point_m": round(dist[worst[1]], 1) if worst[1] is not None else None,
        "edges": edges, "rain_a001_db": round(a001, 2), "rain_mm_h": rain_mm_h, "pol": pol,
        "availability_pct": round(avail, 4) if avail is not None else None, "avail_target_pct": avail_target_pct,
        "k": k, "verdict": verdict, "issues": issues,
        "profile": {"dist": [round(x, 1) for x in dist], "terrain": [round(x, 1) for x in terrain],
                    "bulged": [round(x, 1) for x in bulged], "los": [round(x, 1) for x in los],
                    "f1": [round(x, 2) for x in r1]},
    }


# ---- ground reflection (low antennas) ---------------------------------------------------------------------------
GROUND_MIN_F_HZ = 30e6          # below this (HF) the surface wave dominates; not modelled here
LAND = (15.0, 0.005)            # relative permittivity, conductivity S/m (ITU-R P.527 average ground)
SEA = (70.0, 5.0)


def min_eff_height_m(f_hz: float, sea: bool = False) -> float:
    """Bullington minimum effective antenna height, vertical polarisation: an antenna at ground level still behaves
    as if raised by this much because of the ground's electrical constants (about 3.8 m at 50 MHz over land,
    0.5 m at 400 MHz, 40 m at 50 MHz over sea)."""
    er, sig = SEA if sea else LAND
    lam = 299792458.0 / f_hz
    return lam / (2 * math.pi) * ((er + 1) ** 2 + (60 * sig * lam) ** 2) ** 0.25


def plane_earth_db(d_m, h_a_abs, h_b_abs, mean_terrain_m, sea_frac, h_a_agl, h_b_agl, f_hz):
    """Plane-earth (two-ray asymptote) loss, dB: 40 log d - 20 log(h1e h2e). Effective heights are height above the
    mean terrain of the path (credits a hilltop site), floored at sqrt(h_agl^2 + h_min^2). Works on scalars or numpy
    arrays. Only meaningful beyond the two-ray breakpoint, so callers take max() with the free-space-based loss."""
    import numpy as _np
    sea = _np.asarray(sea_frac) > 0.5
    h0 = _np.where(sea, min_eff_height_m(f_hz, True), min_eff_height_m(f_hz, False))
    h1 = _np.maximum(_np.asarray(h_a_abs) - mean_terrain_m, _np.sqrt(h_a_agl ** 2 + h0 ** 2))
    h2 = _np.maximum(_np.asarray(h_b_abs) - mean_terrain_m, _np.sqrt(_np.asarray(h_b_agl, dtype=float) ** 2 + h0 ** 2))
    return 40 * _np.log10(_np.maximum(d_m, 1.0)) - 20 * _np.log10(h1 * h2)
