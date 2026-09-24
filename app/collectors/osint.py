"""OSINT geo context via the GDELT DOC 2.0 API.

The old GEO 2.0 endpoint no longer exists, so articles are pulled per theme with
the DOC API (rate limit: one request per 5 s) and placed on the map using country
detection on the headline, falling back to the publisher's country."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone

from .. import geo
from ..db import iso
from ..tagging import enrich, strip_html
from .base import Context, Result, item_id, parse_dt, register

GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"
# Waits after a 429, in seconds.
#
# 2026-09-24, second pass: escalating 60/120/240 did NOT fix the 429s -- a run
# with three retries per theme still lost 2 of 4 themes and took 21 min instead
# of 6. GDELT's throttle here is cumulative across a run, not a short window
# you can wait out, so a long backoff buys nothing and just stretches the run.
# Kept short, and the real fix is the rotation below.
GDELT_429_BACKOFF_S = (30, 90)
# Gap between themes. Measured 2026-09-24, one run each:
#   30 s  -> lost 2-3 of 4 themes
#   60 s  -> lost 1 (satcom, last),  run 7.7 min
#   120 s -> lost 1 (infra, 3rd),    run 12.7 min
# Doubling the gap did not improve the count, it only moved which theme was
# dropped, so 60 s it is. GDELT's limit here is not something spacing solves;
# the query itself is fine (an isolated `satcom` call after a ~90 s quiet gap
# returns HTTP 200 with articles). Losing ~1 theme per run is acceptable
# because rotated_themes() guarantees it is a different theme each time.
GDELT_THEME_GAP_S = 60

THEMES: list[dict] = [
    {"key": "cyber", "label": "Cyber attacks", "tags": ["gdelt"],
     "query": '(cyberattack OR "cyber attack" OR ransomware OR "data breach" OR "state hackers") sourcelang:english'},
    {"key": "gnss", "label": "GNSS / EW interference", "tags": ["gdelt", "gnss", "ew"],
     "query": '("GPS jamming" OR "GNSS jamming" OR "GPS spoofing" OR "electronic warfare" OR "signal jamming" OR "radar jamming") sourcelang:english'},
    {"key": "infra", "label": "Connectivity disruption", "tags": ["gdelt", "outage"],
     "query": '("internet outage" OR "internet shutdown" OR "undersea cable" OR "submarine cable" OR "telecom outage") sourcelang:english'},
    {"key": "satcom", "label": "Satellite / space", "tags": ["gdelt", "space"],
     "query": '("satellite jamming" OR "anti-satellite" OR "satellite interference" OR "Starlink outage" OR "spy satellite") sourcelang:english'},
]


def _seendate(s: str | None) -> str | None:
    # GDELT format: 20260921T170000Z
    if not s or len(s) < 15:
        return None
    return parse_dt(f"{s[0:4]}-{s[4:6]}-{s[6:8]}T{s[9:11]}:{s[11:13]}:{s[13:15]}Z", default_now=False)


async def _theme(ctx: Context, theme: dict) -> tuple[dict, list[dict]]:
    params = {"query": theme["query"], "mode": "artlist", "format": "json", "timespan": "24h",
              "maxrecords": 75, "sort": "hybridrel"}
    # GDELT documents "one request per 5 s" but throttles far harder in
    # practice: with 30 s spacing and a single 45 s retry, 2-3 of the 4 themes
    # were 429-ing on EVERY run (2026-09-24 audit), so the OSINT layer had been
    # running on partial coverage indefinitely. The collector interval is 2 h,
    # so patience is nearly free — escalate the backoff instead of giving up.
    r = await ctx.http.get(GDELT_DOC, params=params, timeout=60)
    for backoff in GDELT_429_BACKOFF_S:
        if r.status_code != 429:
            break
        await asyncio.sleep(backoff)
        r = await ctx.http.get(GDELT_DOC, params=params, timeout=60)
    if r.status_code == 429:
        raise RuntimeError(
            f"GDELT rate limited (429) after {len(GDELT_429_BACKOFF_S)} retries")
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"GDELT returned non-JSON for {theme['key']}: {r.text[:100]}")
    by_country: dict[str, dict] = defaultdict(lambda: {"count": 0, "links": [], "inferred": 0})
    items: list[dict] = []
    seen_titles: set[str] = set()
    for a in data.get("articles", []):
        title = strip_html(a.get("title") or "", 220)
        url = a.get("url") or ""
        if not title or not url:
            continue
        key = title.lower()[:70]
        if key in seen_titles:
            continue
        seen_titles.add(key)
        cs = geo.detect_countries(title, limit=2)
        inferred = False
        if not cs:
            src = geo.resolve(a.get("sourcecountry"))
            if src:
                cs = [src]
                inferred = True
        for iso2 in cs[:1]:
            e = by_country[iso2]
            e["count"] += 1
            e["inferred"] += 1 if inferred else 0
            if len(e["links"]) < 6:
                e["links"].append({"url": url, "title": title, "domain": a.get("domain"), "seen": a.get("seendate")})
        if len(items) < 12:
            item = {
                "id": item_id("gdelt", url), "source": a.get("domain") or "GDELT", "domain": "osint", "kind": "gdelt",
                "title": title, "url": url, "summary": "", "published_at": _seendate(a.get("seendate")) or iso(datetime.now(timezone.utc)),
                "country": cs[0] if cs and not inferred else None,
                "extra": {"theme": theme["key"], "sourcecountry": a.get("sourcecountry"), "language": a.get("language")},
            }
            enrich(item, base_tags=list(theme["tags"]), default_severity=1)
            items.append(item)
    points = []
    for iso2, e in by_country.items():
        c = geo.centroid(iso2)
        if not c:
            continue
        points.append({"country": iso2, "name": geo.name_of(iso2), "lat": c[0], "lon": c[1], "count": e["count"],
                       "inferred": e["inferred"], "links": e["links"]})
    points.sort(key=lambda p: -p["count"])
    return {"key": theme["key"], "label": theme["label"], "points": points, "total": sum(p["count"] for p in points),
            "articles": len(data.get("articles", []))}, items


def rotated_themes(now: datetime | None = None) -> list[dict]:
    """THEMES, rotated so a different one leads each run.

    Later positions in a run are far likelier to be throttled: over the six
    runs before 2026-09-24, `satcom` -- always last -- failed 6/6, while
    `infra` failed 2/6. With a fixed order the same theme is starved forever.
    Rotating by the 2-hourly slot gives every theme the lead position once per
    8 h, so a theme missed on one run is picked up on the next.
    """
    now = now or datetime.now(timezone.utc)
    offset = (now.hour // 2) % len(THEMES)
    return THEMES[offset:] + THEMES[:offset]


@register("gdelt", interval_s=2 * 60 * 60, domain="osint", description="GDELT DOC: news for cyber, GNSS/EW, connectivity and space themes (24h), placed by headline country")
async def collect_gdelt(ctx: Context) -> Result:
    results, errors, items = [], [], []
    for i, t in enumerate(rotated_themes()):  # sequential: GDELT throttles concurrent callers hard
        if i:
            await asyncio.sleep(GDELT_THEME_GAP_S)
        try:
            res, its = await _theme(ctx, t)
            results.append(res)
            items.extend(its)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{t['key']}: {type(e).__name__}: {str(e)[:90]}")
    new = ctx.db.upsert_items(items)
    ctx.db.set_snapshot("gdelt", {"fetched_at": iso(datetime.now(timezone.utc)), "themes": results, "errors": errors})
    total = sum(r["total"] for r in results)
    msg = f"{total} located articles across {len(results)} themes; {new} new items"
    if errors:
        msg += f"; errors: {'; '.join(errors)}"
    if not results:
        raise RuntimeError(msg)
    return Result(new, msg)
