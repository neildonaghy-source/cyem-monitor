"""Meteorology for propagation: refractivity, k-factor, ducts, rain, fog and cloud. Pure stdlib; unit-tested.

Screening grade. Sources: ITU-R P.453-14 (refractivity, saturation vapour pressure, refraction categories),
ITU-R P.840 (cloud and fog attenuation), ITU-R P.838 and P.530 (rain, in link_core), the neutral Paulus-Jeske
evaporation duct model, and Kerr's cut-off for the longest wavelength a duct traps. What it cannot see: layers
thinner than the forecast model's pressure levels (about 250 m apart near the ground), so elevated ducts are found
only when thick, and the evaporation duct is the neutral-stability estimate (it says when the air is stable).
"""
from __future__ import annotations

import math

C = 299_792_458.0
Z0_SEA = 1.5e-4          # roughness length of the sea surface for the evaporation duct (m)
K_MIN, K_MAX = 0.5, 10.0 # effective earth radius factor limits; trapping gradients are flagged rather than modelled
STANDARD_DN = -40.0      # N-units per km in the lowest kilometre of the standard atmosphere (k = 4/3)


def sat_vapour_hpa(t_c: float, p_hpa: float = 1013.25) -> float:
    """Saturation vapour pressure over water (hPa), ITU-R P.453-14 eq. 9 and 10 with the enhancement factor."""
    ef = 1 + 1e-4 * (7.2 + p_hpa * (0.0320 + 5.9e-6 * t_c * t_c))
    return ef * 6.1121 * math.exp((18.678 - t_c / 234.5) * t_c / (t_c + 257.14))


def vapour_hpa(t_c: float, rh_pct: float, p_hpa: float = 1013.25) -> float:
    return max(0.0, min(rh_pct, 100.0)) / 100.0 * sat_vapour_hpa(t_c, p_hpa)


def refractivity(p_hpa: float, t_c: float, e_hpa: float) -> float:
    """Radio refractivity N (N-units), ITU-R P.453: N = 77.6/T (P + 4810 e/T)."""
    t = t_c + 273.15
    return 77.6 / t * (p_hpa + 4810.0 * e_hpa / t)


def k_factor(dn_per_km: float) -> float:
    """Effective earth radius factor from the refractivity gradient in the lowest kilometre, clamped to K_MIN..K_MAX."""
    if dn_per_km <= -157.0 + 157.0 / K_MAX:
        return K_MAX
    return max(K_MIN, min(K_MAX, 157.0 / (157.0 + dn_per_km)))


def refraction_class(dn_per_km: float) -> str:
    """ITU-R categories by gradient (N-units per km)."""
    if dn_per_km > 0:
        return "sub-refraction"
    if dn_per_km > -79:
        return "normal"
    if dn_per_km > -157:
        return "super-refraction"
    return "trapping"


def radio_horizon_km(h1_m: float, h2_m: float = 0.0, k: float = 4 / 3) -> float:
    """Smooth-earth radio horizon between two antenna heights (km)."""
    r = 2 * k * 6_371_008.8
    return (math.sqrt(r * max(h1_m, 0.0)) + math.sqrt(r * max(h2_m, 0.0))) / 1000.0


def duct_cutoff_ghz(thickness_m: float, deficit_m: float) -> float | None:
    """Lowest frequency a duct traps (GHz): Kerr's cut-off, longest trapped wavelength 2.51e-3 d sqrt(dM) metres."""
    if thickness_m <= 0 or deficit_m <= 0:
        return None
    return C / (2.51e-3 * thickness_m * math.sqrt(deficit_m)) / 1e9


def profile(points: list[dict]) -> dict:
    """Refractivity profile from points {h (m above ground), p (hPa), t (C), rh (%)}; the first is the surface.

    Returns N at the surface, the gradient over the lowest kilometre (interpolated), k, the refraction class, and
    any trapping layers found between points (M decreasing with height) as ducts with base, top, thickness, M
    deficit and cut-off frequency. A duct that reaches the ground is surface-based."""
    pts = sorted(({**q, "n": refractivity(q["p"], q["t"], vapour_hpa(q["t"], q["rh"], q["p"]))} for q in points),
                 key=lambda q: q["h"])
    for q in pts:
        q["m"] = q["n"] + 0.157 * q["h"]
    ns = pts[0]["n"]
    dn = None
    for a, b in zip(pts, pts[1:]):
        if a["h"] <= 1000.0 <= b["h"] and b["h"] > a["h"]:
            n1 = a["n"] + (b["n"] - a["n"]) * (1000.0 - a["h"]) / (b["h"] - a["h"])
            dn = n1 - ns
            break
    if dn is None and len(pts) > 1 and pts[-1]["h"] > 0:          # profile ends below 1 km: use what there is
        dn = (pts[-1]["n"] - ns) / (pts[-1]["h"] / 1000.0)
    ducts = []
    i = 0
    while i < len(pts) - 1:
        if pts[i + 1]["m"] < pts[i]["m"]:
            j = i + 1
            while j < len(pts) - 1 and pts[j + 1]["m"] < pts[j]["m"]:
                j += 1
            top, mtop = pts[j]["h"], pts[j]["m"]
            base = 0.0                                             # walk down until M falls back to the top value
            for k_ in range(i, -1, -1):
                if pts[k_]["m"] <= mtop:
                    lo, hi = pts[k_], pts[k_ + 1]
                    base = lo["h"] + (hi["h"] - lo["h"]) * (mtop - lo["m"]) / ((hi["m"] - lo["m"]) or 1e-9)
                    break
            deficit = max(q["m"] for q in pts if base - 1e-6 <= q["h"] <= top) - mtop
            thick = top - base
            ducts.append({"kind": "surface-based" if base <= 1.0 else "elevated", "base_m": round(base),
                          "top_m": round(top), "thickness_m": round(thick), "deficit_m": round(deficit, 1),
                          "cutoff_ghz": _r(duct_cutoff_ghz(thick, deficit), 2)})
            i = j
        else:
            i += 1
    dn = STANDARD_DN if dn is None else dn
    return {"n_surface": round(ns, 1), "dn_per_km": round(dn, 1), "k": round(k_factor(dn), 3),
            "refraction": refraction_class(dn), "ducts": ducts,
            "levels": [{"h": round(q["h"]), "n": round(q["n"], 1), "m": round(q["m"], 1)} for q in pts]}


def evaporation_duct(sst_c: float, t_air_c: float, rh_pct: float, p_hpa: float, z_ref_m: float = 2.0) -> dict:
    """Neutral-stability evaporation duct height (Paulus-Jeske) from sea surface temperature and air at z_ref.

    delta = -dNp / (0.125 ln(z_ref / z0)), with the sea surface saturated (vapour pressure reduced 2 % for salt).
    Stable air (warmer than the sea) makes the real duct higher and patchier; unstable air makes it lower."""
    n_air = refractivity(p_hpa, t_air_c, vapour_hpa(t_air_c, rh_pct, p_hpa))
    n_sea = refractivity(p_hpa, sst_c, 0.98 * sat_vapour_hpa(sst_c, p_hpa))
    dnp = n_air - n_sea
    height = 0.0 if dnp >= 0 else min(40.0, -dnp / (0.125 * math.log(z_ref_m / Z0_SEA)))
    deficit = 0.125 * height * (math.log(height / Z0_SEA) - 1) if height > 0.5 else 0.0
    dt = t_air_c - sst_c
    stability = "stable" if dt > 1.0 else "unstable" if dt < -1.0 else "near neutral"
    return {"height_m": round(height, 1), "deficit_m": round(deficit, 1), "cutoff_ghz": _r(duct_cutoff_ghz(height, deficit), 2),
            "air_minus_sea_c": round(dt, 1), "stability": stability}


def fog_lwc_gm3(visibility_m: float | None) -> float:
    """Liquid water content of fog (g/m3) from visibility: a power law through ITU-R P.840's typical values
    (0.05 g/m3 at about 300 m, 0.5 g/m3 at about 50 m). Zero at 1 km or more (not fog)."""
    if visibility_m is None or visibility_m >= 1000 or visibility_m <= 0:
        return 0.0
    return min(1.0, 0.0106 * (max(visibility_m, 20.0) / 1000.0) ** -1.285)


def cloud_kl(f_ghz: float, t_c: float = 0.0) -> float:
    """ITU-R P.840 specific attenuation coefficient of liquid water ((dB/km)/(g/m3)), double-Debye permittivity."""
    th = 300.0 / (t_c + 273.15)
    e0 = 77.66 + 103.3 * (th - 1)
    e1, e2 = 0.0671 * e0, 3.52
    fp = 20.20 - 146 * (th - 1) + 316 * (th - 1) ** 2
    fs = 39.8 * fp
    e_im = f_ghz * (e0 - e1) / (fp * (1 + (f_ghz / fp) ** 2)) + f_ghz * (e1 - e2) / (fs * (1 + (f_ghz / fs) ** 2))
    e_re = (e0 - e1) / (1 + (f_ghz / fp) ** 2) + (e1 - e2) / (1 + (f_ghz / fs) ** 2) + e2
    eta = (2 + e_re) / e_im
    return 0.819 * f_ghz / (e_im * (1 + eta * eta))


def fog_db_per_km(f_ghz: float, lwc_gm3: float, t_c: float = 10.0) -> float:
    return cloud_kl(f_ghz, t_c) * lwc_gm3 if lwc_gm3 > 0 and f_ghz > 1 else 0.0


def cloud_base_m(t_c: float | None, dew_c: float | None) -> float | None:
    """Convective cloud base above ground (m) from the dew-point spread (Espy: 125 m per degree)."""
    if t_c is None or dew_c is None:
        return None
    return round(max(0.0, 125.0 * (t_c - dew_c)))


def _r(x, nd):
    return None if x is None else round(x, nd)
