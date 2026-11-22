"""Satcom and GNSS windows through the current EMO scenario (phase 6 part 3).

For a satcom terminal and the side's GNSS users, step through time (units move on their tracks, emitters keep their
on-air schedules) and say, at each step, whether the satellite is above the terrain horizon on the terminal's bearing,
whether opposing uplink jammers that can see the same satellite deny it, and whether each GNSS user holds its fix
against opposing jammers and spoofers (exact pairwise paths) and the space weather. Windows are the runs of steps
where the link or the fix works. Screening grade; satellite slots and jammer powers are notional.
"""
from __future__ import annotations

import asyncio
import math
from datetime import timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import satwin_core as sc

router = APIRouter(prefix="/api/emo/plan", tags=["emo-plan"])
MARGIN_DEG = 0.5            # the satellite must clear the terrain horizon by this much
MASK_KM = 20.0              # terrain horizon profile length


class WindowsIn(BaseModel):
    terminal: str | None = None                                # satcom terminal (an emitter); none: GNSS only
    sat_lon: float | None = Field(default=None, ge=-180, le=180)   # geostationary slot; blank: where the antenna points
    side: str | None = Field(default=None, pattern="^(blue|red)$")  # GNSS users of this side (default: the terminal's, else blue)
    gnss: bool = True
    step_min: float = Field(default=10, gt=0, le=120)
    horizon_min: float | None = Field(default=None, gt=0, le=1440)  # default: the scenario's track horizon (at least 60)
    max_steps: int = Field(default=25, ge=2, le=60)


def _dest(lat, lon, az_deg, d_m):
    d, b = d_m / sc.R_MEAN, math.radians(az_deg)
    la1, lo1 = math.radians(lat), math.radians(lon)
    la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(b))
    lo2 = lo1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(la1), math.cos(d) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)


async def _sky(pos, h_ant, sat_lon, k, memo):
    """Elevation, azimuth, range and the terrain horizon on that azimuth, memoised per position."""
    from . import dem
    key = (round(pos[0], 4), round(pos[1], 4), round(h_ant, 1), sat_lon)
    if key not in memo:
        el, az, rng = sc.geo_look(pos[0], pos[1], sat_lon)
        ds = [MASK_KM * 1000 * (i / 60) ** 1.5 for i in range(1, 61)]        # denser near the antenna
        pts = [tuple(pos)] + [_dest(pos[0], pos[1], az, d) for d in ds]
        hs = await asyncio.to_thread(dem.heights, pts)
        hz = sc.horizon_deg(ds, hs[1:], hs[0], h_ant, k)
        memo[key] = {"el": round(el, 2), "az": round(az, 1), "range_km": round(rng), "horizon": round(hz, 2),
                     "visible": el > hz + MARGIN_DEG}
    return memo[key]


@router.post("/windows")
async def plan_windows(body: WindowsIn, t_min: float = 0):
    from . import spacewx_core
    from .db import get_db
    from .emo_plan import _ctx
    from .ems_core import overlap
    emo_api, ents, p, pos0 = _ctx(t_min)
    byname = {e["name"]: e for e in ents.values()}
    term = None
    if body.terminal:
        term = byname.get(body.terminal)
        if not term:
            raise HTTPException(404, "terminal not found")
        if term.get("eirp_dbm") is None or term["kind"] not in ("emitter", "receiver"):
            raise HTTPException(422, "the terminal must be a transmitting emitter")
    side = body.side or (term["side"] if term and term["side"] in ("blue", "red") else "blue")
    opp = "red" if side == "blue" else "blue"
    horizon = body.horizon_min or max([emo_api.track_minutes(e) for e in ents.values()] + [60.0])
    times = [round(t_min + i * body.step_min, 1) for i in range(body.max_steps) if i * body.step_min <= horizon + 1e-6]
    k = (emo_api._atm() or {}).get("k", 4 / 3)
    forecast = getattr(p, "met", "standard") == "forecast"
    sw = get_db().get_snapshot("spaceweather")[0] if forecast else None
    t0 = emo_api._parse_time(getattr(p, "met_time", None))
    here = lambda e, t: tuple(emo_api.position_at(e, t))                           # noqa: E731
    out = {"times": times, "side": side, "step_min": body.step_min}

    # ---- satcom
    if term:
        tp = here(term, times[0])
        slot, how = body.sat_lon, "given"
        if slot is None and term.get("pattern") == "sector" and term.get("azimuth") is not None:
            slot, how = sc.slot_for_azimuth(tp[0], tp[1], term["azimuth"]), "where the antenna points"
        if slot is None:
            slot, how = round(tp[1], 2), "due south of the terminal (no pointing given)"
        tlo, thi = emo_api.band(term)
        jams = [e for e in ents.values() if e["kind"] == "effector" and e["side"] == opp and e.get("eirp_dbm") is not None
                and overlap(tlo, thi, *emo_api.band(e))]
        req = term["js_req_db"] if term.get("js_req_db") is not None else p.js_req_db
        memo, rows = {}, []
        for t in times:
            sky = await _sky(here(term, t), term["h_agl"], slot, k, memo)
            on = emo_api.on_air(term, t)
            js_list, who = [], []
            for j in jams:
                if not emo_api.on_air(j, t):
                    continue
                jsky = await _sky(here(j, t), j["h_agl"], slot, k, memo)
                if not jsky["visible"]:
                    continue                                   # the jammer cannot see the satellite
                js = sc.uplink_js_db(j["eirp_dbm"], term["eirp_dbm"], sky["range_km"], jsky["range_km"], emo_api.jam_penalty(j, term))
                js_list.append(js)
                who.append({"jammer": j["name"], "js_db": round(js, 1)})
            js = sc.power_sum_db(js_list)
            st = "off air" if not on else "blocked" if not sky["visible"] else sc.link_status(js, req)
            rows.append({"t": t, **sky, "js_db": None if js is None else round(js, 1), "jammers": who, "status": st})
        pointing = None
        if term.get("pattern") == "sector" and term.get("azimuth") is not None:
            d = abs((rows[0]["az"] - term["azimuth"] + 180) % 360 - 180)
            if d > max(2.0, (term.get("beamwidth") or 3) / 2):
                pointing = f"the antenna points {term['azimuth']:g} deg but the slot is at {rows[0]['az']:g} deg: re-point it"
        out["satcom"] = {"terminal": term["name"], "sat_lon": slot, "slot_from": how, "js_req_db": req, "rows": rows,
                         "jammers_considered": [j["name"] for j in jams], "pointing": pointing,
                         "windows": sc.spans([r["status"] in ("clear", "degraded") for r in rows], times)}

    # ---- GNSS
    if body.gnss:
        nets = [n for n in ents.values() if n["side"] == side and n.get("category") == "nav" and n.get("fixed_level_dbm") is not None]
        fx = [e for e in ents.values() if e["kind"] == "effector" and e["side"] == opp and e.get("category") == "nav"
              and e.get("eirp_dbm") is not None]
        users = []
        for nn in nets:
            req0 = nn["js_req_db"] if nn.get("js_req_db") is not None else p.js_req_db
            for v in [r for r in ents.values() if r.get("net") == nn["id"] and r["kind"] == "receiver"]:
                rows = []
                for t in times:
                    loss = spacewx_core.at_time(sw, t0 + timedelta(minutes=t), *here(v, t))["gnss"]["loss_db"] if forecast else 0.0
                    req = req0 - loss
                    noise, spoof, who = [], [], []
                    for y in fx:
                        if not emo_api.on_air(y, t):
                            continue
                        J = await emo_api.p2p_level(y, here(y, t), v, here(v, t)) - emo_api.jam_penalty(y, nn)
                        js = J - float(nn["fixed_level_dbm"])
                        (spoof if y.get("ea_mode") == "spoof" else noise).append(js)
                        who.append({"effector": y["name"], "js_db": round(js, 1), "mode": y.get("ea_mode") or "noise"})
                    nj, sj = sc.power_sum_db(noise), (max(spoof) if spoof else None)
                    rows.append({"t": t, "noise_js_db": None if nj is None else round(nj, 1), "spoof_js_db": None if sj is None else round(sj, 1),
                                 "req_db": round(req, 1), "space_db": loss, "status": sc.gnss_status(nj, sj, req),
                                 "worst": max(who, key=lambda x: x["js_db"])["effector"] if who else None})
                users.append({"user": v["name"], "net": nn["name"], "moving": bool(v.get("track")), "rows": rows,
                              "windows": sc.spans([r["status"] in ("clear", "degraded") for r in rows], times)})
        out["gnss"] = {"users": users, "effectors": [y["name"] for y in fx]}

    out["notes"] = ("Screening grade, notional data. Satcom: geostationary look angle from the terminal, terrain horizon "
                    f"from the surface model over {MASK_KM:g} km on that bearing (k {k:.2f}); the satellite must clear it by "
                    f"{MARGIN_DEG:g} deg. Uplink jamming: opposing jammers in the terminal's band that can see the same slot, "
                    "J/S at the satellite from the EIRP difference and the two slant ranges, diluted by the terminal's hopping "
                    "or spreading; the satellite's receive antenna is taken as equal towards both (no spot-beam isolation or "
                    "nulling), downlink jamming is not assessed. GNSS: each user against opposing jammers (power-summed) and "
                    "spoofers on exact terrain paths at each step, by the run's rules"
                    + (", with the space weather for each step's time." if forecast else "; space weather needs the forecast chosen.")
                    + " A window is a run of steps where the link or fix holds (clear or degraded).")
    return out
