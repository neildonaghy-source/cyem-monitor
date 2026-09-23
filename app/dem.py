"""Terrain heights from Copernicus GLO-30 DEM (30 m, AWS open data, free to use).

Tiles (1 x 1 degree Cloud-Optimised GeoTIFF, ~5-25 MB) are downloaded on first
use into <data_dir>/dem/ and kept. A tile that does not exist (open sea) is
recorded with a .missing marker and treated as 0 m. Heights are metres above
the EGM2008 geoid, i.e. roughly mean sea level. It is a surface model: tree and
building canopy is partly included, which is conservative for clearance.
"""
from __future__ import annotations

import logging
import math
import threading
from pathlib import Path

import httpx

from .config import settings

log = logging.getLogger("cyem.dem")
BASE = "https://copernicus-dem-30m.s3.amazonaws.com"
_lock = threading.Lock()
_open: dict[str, object] = {}


def tile_name(lat: float, lon: float) -> str:
    la, lo = math.floor(lat), math.floor(lon)
    ns = f"N{la:02d}" if la >= 0 else f"S{-la:02d}"
    ew = f"E{lo:03d}" if lo >= 0 else f"W{-lo:03d}"
    return f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"


def dem_dir() -> Path:
    d = settings.data_dir / "dem"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_tile(name: str) -> Path | None:
    """Download the tile if needed. Returns its path, or None for sea (no tile)."""
    path = dem_dir() / f"{name}.tif"
    miss = dem_dir() / f"{name}.missing"
    if path.exists():
        return path
    if miss.exists():
        return None
    url = f"{BASE}/{name}/{name}.tif"
    part = path.with_suffix(".tif.part")
    with httpx.Client(timeout=httpx.Timeout(120, connect=15), follow_redirects=True) as c:
        with c.stream("GET", url) as r:
            if r.status_code in (403, 404):
                miss.touch()
                log.info("DEM %s: no tile (sea)", name)
                return None
            r.raise_for_status()
            with open(part, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
    part.replace(path)
    log.info("DEM %s downloaded (%.1f MB)", name, path.stat().st_size / 1e6)
    return path


def _dataset(path: Path):
    import rasterio   # imported lazily: only link planning needs it
    key = str(path)
    ds = _open.get(key)
    if ds is None:
        if len(_open) > 8:     # keep a handful of tiles open
            for k in list(_open)[:4]:
                try:
                    _open.pop(k).close()   # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass
        ds = rasterio.open(path)
        _open[key] = ds
    return ds


def heights(points: list[tuple[float, float]]) -> list[float]:
    """Terrain height (m) for each (lat, lon). Synchronous; call via asyncio.to_thread."""
    by_tile: dict[str, list[int]] = {}
    for i, (la, lo) in enumerate(points):
        by_tile.setdefault(tile_name(la, lo), []).append(i)
    out = [0.0] * len(points)
    with _lock:
        for name, idx in by_tile.items():
            path = ensure_tile(name)
            if path is None:
                continue
            ds = _dataset(path)
            nodata = ds.nodata
            coords = [(points[i][1], points[i][0]) for i in idx]    # rasterio wants (x=lon, y=lat)
            for i, val in zip(idx, ds.sample(coords, indexes=1)):
                v = float(val[0])
                out[i] = 0.0 if (nodata is not None and v == nodata) or not math.isfinite(v) or v < -500 else v
    return out


def status() -> dict:
    d = dem_dir()
    tifs = sorted(p.name for p in d.glob("*.tif"))
    return {"tiles_cached": len(tifs), "sea_tiles": len(list(d.glob("*.missing"))),
            "cache_mb": round(sum(p.stat().st_size for p in d.glob("*.tif")) / 1e6, 1), "source": BASE}
