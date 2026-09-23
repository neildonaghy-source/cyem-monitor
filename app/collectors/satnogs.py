"""SatNOGS DB: active satellite transmitters with downlink frequencies (weekly)."""
from __future__ import annotations

from .base import Context, Result, register

URL = "https://db.satnogs.org/api/transmitters/?format=json&alive=true"
SATS = "https://db.satnogs.org/api/satellites/?format=json"


@register("satnogs", interval_s=7 * 24 * 3600, domain="em",
          description="SatNOGS DB active satellite transmitters (downlink frequencies), weekly")
async def collect_satnogs(ctx: Context) -> Result:
    r = await ctx.http.get(URL, timeout=120)
    r.raise_for_status()
    names = {}
    try:
        s = await ctx.http.get(SATS, timeout=120)
        s.raise_for_status()
        names = {x.get("sat_id"): (x.get("name"), x.get("norad_cat_id")) for x in s.json()}
    except Exception:  # noqa: BLE001 - names are a nicety
        pass
    tx = []
    for t in r.json():
        lo = t.get("downlink_low")
        if not lo or t.get("status") != "active":
            continue
        nm, norad = names.get(t.get("sat_id"), (None, None))
        tx.append({"lo": float(lo), "hi": float(t["downlink_high"]) if t.get("downlink_high") else None,
                   "mode": t.get("mode") or "", "desc": (t.get("description") or "")[:80], "service": t.get("service") or "",
                   "sat": nm or t.get("sat_id"), "norad": t.get("norad_cat_id") or norad, "type": t.get("type") or ""})
    tx.sort(key=lambda x: x["lo"])
    ctx.db.set_snapshot("satnogs", {"tx": tx, "count": len(tx), "source": "SatNOGS DB (CC BY-SA 4.0)"})
    return Result(len(tx), f"{len(tx)} active downlinks")
