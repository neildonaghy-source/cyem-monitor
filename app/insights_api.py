"""Plain-language insights from the local model (shared Ollama qwen) for the SDR and AR modes.
Facts are pre-sorted server-side so the small model narrates rather than infers."""
from __future__ import annotations

from fastapi import APIRouter, Query

from . import llm

router = APIRouter(prefix="/api/insight", tags=["insight"])

STYLE = ("British English, plain and concise, for a senior UK electromagnetic operations practitioner. Use only the facts "
         "given; quote names and numbers exactly; never move an item between the sorted lists. If something cannot be "
         "judged from the facts, say so. Do not speculate about causes (clutter, multipath, weather) not in the facts. Jamming degrades what receivers near the jammer receive; it does not stop emissions being heard. No listening to content is involved or suggested. Under 200 words.")


async def _ask(system: str, facts: str) -> str:
    out = ""
    async for tok in llm.chat_stream([{"role": "system", "content": system}, {"role": "user", "content": facts}],
                                     num_predict=450, temperature=0.1):
        out += tok
    return out.strip()


@router.get("/sdr")
async def sdr_insight(node: str):
    from .sdr_api import correlate
    c = await correlate(node)
    P = c["peaks"]
    def lines(status, fmt):
        return "; ".join(fmt(p) for p in P if p["status"] == status) or "none"
    lic = lambda p: (f"{p['f_hz']/1e6:.3f} MHz ({p['snr_db']} dB above floor): {p['licences'][0]['who']}, {p['licences'][0]['what']}, "  # noqa: E731
                     f"{p['licences'][0]['dist_km']} km at {p['licences'][0]['bearing']} deg, {p['licence_count']} candidate(s)")
    band = lambda p: f"{p['f_hz']/1e6:.3f} MHz {p['band']}" + (f" [{p['context']}]" if p.get("context") else "")  # noqa: E731
    facts = "\n".join([
        f"Receiver {node}, sweep {c['ts']}, position {'set' if c['position'] else 'NOT SET (no licence correlation possible)'}.",
        f"Counts by status: {c['counts']}. Sweep bins {c['tolerance_khz']*2:.0f} kHz wide, so licence matches are candidates.",
        "UNEXPLAINED (no nearby licence, no exempt/public band): " + lines("unexplained", lambda p: f"{p['f_hz']/1e6:.3f} MHz, {p['snr_db']} dB above floor"),
        "LICENSED MATCHES: " + lines("licensed", lic),
        "GOVERNMENT BANDS (not in public data): " + lines("government", band),
        "PUBLIC SERVICE: " + lines("public", band),
        "LICENCE-EXEMPT: " + lines("exempt", band),
        "AMATEUR (class licence): " + lines("class", band),
    ])
    system = ("You interpret a spectrum sweep correlated with public licence records. Structure: 1) one-line summary of "
              "the local spectrum picture; 2) anything unexplained and why it matters; 3) up to three next checks "
              "(e.g. a finer re-scan of a peak, sweeps from two or three more positions to compare levels, checking the "
              "time of day). " + STYLE)
    return {"text": await _ask(system, facts), "counts": c["counts"]}


@router.get("/ar")
async def ar_insight(lat: float = Query(ge=-85, le=85), lon: float = Query(ge=-180, le=180), alt: float = 0):
    from .ar_api import ar
    d = await ar(lat=lat, lon=lon, alt=alt, radius_km=30, levels=True)
    it = d["items"]
    emo = sorted([i for i in it if i["source"] == "emo" and i.get("level_dbm") is not None], key=lambda i: -i["level_dbm"])[:8]
    lic = [i for i in it if i["source"] == "licence"][:8]
    air = [i for i in it if i["source"] == "aircraft"]
    ships = [i for i in it if i["source"] == "ship"][:5]
    facts = "\n".join([
        f"Viewer at {lat:.4f}, {lon:.4f}.",
        "EMO ENTITIES BY PREDICTED LEVEL AT VIEWER (notional scenario): " + ("; ".join(
            f"{i['name']} ({i['side']} {i['kind']}, {i['freq_mhz']} MHz) {i['level_dbm']} dBm, {i['dist_km']} km at {i['bearing']:.0f} deg" for i in emo) or "none within range"),
        "NEAREST LICENSED SITES: " + ("; ".join(f"{i['name']} ({i.get('product')}, {i.get('freq_mhz')} MHz) {i['dist_km']} km at {i['bearing']:.0f} deg" for i in lic) or "none"),
        f"AIRCRAFT NEARBY: {len(air)}; with degraded GNSS: " + (", ".join(i["name"] for i in air if i.get("gnss_bad")) or "none"),
        "SHIPS NEARBY: " + ("; ".join(f"{i['name']} {i['dist_km']} km" for i in ships) or "none"),
    ])
    system = ("You brief someone standing at this spot on the electromagnetic picture around them. Structure: 1) what "
              "dominates here; 2) for EMO entities, which red emitters are strongest at this spot and what that implies "
              "(exposure to jamming, whether blue emissions here would be heard); 3) anything unusual (e.g. degraded GNSS "
              "on aircraft). " + STYLE)
    return {"text": await _ask(system, facts), "items": len(it)}
