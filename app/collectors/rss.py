"""RSS / Atom collector for the curated feed list, with conditional GET."""
from __future__ import annotations

import asyncio
import logging
import re

import feedparser

from ..feeds import FEEDS
from ..tagging import enrich, strip_html
from .base import Context, Result, item_id, parse_dt, register

log = logging.getLogger("cyem.rss")
_GN_SUFFIX = re.compile(r"\s+-\s+[^-]{2,60}$")  # "Title - Publisher" from Google News
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36 CyEM-Monitor/0.1"


async def _fetch_feed(ctx: Context, feed: dict, sem: asyncio.Semaphore) -> list[dict]:
    url = feed["url"]
    async with sem:
        state = ctx.db.feed_state(url) or {}
        # Several publishers (CISA, GPS World) return 403 to non-browser agents.
        headers = {"User-Agent": BROWSER_UA, "Accept": "*/*", "Accept-Language": "en-GB,en;q=0.9"}
        if state.get("etag"):
            headers["If-None-Match"] = state["etag"]
        if state.get("modified"):
            headers["If-Modified-Since"] = state["modified"]
        try:
            r = await ctx.http.get(url, headers=headers)
        except Exception as e:  # noqa: BLE001
            ctx.db.set_feed_state(url, etag=None, modified=None, ok=False, error=f"{type(e).__name__}: {e}")
            return []
        if r.status_code == 304:
            ctx.db.set_feed_state(url, etag=state.get("etag"), modified=state.get("modified"), ok=True)
            return []
        if r.status_code >= 400:
            ctx.db.set_feed_state(url, etag=None, modified=None, ok=False, error=f"HTTP {r.status_code}")
            return []
        body = r.content

    parsed = await asyncio.to_thread(feedparser.parse, body)
    if parsed.get("bozo") and not parsed.get("entries"):
        err = str(parsed.get("bozo_exception", "parse error"))[:200]
        ctx.db.set_feed_state(url, etag=None, modified=None, ok=False, error=err)
        return []
    ctx.db.set_feed_state(url, etag=r.headers.get("ETag"), modified=r.headers.get("Last-Modified"), ok=True)

    items = []
    is_gnews = "gnews" in feed.get("tags", [])
    for e in parsed.entries[:60]:
        link = e.get("link") or ""
        guid = e.get("id") or link or e.get("title", "")
        title = strip_html(e.get("title", ""), 300)
        if not title:
            continue
        publisher = None
        if is_gnews:
            src = e.get("source")
            if isinstance(src, dict):
                publisher = src.get("title")
            title = _GN_SUFFIX.sub("", title) if publisher else title
        summary = strip_html(e.get("summary") or e.get("description") or "", 700)
        if is_gnews:
            summary = ""  # Google News summaries are just link soup
        published = parse_dt(e.get("published_parsed") or e.get("updated_parsed") or e.get("published") or e.get("updated"))
        item = {
            "id": item_id("rss", url, guid),
            "source": publisher or feed["name"],
            "domain": feed["domain"],
            "kind": feed["kind"],
            "title": title,
            "url": link,
            "summary": summary,
            "published_at": published,
            "extra": {"feed": feed["name"], "publisher": publisher} if publisher else {"feed": feed["name"]},
        }
        enrich(item, base_tags=list(feed.get("tags", [])), default_severity=feed.get("severity", 2))
        items.append(item)
    return items


@register("rss", interval_s=20 * 60, domain="all", description="Curated RSS/Atom feeds (cyber, EM, infra, OSINT)")
async def collect_rss(ctx: Context) -> Result:
    sem = asyncio.Semaphore(6)
    results = await asyncio.gather(*(_fetch_feed(ctx, f, sem) for f in FEEDS), return_exceptions=True)
    items: list[dict] = []
    failed = 0
    for r in results:
        if isinstance(r, Exception):
            failed += 1
            continue
        items.extend(r)
    new = ctx.db.upsert_items(items)
    states = ctx.db.feed_states()
    broken = sum(1 for s in states if (s.get("fail_count") or 0) >= 3)
    return Result(new, f"{new} new from {len(FEEDS)} feeds; {broken} feeds failing", ok=broken <= len(FEEDS) // 2)
