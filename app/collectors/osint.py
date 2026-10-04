"""OSINT geo context via the GDELT DOC 2.0 API.

The old GEO 2.0 endpoint no longer exists, so articles are pulled per theme with
the DOC API (rate limit: one request per 5 s) and placed on the map using country
detection on the headline, falling back to the publisher's country."""
from __future__ import annotations

import asyncio
import os
import random
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .. import geo
from ..db import iso
from ..tagging import enrich, strip_html
from .base import Context, Result, item_id, parse_dt, register

GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"

# 2026-10-04: spread the themes out. Requesting all four themes back to back
# every 2 h (even with 60 s gaps and in-run 429 retries) kept tripping GDELT's
# throttle, so now each run fetches GDELT_THEMES_PER_RUN theme(s) round-robin
# (the pointer is persisted in the DB), the collector runs every 30 min (each
# theme still refreshes every 2 h), there are no in-run retries, and a theme
# that gets a 429 is put on its own cooldown (2 h, doubling, max 12 h) and
# skipped by the round-robin until it expires.
GDELT_INTERVAL_S = 30 * 60
GDELT_THEMES_PER_RUN = max(1, int(os.environ.get("GDELT_THEMES_PER_RUN", "1") or 1))
GDELT_THEME_GAP_S = (60.0, 120.0)        # jittered gap when >1 theme per run
GDELT_MIN_SPACING_S = 5.0                # GDELT guidance: <= 1 request / 5 s
GDELT_COOLDOWN_S = 2 * 60 * 60           # first 429 on a theme
GDELT_MAX_COOLDOWN_S = 12 * 60 * 60
GDELT_STATE_KEY = "gdelt_state"
GDELT_USER_AGENT = os.environ.get(
    "GDELT_USER_AGENT",
    "CyEM-Monitor/1.1 (+https://github.com/neildonaghy-source/cyem-monitor; "
    "personal self-hosted OSINT dashboard; ~2 requests/hour)")

_last_request_at = 0.0


class GdeltRateLimited(RuntimeError):
    pass


async def _respect_spacing() -> None:
    global _last_request_at
    wait = GDELT_MIN_SPACING_S - (time.monotonic() - _last_request_at)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_request_at = time.monotonic()


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
    # One request, no in-run retries: retrying inside a run only deepened the
    # throttle (2026-09-24 / 10-04). A 429 puts this theme on cooldown instead.
    await _respect_spacing()
    r = await ctx.http.get(GDELT_DOC, params=params, timeout=60,
                           headers={"User-Agent": GDELT_USER_AGENT, "Accept": "application/json"})
    if r.status_code == 429:
        raise GdeltRateLimited(f"GDELT rate limited (429) for {theme['key']}")
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


def _parse_iso(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def pick_themes(state: dict, now: datetime, n: int) -> tuple[list[dict], int]:
    """Next `n` themes round-robin from state['next'], skipping themes on
    cooldown. Returns (themes, new_next_index)."""
    count = len(THEMES)
    start = int(state.get("next", 0) or 0) % count
    per = state.get("themes") or {}
    picked, nxt = [], start
    for step in range(count):
        idx = (start + step) % count
        theme = THEMES[idx]
        until = _parse_iso((per.get(theme["key"]) or {}).get("cooldown_until"))
        nxt = (idx + 1) % count
        if until and until > now:
            continue
        picked.append(theme)
        if len(picked) >= n:
            break
    return picked, nxt


def cooldown_s(failures: int) -> int:
    return int(min(GDELT_COOLDOWN_S * 2 ** (max(1, failures) - 1), GDELT_MAX_COOLDOWN_S))


@register("gdelt", interval_s=GDELT_INTERVAL_S, domain="osint", description="GDELT DOC: news for cyber, GNSS/EW, connectivity and space themes (24h), placed by headline country; one theme per run, round-robin")
async def collect_gdelt(ctx: Context) -> Result:
    now = datetime.now(timezone.utc)
    state, _ = ctx.db.get_snapshot(GDELT_STATE_KEY)
    state = state if isinstance(state, dict) else {}
    per: dict = state.setdefault("themes", {})
    themes, state["next"] = pick_themes(state, now, GDELT_THEMES_PER_RUN)
    if not themes:
        soonest = min((_parse_iso(v.get("cooldown_until")) for v in per.values() if v.get("cooldown_until")),
                      default=None)
        ctx.db.set_snapshot(GDELT_STATE_KEY, state)
        return Result(0, f"all GDELT themes cooling down after 429s (next {iso(soonest) if soonest else '?'})")

    ok_keys, errors, items = [], [], []
    for i, t in enumerate(themes):
        if i:
            await asyncio.sleep(random.uniform(*GDELT_THEME_GAP_S))
        st = per.setdefault(t["key"], {})
        try:
            res, its = await _theme(ctx, t)
            res["fetched_at"] = iso(datetime.now(timezone.utc))
            st.update({"result": res, "failures": 0, "cooldown_until": None,
                       "last_ok": res["fetched_at"], "last_error": None})
            items.extend(its)
            ok_keys.append(f"{t['key']} {res['total']}")
        except Exception as e:  # noqa: BLE001
            msg = f"{t['key']}: {type(e).__name__}: {str(e)[:90]}"
            errors.append(msg)
            st["last_error"] = msg
            if isinstance(e, GdeltRateLimited):
                st["failures"] = int(st.get("failures", 0) or 0) + 1
                st["cooldown_until"] = iso(datetime.now(timezone.utc) + timedelta(seconds=cooldown_s(st["failures"])))
    new = ctx.db.upsert_items(items) if items else 0
    ctx.db.set_snapshot(GDELT_STATE_KEY, state)
    # Map layer / brief snapshot: the latest good result of EVERY theme, so
    # fetching one theme per run never blanks the others.
    results = [per[t["key"]]["result"] for t in THEMES if (per.get(t["key"]) or {}).get("result")]
    ctx.db.set_snapshot("gdelt", {"fetched_at": iso(now), "themes": results, "errors": errors,
                                  "next_theme": THEMES[state["next"]]["key"]})
    msg = (f"fetched {', '.join(ok_keys) or 'nothing'} (located articles); {new} new items; "
           f"next theme {THEMES[state['next']]['key']}")
    if errors:
        msg += f"; errors: {'; '.join(errors)}"
    if not ok_keys:
        # every theme tried this run failed: let the scheduler back off
        # (a 429 message gets the >= 2 h rate-limit back-off)
        raise RuntimeError(msg)
    return Result(new, msg)
