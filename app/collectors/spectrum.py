"""Spectrum / ionosphere overlays: NOAA D-RAP HF absorption grid, NOAA OVATION
aurora probability grid, KC2G real-time MUF contours and ionosonde values."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from ..db import iso
from .base import Context, Result, get_json, get_text, parse_dt, register

DRAP_URL = "https://services.swpc.noaa.gov/text/drap_global_frequencies.txt"
OVATION_URL = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"
KC2G_CONTOURS = "https://prop.kc2g.com/renders/current/mufd-normal-now.geojson"
KC2G_STATIONS = "https://prop.kc2g.com/api/stations.json"


@register("drap", interval_s=15 * 60, domain="em", description="NOAA D-RAP: highest HF frequency affected by D-region absorption (global grid)")
async def collect_drap(ctx: Context) -> Result:
    text = await get_text(ctx, DRAP_URL)
    valid = None
    lons: list[float] = []
    lats: list[float] = []
    grid: list[list[float]] = []
    for line in text.splitlines():
        if line.startswith("#"):
            m = re.search(r"Product Valid At\s*:\s*(.+UTC)", line)
            if m:
                valid = parse_dt(m.group(1).replace(" UTC", "Z").replace(" ", "T", 1), default_now=False)
            continue
        if "|" in line:
            left, right = line.split("|", 1)
            try:
                lat = float(left.strip())
            except ValueError:
                continue
            vals = []
            for tok in right.split():
                try:
                    vals.append(round(float(tok), 1))
                except ValueError:
                    vals.append(0.0)
            if vals:
                lats.append(lat)
                grid.append(vals)
        elif not lons and re.match(r"^\s*-?\d", line):
            # longitude header row (no '|'), e.g. "-180 -178 ... 178"
            try:
                lons = [float(t) for t in line.split()]
            except ValueError:
                lons = []
    if not grid:
        raise RuntimeError("no D-RAP rows parsed")
    ncol = len(grid[0])
    if len(lons) != ncol:
        lons = [-180 + i * (360 / ncol) for i in range(ncol)]
    # Ensure rows are south->north for the renderer.
    order = sorted(range(len(lats)), key=lambda i: lats[i])
    lats = [lats[i] for i in order]
    grid = [grid[i] for i in order]
    mx = max(max(r) for r in grid)
    affected = sum(1 for r in grid for v in r if v >= 1)
    ctx.db.set_snapshot("drap", {"valid_at": valid, "fetched_at": iso(datetime.now(timezone.utc)), "lats": lats, "lons": lons,
                                 "grid": grid, "max_mhz": mx, "cells_affected": affected,
                                 "attribution": "NOAA SWPC D-Region Absorption Prediction"})
    return Result(len(grid), f"{len(grid)}x{ncol} grid, max {mx} MHz, {affected} cells affected, valid {valid}")


@register("aurora", interval_s=15 * 60, domain="em", description="NOAA OVATION aurora probability (30-40 min forecast), downsampled to 2°")
async def collect_aurora(ctx: Context) -> Result:
    data = await get_json(ctx, OVATION_URL)
    coords = data.get("coordinates") or []
    step = 2
    w, h = 360 // step, 180 // step + 1  # lon 0..358, lat -90..90
    grid = [[0] * w for _ in range(h)]
    for lon, lat, val in coords:
        try:
            x = int(lon) // step
            y = (int(lat) + 90) // step
            if 0 <= x < w and 0 <= y < h:
                grid[y][x] = max(grid[y][x], int(val))
        except (TypeError, ValueError):
            continue
    mx = max(max(r) for r in grid)
    # Hemisphere maxima are a useful summary for the status strip and brief.
    north = max(max(r) for r in grid[h // 2:])
    south = max(max(r) for r in grid[: h // 2])
    ctx.db.set_snapshot("aurora", {"observation_time": data.get("Observation Time"), "forecast_time": data.get("Forecast Time"),
                                   "fetched_at": iso(datetime.now(timezone.utc)), "step": step, "lon0": 0, "lat0": -90, "grid": grid,
                                   "max": mx, "max_north": north, "max_south": south,
                                   "attribution": "NOAA SWPC OVATION aurora forecast"})
    return Result(len(coords), f"max probability {mx}% (N {north}%, S {south}%), forecast {data.get('Forecast Time')}")


@register("hfmap", interval_s=15 * 60, domain="em", description="KC2G real-time MUF(3000) contours and GIRO ionosonde foF2/MUF values")
async def collect_hfmap(ctx: Context) -> Result:
    contours = await get_json(ctx, KC2G_CONTOURS)
    feats = []
    for f in contours.get("features", []):
        p = f.get("properties") or {}
        g = f.get("geometry") or {}
        coords = g.get("coordinates") or []
        if g.get("type") != "LineString" or not coords:
            continue
        feats.append({"mhz": p.get("level-value"), "colour": p.get("stroke"),
                      "coords": [[round(x, 1), round(y, 1)] for x, y in coords]})
    stations_raw = await get_json(ctx, KC2G_STATIONS)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=3)
    stations = []
    for s in stations_raw:
        st = s.get("station") or {}
        t = parse_dt(s.get("time"), default_now=False)
        if not t:
            continue
        try:
            tdt = datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        fresh = tdt >= cutoff
        try:
            lat = float(st.get("latitude"))
            lon = float(st.get("longitude"))
        except (TypeError, ValueError):
            continue
        if lon > 180:
            lon -= 360
        stations.append({"code": st.get("code"), "name": st.get("name"), "lat": round(lat, 2), "lon": round(lon, 2),
                         "fof2": s.get("fof2"), "mufd": s.get("mufd"), "hmf2": s.get("hmf2"), "tec": s.get("tec"), "foe": s.get("foe"),
                         "time": t, "fresh": fresh, "cs": s.get("cs")})
    fresh_n = sum(1 for s in stations if s["fresh"])
    ctx.db.set_snapshot("hfmap", {"fetched_at": iso(datetime.now(timezone.utc)), "contours": feats, "stations": stations,
                                  "fresh_stations": fresh_n,
                                  "attribution": "MUF map and ionosonde data via prop.kc2g.com (GIRO / NOAA), GPL"})
    return Result(len(feats), f"{len(feats)} MUF contours, {fresh_n}/{len(stations)} ionosondes reporting in 3h")
