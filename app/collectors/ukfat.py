"""Ofcom UK Frequency Allocation Table: monthly check, re-parse only when the PDF changes."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re

from ..config import settings
from ..ukfat import PARSER_VERSION, coverage_gaps, parse_pdf, path_json
from .base import Context, Result, register

# Gaps present in the published UKFAT itself (not parser faults), in kHz. Add only after reading the PDF page.
KNOWN_SOURCE_GAPS_KHZ = {(16300.0, 16360.0)}

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
    if snap and snap.get("sha") == digest and snap.get("parser") == PARSER_VERSION and path_json().exists():
        return Result(snap.get("bands", 0), f"unchanged ({snap.get('bands')} bands)")
    (d / "ukfat.pdf").write_bytes(pdf.content)
    data = await asyncio.to_thread(parse_pdf, d / "ukfat.pdf")
    if len(data["entries"]) < 300:
        raise RuntimeError(f"parse looks incomplete: {len(data['entries'])} bands")
    path_json().write_text(json.dumps(data))
    # Coverage check (8.3 kHz to 275 GHz): each gap is a band the parser dropped or misread until the PDF shows
    # otherwise. 16.30-16.36 MHz is a gap in Ofcom's own table (checked 20 Nov 2026: page 22 goes 16.2-16.3 MHz then
    # 16.36-17.41 MHz), so it is reported as a known source gap, not as a parse fault. Nothing is filled in.
    gaps = [(round(a / 1e3, 3), round(b / 1e3, 3)) for a, b in coverage_gaps(data["entries"])]
    known = [g for g in gaps if g in KNOWN_SOURCE_GAPS_KHZ]
    gaps = [g for g in gaps if g not in KNOWN_SOURCE_GAPS_KHZ]
    ctx.db.set_snapshot("ukfat", {"sha": digest, "parser": PARSER_VERSION, "url": url.split("?")[0], "bands": len(data["entries"]),
                                  "uk_footnotes": len(data["uk_footnotes"]), "gaps_khz": gaps, "known_source_gaps_khz": known})
    msg = f"{len(data['entries'])} bands, {len(data['uk_footnotes'])} UK footnotes"
    if gaps:
        msg += "; uncovered (kHz): " + ", ".join(f"{a:g}-{b:g}" for a, b in gaps[:6])
    if known:
        msg += "; gap in Ofcom's table (kHz): " + ", ".join(f"{a:g}-{b:g}" for a, b in known)
    return Result(len(data["entries"]), msg)
