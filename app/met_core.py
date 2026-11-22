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


# ---- sea state, sea clutter and platform limits (phase 4 part 2) -------------------------------------------------
DOUGLAS_M = (0.0, 0.1, 0.5, 1.25, 2.5, 4.0, 6.0, 9.0, 14.0)   # upper wave heights (m) of Douglas sea states 0 to 8


def sea_state(wave_m: float | None) -> int | None:
    """Douglas sea state (0 to 9) from significant wave height."""
    if wave_m is None:
        return None
    return sum(1 for t in DOUGLAS_M if wave_m > t)


def sea_clutter_db(state: int | None, f_mhz: float, h_m: float) -> float:
    """Screening loss of radar detection margin (dB) against a small target on or just above the sea, from sea clutter.

    Not a clutter model: a heuristic that grows 2.5 dB per sea state above 1, a little more at X band than at S band
    and less at L band, and fades out for targets above 50 m (none above 300 m). Capped at 20 dB."""
    if state is None or state <= 1 or h_m > 300 or f_mhz < 300:
        return 0.0
    band = max(0.5, min(1.5, 1 + 0.25 * math.log2(f_mhz / 3000.0)))
    height = 1.0 if h_m <= 50 else max(0.0, 1 - (h_m - 50) / 250.0)
    return round(min(20.0, 2.5 * (state - 1) * band * height), 1)


# Generic, notional limits for screening (not any service's figures): small UAS or helicopter at low level, small craft,
# and vehicles. Values: (marginal, no-go).
LIMITS = {
    "air": {"wind_ms": (10.0, 15.0), "gust_ms": (15.0, 20.0), "rain_mm_h": (4.0, 10.0), "visibility_m": (1500.0, None)},
    "sea": {"wind_ms": (11.0, 17.0), "sea_state": (4, 5), "visibility_m": (1000.0, None)},
    "ground": {"rain_mm_h": (8.0, None), "snow_cm_h": (1.0, None), "visibility_m": (200.0, None)},
    "foot": {"rain_mm_h": (8.0, None), "snow_cm_h": (1.0, None), "wind_ms": (17.0, None)},
}
SURF_M = (1.0, 1.5)                                            # wave height at the beach: marginal, no-go for beaching craft


def battery_factor(t_c: float | None) -> float:
    """Usable fraction of a lithium battery's rated capacity at an air temperature (notional): 1 at 20 C and above,
    falling 2% per degree below, not under 0.4."""
    if t_c is None:
        return 1.0
    return round(max(0.4, min(1.0, 1 - 0.02 * (20.0 - t_c))), 2)


def surf_limits(wave_m: float | None) -> dict:
    """Beaching limit for landing craft from the wave height off the beach (notional)."""
    if wave_m is None:
        return {"status": "unknown", "reason": "no sea state for the beach"}
    mg, ng = SURF_M
    st = "no-go" if wave_m >= ng else "marginal" if wave_m >= mg else "go"
    return {"status": st, "reason": f"surf: waves {wave_m:g} m off the beach (marginal from {mg:g} m, no-go from {ng:g} m)"}
LIMIT_COST = {"go": 0.0, "marginal": 0.3, "no-go": 3.0, "unknown": 0.0}
SEA_SPEED = {3: 0.9, 4: 0.75, 5: 0.5}                          # small craft speed factor by sea state (6 and over: 0.3)


def headwind_ms(wind_ms: float | None, wind_from_deg: float | None, track_deg: float) -> float:
    """Wind component against the direction of travel (m/s; negative is a tailwind)."""
    if wind_ms is None or wind_from_deg is None:
        return 0.0
    return wind_ms * math.cos(math.radians(wind_from_deg - track_deg))


def platform_limits(domain: str, st: dict, alt_m: float | None = None, track_deg: float = 0.0, speed_kmh: float = 0.0) -> dict:
    """Go, marginal or no-go for a platform in a met state, with a speed factor, a per-cell cost and the reasons.

    Air: wind, gusts, rain, visibility, cloud base against the flying height, icing (freezing level at or near the
    flying height in cloud, rain or fog); ground speed from the headwind along the track. Sea: wind, sea state
    (speed falls with it), visibility. Ground: heavy rain, snow, fog slow the move but never stop it."""
    if st.get("source") != "open-meteo":
        return {"status": "unknown", "speed_factor": 1.0, "cost": 0.0, "sea_state": None, "battery_factor": 1.0,
                "reasons": ["no forecast chosen: platform limits not assessed"]}
    lim, reasons, worst = LIMITS[domain], [], "go"
    rank = {"go": 0, "marginal": 1, "no-go": 2}

    def flag(level, why):
        nonlocal worst
        reasons.append(f"{level}: {why}")
        if rank[level] > rank[worst]:
            worst = level

    def check(name, value, label, unit, below=False):
        if value is None or name not in lim:
            return
        mg, ng = lim[name]
        bad = (lambda t: t is not None and value < t) if below else (lambda t: t is not None and value >= t)
        if bad(ng):
            flag("no-go", f"{label} {value:g} {unit}")
        elif bad(mg):
            flag("marginal", f"{label} {value:g} {unit}")

    ss = sea_state((st.get("sea") or {}).get("wave_m"))
    check("wind_ms", st.get("wind_ms"), "wind", "m/s")
    check("gust_ms", st.get("gust_ms"), "gusts", "m/s")
    check("rain_mm_h", st.get("rain_mm_h"), "rain", "mm/h")
    check("snow_cm_h", st.get("snow_cm_h"), "snow", "cm/h")
    check("visibility_m", st.get("visibility_m"), "visibility", "m", below=True)
    if domain == "sea":
        check("sea_state", ss, "sea state", "(Douglas)")
    factor = 1.0
    if domain == "air":
        h = alt_m or 150.0
        cb, low = st.get("cloud_base_m"), st.get("cloud_low_pct") or 0
        if cb is not None and low >= 50 and cb < h + 100:
            flag("marginal", f"low cloud base about {cb:g} m ({low:g}% low cloud) against {h:g} m flying height")
        fz = st.get("freezing_level_m")
        moist = low >= 50 or (st.get("rain_mm_h") or 0) > 0 or (st.get("visibility_m") or 1e9) < 1000 or (st.get("rh_pct") or 0) >= 90
        if fz is not None and moist and fz <= h + 300:
            flag("no-go" if fz <= h else "marginal", f"icing risk: freezing level {fz:g} m with visible moisture")
        if speed_kmh > 0:
            hw = headwind_ms(st.get("wind_ms"), st.get("wind_dir"), track_deg)
            factor = max(0.3, min(1.3, (speed_kmh / 3.6 - hw) / (speed_kmh / 3.6)))
            if hw > 0.25 * speed_kmh / 3.6:
                reasons.append(f"headwind about {hw:.0f} m/s along the track: ground speed {factor * 100:.0f}% of air speed")
    elif domain == "sea":
        factor = SEA_SPEED.get(ss, 1.0 if (ss or 0) < 3 else 0.3)
    else:                                                       # ground and foot
        if (st.get("snow_cm_h") or 0) >= 3:
            factor = 0.5
        elif (st.get("snow_cm_h") or 0) >= 1 or (st.get("rain_mm_h") or 0) >= 8:
            factor = 0.7
        if (st.get("visibility_m") or 1e9) < 200:
            factor = min(factor, 0.8)
    bat = battery_factor(st.get("temp_c")) if domain in ("air", "foot") else 1.0
    if bat < 1.0:
        reasons.append(f"batteries about {bat * 100:.0f}% of rated capacity at {st.get('temp_c'):g} C (radios, UAS endurance)")
    return {"status": worst, "speed_factor": round(factor, 2), "cost": LIMIT_COST[worst], "sea_state": ss,
            "battery_factor": bat, "reasons": reasons}
