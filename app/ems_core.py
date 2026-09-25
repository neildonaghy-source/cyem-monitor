"""Red / blue electromagnetic interaction screening on terrain.

Builds on coverage_core: each emitter or jammer gets a polar coverage grid (Deygout, 3 edges,
Copernicus terrain). This module resamples those grids onto one lat/lon raster and derives:

  exposure   blue emitter received level >= red receiver sensitivity (where red could detect blue)
  coverage   blue emitter level >= blue receiver sensitivity (where the blue net works)
  denial     inside blue coverage, J/S >= threshold, with
             J/S = J - S - 10 log10(max(1, Bj / Bv))   (wideband jamming spread over the victim channel)

and pairwise results (blue emitter -> red receiver detection margin, red jammer -> blue receiver J/S).
Frequencies must overlap for any interaction to count. Screening grade: no processing gain,
hopping, antenna nulling, clutter or time variability.
"""
from __future__ import annotations

import base64
import math

import numpy as np

from .coverage_core import Coverage, _png
from .link_core import EARTH_R_M


def overlap(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> bool:
    return a_lo <= b_hi and b_lo <= a_hi


def bw_penalty_db(jam_bw_hz: float, victim_bw_hz: float) -> float:
    """Only the part of a wideband jammer inside the victim channel counts."""
    if victim_bw_hz <= 0 or jam_bw_hz <= victim_bw_hz:
        return 0.0
    return 10 * math.log10(jam_bw_hz / victim_bw_hz)


def union_bounds(covs: list[Coverage]) -> tuple[float, float, float, float]:
    b = [c.bounds() for c in covs]
    return min(x[0] for x in b), min(x[1] for x in b), max(x[2] for x in b), max(x[3] for x in b)


def raster_axes(s: float, w: float, n: float, e: float, px: int = 520) -> tuple[np.ndarray, np.ndarray]:
    mid = (s + n) / 2
    H = px
    W = max(8, int(round(px * (e - w) * math.cos(math.radians(mid)) / max(n - s, 1e-6))))
    lats = n - (np.arange(H) + 0.5) / H * (n - s)
    lons = w + (np.arange(W) + 0.5) / W * (e - w)
    return np.meshgrid(lats, lons, indexing="ij")


def sample(cov: Coverage, LA: np.ndarray, LO: np.ndarray) -> np.ndarray:
    """Received level (dBm) from a polar coverage grid at raster points; -inf outside its radius."""
    p1, p2 = math.radians(cov.lat), np.radians(LA)
    dl = np.radians(LO - cov.lon)
    a = np.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    dist = 2 * EARTH_R_M * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    brg = (np.degrees(np.arctan2(np.sin(dl) * np.cos(p2),
                                 math.cos(p1) * np.sin(p2) - math.sin(p1) * np.cos(p2) * np.cos(dl))) + 360) % 360
    ai = np.round(brg / (360 / cov.n_az)).astype(int) % cov.n_az
    ri = np.clip(np.round(dist / cov.step_m).astype(int), 1, cov.prx.shape[1] - 1)
    lv = cov.prx[ai, ri].astype(np.float64)
    lv = np.where(np.isnan(lv), -np.inf, lv)
    return np.where(dist <= cov.radius_m, lv, -np.inf)


def cell_km2(LA: np.ndarray, LO: np.ndarray) -> float:
    dlat = abs(LA[0, 0] - LA[1, 0]) if LA.shape[0] > 1 else 0
    dlon = abs(LO[0, 1] - LO[0, 0]) if LO.shape[1] > 1 else 0
    mid = math.radians(float(LA.mean()))
    return (dlat * 111.195) * (dlon * 111.195 * math.cos(mid))


def overlay_png(masks: list[tuple[np.ndarray, tuple[int, int, int, int]]]) -> str:
    """Stack boolean masks (later masks draw on top) into one RGBA PNG data URL."""
    H, W = masks[0][0].shape
    img = np.zeros((H, W, 4), dtype=np.uint8)
    for m, rgba in masks:
        img[m] = rgba
    return "data:image/png;base64," + base64.b64encode(_png(img)).decode()


BLUE_COV = (60, 140, 255, 70)
RED_EXPO = (255, 70, 70, 95)
DENIED = (220, 60, 220, 150)


# ---- high-contrast rendering ----------------------------------------------------------------
PALETTE = {  # weak -> strong, then the edge line; brighter means stronger
    "blue": [(35, 80, 190, 150), (55, 190, 255, 160), (205, 245, 255, 185), (130, 225, 255, 255)],
    "red": [(130, 20, 20, 150), (255, 70, 70, 160), (255, 205, 205, 185), (255, 130, 130, 255)],
    "grey": [(90, 98, 110, 140), (150, 160, 172, 150), (215, 222, 230, 175), (200, 205, 215, 255)],
}


def edge(mask: np.ndarray) -> np.ndarray:
    """Pixels on the boundary of a mask (4-neighbour)."""
    inner = mask.copy()
    for ax in (0, 1):
        for sh in (1, -1):
            inner &= np.roll(mask, sh, axis=ax)
    return mask & ~inner


def hatch(shape, period: int = 8, width: int = 3) -> np.ndarray:
    i, j = np.indices(shape)
    return ((i + j) % period) < width


def band_masks(lv: np.ndarray, thr: float, side: str) -> list:
    p = PALETTE[side]
    base = lv >= thr
    return [(base, p[0]), (lv >= thr + 10, p[1]), (lv >= thr + 20, p[2]), (edge(base), p[3])]


def region_masks(mask: np.ndarray, rgba: tuple, hatched: bool = False, edge_rgba: tuple | None = None) -> list:
    if not mask.any():
        return []
    out = [(mask & hatch(mask.shape), rgba), (mask & ~hatch(mask.shape), rgba[:3] + (max(30, rgba[3] // 3),))] if hatched else [(mask, rgba)]
    out.append((edge(mask), edge_rgba or rgba[:3] + (255,)))
    return out
