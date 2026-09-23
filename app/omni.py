"""Home-page omnibox: unified search across CyEM data, and a wider Ask AI context.

Search covers feed items (FTS), Ofcom WTR licences (by company, licence number or
frequency), planned emitters, planned links and coverage sites. Ask AI builds its
context from the same sources plus status, latest brief and the current plan, and
may add general knowledge only under a labelled heading.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from .db import Database, get_db, iso

router = APIRouter(prefix="/api", tags=["omnibox"])

_FREQ = re.compile(r"(?<![\w.])(\d{1,6}(?:\.\d{1,6})?)\s*(ghz|mhz|khz)?\b", re.I)
_UNIT = {"ghz": 1e9, "mhz": 1e6, "khz": 1e3}


def parse_freqs(q: str) -> list[float]:
    """Frequencies mentioned in free text, in Hz. A bare number is read as MHz and
    only accepted between 1 and 100000 (so years and counts are ignored)."""
    out = []
    for m in _FREQ.finditer(q):
        num, unit = float(m.group(1)), (m.group(2) or "").lower()
        if unit:
            out.append(num * _UNIT[unit])
        elif "." in m.group(1) and 1 <= num <= 100_000:
            out.append(num * 1e6)
    return out[:3]


def _win(f_hz: float) -> float:
    return max(12.5e3, f_hz * 2e-5)       # +/-12.5 kHz, or 20 ppm at microwave


def _mhz(h):
    return round(h / 1e6, 6)


# ---- place names: "near Chichester" -> lat/lon via OpenStreetMap Nominatim (cached) ----
_PLACE = re.compile(r"\b(?:near|around|at|in|by|close to)\s+([A-Z][\w'\-]+(?:\s+(?:[A-Z][\w'\-]+|upon|on|le|de))*)")
_GEO_CACHE: dict = {}
NEAR_KM = 30.0
_STOP = {"GNSS", "UK", "HF", "VHF", "UHF", "SHF", "EHF", "MHz", "GHz", "The"}


def find_place(q):
    """First place name after near/around/at/in, geocoded within Great Britain via
    Nominatim (one request per new name, cached). None if offline or not found."""
    import httpx
    for m in _PLACE.finditer(q):
        name = m.group(1).strip()
        if name.split()[0] in _STOP or len(name) < 3:
            continue
        if name not in _GEO_CACHE:
            try:
                r = httpx.get("https://nominatim.openstreetmap.org/search",
                              params={"q": name, "format": "json", "limit": 1, "countrycodes": "gb"},
                              headers={"User-Agent": "CyEM-Monitor/1.0 (personal, self-hosted)"}, timeout=8)
                j = r.json() if r.status_code == 200 else []
                _GEO_CACHE[name] = (float(j[0]["lat"]), float(j[0]["lon"]), name) if j else None
            except Exception:  # noqa: BLE001
                return None
        if _GEO_CACHE[name]:
            return _GEO_CACHE[name]
    return None


def licences_near(db, f, place, limit):
    from .spectrum_core import bbox_for_radius, haversine_km
    w = _win(f)
    if not place:
        return db.query("SELECT licence, company, product, freq_hz, bw_hz, lat, lon FROM wtr WHERE freq_hz BETWEEN ? AND ? "
                        "ORDER BY ABS(freq_hz - ?) LIMIT ?", (f - w, f + w, f, limit))
    la, lo, _ = place
    s_, n_, w_, e_ = bbox_for_radius(la, lo, NEAR_KM)
    rows = db.query("SELECT licence, company, product, freq_hz, bw_hz, lat, lon FROM wtr WHERE freq_hz BETWEEN ? AND ? "
                    "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? GROUP BY licence, freq_hz, lat, lon", (f - w, f + w, s_, n_, w_, e_))
    for r in rows:
        r["dist_km"] = round(haversine_km(la, lo, r["lat"], r["lon"]), 1)
    rows = sorted((r for r in rows if r["dist_km"] <= NEAR_KM), key=lambda r: r["dist_km"])
    return rows[:limit]


def search_all(db: Database, q: str, limit: int = 12) -> dict:
    q = q.strip()
    res: dict[str, list] = {"items": [], "licences": [], "planned": [], "links": [], "sites": []}
    if len(q) < 2:
        return res
    freqs = parse_freqs(q)
    words = re.sub(r"[^\w\s\-/.]", " ", q).strip()
    rest = _PLACE.sub(" ", q) if freqs else q
    only_freq = bool(freqs) and not re.sub(r"(\d+(\.\d+)?)|\b(ghz|mhz|khz|near|around|at|in|by|on|who|is|licensed|licences?)\b|[\s?.,]", "", rest, flags=re.I)
    try:
        for it in ([] if only_freq else db.list_items(q=q, since_hours=24 * 30, limit=limit)):
            res["items"].append({"id": it["id"], "title": it["title"], "source": it.get("source"), "domain": it.get("domain"),
                                 "url": it.get("url"), "when": it.get("published_at"), "lat": it.get("lat"), "lon": it.get("lon"),
                                 "severity": it.get("severity")})
    except Exception:  # noqa: BLE001 - FTS syntax edge cases
        pass
    try:
        if freqs:
            place = find_place(q)
            res["place"] = {"name": place[2], "lat": place[0], "lon": place[1], "radius_km": NEAR_KM} if place else None
            for f in freqs:
                for r in licences_near(db, f, place, limit * 2):
                    res["licences"].append({**r, "freq_mhz": _mhz(r["freq_hz"])})
        elif len(words) >= 3:
            like = f"%{words}%"
            for r in db.query("SELECT licence, company, product, freq_hz, bw_hz, lat, lon FROM wtr WHERE company LIKE ? OR licence = ? "
                              "GROUP BY licence, freq_hz, lat, lon LIMIT ?", (like, words, limit * 2)):
                res["licences"].append({**r, "freq_mhz": _mhz(r["freq_hz"])})
    except Exception:  # noqa: BLE001 - table may be absent on a fresh box
        pass
    like = f"%{words}%"
    for tbl, key, cols in (("planned_emitters", "planned", "id, name, freq_hz, lat, lon"),
                           ("planned_links", "links", "id, name, freq_hz, a_lat AS lat, a_lon AS lon, last_verdict"),
                           ("coverage_sites", "sites", "id, name, freq_hz, lat, lon")):
        try:
            conds, params = ["name LIKE ?"], [like]
            for f in freqs:
                conds.append("freq_hz BETWEEN ? AND ?")
                params += [f - _win(f), f + _win(f)]
            for r in db.query(f"SELECT {cols} FROM {tbl} WHERE {' OR '.join(conds)} LIMIT ?", (*params, limit)):
                res[key].append({**r, "freq_mhz": _mhz(r["freq_hz"])})
        except Exception:  # noqa: BLE001
            pass
    return res


@router.get("/search")
async def search(q: str = Query(min_length=1, max_length=200), limit: int = Query(default=12, ge=1, le=50)):
    return {"q": q, "freqs_mhz": [_mhz(f) for f in parse_freqs(q)], "results": search_all(get_db(), q, limit)}


ASK_WIDE_SYSTEM = """You are the analyst for CyEM Monitor, a self-hosted cyber and electromagnetic situational awareness tool used by a senior UK signals and spectrum practitioner. British English, plain and concise, for an expert.
Structure every answer under exactly two headings, in this order:
**From CyEM data** - only what the supplied data shows: status, latest brief, numbered items, Ofcom licence list, the user's plan. Cite numbered items as [4]. The Ofcom licence list and the plan are NOT numbered items: refer to them by name ("the Ofcom register", "your plan") and never give them a number. The Ofcom list is UK-wide unless its heading gives a place and radius; only then describe licensees as near that place, with their distances. Ofcom entries are licensed assignments, not measured activity. If the data does not answer part of the question, say so in one line.
**General knowledge (not from CyEM data)** - background from your training only where it helps. Mark uncertainty. Never present it as current events or as confirmed facts about specific organisations or states. Write "None needed." if nothing is useful.
Never invent incidents, numbers, frequencies, licensees or attributions. Under 300 words unless a list is needed."""


def plan_summary(db: Database) -> str:
    lines = []
    try:
        from .spectrum_store import run_conflicts
        res = run_conflicts(db, guard_hz=0, radius_km=50)
        t = res["totals"]
        lines.append(f"Planned emitters: {t['planned']}; conflicts: {t['high']} high, {t['medium']} medium, {t['low']} low "
                     f"({t['vs_licensed']} against licences, {t['planned_pairs']} planned pairs, {t.get('harmonic', 0)} harmonic, {t.get('im3', 0)} IM3).")
        for p in res["planned"][:15]:
            worst = next((c for c in p["conflicts"] if c["severity"] == "high"), None) or (p["conflicts"][0] if p["conflicts"] else None)
            w = f"; worst: {worst['severity']} vs {worst['b_name']} at {_mhz(worst['b_freq_hz'])} MHz" if worst else "; no conflicts"
            lines.append(f"  - {p['name']}: {_mhz(p['freq_hz'])} MHz, {p['bw_hz'] / 1e3:g} kHz, {len(p['conflicts'])} conflicts{w}")
    except Exception as e:  # noqa: BLE001
        lines.append(f"(plan summary unavailable: {type(e).__name__})")
    try:
        for r in db.query("SELECT name, freq_hz, last_verdict, last_margin_db, last_distance_m FROM planned_links ORDER BY name LIMIT 15"):
            lines.append(f"Link {r['name']}: {_mhz(r['freq_hz'])} MHz, {(r['last_distance_m'] or 0) / 1000:.1f} km, "
                         f"margin {r['last_margin_db']} dB, {r['last_verdict']}")
    except Exception:  # noqa: BLE001
        pass
    try:
        import json
        for r in db.query("SELECT name, freq_hz, pattern, stats FROM coverage_sites ORDER BY name LIMIT 15"):
            s = json.loads(r["stats"] or "{}")
            lines.append(f"Coverage site {r['name']}: {_mhz(r['freq_hz'])} MHz {r['pattern']}, adequate {s.get('area_km2')} km2 "
                         f"to {s.get('max_range_km')} km")
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(lines) or "(no plan entered)"


def build_wide_ask(db: Database, question: str) -> tuple[list[dict], dict]:
    from . import llm
    hits = []
    try:
        hits = db.list_items(q=question, since_hours=24 * 30, limit=18)
    except Exception:  # noqa: BLE001
        pass
    recent = db.list_items(since_hours=24, min_severity=3, limit=10)
    seen, items = set(), []
    for it in hits + recent:
        if it["id"] not in seen:
            seen.add(it["id"])
            items.append(it)
    body = "\n".join(llm._fmt_item(i + 1, it) for i, it in enumerate(items[:26]))
    lic_lines = []
    place = find_place(question) if parse_freqs(question) else None
    for f in parse_freqs(question):
        w = _win(f)
        if place:
            near = licences_near(db, f, place, 25)
            lic_lines.append(f"{_mhz(f)} MHz +/-{w / 1e3:g} kHz within {NEAR_KM:g} km of {place[2]}: {len(near)} licensed assignments, nearest first")
            lic_lines += [f"  - {(r['company'] or 'withheld')} | {r['product']} | {_mhz(r['freq_hz'])} MHz | {r['bw_hz'] / 1e3:g} kHz | {r['dist_km']} km"
                          for r in near]
            continue
        rows = db.query("SELECT company, product, freq_hz, bw_hz, COUNT(*) AS n FROM wtr WHERE freq_hz BETWEEN ? AND ? "
                        "GROUP BY company, product, freq_hz ORDER BY n DESC LIMIT 12", (f - w, f + w))
        total = db.one("SELECT COUNT(*) AS n FROM wtr WHERE freq_hz BETWEEN ? AND ?", (f - w, f + w))["n"]
        lic_lines.append(f"{_mhz(f)} MHz +/-{w / 1e3:g} kHz: {total} licensed assignments UK-wide, no location filter (withheld names shown as 'withheld')")
        lic_lines += [f"  - {(r['company'] or 'withheld')} | {r['product']} | {_mhz(r['freq_hz'])} MHz | {r['bw_hz'] / 1e3:g} kHz | {r['n']} sites"
                      for r in rows]
    latest = db.brief()
    brief_txt = f"LATEST BRIEF ({latest['created_at']}):\n{latest['content'][:2200]}" if latest else "LATEST BRIEF: none"
    user = (f"Current time: {iso(datetime.now(timezone.utc))}.\n\nSTATUS\n{llm.status_block(db)}\n\n{brief_txt}\n\n"
            f"USER'S PLAN\n{plan_summary(db)}\n\n"
            + ("OFCOM REGISTER, UK-WIDE, FREQUENCIES IN THE QUESTION (not a numbered item)\n" + "\n".join(lic_lines) + "\n\n" if lic_lines else "")
            + f"RELEVANT ITEMS\n{body or '(no matching items)'}\n\nQUESTION: {question}")
    meta = {"items": len(items[:26]), "freqs_mhz": [_mhz(f) for f in parse_freqs(question)],
            "place": place[2] if place else None,
            "sources": [{"n": i + 1, "title": it["title"], "url": it.get("url"), "source": it.get("source")}
                        for i, it in enumerate(items[:26])]}
    return [{"role": "system", "content": ASK_WIDE_SYSTEM}, {"role": "user", "content": user}], meta
