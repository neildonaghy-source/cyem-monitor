"""CyEM Monitor: FastAPI application."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import geo, llm
from .collectors import REGISTRY
from .config import settings
from .db import get_db, iso
from .scheduler import Scheduler
from .spectrum_api import router as spectrum_router
from .link_api import ensure_link_schema, router as link_router
from .coverage_api import ensure_coverage_schema, router as coverage_router
from .omni import build_wide_ask, router as omni_router
from .spectrum_store import ensure_schema

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("cyem")

scheduler: Scheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    db = get_db()
    ensure_schema(db)
    ensure_link_schema(db)
    ensure_coverage_schema(db)
    scheduler = Scheduler(db)
    scheduler.start()
    log.info("CyEM Monitor up; data dir %s; model %s at %s", settings.data_dir, settings.ollama_model, settings.ollama_url)
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(title="CyEM Monitor", version="0.1.0", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
app.include_router(spectrum_router)
app.include_router(link_router)
app.include_router(coverage_router)
app.include_router(omni_router)
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")


@app.get("/")
async def index():
    return FileResponse(settings.static_dir / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
async def service_worker():
    return FileResponse(settings.static_dir / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(settings.static_dir / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "time": iso(datetime.now(timezone.utc))}


# ---- status -----------------------------------------------------------------------
@app.get("/api/status")
async def status():
    db = get_db()
    sw, sw_t = db.get_snapshot("spaceweather")
    hf, _ = db.get_snapshot("hf")
    gj, _ = db.get_snapshot("gpsjam")
    io, _ = db.get_snapshot("ioda")
    kev, _ = db.get_snapshot("kev_stats")
    rw, _ = db.get_snapshot("ransomware_stats")
    c2, _ = db.get_snapshot("c2")
    cf, _ = db.get_snapshot("cloudflare")
    octi, octi_t = db.get_snapshot("opencti")
    aur, aur_t = db.get_snapshot("aurora")
    drap, drap_t = db.get_snapshot("drap")
    hfm, _ = db.get_snapshot("hfmap")
    latest = db.brief()
    runs = scheduler.status() if scheduler else []
    return {
        "time": iso(datetime.now(timezone.utc)),
        "tz": settings.tz,
        "spaceweather": {
            "updated": sw_t,
            "kp": (sw or {}).get("kp", {}).get("value") if sw else None,
            "kp_max_24h": (sw or {}).get("kp", {}).get("max_24h") if sw else None,
            "scales": (sw or {}).get("scales", {}).get("now") if sw else None,
            "past24h": (sw or {}).get("scales", {}).get("past24h") if sw else None,
            "predicted": (sw or {}).get("scales", {}).get("predicted") if sw else None,
            "max_flare_24h": (sw or {}).get("max_flare_24h") if sw else None,
            "f107": ((sw or {}).get("f107") or {}).get("flux") if sw else None,
            "solar_wind": (sw or {}).get("solar_wind") if sw else None,
            "alerts": ((sw or {}).get("alerts_3d") or [])[:8] if sw else [],
            "flares": ((sw or {}).get("flares_3d") or [])[:10] if sw else [],
            "kp_series": ((sw or {}).get("kp") or {}).get("series") if sw else None,
        },
        "hf": hf,
        "aurora": {"updated": aur_t, "max": aur.get("max"), "max_north": aur.get("max_north"), "max_south": aur.get("max_south"),
                   "forecast_time": aur.get("forecast_time")} if aur else None,
        "drap": {"updated": drap_t, "valid_at": drap.get("valid_at"), "max_mhz": drap.get("max_mhz"), "cells_affected": drap.get("cells_affected")} if drap else None,
        "hfmap": {"fresh_stations": hfm.get("fresh_stations"), "contours": len(hfm.get("contours") or [])} if hfm else None,
        "gnss": {"date": gj.get("date"), "high": gj.get("high"), "medium": gj.get("medium"), "by_region": gj.get("by_region")} if gj else None,
        "outages": {"alerts_24h": io.get("alerts"), "countries_critical": [
            {"name": c.get("name"), "code": c.get("code"), "critical": c.get("critical")} for c in (io.get("countries_critical") or [])[:12]]} if io else None,
        "kev": kev, "ransomware": rw,
        "c2": {"total": c2.get("total"), "families": c2.get("families"), "new_7d": len(c2.get("recent_7d") or [])} if c2 else None,
        "cloudflare": {"outages_7d": len(cf.get("outages_7d") or []), "bgp_hijacks_24h": len(cf.get("bgp_hijacks_24h") or []),
                       "l7_origin": cf.get("layer7_origin"), "l3_origin": cf.get("layer3_origin")} if cf else None,
        "opencti": {"updated": octi_t, "version": octi.get("version"), "reports_24h": octi.get("reports_24h"), "indicators_24h": octi.get("indicators_24h"),
                    "indicator_types": octi.get("indicator_types"), "errors": octi.get("errors")} if octi else None,
        "counts": {
            "items_24h": db.count_items(since_hours=24),
            "cyber_24h": db.count_items(domain="cyber", since_hours=24),
            "em_24h": db.count_items(domain="em", since_hours=24),
            "infra_24h": db.count_items(domain="infra", since_hours=24),
            "osint_24h": db.count_items(domain="osint", since_hours=24),
            "high_24h": db.count_items(since_hours=24, min_severity=4),
            "cve_7d": db.count_items(kind="cve", since_hours=24 * 7),
        },
        "brief": {"latest_at": latest["created_at"] if latest else None, "latest_id": latest["id"] if latest else None,
                  "generating": llm.state.generating, "started_at": llm.state.started_at, "last_error": llm.state.last_error,
                  "hours": settings.brief_hours, "model": settings.ollama_model},
        "collectors": runs,
    }


@app.get("/api/ollama")
async def ollama():
    return await llm.ollama_status()


# ---- items ------------------------------------------------------------------------
@app.get("/api/items")
async def items(domain: str | None = None, kind: str | None = None, country: str | None = None, tag: str | None = None,
                hours: int | None = Query(default=48, ge=1, le=24 * 120), min_severity: int | None = None,
                q: str | None = None, limit: int = Query(default=150, ge=1, le=1000), offset: int = 0):
    db = get_db()
    rows = db.list_items(domain=domain, kind=kind, country=country, tag=tag, since_hours=hours,
                         min_severity=min_severity, q=q, limit=limit, offset=offset)
    for r in rows:
        r["country_name"] = geo.name_of(r.get("country")) if r.get("country") else None
    return {"items": rows, "count": len(rows)}


# ---- map layers -------------------------------------------------------------------
@app.get("/api/layers/{name}")
async def layer(name: str, hours: int = Query(default=24 * 30, ge=1, le=24 * 120)):
    db = get_db()
    if name == "ransomware":
        rows = db.group_count("country", kind="ransomware", since_hours=hours, limit=120)
        out = []
        for r in rows:
            c = geo.centroid(r["key"])
            if c:
                out.append({"country": r["key"], "name": geo.name_of(r["key"]), "lat": c[0], "lon": c[1], "count": r["n"]})
        return {"points": out, "hours": hours}
    if name in ("c2", "gpsjam", "ioda", "cables", "gdelt", "launches", "cloudflare", "spaceweather", "radars", "milair", "sats", "opencti", "drap", "aurora", "hfmap"):
        data, updated = db.get_snapshot(name)
        if data is None:
            return {"updated": None, "data": None}
        return {"updated": updated, "data": data}
    if name == "apt":
        with open(settings.ref_dir / "apt_groups.json", encoding="utf-8") as f:
            groups = json.load(f)
        out = []
        per_country: dict[str, int] = {}
        for g in groups:
            c = (g.get("lat"), g.get("lon")) if g.get("lat") is not None else geo.centroid(g.get("country"))
            if not c:
                continue
            k = per_country.get(g["country"], 0)
            per_country[g["country"]] = k + 1
            # deterministic spread so several groups per country stay clickable
            out.append({**g, "lat": c[0] + ((k % 3) - 1) * 1.6, "lon": c[1] + ((k // 3) - 1) * 2.4 + (k % 2) * 1.1,
                        "country_name": geo.name_of(g.get("country"))})
        return {"groups": out}
    if name == "emitters":
        from .collectors.emitters import emitters_reference
        return {"emitters": emitters_reference(settings.ref_dir / "emitters.json")}
    if name == "items":
        rows = db.list_items(since_hours=min(hours, 24 * 7), limit=600)
        pts = [r for r in rows if r.get("lat") is not None and r.get("lon") is not None and r["kind"] not in ("ransomware",)]
        return {"points": pts}
    raise HTTPException(404, "unknown layer")


@app.get("/api/config")
async def config():
    """Non-secret runtime configuration: which optional keys are present, model, brief hours."""
    return {
        "keys": {
            "CLOUDFLARE_API_TOKEN": bool(settings.cloudflare_token),
            "NVD_API_KEY": bool(settings.nvd_api_key),
            "ABUSECH_AUTH_KEY": bool(settings.abusech_auth_key),
            "OPENCTI_URL+TOKEN": bool(settings.opencti_url and settings.opencti_token),
        },
        "model": settings.ollama_model, "brief_hours": settings.brief_hours, "tz": settings.tz,
    }


@app.get("/api/sat/{norad}/track")
async def sat_track(norad: int, minutes: int = Query(default=90, ge=10, le=360), step: int = Query(default=2, ge=1, le=10)):
    """Ground track for one satellite from the cached TLEs: -minutes/3 .. +2*minutes/3 around now."""
    from sgp4.api import Satrec, jday
    from .collectors.emitters import _gmst_deg, _teme_to_geodetic
    tle, _ = get_db().get_snapshot("sat_tle")
    if not tle:
        raise HTTPException(404, "no TLEs cached yet")
    found = None
    for group, tles in (tle.get("groups") or {}).items():
        for name, l1, l2 in tles:
            try:
                if int(l1[2:7]) == norad:
                    found = (name, l1, l2, group)
                    break
            except ValueError:
                continue
        if found:
            break
    if not found:
        raise HTTPException(404, "satellite not in cached groups")
    name, l1, l2, group = found
    s = Satrec.twoline2rv(l1, l2)
    now = datetime.now(timezone.utc)
    pts = []
    from datetime import timedelta
    for m in range(-minutes // 3, 2 * minutes // 3 + 1, step):
        t = now + timedelta(minutes=m)
        jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second)
        e, r, v = s.sgp4(jd, fr)
        if e != 0:
            continue
        lat, lon, alt = _teme_to_geodetic(r[0], r[1], r[2], _gmst_deg(jd, fr))
        pts.append([round(lat, 2), round(lon, 2), m])
    return {"name": name, "norad": norad, "group": group, "points": pts, "minutes": minutes}


@app.get("/api/countries")
async def countries_ref():
    return {k: {"name": v["name"], "lat": v["lat"], "lon": v["lon"]} for k, v in geo.countries().items()}


# ---- briefs -----------------------------------------------------------------------
@app.get("/api/briefs")
async def briefs(limit: int = 20):
    return {"briefs": get_db().briefs(limit)}


@app.get("/api/briefs/state")
async def brief_state():
    return {"generating": llm.state.generating, "started_at": llm.state.started_at, "last_error": llm.state.last_error,
            "last_kind": llm.state.last_kind}


@app.get("/api/briefs/latest")
async def brief_latest():
    b = get_db().brief()
    if not b:
        return JSONResponse({"brief": None})
    return {"brief": b}


@app.get("/api/briefs/preview-context")
async def brief_context_preview(hours: int = 24):
    """Debug: what the model would be shown."""
    msgs, n = llm.build_brief_messages(get_db(), hours)
    return {"items": n, "chars": sum(len(m["content"]) for m in msgs), "messages": msgs}


@app.get("/api/briefs/{brief_id}")
async def brief_get(brief_id: int):
    b = get_db().brief(brief_id)
    if not b:
        raise HTTPException(404, "no such brief")
    return {"brief": b}


class GenerateReq(BaseModel):
    hours: int = Field(default=24, ge=6, le=96)


@app.post("/api/briefs/generate")
async def brief_generate(req: GenerateReq | None = None):
    if llm.state.generating:
        return JSONResponse({"ok": False, "error": "already generating", "started_at": llm.state.started_at}, status_code=409)
    hours = req.hours if req else 24
    asyncio.create_task(llm.generate_brief(get_db(), kind="manual", hours=hours))
    return {"ok": True, "started": True}


# ---- ask --------------------------------------------------------------------------
class AskReq(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


@app.post("/api/ask")
async def ask(req: AskReq):
    messages, meta = build_wide_ask(get_db(), req.question.strip())

    async def gen():
        try:
            yield f"data: {json.dumps({'meta': meta})}\n\n"
            async for tok in llm.chat_stream(messages, num_predict=700, temperature=0.2):
                yield f"data: {json.dumps({'t': tok})}\n\n"
            yield "data: {\"done\": true}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'error': f'{type(e).__name__}: {str(e)[:200]}'})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---- collectors -------------------------------------------------------------------
@app.get("/api/collectors")
async def collectors():
    return {"collectors": scheduler.status() if scheduler else [], "feeds": get_db().feed_states()}


@app.post("/api/collect/{name}")
async def collect(name: str):
    if name == "all":
        started = [n for n in REGISTRY if scheduler and scheduler.trigger(n)]
        return {"ok": True, "started": started}
    if name not in REGISTRY:
        raise HTTPException(404, "unknown collector")
    ok = scheduler.trigger(name) if scheduler else False
    return {"ok": ok, "started": [name] if ok else []}


@app.middleware("http")
async def no_frame_block(request: Request, call_next):
    # Deliberately no X-Frame-Options so Home Assistant can embed the dashboard in an iframe.
    resp = await call_next(request)
    resp.headers.setdefault("Cache-Control", "no-store" if request.url.path.startswith("/api/") else "public, max-age=300")
    return resp
