"""HF skywave now-cast API: path MUF / FOT / space-weather LUF from live ionosondes and D-RAP."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .db import get_db
from .hf_core import plan

router = APIRouter(prefix="/api/hf", tags=["hf"])


class HFReq(BaseModel):
    a_lat: float = Field(ge=-90, le=90)
    a_lon: float = Field(ge=-180, le=180)
    b_lat: float = Field(ge=-90, le=90)
    b_lon: float = Field(ge=-180, le=180)
    freqs_mhz: list[float] = Field(default_factory=lambda: [3.5, 5.3, 7.0, 10.1, 14.0, 18.1, 21.0, 24.9, 28.0])
    max_age_h: float = Field(default=3.0, gt=0, le=48)


def _age_h(t: str | None) -> float | None:
    if not t:
        return None
    try:
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600


@router.post("/plan")
async def hf_plan(req: HFReq):
    db = get_db()
    hf, hf_t = db.get_snapshot("hfmap")
    if not hf:
        raise HTTPException(503, "no ionosonde data yet")
    stations = []
    for s in hf.get("stations", []):
        age = _age_h(s.get("time"))
        if age is not None and age <= req.max_age_h and s.get("fof2") and s.get("mufd"):
            stations.append({**s, "age_h": round(age, 1)})
    drap, _ = db.get_snapshot("drap")

    def luf_fn(lat, lon):
        if not drap:
            return None
        lats, lons, grid = drap["lats"], drap["lons"], drap["grid"]
        i = min(range(len(lats)), key=lambda k: abs(lats[k] - lat))
        j = min(range(len(lons)), key=lambda k: abs(lons[k] - lon))
        v = grid[i][j]
        return round(float(v), 1) if v else None

    res = plan(req.a_lat, req.a_lon, req.b_lat, req.b_lon, stations, sorted(set(req.freqs_mhz)), luf_fn)
    ages = {s.get("name") or s.get("code"): s["age_h"] for s in stations}
    for c in res["control_points"]:
        c["sources"] = [{"name": n, "km": km, "age_h": ages.get(n)} for n, km in c["sources"]]
    res.update({"stations_used": len(stations), "max_age_h": req.max_age_h, "ionosonde_fetched": hf_t,
                "drap_valid": (drap or {}).get("valid_at"),
                "notes": "Now-cast from live ionosondes (KC2G / GIRO) and NOAA D-RAP. FOT = 0.85 x MUF. The lower limit covers "
                         "space-weather absorption only; normal daytime D-layer absorption raises the usable floor, typically to "
                         "3 to 7 MHz on long daytime paths. Not a forecast: conditions change within the hour, and paths over "
                         "areas with no nearby ionosonde are not assessed."})
    return res
