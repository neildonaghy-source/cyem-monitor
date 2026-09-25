"""UK Frequency Allocation Table (Ofcom UKFAT) as a band index, built from the PDF's
tables with pdfplumber (text extraction scrambles the layout; table extraction keeps
each row and each footnote label with its own text). Lookups return the UK table rows
for a frequency plus the text of the UK footnotes they cite. The PDF is authoritative."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import settings

UNIT = {"khz": 1e3, "mhz": 1e6, "ghz": 1e9}
_BAND = re.compile(r"^\s*([\d.]+)\s*[–-]\s*([\d.]+)\s*(khz|mhz|ghz)\s*$", re.I)       # Ofcom PDF has e.g. "108 MHZ"
_BAND_NOUNIT = re.compile(r"^\s*(\d[\d.]*)\s*[–-]\s*(\d[\d.]*)\s*$")                 # e.g. "10.45 – 10.475"
_TXTBAND = re.compile(r"^\s*(\d[\d.]*)\s*[–-]\s*(\d[\d.]*)\s*(khz|mhz|ghz)\b(.*)$", re.I)
_ABBR = re.compile(r"^([A-Z][A-Z0-9()\- ]{1,20}?)\s{1,}([A-Z][a-z].{3,90})$")
_UKFN = re.compile(r"\bUK\d+(?:\.\d+)?\b")
_CACHE: dict = {}


def path_json() -> Path:
    return settings.data_dir / "ofcom" / "ukfat.json"


def _clean(c) -> str:
    return re.sub(r"\s+", " ", (c or "").replace("\n", " ")).strip()


def parse_pdf(pdf_path: Path) -> dict:
    import pdfplumber
    abbr, entries, fns = {}, [], {}
    cur = None
    with pdfplumber.open(str(pdf_path)) as pdf:
        for n, page in enumerate(pdf.pages, start=1):
            if 8 <= n <= 12:
                for line in (page.extract_text() or "").splitlines():
                    m = _ABBR.match(line.strip())
                    if m and m.group(1).strip() not in abbr:
                        abbr[m.group(1).strip()] = m.group(2).strip()
            for tab in page.extract_tables():
                if not tab or not tab[0]:
                    continue
                head = [_clean(c).lower() for c in tab[0]]
                has_band = any(_BAND.match(_clean(r[0])) for r in tab if r and r[0])
                if head and (head[0].startswith("frequency band") or (has_band and len(tab[0]) >= 4 and not head[0].startswith("footnote"))):
                    for row in (tab[1:] if head[0].startswith("frequency band") else tab):
                        cells = [_clean(c) for c in row]
                        band = cells[0] if cells else ""
                        svc = prse = fn = rr = ""
                        for c in cells[1:]:          # classify by content: column positions vary between sections
                            if not c:
                                continue
                            if c in ("PR", "SE") and not prse:
                                prse = c
                            elif re.search(r"(UK\d|\b5\.\d)", c) and not fn:
                                fn = c
                            elif not svc and (c.split(" ")[0] in abbr or re.match(r"^[A-Z]{2,12}(\s*\(.*\))?$", c)):
                                svc = c
                            else:
                                rr = (rr + " " + c).strip()
                        m = _BAND.match(band) if band else None
                        if not m and band and cur and _BAND_NOUNIT.match(band):
                            m = _BAND.match(band + " " + cur["band"].split()[-1])
                        if m:
                            try:
                                float(m.group(1).rstrip(".")); float(m.group(2).rstrip("."))
                            except ValueError:
                                m = None          # malformed label in the PDF (e.g. "9.9.")
                        if m:
                            if cur:
                                entries.append(cur)
                            u = UNIT[m.group(3).lower()]
                            cur = {"band": band, "lo_hz": float(m.group(1).rstrip(".")) * u, "hi_hz": float(m.group(2).rstrip(".")) * u,
                                   "rows": [], "rr_region1": rr, "page": n}
                        if cur and (svc or fn):
                            cur["rows"].append({"service": svc, "status": prse, "footnotes": fn})
                            if rr and not cur["rr_region1"]:
                                cur["rr_region1"] = rr
                elif head and head[0].startswith("footnote"):
                    for row in tab[1:]:
                        row = [_clean(c) for c in row] + ["", ""]
                        if row[0].startswith("UK"):
                            fns[row[0]] = row[1][:1500]
    if cur:
        entries.append(cur)
    # Fallback: some rows never reach extract_tables(); recover them from the page text.
    covered = [(e["lo_hz"], e["hi_hz"]) for e in entries]
    with pdfplumber.open(str(pdf_path)) as pdf:
        for n, page in enumerate(pdf.pages, start=1):
            if n < 13:
                continue
            for line in (page.extract_text() or "").splitlines():
                m = _TXTBAND.match(line)
                if not m:
                    continue
                try:
                    u = UNIT[m.group(3).lower()]
                    lo, hi = float(m.group(1).rstrip(".")) * u, float(m.group(2).rstrip(".")) * u
                except (ValueError, KeyError):
                    continue
                if hi <= lo or any(a <= lo + 1 and hi <= b + 1 for a, b in covered):
                    continue
                toks = m.group(4).split()
                svc = [t for t in toks if t in abbr or re.match(r"^[A-Z]{2,6}$", t)]
                prse = next((t for t in toks if t in ("PR", "SE")), "")
                fn = " ".join(t for t in toks if re.search(r"(UK\d|\b5\.\d)", t))
                if not svc:
                    continue
                entries.append({"band": f"{m.group(1)} – {m.group(2)} {m.group(3)}", "lo_hz": lo, "hi_hz": hi, "page": n,
                                "rr_region1": "", "source": "text",
                                "rows": [{"service": svc[0], "status": prse, "footnotes": fn}] + [{"service": x, "status": "", "footnotes": ""} for x in svc[1:3]]})
                covered.append((lo, hi))
    entries.sort(key=lambda e: e["lo_hz"])
    for e in entries:
        codes = set()
        for r in e["rows"]:
            base = re.sub(r"\s*\(.*?\)", "", r["service"]).strip()
            r["service_name"] = abbr.get(r["service"]) or abbr.get(base) or ""
            codes |= set(_UKFN.findall(r["footnotes"].replace(" ", "")))
        e["uk_footnotes"] = sorted(codes)
    return {"entries": entries, "abbreviations": abbr, "uk_footnotes": fns}


def load() -> dict:
    p = path_json()
    if not p.exists():
        return {"entries": [], "abbreviations": {}, "uk_footnotes": {}}
    mt = p.stat().st_mtime
    if _CACHE.get("mt") != mt:
        _CACHE["data"] = json.loads(p.read_text())
        _CACHE["mt"] = mt
    return _CACHE["data"]


def lookup(f_hz: float, limit: int = 2) -> list[dict]:
    d = load()
    hits = sorted((e for e in d["entries"] if e["lo_hz"] <= f_hz < e["hi_hz"]), key=lambda e: e["hi_hz"] - e["lo_hz"])
    return [{**e, "footnote_text": {k: d["uk_footnotes"].get(k, "") for k in e["uk_footnotes"]}} for e in hits[:limit]]


def describe(f_hz: float) -> str:
    """Plain-text block for Ask AI context."""
    out = []
    for e in lookup(f_hz):
        out.append(f"UKFAT {e['band']} (page {e['page']}):")
        for r in e["rows"]:
            out.append(f"  - {r['service']}{' = ' + r['service_name'] if r['service_name'] else ''} | {r['status']} | footnotes {r['footnotes']}")
        for k, v in e["footnote_text"].items():
            if v:
                out.append(f"  {k}: {v[:400]}")
    return "\n".join(out)
