"""Space weather by time step: HF availability and GNSS degradation at a place and time (pure, stdlib, unit-tested).

Input is the spaceweather snapshot (NOAA SWPC: Kp, R/S/G scales now, and G plus R and S probabilities for the next
three days). A time within 6 hours of the snapshot uses the current scales; a time on one of the forecast days uses that
day's G level and, where the probability is 50% or more, R1 (minor), R3 (major) or S1; anything else is unknown.

Screening rules (notional values, not ITU or SWPC figures):
  HF: R1-R2 on the sunlit side degrade the lower HF (D-region absorption, minutes to tens of minutes); R3 and over
      black HF out on the sunlit side; S1 and over cause polar cap absorption poleward of 60 degrees (S3: blackout);
      G3 and over depress the MUF and make NVIS unreliable; any storm adds auroral absorption at night poleward of 60.
  GNSS: the J/S at which a receiver fails falls by 1, 2, 3, 5 and 8 dB for G1 to G5 (scintillation and loss of
      margin), half as much again poleward of 55 degrees, and 3 dB more in daylight during R3 and over (solar radio
      noise). Positioning error grows in storms too; that is noted, not modelled.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

G_LOSS_DB = {0: 0.0, 1: 1.0, 2: 2.0, 3: 3.0, 4: 5.0, 5: 8.0}
NOW_WINDOW_H = 6.0


def sun_elevation_deg(lat: float, lon: float, when: datetime) -> float:
    """Solar elevation (degrees), NOAA's low-precision formulae (about 0.5 degree)."""
    w = when.astimezone(timezone.utc)
    doy = w.timetuple().tm_yday
    hour = w.hour + w.minute / 60 + w.second / 3600
    g = 2 * math.pi / 365 * (doy - 1 + (hour - 12) / 24)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g)
                    - 0.040849 * math.sin(2 * g))
    tst = hour * 60 + eqt + 4 * lon
    ha = math.radians(tst / 4 - 180)
    la = math.radians(lat)
    cz = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    return math.degrees(math.asin(max(-1.0, min(1.0, cz))))


def _lvl(x) -> int | None:
    try:
        return None if x is None or x == "" else int(float(x))
    except (TypeError, ValueError):
        return None


def _parse(t) -> datetime | None:
    if not t:
        return None
    try:
        d = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def levels_at(sw: dict | None, when: datetime) -> dict:
    """G, R and S levels for a time from the snapshot: current, forecast or unknown."""
    if not sw:
        return {"source": "none", "g": None, "r": None, "s": None, "kp": None}
    sc = sw.get("scales") or {}
    ref = _parse(sw.get("fetched_at")) or _parse((sw.get("kp") or {}).get("time"))
    w = when.astimezone(timezone.utc)
    if ref and abs((w - ref).total_seconds()) <= NOW_WINDOW_H * 3600:
        now = sc.get("now") or {}
        return {"source": "now", "g": _lvl((now.get("G") or {}).get("level")), "r": _lvl((now.get("R") or {}).get("level")),
                "s": _lvl((now.get("S") or {}).get("level")), "kp": (sw.get("kp") or {}).get("value")}
    day = w.date().isoformat()
    for d in (sc.get("predicted") or {}).values():
        if str(d.get("date") or "")[:10] == day:
            pr = lambda k: _lvl(d.get(k)) or 0                                     # noqa: E731
            r = 3 if pr("R_major_prob") >= 50 else 1 if pr("R_minor_prob") >= 50 else 0
            return {"source": f"forecast {day}", "g": _lvl(d.get("G")) or 0, "r": r, "s": 1 if pr("S_prob") >= 50 else 0, "kp": None}
    return {"source": "none", "g": None, "r": None, "s": None, "kp": None}


def at_time(sw: dict | None, when: datetime, lat: float, lon: float) -> dict:
    """HF and GNSS state for a place and time."""
    lv = levels_at(sw, when)
    elev = sun_elevation_deg(lat, lon, when)
    sunlit = elev > 0
    out = {**lv, "sun_elev_deg": round(elev, 1), "sunlit": sunlit, "valid_time": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
    if lv["source"] == "none":
        out.update(hf={"status": "unknown", "notes": ["no space-weather data for this time"]},
                   gnss={"loss_db": 0.0, "notes": []}, text="Space weather: no data for this time.")
        return out
    g, r, s = lv["g"] or 0, lv["r"] or 0, lv["s"] or 0
    high = abs(lat) >= 60
    hf, rank = [], {"normal": 0, "degraded": 1, "blackout": 2}
    status = "normal"

    def bump(level, why):
        nonlocal status
        hf.append(why)
        if rank[level] > rank[status]:
            status = level
    if r >= 3 and sunlit:
        bump("blackout", f"R{r} radio blackout on the sunlit side: HF largely unusable during flares (about an hour each)")
    elif r >= 1 and sunlit:
        bump("degraded", f"R{r} on the sunlit side: lower HF absorbed for minutes to tens of minutes per flare")
    if s >= 1 and high:
        bump("blackout" if s >= 3 else "degraded", f"S{s} polar cap absorption poleward of 60 degrees")
    if g >= 3:
        bump("degraded", f"G{g} ionospheric storm: MUF may fall well below normal, NVIS unreliable")
    if g >= 1 and high and not sunlit:
        bump("degraded", f"G{g} at night poleward of 60 degrees: auroral absorption")
    loss = G_LOSS_DB.get(min(g, 5), 0.0) * (1.5 if abs(lat) >= 55 else 1.0) + (3.0 if r >= 3 and sunlit else 0.0)
    gn = []
    if g:
        gn.append(f"G{g}: receivers fail at about {G_LOSS_DB[min(g, 5)] * (1.5 if abs(lat) >= 55 else 1):g} dB less J/S (scintillation); position error grows")
    if r >= 3 and sunlit:
        gn.append(f"R{r} in daylight: solar radio noise, about 3 dB less margin")
    out.update(hf={"status": status, "notes": hf}, gnss={"loss_db": round(loss, 1), "notes": gn})
    out["text"] = (f"Space weather ({lv['source']}): G{g} R{r} S{s}; HF {status}"
                   + (f"; GNSS margin {loss:g} dB lower" if loss else "; GNSS unaffected") + ".")
    return out


def steps(sw: dict | None, t0: datetime, minutes: list[float], lat: float, lon: float) -> list[dict]:
    return [at_time(sw, t0 + timedelta(minutes=m), lat, lon) for m in minutes]
