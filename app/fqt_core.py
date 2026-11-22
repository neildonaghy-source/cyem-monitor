"""Spectrum by frequency and time (phase 6 part 4): pure helpers, stdlib only, unit-tested.

Candidate channels across a band, the status of a net on a channel at a time step from its users' J/S, ranking, and
which of the scenario's own and civil emitters share a channel. Screening grade; the band defaults are generic
(NATO VHF 30-88 MHz, military UHF 225-400 MHz), not any assignment.
"""
from __future__ import annotations

import math

BANDS = ((30.0, 88.0), (225.0, 400.0))
MAX_CHANNELS = 48


def default_band(f_mhz: float) -> tuple[float, float]:
    """The generic band a net's frequency sits in, else plus or minus 10%."""
    for lo, hi in BANDS:
        if lo <= f_mhz <= hi:
            return lo, hi
    return round(f_mhz * 0.9, 3), round(f_mhz * 1.1, 3)


def channels(lo_mhz: float, hi_mhz: float, bw_khz: float, step_khz: float | None = None, most: int = MAX_CHANNELS) -> list[float]:
    """Channel centres (MHz) from lo to hi: every step_khz (default the channel width), thinned evenly to at most
    `most`, always keeping the ends."""
    bw = max(bw_khz, 1.0) / 1000.0
    step = max((step_khz or bw_khz) / 1000.0, bw)
    a, b = lo_mhz + bw / 2, hi_mhz - bw / 2
    if b < a:
        return [round((lo_mhz + hi_mhz) / 2, 4)]
    n = int(math.floor((b - a) / step + 1e-9)) + 1
    k = max(1, math.ceil(n / most))
    out = [round(a + i * step, 4) for i in range(0, n, k)]
    last = round(a + (n - 1) * step, 4)
    if out[-1] != last:
        out.append(last)
    return out


def overlaps(f1_mhz: float, bw1_khz: float, lo2_mhz: float, hi2_mhz: float) -> bool:
    """Does a channel (centre, width) overlap the band lo2..hi2?"""
    h = bw1_khz / 2000.0
    return f1_mhz + h > lo2_mhz and f1_mhz - h < hi2_mhz


def net_status(user_js: list[float | None], req_db: float) -> tuple[str, float | None]:
    """The net on a channel at one step: denied if any user is at or over the threshold, degraded if any is within
    6 dB of it, else clear; with the worst user's J/S (None if no jammer reaches any user)."""
    vals = [x for x in user_js if x is not None]
    if not vals:
        return "clear", None
    worst = max(vals)
    return ("denied" if worst >= req_db else "degraded" if worst >= req_db - 6 else "clear"), round(worst, 1)


def rank_key(ch: dict) -> tuple:
    """Best first: most usable steps, fewest scenario conflicts (own, then civil), lowest worst J/S, fewest licences."""
    c = ch.get("conflicts") or {}
    js = ch.get("worst_js_db")
    return (-ch.get("usable_steps", 0), len(c.get("own") or []), len(c.get("civil") or []),
            js if js is not None else -999.0, (c.get("wtr") or {}).get("count", 0), ch.get("f_mhz", 0))
