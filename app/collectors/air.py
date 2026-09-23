"""All aircraft on ADS-B within 250 nm of the UK (adsb.fi open data, adsb.lol fallback).

Flags aircraft reporting degraded position integrity (NIC 1 to 6), the basis
of the gpsjam method, and emergency squawks (7500 / 7600 / 7700)."""
from __future__ import annotations

from .base import Context, Result, register

CENTRE = (53.8, -2.5)
DIST_NM = 250
URLS = [f"https://opendata.adsb.fi/api/v2/lat/{CENTRE[0]}/lon/{CENTRE[1]}/dist/{DIST_NM}",
        f"https://api.adsb.lol/v2/lat/{CENTRE[0]}/lon/{CENTRE[1]}/dist/{DIST_NM}"]
EMERG = {"7500": "hijack", "7600": "radio failure", "7700": "emergency"}


@register("air", interval_s=120, domain="em",
          description="All aircraft on ADS-B within 250 nm of the UK; degraded-GNSS and emergency-squawk flags")
async def collect_air(ctx: Context) -> Result:
    last_err = None
    for url in URLS:
        try:
            r = await ctx.http.get(url, timeout=40)
            r.raise_for_status()
            j = r.json()
            src = url.split("/")[2]
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
    else:
        raise RuntimeError(f"all ADS-B sources failed: {type(last_err).__name__}")
    out, degraded, emerg = [], 0, 0
    for a in j.get("ac") or j.get("aircraft") or []:
        lat, lon = a.get("lat"), a.get("lon")
        if lat is None or lon is None:
            continue
        nic, nacp = a.get("nic"), a.get("nac_p")
        bad = nic is not None and 0 < nic < 7        # NIC 0 = not reported by older transponders
        sq = str(a.get("squawk") or "")
        em = EMERG.get(sq)
        degraded += bad
        emerg += bool(em)
        alt = a.get("alt_baro")
        out.append({"hex": a.get("hex"), "flight": (a.get("flight") or "").strip(), "reg": a.get("r"), "type": a.get("t"),
                    "lat": round(lat, 4), "lon": round(lon, 4), "alt": alt if isinstance(alt, (int, float)) else None,
                    "ground": alt == "ground", "gs": a.get("gs"), "track": a.get("track"), "squawk": sq or None,
                    "nic": nic, "nacp": nacp, "gnss_bad": bool(bad), "emerg": em, "mil": bool((a.get("dbFlags") or 0) & 1)})
    ctx.db.set_snapshot("air", {"aircraft": out, "count": len(out), "degraded": degraded, "emergency": emerg,
                                "centre": CENTRE, "dist_nm": DIST_NM, "source": src})
    return Result(len(out), f"{len(out)} aircraft, {degraded} degraded GNSS, {emerg} emergency squawks ({src})")
