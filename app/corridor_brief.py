"""Phase 7: the last planned corridor as a Word brief, and as a structured answer for Ask (no language model).

Both read the workspace's last corridor (`emo_api._LAST["corridor"]`, kept by `corridor_api.plan_corridor`): what the
planner computed, with positions as lat/lon and the legs as planned. Nothing is re-planned or invented here.
"""
from __future__ import annotations

import io
import math

CORRIDOR_WORDS = ("corridor", "route", "transit", "infiltrat", "ingress", "egress", "path to", "get to", "which way",
                  "best way")


def _ll(p) -> str:
    return f"{p[0]:.4f}, {p[1]:.4f}" if p else "-"


def _dm(p) -> str:
    """Degrees and decimal minutes, the form a map reader can plot."""
    if not p:
        return "-"
    def one(v, pos, neg):
        h = pos if v >= 0 else neg
        v = abs(v)
        return f"{int(v):d}°{(v - int(v)) * 60:05.2f}'{h}"
    return f"{one(p[0], 'N', 'S')} {one(p[1], 'E', 'W')}"


def leg_rows(res: dict) -> list[list]:
    rows = []
    for i, lg in enumerate(res.get("legs") or [], 1):
        v = lg.get("verified") or {}
        what = ("hold" if lg.get("hold") else lg.get("emcon", "")) + (f" ({lg['phase']})" if lg.get("phase") else "")
        rows.append([i, f"{lg.get('t_from', '-')}-{lg.get('t_to', '-')}", _ll(lg.get("from")), _ll(lg.get("to")), lg.get("km"),
                     lg.get("minutes"), what, f"{lg.get('p_detect')}%", f"{lg.get('p_fix')}%", f"{lg.get('p_radar')}%",
                     f"{lg.get('p_gnss', 0)}%", f"{lg.get('p_c2')}%",
                     f"{v.get('p_detect', '-')}% / {v.get('p_c2') if v.get('p_c2') is not None else '-'}%",
                     ", ".join(lg.get("heard_by") or []) or "-"])
    return rows


def summary_line(res: dict) -> str:
    s = res.get("summary") or {}
    out = (f"{res.get('unit')} ({res.get('side')}, {res.get('domain')}): {s.get('km')} km in about {s.get('minutes')} min at "
           f"{s.get('speed_kmh')} km/h (direct {s.get('direct_km')} km), arriving T+{s.get('arrive_t')}"
           + (f" with {s.get('hold_min')} min holding" if s.get("hold_min") else "")
           + f"; transmitting on {s.get('transmit_pct')}% of the route. Worst on any leg: detected {s.get('max_p_detect')}%, "
           f"fixed {s.get('max_p_fix')}%, radar {s.get('max_p_radar')}%, GNSS denied {s.get('max_p_gnss', 0)}%; C2 at least "
           f"{s.get('min_p_c2')}%.")
    if s.get("limits") and s["limits"] != "unknown":
        out += f" Platform limits: {s['limits']}" + (f" ({'; '.join(s.get('limit_reasons') or [])})" if s.get("limit_reasons") else "") + "."
    if s.get("duct"):
        out += f" Duct: {s['duct']}"
    return out


def ask_answer(c: dict) -> str:
    """The structured Ask answer for a planned corridor: summary, positions and legs, verified checks, limits."""
    res, body = c["res"], c.get("in") or {}
    s = res.get("summary") or {}
    out = [f"**Computed corridor** for {res.get('unit')} (planned from T+{c.get('t_min', 0):g}; screening model, notional data)", "",
           summary_line(res), "",
           f"**From** {_dm((res.get('legs') or [{}])[0].get('from'))} ({_ll((res.get('legs') or [{}])[0].get('from'))}) "
           f"**to** {_dm([body.get('to_lat'), body.get('to_lon')])} ({body.get('to_lat'):.4f}, {body.get('to_lon'):.4f}).", ""]
    if s.get("beach"):
        b = s["beach"]
        out.append(f"**Beach:** landing at {_ll(b.get('at'))} at T+{b.get('t')}; surf {b.get('surf')}" + (f" ({b.get('surf_reason')})" if b.get("surf_reason") else "") + ".")
        out.append("")
    out.append("**Legs**")
    for r in leg_rows(res):
        out.append(f"- Leg {r[0]}, T+{r[1]}: {r[2]} to {r[3]}, {r[4]} km, {r[5]} min, {r[6]}; detect {r[7]}, fix {r[8]}, radar {r[9]}, "
                   f"GNSS {r[10]}, C2 {r[11]}; verified detect / C2 {r[12]}" + (f"; heard by {r[13]}" if r[13] != "-" else "") + ".")
    if res.get("collateral"):
        out.append("")
        out.append("**GNSS denied by** " + "; ".join(f"{x['effector']} ({sd}, legs {', '.join(map(str, x['legs']))})"
                                                      for sd, xs in res["collateral"].items() for x in xs) + ".")
    out += ["", "_Positions are cell centres of the planning grid (" + f"{s.get('cell_m')} m" + "); verified values are the exact "
            "pairwise model at each leg's worst point. Word brief: Corridor card > Word brief._"]
    return "\n".join(out)


def context_lines(c: dict | None) -> list[str]:
    """Corridor facts for the language model's context (one line per leg)."""
    if not c:
        return []
    res = c["res"]
    out = ["CORRIDOR PLANNED: " + summary_line(res)]
    for r in leg_rows(res)[:12]:
        out.append(f"  LEG {r[0]} T+{r[1]}: {r[2]} -> {r[3]}, {r[4]} km, {r[6]}, detect {r[7]}, fix {r[8]}, radar {r[9]}, GNSS {r[10]}, C2 {r[11]}")
    return out


def schematic_png(res: dict, ents: list[dict], positions: dict) -> bytes:
    """Route legs by EMCON over the units (no basemap)."""
    from PIL import Image, ImageDraw
    (s, w), (n, e) = res["bounds"]
    W = 900
    H = max(300, int(W * (n - s) / max(e - w, 1e-6) / max(math.cos(math.radians((s + n) / 2)), 0.2)))
    img = Image.new("RGB", (W, H), (14, 20, 28))
    d = ImageDraw.Draw(img)
    xy = lambda la, lo: ((lo - w) / (e - w) * W, (n - la) / (n - s) * H)          # noqa: E731
    col = {"transmit": (243, 178, 62), "silent": (69, 211, 138)}
    for en in ents:
        la, lo = positions.get(en["id"], (en["lat"], en["lon"]))
        if not (s <= la <= n and w <= lo <= e):
            continue
        x, y = xy(la, lo)
        c = (60, 140, 255) if en["side"] == "blue" else (255, 70, 70) if en["side"] == "red" else (170, 180, 190)
        d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=c)
        d.text((x + 6, y - 6), en["name"][:22], fill=(200, 210, 220))
    for lg in res.get("legs") or []:
        pts = [xy(*p) for p in (lg.get("path") or [])]
        if lg.get("hold") and pts:
            x, y = pts[0]
            d.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(255, 255, 255), width=2)
        elif len(pts) > 1:
            d.line(pts, fill=col.get(lg.get("emcon"), (255, 255, 255)), width=5)
    legs = res.get("legs") or []
    if legs:
        for p, c in ((legs[0].get("from"), (255, 255, 255)), (legs[-1].get("to"), (60, 140, 255))):
            if p:
                x, y = xy(*p)
                d.rectangle([x - 6, y - 6, x + 6, y + 6], outline=c, width=3)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def brief_docx(c: dict, ents: list[dict], positions: dict, met_line: str, caveat: str) -> bytes:
    from datetime import datetime, timezone
    from docx import Document
    from docx.shared import Cm, Pt
    res, body = c["res"], c.get("in") or {}
    s = res.get("summary") or {}
    doc = Document()
    st = doc.styles["Normal"]; st.font.name = "Arial"; st.font.size = Pt(10)                  # noqa: E702
    doc.add_heading(f"CyEM corridor brief: {res.get('unit')} (notional scenario)", 0)
    doc.add_paragraph(f"Produced {datetime.now(timezone.utc):%d %b %Y %H:%MZ}. Screening grade on notional data. {caveat}")

    def table(head, rows):
        tb = doc.add_table(rows=1, cols=len(head)); tb.style = "Light Grid Accent 1"         # noqa: E702
        for i, h in enumerate(head):
            tb.rows[0].cells[i].text = h
        for r in rows:
            cs = tb.add_row().cells
            for i, v in enumerate(r):
                cs[i].text = str(v)
    legs = res.get("legs") or []
    doc.add_heading("Task", 1)
    table(["Item", "Value"], [
        ["Unit", f"{res.get('unit')} ({res.get('side')})"], ["Domain", res.get("domain")],
        ["From", f"{_dm(legs[0].get('from')) if legs else '-'} ({_ll(legs[0].get('from')) if legs else '-'})"],
        ["To", f"{_dm([body.get('to_lat'), body.get('to_lon')])} ({body.get('to_lat'):.4f}, {body.get('to_lon'):.4f})"],
        ["Start", f"T+{c.get('t_min', 0):g}"], ["Speed", f"{s.get('speed_kmh')} km/h" + (f" (nominal {s.get('nominal_speed_kmh')})" if s.get("nominal_speed_kmh") and s.get("nominal_speed_kmh") != s.get("speed_kmh") else "")],
        ["EMCON", body.get("emcon", "auto")], ["Time layers", f"{s.get('layers')} at {s.get('step_min')} min" if s.get("layers", 1) > 1 else "one (others frozen)"]])
    doc.add_heading("Summary", 1)
    doc.add_paragraph(summary_line(res))
    doc.add_paragraph(met_line)
    if s.get("space"):
        doc.add_paragraph(s["space"])
    if s.get("limits_warning"):
        doc.add_paragraph(s["limits_warning"])
    if s.get("beach"):
        b = s["beach"]
        doc.add_heading("Beach", 2)
        doc.add_paragraph(f"Landing at {_dm(b.get('at'))} ({_ll(b.get('at'))}) at T+{b.get('t')}; surf {b.get('surf')}"
                          + (f" ({b.get('surf_reason')})" if b.get("surf_reason") else "") + ".")
    if res.get("collateral"):
        doc.add_heading("GNSS jammers that deny the route", 2)
        table(["Effector", "Side", "Legs"], [[x["effector"], sd, ", ".join(map(str, x["legs"]))] for sd, xs in res["collateral"].items() for x in xs])
    doc.add_heading("Route", 1)
    doc.add_picture(io.BytesIO(schematic_png(res, ents, positions)), width=Cm(16))
    doc.add_paragraph("Schematic, no basemap. Amber: transmit legs; green: silent legs; white circles: holds; white square: start; "
                      "blue square: destination; dots: units at the planning time (blue, red, grey).").runs[0].italic = True
    doc.add_heading("Legs", 1)
    table(["Leg", "T+", "From", "To", "km", "min", "EMCON", "Detect", "Fix", "Radar", "GNSS", "C2", "Verified det / C2", "Heard by"], leg_rows(res))
    doc.add_paragraph(res.get("notes") or "").runs[0].italic = True
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
