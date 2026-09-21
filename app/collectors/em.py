"""Electromagnetic collectors: NOAA SWPC space weather, HF band conditions,
GNSS interference (gpsjam.org, ADS-B derived), upcoming launches."""
from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone

import h3

from .. import geo
from ..db import iso
from .base import Context, Result, get_json, get_text, item_id, parse_dt, register

SWPC = "https://services.swpc.noaa.gov"
HAMQSL_URL = "https://www.hamqsl.com/solarxml.php"
GPSJAM_BASE = "https://gpsjam.org/data"
LL2_URL = "https://ll.thespacedevs.com/2.3.0/launches/upcoming/"


# ---- NOAA SWPC --------------------------------------------------------------
def _scale_text(code: str, level: str) -> str:
    level = str(level or "0")
    table = {
        "R": {"0": "none", "1": "minor", "2": "moderate", "3": "strong", "4": "severe", "5": "extreme"},
        "S": {"0": "none", "1": "minor", "2": "moderate", "3": "strong", "4": "severe", "5": "extreme"},
        "G": {"0": "none", "1": "minor", "2": "moderate", "3": "strong", "4": "severe", "5": "extreme"},
    }
    return table.get(code, {}).get(level, "?")


def _alert_severity(msg: str) -> int:
    m = msg.upper()
    if re.search(r"\bG5\b|\bK-INDEX OF 9\b|\bR5\b|\bS5\b", m):
        return 5
    if re.search(r"\bG4\b|\bK-INDEX OF 8\b|\bR4\b|\bS4\b", m):
        return 5
    if re.search(r"\bG3\b|\bK-INDEX OF 7\b|\bR3\b|\bS3\b|X-RAY EVENT EXCEEDED X", m):
        return 4
    if re.search(r"\bG2\b|\bK-INDEX OF 6\b|\bR2\b|\bS2\b", m):
        return 3
    if re.search(r"\bG1\b|\bK-INDEX OF 5\b|\bR1\b|\bS1\b|\bM5\b", m):
        return 2
    return 1


@register("spaceweather", interval_s=15 * 60, domain="em", description="NOAA SWPC: Kp, R/S/G scales, X-ray flares, F10.7, solar wind, alerts")
async def collect_spaceweather(ctx: Context) -> Result:
    scales, kp, flares, f107, wind, mag, alerts = await asyncio.gather(
        get_json(ctx, f"{SWPC}/products/noaa-scales.json"),
        get_json(ctx, f"{SWPC}/products/noaa-planetary-k-index.json"),
        get_json(ctx, f"{SWPC}/json/goes/primary/xray-flares-7-day.json"),
        get_json(ctx, f"{SWPC}/json/f107_cm_flux.json"),
        get_json(ctx, f"{SWPC}/products/summary/solar-wind-speed.json"),
        get_json(ctx, f"{SWPC}/products/summary/solar-wind-mag-field.json"),
        get_json(ctx, f"{SWPC}/products/alerts.json"),
        return_exceptions=True,
    )
    snap: dict = {"fetched_at": iso(datetime.now(timezone.utc)), "errors": []}

    if isinstance(scales, dict):
        now = scales.get("0", {})
        past = scales.get("-1", {})
        pred = {k: scales.get(k, {}) for k in ("1", "2", "3")}
        snap["scales"] = {
            "now": {c: {"level": now.get(c, {}).get("Scale"), "text": _scale_text(c, now.get(c, {}).get("Scale"))} for c in "RSG"},
            "past24h": {c: {"level": past.get(c, {}).get("Scale"), "text": _scale_text(c, past.get(c, {}).get("Scale"))} for c in "RSG"},
            "predicted": {
                d: {"date": pred[d].get("DateStamp"),
                    "G": pred[d].get("G", {}).get("Scale"),
                    "R_minor_prob": pred[d].get("R", {}).get("MinorProb"), "R_major_prob": pred[d].get("R", {}).get("MajorProb"),
                    "S_prob": pred[d].get("S", {}).get("Prob")} for d in pred},
            "timestamp": f"{now.get('DateStamp', '')} {now.get('TimeStamp', '')}".strip(),
        }
    else:
        snap["errors"].append(f"scales: {scales}")

    kp_rows = _kp_rows(kp)
    if kp_rows:
        latest = kp_rows[-1]
        snap["kp"] = {"value": latest["kp"], "time": latest["t"], "max_24h": max(r["kp"] for r in kp_rows[-8:]),
                      "series": kp_rows[-32:]}
    else:
        snap["errors"].append("kp unavailable")

    if isinstance(flares, list):
        recent = []
        cutoff = iso(datetime.now(timezone.utc) - timedelta(days=3))
        for f in flares:
            mc = f.get("max_class") or f.get("current_class") or ""
            begin = parse_dt(f.get("begin_time"), default_now=False)
            recent.append({"begin": begin, "max_time": f.get("max_time"), "end": f.get("end_time"),
                           "class": mc, "region": f.get("max_region") or f.get("current_region")})
        recent = [r for r in recent if r["begin"] and r["begin"] >= cutoff]
        recent.sort(key=lambda r: r["begin"], reverse=True)
        snap["flares_3d"] = recent[:30]
        snap["max_flare_24h"] = _max_class([r["class"] for r in recent if r["begin"] >= iso(datetime.now(timezone.utc) - timedelta(days=1))])
    else:
        snap["errors"].append("flares unavailable")

    if isinstance(f107, list) and f107:
        last = f107[-1]
        snap["f107"] = {"flux": float(last.get("flux", 0)), "time": last.get("time_tag")}
    w = _first(wind)
    if w:
        snap["solar_wind"] = {"speed_kms": _float(w.get("proton_speed", w.get("WindSpeed"))), "time": w.get("time_tag", w.get("TimeStamp"))}
    m = _first(mag)
    if m:
        snap.setdefault("solar_wind", {})["bt"] = _float(m.get("bt", m.get("Bt")))
        snap["solar_wind"]["bz"] = _float(m.get("bz_gsm", m.get("Bz")))

    items = []
    if isinstance(alerts, list):
        keep = []
        cutoff = iso(datetime.now(timezone.utc) - timedelta(days=3))
        for a in alerts[:80]:
            issued = parse_dt(a.get("issue_datetime"), default_now=False)
            msg = (a.get("message") or "").strip()
            if not issued or issued < cutoff or not msg:
                continue
            first = msg.splitlines()
            headline = next((l for l in first if l.upper().startswith(("ALERT", "WARNING", "WATCH", "SUMMARY", "EXTENDED", "CONTINUED"))), first[0] if first else "SWPC alert")
            keep.append({"issued": issued, "product": a.get("product_id"), "headline": headline[:160], "message": msg[:1200]})
            sev = _alert_severity(msg)
            if sev >= 2:
                items.append({
                    "id": item_id("swpc", a.get("product_id"), issued),
                    "source": "NOAA SWPC", "domain": "em", "kind": "alert",
                    "title": f"SWPC: {headline[:140]}", "url": "https://www.swpc.noaa.gov/products/alerts-watches-and-warnings",
                    "summary": re.sub(r"\s+", " ", msg)[:600], "published_at": issued, "severity": sev,
                    "tags": ["space-weather", "alert"], "extra": {"product": a.get("product_id")},
                })
        snap["alerts_3d"] = keep[:25]
    # M/X flares become items too (so they appear in the feed rail and briefs)
    for f in snap.get("flares_3d", []):
        cls = f.get("class") or ""
        if cls[:1] in ("M", "X"):
            try:
                mag_v = float(cls[1:])
            except ValueError:
                mag_v = 0
            sev = 4 if cls.startswith("X") else (3 if mag_v >= 5 else 2)
            items.append({
                "id": item_id("flare", f["begin"], cls),
                "source": "NOAA GOES", "domain": "em", "kind": "flare",
                "title": f"Solar flare {cls} (region {f.get('region') or '?'})",
                "url": "https://www.swpc.noaa.gov/products/goes-x-ray-flux",
                "summary": f"X-ray flare class {cls}, begin {f['begin']}, peak {f.get('max_time')}, end {f.get('end') or 'ongoing'}. "
                           f"M/X flares cause HF radio blackouts on the sunlit side of Earth (R1–R3+) and can degrade GNSS.",
                "published_at": f["begin"], "severity": sev, "tags": ["space-weather", "hf", "flare"],
                "extra": {"class": cls, "region": f.get("region")},
            })
    new = ctx.db.upsert_items(items)
    ctx.db.set_snapshot("spaceweather", snap)
    kpv = snap.get("kp", {}).get("value")
    return Result(new, f"Kp {kpv}, R{snap.get('scales', {}).get('now', {}).get('R', {}).get('level', '?')} "
                       f"S{snap.get('scales', {}).get('now', {}).get('S', {}).get('level', '?')} "
                       f"G{snap.get('scales', {}).get('now', {}).get('G', {}).get('level', '?')}; {new} new alerts/flares"
                       + (f"; errors: {len(snap['errors'])}" if snap["errors"] else ""))


def _first(v):
    """SWPC summary products are sometimes a one-element list, sometimes a dict."""
    if isinstance(v, list):
        return v[0] if v and isinstance(v[0], dict) else None
    return v if isinstance(v, dict) else None


def _kp_rows(kp) -> list[dict]:
    """Normalise the planetary K-index product: list of dicts, or header + list rows."""
    out: list[dict] = []
    if not isinstance(kp, list):
        return out
    for r in kp:
        try:
            if isinstance(r, dict):
                out.append({"t": r.get("time_tag"), "kp": float(r.get("Kp", r.get("kp")))})
            elif isinstance(r, (list, tuple)) and len(r) >= 2 and r[0] != "time_tag":
                out.append({"t": r[0], "kp": float(r[1])})
        except (TypeError, ValueError):
            continue
    return out


def _float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _max_class(classes: list[str]) -> str | None:
    order = {"A": 0, "B": 1, "C": 2, "M": 3, "X": 4}
    best = None
    for c in classes:
        if not c:
            continue
        key = (order.get(c[0].upper(), -1), _float(c[1:]) or 0)
        if best is None or key > best[0]:
            best = (key, c)
    return best[1] if best else None


# ---- HF band conditions (hamqsl.com) ------------------------------------------
@register("hf", interval_s=60 * 60, domain="em", description="HF band conditions and solar-terrestrial summary (hamqsl.com)")
async def collect_hf(ctx: Context) -> Result:
    text = await get_text(ctx, HAMQSL_URL)
    root = ET.fromstring(text)
    sd = root.find("solardata")
    if sd is None:
        raise RuntimeError("no solardata element")

    def g(tag: str) -> str | None:
        el = sd.find(tag)
        return el.text.strip() if el is not None and el.text else None

    bands: dict[str, dict[str, str]] = {}
    cc = sd.find("calculatedconditions")
    if cc is not None:
        for b in cc.findall("band"):
            bands.setdefault(b.get("name", "?"), {})[b.get("time", "?")] = (b.text or "").strip()
    vhf: list[dict] = []
    cv = sd.find("calculatedvhfconditions")
    if cv is not None:
        for p in cv.findall("phenomenon"):
            vhf.append({"name": p.get("name"), "location": p.get("location"), "value": (p.text or "").strip()})
    snap = {
        "updated": g("updated"), "solarflux": g("solarflux"), "aindex": g("aindex"), "kindex": g("kindex"),
        "kindexnt": g("kindexnt"), "xray": g("xray"), "sunspots": g("sunspots"), "heliumline": g("heliumline"),
        "protonflux": g("protonflux"), "electonflux": g("electonflux"), "aurora": g("aurora"),
        "normalization": g("normalization"), "latdegree": g("latdegree"), "solarwind": g("solarwind"),
        "magneticfield": g("magneticfield"), "geomagfield": g("geomagfield"), "signalnoise": g("signalnoise"),
        "fof2": g("fof2"), "muffactor": g("muffactor"), "muf": g("muf"), "bands": bands, "vhf": vhf,
        "source": "hamqsl.com (N0NBH)",
    }
    ctx.db.set_snapshot("hf", snap)
    return Result(len(bands), f"SFI {snap['solarflux']}, K {snap['kindex']}, geomag {snap['geomagfield']}")


# ---- GNSS interference (gpsjam.org) --------------------------------------------
REGIONS: list[tuple[str, float, float, float, float]] = [  # name, lat_min, lat_max, lon_min, lon_max
    ("Baltic / Kaliningrad", 53, 61, 12, 30),
    ("Nordics / High North", 61, 72, 4, 32),
    ("Ukraine / Black Sea", 43, 53, 27, 42),
    ("Russia (west)", 50, 70, 30, 60),
    ("Eastern Mediterranean / Levant", 30, 38, 28, 38),
    ("Turkey / Caucasus", 36, 44, 26, 50),
    ("Gulf / Iran / Iraq", 23, 40, 38, 64),
    ("Red Sea / Yemen / Horn", 8, 23, 32, 55),
    ("Egypt / Libya", 20, 34, 9, 36),
    ("Sahel / Sudan", 8, 22, -18, 36),
    ("Afghanistan / Pakistan", 24, 38, 60, 76),
    ("India / South Asia", 5, 36, 68, 92),
    ("Korean Peninsula", 33, 43, 124, 131),
    ("Taiwan Strait / East China Sea", 20, 33, 116, 128),
    ("South China Sea", 0, 22, 105, 122),
    ("Myanmar / SE Asia", -10, 24, 92, 110),
    ("Western Europe", 36, 60, -12, 16),
    ("Central Europe", 45, 55, 10, 25),
    ("North America", 24, 60, -130, -60),
    ("Latin America", -56, 24, -95, -33),
    ("Australasia", -48, -8, 110, 180),
    ("Africa (other)", -36, 8, -20, 52),
]


def region_of(lat: float, lon: float) -> str:
    for name, la0, la1, lo0, lo1 in REGIONS:
        if la0 <= lat <= la1 and lo0 <= lon <= lo1:
            return name
    return "Other"


@register("gpsjam", interval_s=6 * 60 * 60, domain="em", description="GNSS interference hexes derived from ADS-B (gpsjam.org, daily)")
async def collect_gpsjam(ctx: Context) -> Result:
    manifest = await get_text(ctx, f"{GPSJAM_BASE}/manifest.csv")
    lines = [l for l in manifest.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        raise RuntimeError("manifest too short")
    date = lines[-1].split(",")[0].strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise RuntimeError(f"unexpected manifest tail: {lines[-1][:60]}")
    prev, _ = ctx.db.get_snapshot("gpsjam")
    if prev and prev.get("date") == date and prev.get("hexes"):
        return Result(len(prev["hexes"]), f"unchanged ({date})")
    csv = await get_text(ctx, f"{GPSJAM_BASE}/{date}-h3_4.csv")
    rows = csv.strip().splitlines()
    header = rows[0].lower()
    if "hex" not in header:
        raise RuntimeError(f"unexpected header: {header[:60]}")
    hexes = []
    regions: Counter = Counter()
    min_aircraft = 3
    for line in rows[1:]:
        parts = line.split(",")
        if len(parts) < 3:
            continue
        cell = parts[0].strip()
        try:
            good, bad = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        total = good + bad
        if total < min_aircraft:
            continue
        pct = bad / total * 100
        if pct < 2:
            continue
        level = "high" if pct > 10 else "medium"
        if not h3.is_valid_cell(cell):
            continue
        lat, lon = h3.cell_to_latlng(cell)
        boundary = [[round(a, 3), round(b, 3)] for a, b in h3.cell_to_boundary(cell)]
        region = region_of(lat, lon)
        regions[region] += 1
        hexes.append({"h3": cell, "lat": round(lat, 3), "lon": round(lon, 3), "level": level,
                      "pct": round(pct, 1), "aircraft": total, "bad": bad, "region": region, "boundary": boundary})
    high = sum(1 for h in hexes if h["level"] == "high")
    snap = {"date": date, "fetched_at": iso(datetime.now(timezone.utc)), "hexes": hexes, "high": high,
            "medium": len(hexes) - high, "by_region": regions.most_common(),
            "attribution": "Data derived from ADS-B via gpsjam.org (John Wiseman)"}
    ctx.db.set_snapshot("gpsjam", snap)
    # One daily summary item so the feed and brief see it.
    top = ", ".join(f"{r} ({n})" for r, n in regions.most_common(5))
    ctx.db.upsert_items([{
        "id": item_id("gpsjam", date), "source": "gpsjam.org", "domain": "em", "kind": "gnss",
        "title": f"GNSS interference {date}: {high} high and {len(hexes) - high} medium hexes",
        "url": f"https://gpsjam.org/?date={date}", "published_at": parse_dt(date + "T12:00:00Z"),
        "summary": f"ADS-B derived GNSS interference for {date}. Hot regions: {top or 'none'}. "
                   f"High = more than 10% of aircraft reporting degraded navigation accuracy in the hex.",
        "severity": 3 if high >= 40 else 2, "tags": ["gnss", "ew"], "extra": {"date": date, "high": high, "regions": regions.most_common(8)},
    }])
    return Result(len(hexes), f"{date}: {high} high, {len(hexes) - high} medium")


# ---- Upcoming launches (space domain context) -----------------------------------
@register("launches", interval_s=6 * 60 * 60, domain="em", description="Upcoming orbital launches (Launch Library 2)")
async def collect_launches(ctx: Context) -> Result:
    data = await get_json(ctx, LL2_URL, params={"limit": 20, "mode": "normal", "ordering": "net"})
    out = []
    for l in data.get("results", []):
        pad = l.get("pad") or {}
        loc = pad.get("location") or {}
        out.append({
            "name": l.get("name"), "net": l.get("net"), "status": (l.get("status") or {}).get("abbrev"),
            "provider": (l.get("launch_service_provider") or {}).get("name"),
            "mission": (l.get("mission") or {}).get("name"), "mission_type": (l.get("mission") or {}).get("type"),
            "orbit": ((l.get("mission") or {}).get("orbit") or {}).get("abbrev"),
            "pad": pad.get("name"), "location": loc.get("name"), "country": geo.resolve(loc.get("country_code")),
            "lat": _float(pad.get("latitude")), "lon": _float(pad.get("longitude")),
            "url": l.get("url"),
        })
    ctx.db.set_snapshot("launches", {"launches": out})
    return Result(len(out), f"{len(out)} upcoming launches")
