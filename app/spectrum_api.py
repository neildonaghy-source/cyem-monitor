"""Spectrum deconfliction API: WTR baseline, planned emitters, conflicts, brief."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from . import llm
from .config import settings
from .db import get_db
from .spectrum_store import (planned_delete, planned_get, planned_list, planned_to_emitter, planned_upsert, run_conflicts,
                             wtr_candidates, wtr_count, wtr_in_bbox, wtr_products)

router = APIRouter(prefix="/api/spectrum", tags=["spectrum"])

DEFAULT_GUARD_KHZ = 0.0
DEFAULT_RADIUS_KM = 50.0


class PlannedIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    freq_mhz: float = Field(gt=0.001, lt=300000)
    bw_khz: float = Field(ge=0, le=2_000_000)
    power_w: float | None = Field(default=None, ge=0, le=10_000_000)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    start_at: str | None = None
    end_at: str | None = None
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("start_at", "end_at")
    @classmethod
    def _iso(cls, v: str | None) -> str | None:
        if not v:
            return None
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as e:
            raise ValueError("use ISO-8601, e.g. 2026-10-01T06:00Z") from e
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)   # naive input is treated as UTC (Zulu)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_row(self) -> dict:
        return {"name": self.name.strip(), "freq_hz": round(self.freq_mhz * 1e6, 1), "bw_hz": round(self.bw_khz * 1e3, 1),
                "power_w": self.power_w, "lat": round(self.lat, 6), "lon": round(self.lon, 6),
                "start_at": self.start_at, "end_at": self.end_at, "notes": (self.notes or "").strip() or None}


def _guard_radius(guard_khz: float, radius_km: float) -> tuple[float, float]:
    return guard_khz * 1e3, radius_km


# ---- baseline --------------------------------------------------------------------
@router.get("/status")
async def status():
    db = get_db()
    snap, updated = db.get_snapshot("wtr")
    return {"loaded": wtr_count(db), "updated": updated, "source": snap or None,
            "planned": len(planned_list(db)), "defaults": {"guard_khz": DEFAULT_GUARD_KHZ, "radius_km": DEFAULT_RADIUS_KM}}


@router.get("/products")
async def products():
    return {"products": wtr_products(get_db())}


@router.get("/bandplan")
async def bandplan():
    with open(settings.ref_dir / "uk_bandplan.json", encoding="utf-8") as f:
        return json.load(f)


@router.get("/wtr")
async def wtr(s: float = Query(ge=-90, le=90), w: float = Query(ge=-180, le=180), n: float = Query(ge=-90, le=90),
              e: float = Query(ge=-180, le=180), fmin_mhz: float | None = None, fmax_mhz: float | None = None,
              product: list[str] | None = Query(default=None), limit: int = Query(default=3000, ge=1, le=8000)):
    if (n - s) * (e - w) > 16:   # roughly 4 x 4 degrees; the UI only asks at zoom >= 8
        raise HTTPException(400, "area too large; zoom in")
    rows, total = wtr_in_bbox(get_db(), s, w, n, e, fmin_hz=fmin_mhz * 1e6 if fmin_mhz is not None else None,
                              fmax_hz=fmax_mhz * 1e6 if fmax_mhz is not None else None, products=product, limit=limit)
    return {"total": total, "returned": len(rows), "rows": rows}


# ---- planned emitters -------------------------------------------------------------
@router.get("/planned")
async def planned():
    return {"planned": planned_list(get_db())}


@router.post("/planned")
async def planned_create(body: PlannedIn):
    return planned_upsert(get_db(), body.to_row())


@router.put("/planned/{pid}")
async def planned_update(pid: str, body: PlannedIn):
    db = get_db()
    if not planned_get(db, pid):
        raise HTTPException(404, "no such planned emitter")
    return planned_upsert(db, body.to_row(), pid)


@router.delete("/planned/{pid}")
async def planned_remove(pid: str):
    if not planned_delete(get_db(), pid):
        raise HTTPException(404, "no such planned emitter")
    return {"deleted": pid}


# ---- conflicts + spectral view ---------------------------------------------------
@router.get("/conflicts")
async def conflicts(guard_khz: float = Query(default=DEFAULT_GUARD_KHZ, ge=0, le=100_000),
                    radius_km: float = Query(default=DEFAULT_RADIUS_KM, gt=0, le=500)):
    db = get_db()
    g, r = _guard_radius(guard_khz, radius_km)
    res = run_conflicts(db, guard_hz=g, radius_km=r)
    res["baseline_rows"] = wtr_count(db)
    return res


@router.get("/view/{pid}")
async def view(pid: str, span_khz: float = Query(default=200, gt=0, le=2_000_000),
               radius_km: float = Query(default=DEFAULT_RADIUS_KM, gt=0, le=500)):
    """Data for the spectral display: licensed assignments within radius_km of the
    planned emitter and within +/- span_khz of its centre frequency."""
    db = get_db()
    row = planned_get(db, pid)
    if not row:
        raise HTTPException(404, "no such planned emitter")
    p = planned_to_emitter(row)
    from .spectrum_core import haversine_km
    near = [c for c in wtr_candidates(db, p, guard_hz=0, radius_km=radius_km, extra_span_hz=span_khz * 1e3)
            if haversine_km(p.lat, p.lon, c.lat, c.lon) <= radius_km]
    others = [planned_to_emitter(o) for o in planned_list(db) if o["id"] != pid]
    others = [o for o in others if abs(o.freq_hz - p.freq_hz) <= span_khz * 1e3 + o.bw_hz / 2
              and haversine_km(p.lat, p.lon, o.lat, o.lon) <= radius_km]
    to_d = lambda e: {"id": e.id, "name": e.name, "kind": e.kind, "freq_hz": e.freq_hz, "bw_hz": e.bw_hz,  # noqa: E731
                      "dist_km": round(haversine_km(p.lat, p.lon, e.lat, e.lon), 1), "meta": e.meta}
    return {"planned": to_d(p), "span_hz": span_khz * 1e3, "radius_km": radius_km,
            "assignments": [to_d(c) for c in near][:1500], "planned_others": [to_d(o) for o in others]}


# ---- Ollama narrative --------------------------------------------------------------
BRIEF_SYSTEM = (
    "You are a spectrum management staff officer writing for a senior Royal Signals practitioner. "
    "British English, plain and concise, no marketing tone, no headings beyond short bold labels. "
    "You are given the COMPLETE output of a deterministic frequency deconfliction check. "
    "Narrate only what is in that data: do not invent frequencies, licensees, distances or conflicts, "
    "and do not speculate about who is transmitting. Licensed assignments are Ofcom register entries, "
    "not measured on-air activity; say so once if relevant. "
    "Structure: one-line BLUF; then the planned emitters with high or medium conflicts, most serious first, "
    "each with the clashing assignment, spacing and distance; then a short line on low (guard-band only) items; "
    "then one or two practical deconfliction options such as moving frequency outside the listed clashes or "
    "changing site. Under 250 words. Do not state deadlines or dates other than the time windows given; "
    "the check-run time is not a transmission date. Only planned emitters can be moved or retuned: "
    "never suggest changing a licensed assignment.")


def _brief_context(res: dict, per_emitter: int = 8) -> str:
    lines = [f"Check run {res['generated_at']}; guard band {res['guard_hz'] / 1e3:g} kHz; radius {res['radius_km']:g} km; "
             f"baseline {res.get('baseline_rows', '?')} Ofcom WTR assignments.",
             f"Totals: {json.dumps(res['totals'])}"]
    for p in res["planned"]:
        lines.append(f"\nPLANNED {p['name']}: {p['freq_hz'] / 1e6:.6f} MHz, BW {p['bw_hz'] / 1e3:g} kHz, "
                     f"at {p['lat']:.4f},{p['lon']:.4f}, window {p['start'] or 'open'} to {p['end'] or 'open'}; "
                     f"{len(p['conflicts'])} conflicts")
        for c in p["conflicts"][:per_emitter]:
            m = c.get("b_meta") or {}
            who = f"{c['b_name']} ({m.get('product', 'planned')}, licence {m.get('licence', '-')})" if c["b_kind"] != "planned" \
                else f"planned emitter {c['b_name']}"
            lines.append(f"  - {c['severity'].upper()}: {who} at {c['b_freq_hz'] / 1e6:.6f} MHz BW {c['b_bw_hz'] / 1e3:g} kHz; "
                         f"spacing {c['spacing_hz'] / 1e3:g} kHz; occupied bands {'overlap' if c['co_channel'] else 'clear (guard only)'}; "
                         + (f"{c['dist_km']:g} km" if c["dist_km"] is not None else "area licence, location not published"))
        if len(p["conflicts"]) > per_emitter:
            lines.append(f"  - (+{len(p['conflicts']) - per_emitter} further conflicts not listed)")
    return "\n".join(lines)


class BriefReq(BaseModel):
    guard_khz: float = Field(default=DEFAULT_GUARD_KHZ, ge=0, le=100_000)
    radius_km: float = Field(default=DEFAULT_RADIUS_KM, gt=0, le=500)


@router.post("/brief")
async def brief(req: BriefReq | None = None):
    req = req or BriefReq()
    db = get_db()
    res = run_conflicts(db, guard_hz=req.guard_khz * 1e3, radius_km=req.radius_km)
    res["baseline_rows"] = wtr_count(db)
    if not res["planned"]:
        return {"content": "No planned emitters entered, so there is nothing to deconflict.", "totals": res["totals"]}
    ctx = _brief_context(res)
    t0 = time.monotonic()
    try:
        content, meta = await llm.chat([{"role": "system", "content": BRIEF_SYSTEM},
                                        {"role": "user", "content": f"{ctx}\n\nWrite the deconfliction note now."}],
                                       num_predict=500, temperature=0.2)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Ollama unavailable: {type(e).__name__}: {str(e)[:200]}") from e
    return {"content": content, "totals": res["totals"], "context": ctx, "model": settings.ollama_model,
            "duration_s": round(time.monotonic() - t0, 1), "meta": meta}
