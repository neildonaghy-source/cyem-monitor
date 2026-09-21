"""Internet infrastructure collectors: IODA outage alerts, submarine cable
geometry, Cloudflare Radar (outages, attacks, BGP) when a token is present."""
from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timezone

from .. import geo
from ..config import settings
from ..db import iso
from ..tagging import strip_html
from .base import Context, Result, get_json, item_id, parse_dt, register

IODA_URL = "https://api.ioda.inetintel.cc.gatech.edu/v2/outages/alerts"
CABLE_GEO_URL = "https://www.submarinecablemap.com/api/v3/cable/cable-geo.json"
CABLE_LIST_URL = "https://www.submarinecablemap.com/api/v3/cable/all.json"
CF = "https://api.cloudflare.com/client/v4/radar"


# ---- IODA -------------------------------------------------------------------
@register("ioda", interval_s=30 * 60, domain="infra", description="IODA (Georgia Tech): internet outage alerts, last 24h")
async def collect_ioda(ctx: Context) -> Result:
    now = int(time.time())
    data = await get_json(ctx, IODA_URL, params={"from": now - 24 * 3600, "until": now, "limit": 500})
    rows = data.get("data") or []
    entities: dict[str, dict] = {}
    for a in rows:
        ent = a.get("entity") or {}
        etype, code, name = ent.get("type"), ent.get("code"), ent.get("name")
        if not code:
            continue
        key = f"{etype}:{code}"
        attrs = ent.get("attrs") or {}
        iso2 = None
        if etype == "country":
            iso2 = geo.resolve(code)
        else:
            iso2 = geo.resolve(attrs.get("country_code") or attrs.get("country") or attrs.get("country_name"))
        e = entities.setdefault(key, {"type": etype, "code": code, "name": name, "country": iso2,
                                      "alerts": 0, "critical": 0, "warning": 0, "sources": Counter(),
                                      "first": None, "last": None, "levels": Counter()})
        e["alerts"] += 1
        level = (a.get("level") or "").lower()
        e["levels"][level] += 1
        if level == "critical":
            e["critical"] += 1
        elif level == "warning":
            e["warning"] += 1
        e["sources"][a.get("datasource") or "?"] += 1
        t = a.get("time")
        ts = parse_dt(t, default_now=False) if t else None
        if ts:
            e["first"] = min(e["first"], ts) if e["first"] else ts
            e["last"] = max(e["last"], ts) if e["last"] else ts
    out = []
    items = []
    for e in entities.values():
        c = geo.centroid(e["country"]) if e["country"] else None
        rec = {**e, "sources": e["sources"].most_common(), "levels": dict(e["levels"]),
               "lat": c[0] if c else None, "lon": c[1] if c else None}
        out.append(rec)
        if e["type"] == "country" and e["critical"] > 0 and e["country"]:
            sev = 4 if e["critical"] >= 2 else 3
            items.append({
                "id": item_id("ioda", e["type"], e["code"], (e["first"] or "")[:13]),
                "source": "IODA", "domain": "infra", "kind": "outage",
                "title": f"Internet outage signal: {e['name']} ({e['critical']} critical alerts)",
                "url": f"https://ioda.inetintel.cc.gatech.edu/country/{e['code']}",
                "summary": f"IODA raised {e['alerts']} outage alerts for {e['name']} in the last 24h "
                           f"({e['critical']} critical, {e['warning']} warning) from sources: "
                           + ", ".join(f"{s} ({n})" for s, n in e["sources"].most_common()) + ".",
                "published_at": e["last"] or iso(datetime.now(timezone.utc)), "country": e["country"],
                "lat": rec["lat"], "lon": rec["lon"], "severity": sev, "tags": ["outage"],
                "extra": {"critical": e["critical"], "warning": e["warning"], "levels": dict(e["levels"])},
            })
    out.sort(key=lambda r: (-r["critical"], -r["alerts"]))
    new = ctx.db.upsert_items(items)
    ctx.db.set_snapshot("ioda", {"fetched_at": iso(datetime.now(timezone.utc)), "alerts": len(rows), "entities": out[:300],
                                 "countries_critical": [r for r in out if r["type"] == "country" and r["critical"] > 0][:50]})
    crit = sum(1 for r in out if r["type"] == "country" and r["critical"] > 0)
    return Result(new, f"{len(rows)} alerts, {len(out)} entities, {crit} countries with critical alerts")


# ---- Submarine cables --------------------------------------------------------
@register("cables", interval_s=7 * 24 * 60 * 60, domain="infra", description="Submarine cable geometry (TeleGeography Submarine Cable Map)")
async def collect_cables(ctx: Context) -> Result:
    geo_json = await get_json(ctx, CABLE_GEO_URL)
    feats = []
    for f in geo_json.get("features", []):
        g = f.get("geometry") or {}
        props = f.get("properties") or {}
        coords = g.get("coordinates")
        if not coords:
            continue
        # Round coordinates to reduce payload (~2 dp is plenty at world scale).
        if g.get("type") == "MultiLineString":
            coords = [[[round(x, 2), round(y, 2)] for x, y in line] for line in coords]
        elif g.get("type") == "LineString":
            coords = [[round(x, 2), round(y, 2)] for x, y in coords]
        feats.append({"type": "Feature", "geometry": {"type": g.get("type"), "coordinates": coords},
                      "properties": {"id": props.get("id"), "name": props.get("name"), "color": props.get("color")}})
    ctx.db.set_snapshot("cables", {"type": "FeatureCollection", "features": feats,
                                   "attribution": "TeleGeography Submarine Cable Map (CC BY-SA 4.0)"})
    return Result(len(feats), f"{len(feats)} cable systems")


# ---- Cloudflare Radar (optional) -----------------------------------------------
def _cf_headers() -> dict:
    return {"Authorization": f"Bearer {settings.cloudflare_token}"}


@register("cloudflare", interval_s=60 * 60, domain="infra", description="Cloudflare Radar: outage annotations, top attack origins, BGP hijacks (needs CLOUDFLARE_API_TOKEN)",
          enabled=lambda: bool(settings.cloudflare_token))
async def collect_cloudflare(ctx: Context) -> Result:
    h = _cf_headers()
    snap: dict = {"fetched_at": iso(datetime.now(timezone.utc))}
    items = []
    # Outage annotations
    r = await ctx.http.get(f"{CF}/annotations/outages", params={"dateRange": "7d", "limit": 100}, headers=h)
    r.raise_for_status()
    ann = (r.json().get("result") or {}).get("annotations") or []
    outs = []
    for a in ann:
        locs = a.get("locations") or []
        iso2 = geo.resolve(locs[0]) if locs else None
        c = geo.centroid(iso2) if iso2 else None
        outage = a.get("outage") or {}
        rec = {"id": a.get("id"), "description": a.get("description"), "start": a.get("startDate"), "end": a.get("endDate"),
               "locations": locs, "asns": a.get("asns"), "cause": outage.get("outageCause"), "type": outage.get("outageType"),
               "scope": a.get("scope"), "url": a.get("linkedUrl"), "country": iso2, "lat": c[0] if c else None, "lon": c[1] if c else None}
        outs.append(rec)
        sev = 4 if (outage.get("outageType") or "").lower() == "nationwide" else 3
        items.append({
            "id": item_id("cfoutage", a.get("id")), "source": "Cloudflare Radar", "domain": "infra", "kind": "outage",
            "title": f"Outage: {a.get('description') or 'Cloudflare Radar annotation'}"[:200],
            "url": a.get("linkedUrl") or "https://radar.cloudflare.com/outage-center",
            "summary": strip_html(f"{outage.get('outageType') or ''} outage, cause: {outage.get('outageCause') or 'unknown'}. "
                                  f"Locations: {', '.join(locs)}. Start {a.get('startDate')}, end {a.get('endDate') or 'ongoing'}.", 500),
            "published_at": parse_dt(a.get("startDate")), "country": iso2, "lat": rec["lat"], "lon": rec["lon"],
            "severity": sev, "tags": ["outage"], "extra": {"cause": outage.get("outageCause"), "type": outage.get("outageType")},
        })
    snap["outages_7d"] = outs
    # Attack origins / targets (L7 and L3), last 24h
    for layer in ("layer7", "layer3"):
        for side in ("origin", "target"):
            try:
                rr = await ctx.http.get(f"{CF}/attacks/{layer}/top/locations/{side}", params={"dateRange": "1d", "limit": 15}, headers=h)
                rr.raise_for_status()
                top = (rr.json().get("result") or {}).get("top_0") or []
                snap[f"{layer}_{side}"] = [{"country": geo.resolve(t.get(f"{side}CountryAlpha2")),
                                            "name": t.get(f"{side}CountryName"), "value": float(t.get("value") or 0)} for t in top]
            except Exception as e:  # noqa: BLE001
                snap[f"{layer}_{side}_error"] = str(e)[:120]
    # BGP hijacks
    try:
        rr = await ctx.http.get(f"{CF}/bgp/hijacks/events", params={"dateRange": "1d", "per_page": 50}, headers=h)
        rr.raise_for_status()
        ev = (rr.json().get("result") or {}).get("events") or []
        hij = []
        for e in ev:
            hij.append({"id": e.get("id"), "prefixes": e.get("prefixes"), "hijacker": e.get("hijacker_asn"),
                        "victims": e.get("victim_asns"), "confidence": e.get("confidence_score"),
                        "start": e.get("min_msg_timestamp"), "tags": [t.get("name") for t in (e.get("tags") or [])]})
            if (e.get("confidence_score") or 0) >= 8:
                items.append({
                    "id": item_id("cfbgp", e.get("id")), "source": "Cloudflare Radar", "domain": "infra", "kind": "bgp",
                    "title": f"BGP hijack: AS{e.get('hijacker_asn')} announcing {', '.join((e.get('prefixes') or [])[:3])}"[:200],
                    "url": f"https://radar.cloudflare.com/routing/anomalies/hijack/{e.get('id')}",
                    "summary": f"Confidence {e.get('confidence_score')}/10. Victim ASNs: {e.get('victim_asns')}. Tags: {[t.get('name') for t in (e.get('tags') or [])]}",
                    "published_at": parse_dt(e.get("min_msg_timestamp")), "severity": 3, "tags": ["bgp"],
                    "extra": {"hijacker": e.get("hijacker_asn"), "victims": e.get("victim_asns")},
                })
        snap["bgp_hijacks_24h"] = hij
    except Exception as e:  # noqa: BLE001
        snap["bgp_error"] = str(e)[:120]
    new = ctx.db.upsert_items(items)
    ctx.db.set_snapshot("cloudflare", snap)
    return Result(new, f"{len(outs)} outage annotations (7d), {len(snap.get('bgp_hijacks_24h', []))} hijack events (24h)")
