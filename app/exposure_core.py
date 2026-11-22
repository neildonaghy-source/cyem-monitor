"""Sub-surface exposure windows (phase 6 part 2): pure helpers, numpy only, unit-tested.

A submarine raising a mast to transmit or to look is exposed to opposing radar (surface, shore and maritime patrol
aircraft) and, if it transmits, to opposing ES. Each time layer gives a risk raster over the water the boat can reach
by then; a window is a time and place where the risk stays at or under a threshold for the whole mast-up dwell and
the link the mast is raised for works. Mast profiles are notional, generic screening values, not any class's figures.
"""
from __future__ import annotations

import math

import numpy as np

# Notional, generic mast profiles. h_m: mast height above the sea; rcs_m2: radar cross-section of the raised mast.
MASTS = {
    "periscope": {"label": "Periscope or ESM mast (no transmission)", "freq_mhz": None, "bw_khz": None, "eirp_dbm": None,
                  "h_m": 1.5, "rcs_m2": 0.1, "link": None},
    "uhf": {"label": "UHF line of sight to the net (250 MHz, 40 dBm)", "freq_mhz": 250.0, "bw_khz": 25.0, "eirp_dbm": 40.0,
            "h_m": 2.0, "rcs_m2": 0.5, "link": "net"},
    "satcom": {"label": "UHF satcom uplink (300 MHz, 20 dBm towards the horizon)", "freq_mhz": 300.0, "bw_khz": 25.0,
               "eirp_dbm": 20.0, "h_m": 2.0, "rcs_m2": 0.5, "link": "space"},
    "hf": {"label": "HF (8 MHz, 47 dBm)", "freq_mhz": 8.0, "bw_khz": 3.0, "eirp_dbm": 47.0, "h_m": 2.0, "rcs_m2": 0.5,
           "link": "hf"},
}
# chance the HF link works, by the space-weather HF status (spacewx_core.at_time)
HF_LINK = {"normal": 0.95, "degraded": 0.6, "blackout": 0.1, "unknown": 0.9}
LINK_OK = 0.5                                                  # a window needs at least this chance the link works
HF_GW_KM = 250.0                                               # notional HF groundwave interception range over the sea


def hf_groundwave_p(d_km, range_km: float = HF_GW_KM):
    """Chance an opposing HF ES sensor hears a mast's HF groundwave at d_km over the sea. The coverage model starts at
    20 MHz, so this is a screening rule, not a propagation model: heard out to about range_km (notional, for 47 dBm
    at 8 MHz against a -110 dBm receiver): certain inside 85% of it, half at range_km, nil beyond 115%."""
    d = np.asarray(d_km, float)
    return np.clip((range_km - d) / (0.3 * range_km) + 0.5, 0.0, 1.0)


def combine(*ps) -> np.ndarray:
    """Chance at least one of several independent events happens."""
    out = None
    for p in ps:
        q = 1 - np.asarray(p, float)
        out = q if out is None else out * q
    return 1 - out if out is not None else np.zeros(())


def reach_mask(dist_m: np.ndarray, speed_kmh: float, t_min: float, cell_m: float) -> np.ndarray:
    """Cells the boat can be at t_min after the start, at speed_kmh, plus one cell for the start itself."""
    return dist_m <= speed_kmh * 1000.0 / 60.0 * max(0.0, t_min) + cell_m


def dwell_layers(dwell_min: float, step_min: float) -> int:
    """Layers a cell must stay clear for the mast to be up for dwell_min (at least 1)."""
    if not step_min:
        return 1
    return max(1, math.ceil(dwell_min / step_min))


def windows(risk: np.ndarray, usable: np.ndarray, times: list[float], threshold: float, n_dwell: int) -> dict:
    """Per layer, the best usable cell and its worst risk over the dwell (the same cell held for n_dwell layers, or
    to the last layer); a layer opens a window if that is at or under threshold. Consecutive window layers merge.

    risk, usable: (K, H, W). Returns {"layers": [{k, cell, risk, safe_cells}], "windows": [{k_from, k_to, cell, risk}]}."""
    K = risk.shape[0]
    r = np.where(usable, risk, np.inf)
    out, wins = [], []
    for k in range(K):
        held = r[k:min(K, k + n_dwell)].max(axis=0)
        if not np.isfinite(held).any():
            out.append({"k": k, "cell": None, "risk": None, "safe_cells": 0})
            continue
        i = int(np.argmin(held))
        c = np.unravel_index(i, held.shape)
        best = float(held[c])
        out.append({"k": k, "cell": (int(c[0]), int(c[1])), "risk": best, "safe_cells": int((held <= threshold).sum())})
        if best <= threshold:
            if wins and wins[-1]["k_to"] == k - 1:
                w = wins[-1]
                w["k_to"] = k
                if best < w["risk"] - 0.01:                # keep the earliest cell unless a later one is clearly better
                    w.update(cell=(int(c[0]), int(c[1])), risk=best, k_best=k)
            else:
                wins.append({"k_from": k, "k_to": k, "k_best": k, "cell": (int(c[0]), int(c[1])), "risk": best})
    for w in wins:
        w["t_from"], w["t_to"] = times[w["k_from"]], times[w["k_to"]]
    return {"layers": out, "windows": wins}
