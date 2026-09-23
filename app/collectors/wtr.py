"""Ofcom Wireless Telegraphy Register (WTR) baseline.

Source: Ofcom spectrum information portal, WTR.csv (~52 MB, ~206k rows, updated
most weekdays). Published by Ofcom under s.31 Wireless Telegraphy Act 2006 and
the Environmental Information Regulations 2004. Positions are licensed station
locations, not verified on-air use.

Conditional GET (ETag / Last-Modified) so a restart or a quiet day costs one
HEAD-sized request. Parse and load run in a worker thread on a separate SQLite
connection with a shadow-table swap (see spectrum_store.load_wtr_csv).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ..config import settings
from ..db import iso
from ..spectrum_store import ensure_schema, load_wtr_csv, wtr_count
from .base import Context, Result, register

WTR_URL = "https://static.ofcom.org.uk/static/radiolicensing/html/register/WTR.csv"
PORTAL_URL = "https://www.ofcom.org.uk/spectrum/frequencies/spectrum-information-portal"


@register("wtr", interval_s=24 * 3600, domain="em",
          description="Ofcom Wireless Telegraphy Register: UK licensed transmitter baseline for spectrum deconfliction")
async def collect_wtr(ctx: Context) -> Result:
    ensure_schema(ctx.db)
    out_dir = settings.data_dir / "ofcom"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "WTR.csv"
    have = wtr_count(ctx.db)
    headers = {}
    st = ctx.db.feed_state(WTR_URL) or {}
    if have and path.exists():
        if st.get("etag"):
            headers["If-None-Match"] = st["etag"]
        if st.get("modified"):
            headers["If-Modified-Since"] = st["modified"]
    part = path.with_suffix(".csv.part")
    async with ctx.http.stream("GET", WTR_URL, headers=headers, timeout=180) as r:
        if r.status_code == 304:
            ctx.db.set_feed_state(WTR_URL, etag=st.get("etag"), modified=st.get("modified"), ok=True)
            return Result(have, f"not modified; {have} assignments loaded")
        r.raise_for_status()
        etag, modified = r.headers.get("etag"), r.headers.get("last-modified")
        expected = int(r.headers.get("content-length") or 0)
        size = 0
        with open(part, "wb") as f:
            async for chunk in r.aiter_bytes(1 << 20):
                f.write(chunk)
                size += len(chunk)
    if expected and size != expected:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"truncated download: {size} of {expected} bytes")
    part.replace(path)
    stats = await asyncio.to_thread(load_wtr_csv, settings.db_path, path)
    ctx.db.set_feed_state(WTR_URL, etag=etag, modified=modified, ok=True)
    ctx.db.set_snapshot("wtr", {
        **stats, "source_url": WTR_URL, "portal_url": PORTAL_URL, "last_modified": modified,
        "fetched_at": iso(datetime.now(timezone.utc)), "bytes": size,
        "attribution": "Ofcom Wireless Telegraphy Register (licensed assignments; not a measure of on-air use)",
    })
    return Result(stats["rows_loaded"], f"{stats['rows_loaded']} assignments loaded "
                                        f"({stats['duplicates_dropped']} duplicates, {stats['rows_skipped']} unusable), source dated {modified}")
