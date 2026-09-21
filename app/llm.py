"""Ollama integration: scheduled / on-demand CyEM briefs and ask-the-monitor.

The model only ever sees data the collectors have already stored; prompts ask it
to cite item numbers so every claim in a brief can be traced back to a source."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import AsyncIterator

import httpx

from . import geo
from .config import settings
from .db import Database, iso

log = logging.getLogger("cyem.llm")

BRIEF_SYSTEM = """You are the analyst for CyEM Monitor, a self-hosted cyber and electromagnetic (CyEM) situational awareness tool used by a UK-based senior practitioner.
Write in British English, in plain staff-officer prose: direct, factual, no filler, no marketing tone, no emojis.
Use only the data provided below. Do not invent incidents, numbers, victims or attributions. If a section has little data, say so in one sentence rather than padding.
Cite the source items you draw on with their bracketed numbers, for example [12] or [3][7]. Every specific claim about an incident needs a citation.
Output Markdown with exactly these headings, in this order:
## BLUF
## Cyber
## Electromagnetic and space weather
## Internet infrastructure
## Watch list
## Gaps
BLUF is three to five sentences giving the overall picture and anything that needs action or attention today. The three domain sections are short paragraphs (no bullet lists). Watch list is a bullet list of at most six one-line indicators to monitor over the next 24 to 48 hours. Gaps is one or two sentences on what the data does not cover or where confidence is low. Keep the whole brief under 450 words."""

ASK_SYSTEM = """You are the analyst for CyEM Monitor, a self-hosted cyber and electromagnetic situational awareness tool used by a UK-based senior practitioner.
Answer the question using the current status and the recent items provided. Write in British English, plainly and concisely. Cite items with their bracketed numbers, for example [4]. If the provided data does not answer the question, say so clearly and do not guess. Do not invent incidents, numbers or attributions. Keep answers under 250 words unless the question needs a list."""


class BriefState:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.generating = False
        self.started_at: str | None = None
        self.last_error: str | None = None
        self.last_kind: str | None = None


state = BriefState()


# ---- Ollama HTTP -------------------------------------------------------------
async def ollama_status() -> dict:
    out = {"url": settings.ollama_url, "model": settings.ollama_model, "reachable": False, "models": [], "loaded": []}
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{settings.ollama_url}/api/tags")
            r.raise_for_status()
            out["models"] = [m.get("name") for m in r.json().get("models", [])]
            out["reachable"] = True
            try:
                p = await c.get(f"{settings.ollama_url}/api/ps")
                out["loaded"] = [{"name": m.get("name"), "size_vram": m.get("size_vram"), "until": m.get("expires_at")}
                                 for m in p.json().get("models", [])]
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    out["model_present"] = settings.ollama_model in out["models"] or any(
        m.split(":")[0] == settings.ollama_model.split(":")[0] for m in out["models"])
    return out


def _payload(messages: list[dict], stream: bool, num_predict: int, temperature: float) -> dict:
    p = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": stream,
        "options": {"num_ctx": settings.ollama_num_ctx, "temperature": temperature, "num_predict": num_predict,
                    "repeat_penalty": 1.1},
    }
    # qwen3 family: disable the hidden reasoning pass on CPU unless explicitly wanted.
    p["think"] = bool(settings.ollama_think)
    return p


async def chat(messages: list[dict], *, num_predict: int = 800, temperature: float = 0.3) -> tuple[str, dict]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.ollama_timeout, connect=10)) as c:
        r = await c.post(f"{settings.ollama_url}/api/chat", json=_payload(messages, False, num_predict, temperature))
        r.raise_for_status()
        data = r.json()
        content = (data.get("message") or {}).get("content") or ""
        meta = {k: data.get(k) for k in ("total_duration", "prompt_eval_count", "eval_count", "eval_duration", "done_reason")}
        return content.strip(), meta


async def chat_stream(messages: list[dict], *, num_predict: int = 600, temperature: float = 0.3) -> AsyncIterator[str]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.ollama_timeout, connect=10)) as c:
        async with c.stream("POST", f"{settings.ollama_url}/api/chat",
                            json=_payload(messages, True, num_predict, temperature)) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tok = (d.get("message") or {}).get("content")
                if tok:
                    yield tok
                if d.get("done"):
                    break


# ---- Context building ----------------------------------------------------------
def _fmt_item(n: int, it: dict) -> str:
    when = (it.get("published_at") or "")[:16].replace("T", " ")
    ctry = it.get("country") or "--"
    summ = (it.get("summary") or "").strip()
    if len(summ) > 170:
        summ = summ[:169].rsplit(" ", 1)[0] + "…"
    tags = ",".join(t for t in (it.get("tags") or [])[:4])
    return f"[{n}] {it['domain']}/{it['kind']} sev{it.get('severity', 2)} {ctry} {when} {it.get('source', '')}: {it['title']}" + (f" — {summ}" if summ else "") + (f" ({tags})" if tags else "")


def select_items(db: Database, hours: int = 24) -> list[dict]:
    """Balanced, severity-weighted selection of recent items for the brief."""
    quotas = {"cyber": 18, "em": 14, "infra": 8, "osint": 5}
    chosen: list[dict] = []
    seen: set[str] = set()
    for domain, n in quotas.items():
        rows = db.list_items(domain=domain, since_hours=hours, limit=400)
        if len(rows) < 6:
            rows = db.list_items(domain=domain, since_hours=hours * 3, limit=400)
        # Prefer high severity, then non-Google-News, then recency. De-duplicate near-identical titles.
        rows.sort(key=lambda r: (-int(r.get("severity") or 2), "gnews" in (r.get("tags") or []), r.get("published_at") or ""), reverse=False)
        rows.sort(key=lambda r: -int(r.get("severity") or 2))
        titles: set[str] = set()
        for r in rows:
            key = r["title"].lower()[:60]
            if key in titles or r["id"] in seen:
                continue
            titles.add(key)
            seen.add(r["id"])
            chosen.append(r)
            if sum(1 for c in chosen if c["domain"] == domain) >= n:
                break
    return chosen


def status_block(db: Database) -> str:
    lines = []
    sw, sw_t = db.get_snapshot("spaceweather")
    if sw:
        sc = (sw.get("scales") or {}).get("now", {})
        kp = sw.get("kp") or {}
        lines.append(f"Space weather (NOAA SWPC, {sw_t}): Kp {kp.get('value')} (24h max {kp.get('max_24h')}); "
                     f"scales now R{sc.get('R', {}).get('level')} S{sc.get('S', {}).get('level')} G{sc.get('G', {}).get('level')}; "
                     f"largest flare 24h: {sw.get('max_flare_24h') or 'none above C'}; F10.7 {((sw.get('f107') or {}).get('flux'))}; "
                     f"solar wind {((sw.get('solar_wind') or {}).get('speed_kms'))} km/s, Bz {((sw.get('solar_wind') or {}).get('bz'))} nT.")
        pred = ((sw.get("scales") or {}).get("predicted") or {})
        if pred:
            lines.append("Predicted G scale next 3 days: " + ", ".join(f"{v.get('date')}: G{v.get('G')}" for v in pred.values()))
    aur, _ = db.get_snapshot("aurora")
    drap, _ = db.get_snapshot("drap")
    if aur or drap:
        bits = []
        if aur:
            bits.append(f"aurora probability max N {aur.get('max_north')}% / S {aur.get('max_south')}% (OVATION forecast {aur.get('forecast_time')})")
        if drap:
            bits.append(f"D-region HF absorption up to {drap.get('max_mhz')} MHz affected across {drap.get('cells_affected')} grid cells (D-RAP {drap.get('valid_at')})")
        lines.append("Ionosphere: " + "; ".join(bits) + ".")
    hf, _ = db.get_snapshot("hf")
    if hf:
        bands = hf.get("bands") or {}
        band_txt = "; ".join(f"{b} day {v.get('day')}/night {v.get('night')}" for b, v in bands.items())
        lines.append(f"HF conditions (hamqsl): SFI {hf.get('solarflux')}, A {hf.get('aindex')}, K {hf.get('kindex')}, "
                     f"geomagnetic field {hf.get('geomagfield')}, noise {hf.get('signalnoise')}. Bands: {band_txt}.")
    gj, _ = db.get_snapshot("gpsjam")
    if gj:
        top = ", ".join(f"{r} ({n})" for r, n in (gj.get("by_region") or [])[:6])
        lines.append(f"GNSS interference (gpsjam.org, {gj.get('date')}): {gj.get('high')} high and {gj.get('medium')} medium hexes. Hot regions: {top}.")
    io, io_t = db.get_snapshot("ioda")
    if io:
        crit = io.get("countries_critical") or []
        names = ", ".join(f"{c.get('name')} ({c.get('critical')} critical)" for c in crit[:8])
        lines.append(f"Internet outages (IODA, 24h): {io.get('alerts')} alerts; countries with critical alerts: {names or 'none'}.")
    cf, _ = db.get_snapshot("cloudflare")
    if cf:
        o = cf.get("outages_7d") or []
        lines.append(f"Cloudflare Radar: {len(o)} outage annotations in 7d; {len(cf.get('bgp_hijacks_24h') or [])} BGP hijack events in 24h. "
                     f"Top L7 attack origins: " + ", ".join(f"{t.get('name')} {t.get('value'):.0f}%" for t in (cf.get('layer7_origin') or [])[:5]) + ".")
    kev, _ = db.get_snapshot("kev_stats")
    if kev:
        lines.append(f"CISA KEV: {kev.get('added_7d')} added in 7d, {kev.get('added_30d')} in 30d; top vendors 30d: "
                     + ", ".join(f"{v} ({n})" for v, n in (kev.get("top_vendors_30d") or [])[:5]) + ".")
    rw, _ = db.get_snapshot("ransomware_stats")
    if rw:
        lines.append(f"Ransomware (ransomware.live): {rw.get('victims_7d')} victims claimed in 7d, {rw.get('victims_30d')} in 30d; "
                     f"top countries 30d: " + ", ".join(f"{geo.name_of(c.get('key'))} {c.get('n')}" for c in (rw.get('by_country_30d') or [])[:6])
                     + "; top groups: " + ", ".join(f"{g} {n}" for g, n in (rw.get("top_groups_30d") or [])[:5]) + ".")
    c2, _ = db.get_snapshot("c2")
    if c2:
        lines.append(f"Botnet C2 (Feodo Tracker): {c2.get('total')} tracked servers, {len(c2.get('recent_7d') or [])} new in 7d; "
                     f"top hosting countries: " + ", ".join(f"{p.get('name')} {p.get('count')}" for p in (c2.get('countries') or [])[:5])
                     + "; families: " + ", ".join(f"{f} {n}" for f, n in (c2.get("families") or [])[:4]) + ".")
    octi, _ = db.get_snapshot("opencti")
    if octi and not octi.get("errors"):
        top = "; ".join(f"{r.get('name')}" for r in (octi.get("reports") or [])[:5])
        lines.append(f"OpenCTI ({octi.get('url')}): {octi.get('reports_24h')} reports in 24h (latest: {top}); {octi.get('indicators_24h')} new indicators "
                     f"({', '.join(f'{t} {n}' for t, n in (octi.get('indicator_types') or [])[:5])}).")
    gd, _ = db.get_snapshot("gdelt")
    if gd:
        parts = []
        for t in gd.get("themes") or []:
            top = ", ".join(p.get("name") or "?" for p in (t.get("points") or [])[:4])
            parts.append(f"{t.get('label')}: {t.get('total')} located mentions (most: {top})")
        lines.append("GDELT 24h geo mentions — " + "; ".join(parts) + ".")
    return "\n".join(lines) if lines else "No structured status available yet."


def build_brief_messages(db: Database, hours: int = 24) -> tuple[list[dict], int]:
    items = select_items(db, hours)
    now = datetime.now(timezone.utc)
    item_lines = [_fmt_item(i + 1, it) for i, it in enumerate(items)]
    body = "\n".join(item_lines)
    if len(body) > 17000:
        body = body[:17000].rsplit("\n", 1)[0]
    user = (f"Current time: {iso(now)}. Brief covers roughly the last {hours} hours.\n\n"
            f"STRUCTURED STATUS\n{status_block(db)}\n\n"
            f"SOURCE ITEMS (most significant first within each domain)\n{body}\n\n"
            f"Write the brief now.")
    return [{"role": "system", "content": BRIEF_SYSTEM}, {"role": "user", "content": user}], len(items)


async def generate_brief(db: Database, kind: str = "manual", hours: int = 24) -> dict:
    if state.generating:
        return {"ok": False, "error": "a brief is already being generated"}
    async with state.lock:
        state.generating = True
        state.started_at = iso(datetime.now(timezone.utc))
        state.last_kind = kind
        state.last_error = None
        t0 = time.time()
        try:
            messages, n_items = build_brief_messages(db, hours)
            input_chars = sum(len(m["content"]) for m in messages)
            content, meta = await chat(messages, num_predict=900, temperature=0.25)
            if not content:
                raise RuntimeError("empty response from model")
            dur = time.time() - t0
            bid = db.add_brief(kind, settings.ollama_model, content, dur, input_chars, n_items)
            log.info("brief %d generated in %.0fs (%s items, %s prompt tokens, %s output tokens)", bid, dur, n_items,
                     meta.get("prompt_eval_count"), meta.get("eval_count"))
            return {"ok": True, "id": bid, "duration_s": round(dur, 1), "meta": meta}
        except Exception as e:  # noqa: BLE001
            state.last_error = f"{type(e).__name__}: {str(e)[:300]}"
            log.warning("brief failed: %s", state.last_error)
            return {"ok": False, "error": state.last_error}
        finally:
            state.generating = False


def build_ask_messages(db: Database, question: str) -> list[dict]:
    hits = db.list_items(q=question, since_hours=24 * 14, limit=18)
    recent = db.list_items(since_hours=24, min_severity=3, limit=12)
    seen = set()
    items = []
    for it in hits + recent:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        items.append(it)
    body = "\n".join(_fmt_item(i + 1, it) for i, it in enumerate(items[:28]))
    latest = db.brief()
    brief_txt = ""
    if latest:
        brief_txt = f"\n\nLATEST BRIEF ({latest['created_at']}):\n{latest['content'][:2500]}"
    user = (f"Current time: {iso(datetime.now(timezone.utc))}.\n\nSTATUS\n{status_block(db)}{brief_txt}\n\n"
            f"RELEVANT ITEMS\n{body or '(no matching items)'}\n\nQUESTION: {question}")
    return [{"role": "system", "content": ASK_SYSTEM}, {"role": "user", "content": user}]


def brief_due(db: Database, now_local: datetime) -> str | None:
    """Return the slot key if a scheduled brief is due and not yet generated."""
    if not settings.brief_enabled or now_local.hour not in settings.brief_hours:
        return None
    slot = now_local.strftime("%Y-%m-%d") + f"T{now_local.hour:02d}"
    last, _ = db.get_snapshot("brief_last_slot")
    if last == slot:
        return None
    return slot
