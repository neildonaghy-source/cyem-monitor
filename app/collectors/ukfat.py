"""Ofcom UK Frequency Allocation Table: monthly check, re-parse only when the PDF changes."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re

from ..config import settings
from ..ukfat import parse_pdf, path_json
from .base import Context, Result, register

PAGE = "https://www.ofcom.org.uk/spectrum/frequencies/uk-fat"


@register("ukfat", interval_s=30 * 24 * 3600, domain="em",
          description="Ofcom UK Frequency Allocation Table, parsed into a band index (monthly)")
async def collect_ukfat(ctx: Context) -> Result:
    r = await ctx.http.get(PAGE, timeout=40)
    r.raise_for_status()
    m = re.search(r'href="([^"]*uk-frequency-allocation-table\.pdf[^"]*)"', r.text)
    if not m:
        raise RuntimeError("UKFAT PDF link not found on the Ofcom page")
    url = m.group(1) if m.group(1).startswith("http") else "https://www.ofcom.org.uk" + m.group(1)
    pdf = await ctx.http.get(url, timeout=120)
    pdf.raise_for_status()
    digest = hashlib.sha256(pdf.content).hexdigest()[:16]
    d = settings.data_dir / "ofcom"
    d.mkdir(parents=True, exist_ok=True)
    snap, _ = ctx.db.get_snapshot("ukfat")
    if snap and snap.get("sha") == digest and path_json().exists():
        return Result(snap.get("bands", 0), f"unchanged ({snap.get('bands')} bands)")
    (d / "ukfat.pdf").write_bytes(pdf.content)
    data = await asyncio.to_thread(parse_pdf, d / "ukfat.pdf")
    if len(data["entries"]) < 300:
        raise RuntimeError(f"parse looks incomplete: {len(data['entries'])} bands")
    path_json().write_text(json.dumps(data))
    ctx.db.set_snapshot("ukfat", {"sha": digest, "url": url.split("?")[0], "bands": len(data["entries"]),
                                  "uk_footnotes": len(data["uk_footnotes"])})
    return Result(len(data["entries"]), f"{len(data['entries'])} bands, {len(data['uk_footnotes'])} UK footnotes")
