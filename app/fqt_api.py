"""Spectrum by frequency and time for one net through the current EMO scenario (phase 6 part 4).

Which channels, which hop set and which time windows keep a net usable as opposing jamming moves, and which of them
are clear of own nets, civil emitters in the scenario and Ofcom WTR licences near the net? For each time step (units
on their tracks, emitters on their schedules) the control station's level at each user and every opposing comms or
datalink jammer's level there are worked out once on exact terrain paths at the net's own frequency (path loss varies
little across one band); on each candidate channel a jammer counts only if its band overlaps the channel, diluted as in
the run (10 log of its width, or the hop set's, over the channel width, plus processing gain). The net is denied on a
channel at a step if any user's J/S reaches the net's threshold. Screening grade, notional data; WTR covers the UK only.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import fqt_core as fc
from . import satwin_core as sc

router = APIRouter(prefix="/api/emo/plan", tags=["emo-plan"])


class SpectrumIn(BaseModel):
    net: str                                                   # the net's control station
    lo_mhz: float | None = Field(default=None, gt=1, le=100_000)
    hi_mhz: float | None = Field(default=None, gt=1, le=100_000)
    step_khz: float | None = Field(default=None, gt=0, le=1_000_000)   # channel spacing (default the channel width)
    hop: bool = True                                           # also assess a hop set across the whole band
    step_min: float = Field(default=10, gt=0, le=120)
    horizon_min: float | None = Field(default=None, gt=0, le=1440)
    max_steps: int = Field(default=13, ge=1, le=40)
    wtr_km: float = Field(default=30, ge=0, le=100)            # Ofcom licences within this distance of the net


@router.post("/spectrum")
async def plan_spectrum(body: SpectrumIn, t_min: float = 0):
    from .db import get_db
    from .emo_plan import _ctx
    from .ems_core import overlap
    emo_api, ents, p, pos0 = _ctx(t_min)
    ctl = next((e for e in ents.values() if e["name"] == body.net), None)
    if not ctl:
        raise HTTPException(404, "net not found")
    users = [u for u in ents.values() if u.get("net") == ctl["id"] and u["kind"] == "receiver"]
    if not users or ctl.get("eirp_dbm") is None or ctl.get("fixed_level_dbm") is not None:
        raise HTTPException(422, "choose a net's control station: a transmitting emitter with users")
    lo, hi = (body.lo_mhz, body.hi_mhz) if body.lo_mhz and body.hi_mhz else fc.default_band(ctl["freq_mhz"])
    if hi <= lo:
        raise HTTPException(422, "band: lo must be below hi")
    side, bw = ctl["side"], ctl.get("bw_khz") or 25.0
    opp = {"red", "blue"} - {side} if side in ("red", "blue") else {"red", "blue"}
    jams = [e for e in ents.values() if e["kind"] == "effector" and e["side"] in opp and e.get("eirp_dbm") is not None
            and e.get("category") in ("comms", "datalink") and overlap(lo * 1e6, hi * 1e6, *emo_api.band(e))]
    horizon = body.horizon_min or max([emo_api.track_minutes(e) for e in ents.values()] + [60.0])
    times = [round(t_min + i * body.step_min, 1) for i in range(body.max_steps) if i * body.step_min <= horizon + 1e-6]
    req = ctl["js_req_db"] if ctl.get("js_req_db") is not None else p.js_req_db
    here = lambda e, t: tuple(emo_api.position_at(e, t))                             # noqa: E731

    # levels once per step: control station at each user, each jammer on the air at each user
    S, J = {}, {}
    for t in times:
        for u in users:
            S[t, u["id"]] = await emo_api.p2p_level(ctl, here(ctl, t), u, here(u, t))
            for y in jams:
                if emo_api.on_air(y, t):
                    J[t, y["id"], u["id"]] = await emo_api.p2p_level(y, here(y, t), u, here(u, t))

    def assess(f_mhz, hop_khz=None):
        cand = {**ctl, "freq_mhz": f_mhz, "hop_bw_khz": hop_khz}
        vlo, vhi = emo_api.victim_band(cand)
        hit = [y for y in jams if overlap(vlo, vhi, *emo_api.band(y))]
        steps, worst = [], None
        for t in times:
            per = []
            for u in users:
                js = [J[t, y["id"], u["id"]] - emo_api.jam_penalty(y, cand) for y in hit if (t, y["id"], u["id"]) in J]
                tot = sc.power_sum_db(js)
                per.append(None if tot is None else tot - S[t, u["id"]])
            st, w = fc.net_status(per, req)
            steps.append({"t": t, "status": st, "js_db": w})
            if w is not None:
                worst = w if worst is None else max(worst, w)
        ok = [s["status"] != "denied" for s in steps]
        return {"f_mhz": f_mhz, "bw_khz": bw, "hop_khz": hop_khz, "steps": steps, "usable_steps": sum(ok),
                "windows": sc.spans(ok, times), "worst_js_db": worst, "jammers": [y["name"] for y in hit]}

    # deconfliction: own nets and civil emitters in the scenario sharing the channel, Ofcom WTR licences near the net
    others = [e for e in ents.values() if e["id"] != ctl["id"] and e.get("net") != ctl["id"] and e["kind"] in ("emitter", "receiver")
              and e.get("eirp_dbm") is not None and e.get("fixed_level_dbm") is None]
    db = get_db()
    have_wtr = bool(db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='wtr'"))
    cp = here(ctl, times[0])

    def conflicts(f_mhz, width_khz):
        lo_c, hi_c = f_mhz - width_khz / 2000, f_mhz + width_khz / 2000
        mine = [e["name"] for e in others if e["side"] == side and fc.overlaps(e["freq_mhz"], e.get("bw_khz") or 25, lo_c, hi_c)]
        civ = [e["name"] for e in others if e["side"] == "grey" and fc.overlaps(e["freq_mhz"], e.get("bw_khz") or 25, lo_c, hi_c)]
        wtr = {"count": 0, "examples": [], "checked": have_wtr}
        if have_wtr and body.wtr_km:
            from .spectrum_core import bbox_for_radius
            from .spectrum_store import wtr_in_bbox
            s_, n_, w_, e_ = bbox_for_radius(cp[0], cp[1], body.wtr_km)       # (min lat, max lat, min lon, max lon)
            rows, total = wtr_in_bbox(db, s_, w_, n_, e_, fmin_hz=lo_c * 1e6, fmax_hz=hi_c * 1e6, limit=3)
            wtr = {"count": total, "examples": [{"f_mhz": round(r["freq_hz"] / 1e6, 4), "product": r.get("product"),
                                                 "company": r.get("company")} for r in rows], "checked": True}
        return {"own": mine, "civil": civ, "wtr": wtr}

    chans = []
    for f in fc.channels(lo, hi, bw, body.step_khz):
        r = assess(f)
        r["conflicts"] = conflicts(f, bw)
        chans.append(r)
    current = assess(ctl["freq_mhz"], ctl.get("hop_bw_khz"))
    current["conflicts"] = conflicts(ctl["freq_mhz"], ctl.get("hop_bw_khz") or bw)
    hopset = None
    if body.hop:
        hopset = assess(round((lo + hi) / 2, 4), round((hi - lo) * 1000, 1))
        hopset["conflicts"] = {"own": [], "civil": [], "wtr": {"count": None, "examples": [], "checked": False}}
    clean = [c for c in chans if not c["conflicts"]["own"] and not c["conflicts"]["civil"]]
    best = sorted(clean or chans, key=fc.rank_key)[:5]
    n = len(times)
    summary = (f"{body.net}: {sum(1 for c in chans if c['usable_steps'] == n)} of {len(chans)} channels in {lo:g}-{hi:g} MHz "
               f"usable throughout T+{times[0]:g} to T+{times[-1]:g}; its own channel {ctl['freq_mhz']:g} MHz"
               + (f" (hopping over {ctl['hop_bw_khz'] / 1000:g} MHz)" if ctl.get("hop_bw_khz") else "")
               + f" is usable on {current['usable_steps']} of {n} steps"
               + (f"; a hop set across the band on {hopset['usable_steps']}" if hopset else "") + ".")
    return {"net": ctl["name"], "side": side, "band": [lo, hi], "times": times, "js_req_db": req, "users": [u["name"] for u in users],
            "jammers": [y["name"] for y in jams], "channels": chans, "current": current, "hopset": hopset,
            "best": [{"f_mhz": c["f_mhz"], "usable_steps": c["usable_steps"], "worst_js_db": c["worst_js_db"], "conflicts": c["conflicts"]} for c in best],
            "summary": summary, "wtr_checked": have_wtr,
            "notes": "Screening grade, notional data. Levels on exact terrain paths at the net's own frequency at each step "
                     "(units on their tracks); a jammer counts on a channel only where its band overlaps it, diluted as in the "
                     "run (its width or the hop set's over the channel width, plus processing gain). Denied: any user's J/S "
                     f"at or over {req:g} dB. Deconfliction: own nets and civil emitters in the scenario on the channel"
                     + (f", and Ofcom WTR licences within {body.wtr_km:g} km of the net (UK only; advisory)." if have_wtr else
                        "; Ofcom WTR not loaded here.")}
