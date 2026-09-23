"""Export the current plan (planned emitters, conflicts, links, coverage) as a Word document."""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from .db import get_db

router = APIRouter(prefix="/api/export", tags=["export"])


def _mhz(h):
    return f"{h / 1e6:.6f}".rstrip("0").rstrip(".") if h else ""


def _table(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = h
        for r in cell.paragraphs[0].runs:
            r.bold = True
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = "" if v is None else str(v)
    return t


def build_plan_docx() -> bytes:
    from docx import Document
    from docx.shared import Pt
    from .spectrum_store import run_conflicts, wtr_count
    db = get_db()
    now = datetime.now(timezone.utc).strftime("%d %b %Y %H:%MZ")
    res = run_conflicts(db, guard_hz=0, radius_km=50)
    t = res["totals"]
    links = db.query("SELECT * FROM planned_links ORDER BY name")
    sites = db.query("SELECT * FROM coverage_sites ORDER BY name")
    snap, _ = db.get_snapshot("wtr")

    doc = Document()
    st = doc.styles["Normal"]; st.font.name = "Arial"; st.font.size = Pt(10)
    doc.add_heading("CyEM Monitor: spectrum and link plan", 0)
    doc.add_paragraph(f"Produced {now} from CyEM Monitor. Open data only; screening-grade analysis.")

    doc.add_heading("Summary", 1)
    doc.add_paragraph(
        f"{t['planned']} planned emitters, {len(links)} planned links and {len(sites)} coverage sites. "
        f"Conflicts: {t['high']} high, {t['medium']} medium, {t['low']} low "
        f"({t['vs_licensed']} against Ofcom licences, {t['planned_pairs']} between planned emitters, "
        f"{t.get('harmonic', 0)} harmonic and {t.get('im3', 0)} third-order intermodulation hits). "
        + (f"Links: {sum(1 for l in links if l['last_verdict'] == 'go')} go, "
           f"{sum(1 for l in links if l['last_verdict'] == 'marginal')} marginal, "
           f"{sum(1 for l in links if l['last_verdict'] == 'no-go')} no-go." if links else ""))

    doc.add_heading("Planned emitters", 1)
    if res["planned"]:
        _table(doc, ["Name", "Freq MHz", "BW kHz", "Power W", "Position", "Window (Z)", "High/Med/Low"],
               [[p["name"], _mhz(p["freq_hz"]), f"{p['bw_hz'] / 1e3:g}", p.get("power_w") or "",
                 f"{p['lat']:.5f}, {p['lon']:.5f}", f"{p['start'] or 'open'} to {p['end'] or 'open'}",
                 "/".join(str(sum(1 for c in p["conflicts"] if c["severity"] == s)) for s in ("high", "medium", "low"))]
                for p in res["planned"]])
    else:
        doc.add_paragraph("None entered.")

    doc.add_heading("High and medium conflicts", 1)
    rows = []
    for p in res["planned"]:
        for c in p["conflicts"]:
            if c["severity"] == "low" or c.get("victim_view"):
                continue
            m = c.get("b_meta") or {}
            typ = "fundamental" if c.get("mechanism", "fundamental") == "fundamental" else (c.get("label") or c.get("mechanism"))
            against = (c["b_name"] or "Licensee withheld") + (f" ({m.get('product')}, {m.get('licence')})" if c["b_kind"] != "planned" and m.get("licence") else "")
            dist = "area licence" if c.get("dist_km") is None else f"{c['dist_km']:g}"
            rows.append([c["severity"], p["name"], typ, against, _mhz(c["b_freq_hz"]), f"{c['spacing_hz'] / 1e3:g}", dist,
                         f"{c['pred_dbm']}" if c.get("pred_dbm") is not None else ""])
    if rows:
        _table(doc, ["Severity", "Planned", "Type", "Against", "MHz", "Spacing kHz", "km", "Pred dBm"], rows)
    else:
        doc.add_paragraph("None.")

    doc.add_heading("Point-to-point links", 1)
    if links:
        _table(doc, ["Link", "Freq MHz", "Return MHz", "Distance km", "Margin dB", "Verdict", "Ends"],
               [[l["name"], _mhz(l["freq_hz"]), _mhz(l["rtn_freq_hz"]) if l["rtn_freq_hz"] else "",
                 f"{(l['last_distance_m'] or 0) / 1000:.2f}", l["last_margin_db"], l["last_verdict"],
                 f"{l['a_name'] or 'A'} {l['a_lat']:.4f},{l['a_lon']:.4f} to {l['b_name'] or 'B'} {l['b_lat']:.4f},{l['b_lon']:.4f}"]
                for l in links])
    else:
        doc.add_paragraph("None saved.")

    doc.add_heading("Coverage sites", 1)
    if sites:
        rows = []
        for s in sites:
            stt = json.loads(s["stats"] or "{}")
            patt = s["pattern"] + (f" {s['azimuth'] or 0:g} deg / {s['beamwidth'] or 65:g} deg" if s["pattern"] == "sector" else "")
            rows.append([s["name"], _mhz(s["freq_hz"]), patt, f"{s['ptx_dbm']:g} dBm", f"{s['radius_km']:g}",
                         stt.get("area_km2"), stt.get("max_range_km"), stt.get("interference_area_km2")])
        _table(doc, ["Site", "Freq MHz", "Pattern", "Tx", "Radius km", "Adequate km2", "Range km", "Above itf thr km2"], rows)
    else:
        doc.add_paragraph("None saved.")

    doc.add_heading("Sources and limits", 1)
    for line in (
        f"Licensed baseline: Ofcom Wireless Telegraphy Register, {wtr_count(db):,} assignments, source dated "
        f"{(snap or {}).get('last_modified', 'unknown')}. Licensed assignments are not measured on-air use; personal names are withheld.",
        "Terrain: Copernicus GLO-30 surface model (30 m). Propagation: free space, Deygout diffraction limited to three edges "
        "(ITU-R P.526), earth radius factor k, coarse gas model, ITU-R P.838/P.530 rain (coefficients to be verified for design use).",
        "Conflict screening: frequency overlap with guard band, distance or predicted-level filter, time windows, harmonics and "
        "third-order intermodulation. Power, filtering, receiver selectivity, clutter and multipath are not modelled.",
    ):
        doc.add_paragraph(line, style="List Bullet")
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


@router.get("/plan.docx")
async def plan_docx():
    import asyncio
    data = await asyncio.to_thread(build_plan_docx)
    name = f"CyEM-plan-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%MZ')}.docx"
    return StreamingResponse(io.BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})
