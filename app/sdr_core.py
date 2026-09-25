"""SDR sweep handling (stdlib only, unit-tested): noise floor, peak finding, compact encoding."""
from __future__ import annotations

import statistics


def noise_floor(db: list[float], window: int = 200) -> list[float]:
    """Running 20th-percentile floor over a sliding window of bins (robust to strong carriers)."""
    n = len(db)
    if n == 0:
        return []
    half = max(1, window // 2)
    out = []
    step = max(1, n // 400)                       # evaluate on a coarse grid, then hold
    cache: dict[int, float] = {}
    for i in range(n):
        k = (i // step) * step
        if k not in cache:
            seg = sorted(db[max(0, k - half): min(n, k + half)])
            cache[k] = seg[int(0.2 * (len(seg) - 1))]
        out.append(cache[k])
    return out


def find_peaks(f0_hz: float, bin_hz: float, db: list[float], snr_db: float = 10.0, max_peaks: int = 60) -> list[dict]:
    """Local maxima at least snr_db above the local floor; merges adjacent bins into one signal with a width."""
    floor = noise_floor(db)
    peaks, i, n = [], 0, len(db)
    while i < n:
        if db[i] - floor[i] >= snr_db:
            j = i
            while j + 1 < n and db[j + 1] - floor[j + 1] >= snr_db:
                j += 1
            k = max(range(i, j + 1), key=lambda x: db[x])
            peaks.append({"f_hz": f0_hz + k * bin_hz, "level_db": round(db[k], 1), "snr_db": round(db[k] - floor[k], 1),
                          "width_hz": (j - i + 1) * bin_hz})
            i = j + 1
        else:
            i += 1
    peaks.sort(key=lambda p: -p["snr_db"])
    return peaks[:max_peaks]


def summary(db: list[float]) -> dict:
    if not db:
        return {}
    return {"median_db": round(statistics.median(db), 1), "max_db": round(max(db), 1), "bins": len(db)}
