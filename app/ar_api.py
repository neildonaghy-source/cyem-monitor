"""AR feed for the iPhone app: what is around the viewer, with bearing, distance, elevation angle and,
for EMO entities, the predicted level at the viewer's position (terrain path, both heights). Notional EMO
data plus open data: Ofcom WTR licensed sites (names masked as elsewhere), ADS-B aircraft, AIS ships."""
from __future__ import annotations

import asyncio
import math

from fastapi import APIRouter, Query

from .db import get_db
from .link_core import bearing_deg, haversine_m

router = APIRouter(prefix="/api/ar", tags=["ar"])
R_EFF = 6371000.0 * 4 / 3


def _elev_deg(dist_m: float, h_view: float, h_obj: float) -> float:
    """Apparent elevation angle with 4/3 earth curvature (negative = below the horizon)."""
    if dist_m < 1:
        return 90.0 if h_obj > h_view else -90.0
    return math.degrees(math.atan2(h_obj - h_view - dist_m * dist_m / (2 * R_EFF), dist_m))


def _item(src, name, lat, lon, alt_m, view, **kw):
    d = haversine_m(view[0], view[1], lat, lon)
    return {"source": src, "name": name, "lat": round(lat, 5), "lon": round(lon, 5), "alt_m": round(alt_m, 1),
            "bearing": round(bearing_deg(view[0], view[1], lat, lon), 1), "dist_km": round(d / 1000, 2),
            "elev_deg": round(_elev_deg(d, view[2], alt_m), 2), **kw}


@router.get("")
async def ar(lat: float = Query(ge=-85, le=85), lon: float = Query(ge=-180, le=180), alt: float = Query(default=0, ge=-500, le=9000),
             radius_km: float = Query(default=30, gt=1, le=150), levels: bool = True):
    db = get_db()
    ground = alt + 1.5
    view = (lat, lon, ground)
    items = []
    # EMO entities (notional), with predicted level at the viewer for anything that radiates
    try:
        from . import emo_api
        ents = emo_api._all()
        pos = (emo_api._LAST or {}).get("pos", {})
        viewer = {"id": f"viewer:{round(lat, 3)}:{round(lon, 3)}", "updated_at": "", "h_agl": 1.5}
        jobs = []
        for e in ents:
            la, lo = pos.get(e["id"], (e["lat"], e["lon"]))
            if haversine_m(lat, lon, la, lo) > 150_000:
                continue
            it = _item("emo", e["name"], la, lo, e["h_agl"], view, side=e["side"], kind=e["kind"], category=e.get("category"),
                       freq_mhz=e["freq_mhz"], active=e["active"])
            items.append(it)
            if levels and e["active"] and e.get("eirp_dbm") is not None and e.get("fixed_level_dbm") is None and e["kind"] in ("emitter", "effector", "receiver"):
                jobs.append((it, emo_api.p2p_level(e, (la, lo), viewer, (lat, lon))))
        for (it, lv) in zip([j[0] for j in jobs], await asyncio.gather(*[j[1] for j in jobs], return_exceptions=True)):
            if not isinstance(lv, Exception):
                it["level_dbm"] = round(lv, 1)
    except Exception:  # noqa: BLE001
        pass
    # Ofcom licensed sites: nearest distinct sites
    try:
        from .spectrum_core import bbox_for_radius, looks_personal
        s, n, w, e_ = bbox_for_radius(lat, lon, radius_km)
        rows = db.query("SELECT company, product, MIN(freq_hz) AS f, COUNT(*) AS n, lat, lon, MAX(ant_height_m) AS h FROM wtr "
                        "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? GROUP BY lat, lon", (s, n, w, e_))
        rows.sort(key=lambda r: haversine_m(lat, lon, r["lat"], r["lon"]))
        for r in rows[:40]:
            nm = r["company"] or ""
            nm = "Licensee withheld (individual)" if (not nm or any(looks_personal(x.strip()) for x in nm.split(";"))) else nm
            items.append(_item("licence", nm, r["lat"], r["lon"], r["h"] or 10, view,
                               product=r["product"], freq_mhz=round(r["f"] / 1e6, 4), assignments=r["n"]))
    except Exception:  # noqa: BLE001
        pass
    # aircraft and ships from the live layers
    for key, src in (("air", "aircraft"), ("ais", "ship")):
        try:
            snap, _ = db.get_snapshot(key)
            for a in (snap or {}).get("aircraft" if key == "air" else "vessels", []):
                if haversine_m(lat, lon, a["lat"], a["lon"]) > (100_000 if key == "air" else 30_000):
                    continue
                if key == "air":
                    alt_m = (a.get("alt") or 0) * 0.3048
                    items.append(_item(src, a.get("flight") or a.get("reg") or a.get("hex"), a["lat"], a["lon"], alt_m, view,
                                       gnss_bad=a.get("gnss_bad"), emerg=a.get("emerg"), mil=a.get("mil")))
                else:
                    items.append(_item(src, a.get("name") or f"MMSI {a['mmsi']}", a["lat"], a["lon"], 10, view, cat=a.get("cat")))
        except Exception:  # noqa: BLE001
            pass
    air = sorted([i for i in items if i["source"] == "aircraft"], key=lambda x: x["dist_km"])[40:]
    drop = {id(i) for i in air}
    items = [i for i in items if id(i) not in drop]
    items.sort(key=lambda x: x["dist_km"])
    return {"viewer": {"lat": lat, "lon": lon, "alt_m": alt}, "count": len(items), "items": items[:150]}
