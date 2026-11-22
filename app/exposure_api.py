"""Sub-surface exposure windows for one unit through the current EMO scenario (phase 6 part 2).

Where and when can a submarine raise a mast for HF, UHF or satcom, or just to look, without opposing radar or ES
catching it? Over the water within a radius of the boat (or a chosen centre), every time layer gives, per cell: the
chance an opposing radar (ship, shore or maritime patrol aircraft) tracks the raised mast, with sea clutter from the
forecast sea state; if the mast transmits, the chance opposing ES hears it (reciprocity coverage grids) and that two
or more DF sensors fix it; and the chance the link the mast is raised for works (the net's control station, less
opposing comms jamming; satcom assumed; HF from the space weather). The boat reaches only the water it can cover at
its speed by each layer. A window is a time and cell where the combined risk stays at or under the threshold for the
whole dwell and the link works; each window's best cell is re-checked with the exact pairwise model.
Screening grade with notional mast profiles (exposure_core.MASTS); no bathymetry (all water is taken as deep enough),
no acoustic or visual detection, no HF skywave interception by distant ES (flagged).
"""
from __future__ import annotations

import math

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import exposure_core as xc
from . import met_core
from .corridor_api import _dist_m, _env_factory, _ll, _pct
from .corridor_core import phi

router = APIRouter(prefix="/api/emo/plan", tags=["emo-plan"])


class ExposureIn(BaseModel):
    mover: str                                                  # entity name: the boat
    mast: str = Field(default="uhf", pattern="^(periscope|uhf|satcom|hf)$")
    dwell_min: float = Field(default=10, ge=1, le=120)         # how long the mast stays up
    radius_km: float = Field(default=15, ge=2, le=60)          # area searched round the centre
    centre_lat: float | None = Field(default=None, ge=-85, le=85)
    centre_lon: float | None = Field(default=None, ge=-180, le=180)
    speed_kmh: float = Field(default=10, gt=0, le=50)          # dived transit speed between windows
    step_min: float = Field(default=30, ge=0, le=180)          # 0: one time step
    layers: int = Field(default=6, ge=1, le=8)
    threshold: float = Field(default=0.2, ge=0.01, le=0.9)     # highest acceptable combined risk
    cell_m: float = Field(default=1000, ge=250, le=5000)
    eirp_dbm: float | None = Field(default=None, ge=-10, le=60)    # override the mast profile's EIRP (power control)


def _box(c, radius_km, cell_m):
    k = 111_195 * max(0.2, math.cos(math.radians(c[0])))
    dla, dlo = radius_km * 1000 / 111_195, radius_km * 1000 / k
    s, n, w, e = c[0] - dla, c[0] + dla, c[1] - dlo, c[1] + dlo
    cell = max(cell_m, 2 * radius_km * 1000 / 120)                # at most 120 cells a side
    H = W = max(5, int(round(2 * radius_km * 1000 / cell)))
    lats = n - (np.arange(H) + 0.5) * (n - s) / H
    lons = w + (np.arange(W) + 0.5) * (e - w) / W
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    return LA, LO, [[s, w], [n, e]], cell


@router.post("/exposure")
async def plan_exposure(body: ExposureIn, t_min: float = 0):
    from . import dem
    from .emo_plan import _ctx, _pseudo
    from .ems_core import overlay_png, region_masks, sample
    from .link_core import haversine_m
    emo_api, ents, p, pos = _ctx(t_min)
    mover = next((e for e in ents.values() if e["name"] == body.mover), None)
    if not mover:
        raise HTTPException(404, "unit not found")
    side = mover["side"]
    if side == "grey":
        raise HTTPException(422, "exposure windows are for blue or red units")
    opp = "red" if side == "blue" else "blue"
    mast = dict(xc.MASTS[body.mast])
    if body.eirp_dbm is not None and mast["eirp_dbm"] is not None:
        mast["eirp_dbm"] = body.eirp_dbm
        mast["label"] = mast["label"].split(" (")[0] + f" ({mast['freq_mhz']:g} MHz, {body.eirp_dbm:g} dBm)"
    start = tuple(pos(mover))
    centre = (body.centre_lat, body.centre_lon) if body.centre_lat is not None and body.centre_lon is not None else start
    LA, LO, bounds, cell = _box(centre, body.radius_km, body.cell_m)
    hts = dem.grid_sampler(bounds[0][0], bounds[0][1], bounds[1][0], bounds[1][1])(LA, LO).astype(float)
    sea = hts <= 0.5
    if not sea.any():
        raise HTTPException(422, "no water in the area searched")
    h = mast["h_m"]
    sig = p.sigma_db
    K = body.layers if body.step_min else 1
    times = [round(t_min + k * body.step_min, 1) for k in range(K)]
    dist0 = _dist_m(start, LA, LO)
    env_at = _env_factory(emo_api, p, "sea", h, 0.0, 0.0)
    tx = mast["eirp_dbm"] is not None
    here_base = {**mover, "h_agl": h, "rcs_m2": mast["rcs_m2"], "id": f"exp:{mover['id']}:{body.mast}",
                 "updated_at": f"{mover['updated_at']}|exp"}
    if tx:
        here_base.update(freq_mhz=mast["freq_mhz"], bw_khz=mast["bw_khz"], eirp_dbm=mast["eirp_dbm"], f_hi_mhz=None,
                         hop_bw_khz=None, pattern="omni", azimuth=None, beamwidth=None)
    mb = emo_api.band(here_base) if tx else None
    sensors = [x for x in ents.values() if x["kind"] == "sensor" and x["side"] == opp and tx and emo_api.overlap(*mb, *emo_api.band(x))]
    ctl = ents.get(mover.get("net") or "")
    c2net = ctl if (mast["link"] == "net" and ctl and ctl.get("eirp_dbm") is not None and ctl.get("fixed_level_dbm") is None) else None
    cjams = [e for e in ents.values() if e["kind"] == "effector" and e["side"] == opp and e.get("category") in ("comms", "datalink")
             and e.get("eirp_dbm") is not None and c2net and emo_api.overlap(*emo_api.victim_band(c2net), *emo_api.band(e))]
    zero = np.zeros(LA.shape)
    corners = ((0, 0), (0, -1), (-1, 0), (-1, -1))

    def far(a):
        return min(100.0, max(haversine_m(a[0], a[1], LA[i, j], LO[i, j]) for i, j in corners) / 1000 + 2)

    def reach(e, a):
        r = max(far(a), e.get("radius_km") or 0)
        return e if r <= (e.get("radius_km") or 0) else {**e, "id": f"{e['id']}:reach{int(r)}", "radius_km": min(100.0, r)}

    async def layer(tk, posk):
        env = await env_at(tk)
        ss = env["lim"]["sea_state"]
        # radar: echo margin from the one-way level (as in the run's radar picture), sea clutter at the mast's height
        tr, names, clut_max = [], [], 0.0
        for rd in [e for e in ents.values() if e.get("category") == "radar" and e["kind"] == "emitter" and e["side"] == opp
                   and emo_api.on_air(e, tk) and e.get("eirp_dbm") is not None]:
            a = posk(rd)
            one = np.nan_to_num(sample(await emo_api.coverage_for(reach(rd, a), a, h), LA, LO), nan=-999, neginf=-999)
            R = np.maximum(200.0, _dist_m(a, LA, LO))
            lam = 3e8 / (rd["freq_mhz"] * 1e6)
            fspl = 20 * np.log10(R) + 20 * math.log10(rd["freq_mhz"] * 1e6) - 147.55
            excess = np.maximum(0.0, rd["eirp_dbm"] - one - fspl)
            clutter = met_core.sea_clutter_db(ss, rd["freq_mhz"], h)
            clut_max = max(clut_max, clutter)
            echo = (rd["eirp_dbm"] + (rd.get("radar_gain_dbi") or 30.0) + 10 * math.log10(mast["rcs_m2"] * lam * lam / (4 * math.pi) ** 3)
                    - 40 * np.log10(R) - 2 * excess - clutter)
            tr.append(phi((echo - (rd.get("radar_mds_dbm") or -100.0)) / sig))
            names.append(rd["name"])
        p_rad = xc.combine(*tr) if tr else zero
        # ES on the mast's own transmission (reciprocity), DF fix from two or more bearings
        P = {}
        for x in [x for x in sensors if emo_api.on_air(x, tk)]:            # sensors keep their on-station schedules
            a = posk(x)
            if mast["freq_mhz"] < 20:                              # HF: groundwave screening rule (coverage starts at 20 MHz)
                P[x["name"]] = xc.hf_groundwave_p(_dist_m(a, LA, LO) / 1000, xc.hf_range_km(mast["eirp_dbm"]))
                continue
            cov = await emo_api.coverage_for(_pseudo(here_base, x, a, mast["eirp_dbm"], far(a)), a, h)
            lv = np.nan_to_num(sample(cov, LA, LO), nan=-999, neginf=-999)
            P[x["name"]] = phi((lv - (x.get("sens_dbm") or p.default_sens)) / sig)
        p_esm = xc.combine(*P.values()) if P else zero
        dfp = [P[x["name"]] for x in sensors if x.get("df_rms_deg") and x["name"] in P]
        if len(dfp) >= 2:
            none = np.prod([1 - v for v in dfp], axis=0)
            one_ = sum(v * np.prod([1 - w for k, w in enumerate(dfp) if k != i], axis=0) for i, v in enumerate(dfp))
            p_fix = 1 - none - one_
        else:
            p_fix = zero
        # the link the mast is raised for
        p_jam, link_what = zero, "no transmission"
        if mast["link"] == "net":
            if c2net and emo_api.on_air(ctl, tk):
                a = posk(ctl)
                lv = np.nan_to_num(sample(await emo_api.coverage_for(reach(ctl, a), a, h), LA, LO), nan=-999, neginf=-999)
                p_link = phi((lv - (mover.get("sens_dbm") or ctl.get("sens_dbm") or p.default_sens)) / sig)
                link_what = f"hears {ctl['name']}"
                on = [e for e in cjams if emo_api.on_air(e, tk)]
                if on:
                    mw = 0.0
                    for e in on:
                        b = posk(e)
                        jl = np.nan_to_num(sample(await emo_api.coverage_for(reach(e, b), b, h), LA, LO), nan=-999, neginf=-999)
                        mw = mw + 10 ** ((jl - emo_api.jam_penalty(e, ctl)) / 10)
                    jsreq = ctl["js_req_db"] if ctl.get("js_req_db") is not None else p.js_req_db
                    p_jam = phi((10 * np.log10(np.maximum(mw, 1e-30)) - lv - jsreq) / sig)
                    p_link = p_link * (1 - p_jam)
            else:
                p_link, link_what = np.ones(LA.shape), "no net control on air: link not assessed"
        elif mast["link"] == "space":
            p_link, link_what = np.ones(LA.shape), "satellite assumed in view (not modelled)"
        elif mast["link"] == "hf":
            st = env["space"]["hf"]["status"]
            p_link, link_what = np.full(LA.shape, xc.HF_LINK.get(st, 0.9)), f"HF {st} (space weather)"
        else:
            p_link = np.ones(LA.shape)
        risk = xc.combine(p_rad, p_esm)
        reach_k = xc.reach_mask(dist0, body.speed_kmh, tk - t_min, cell)
        usable = sea & reach_k & (p_link >= xc.LINK_OK)
        return {"t": tk, "risk": risk, "p_rad": p_rad, "p_esm": p_esm, "p_fix": p_fix, "p_link": p_link, "p_jam": p_jam,
                "P": P, "radars": names, "usable": usable, "reach": reach_k, "env": env, "clutter": clut_max, "link": link_what}

    posfs, L = [], []
    for k, tk in enumerate(times):
        posk = pos if k == 0 else (lambda e, tk=tk: tuple(emo_api.position_at(e, tk)))
        posfs.append(posk)
        L.append(await layer(tk, posk))
    RISK = np.stack([x["risk"] for x in L])
    USE = np.stack([x["usable"] for x in L])
    nd = xc.dwell_layers(body.dwell_min, body.step_min)
    w = xc.windows(RISK, USE, times, body.threshold, nd)
    km2 = (cell / 1000) ** 2

    def cell_info(k, c):
        x = L[k]
        P = x["P"]
        return {"at": _ll(LA, LO, c), "risk": _pct(float(x["risk"][c])), "p_radar": _pct(float(x["p_rad"][c])),
                "p_esm": _pct(float(x["p_esm"][c])), "p_fix": _pct(float(x["p_fix"][c])), "p_link": _pct(float(x["p_link"][c])),
                "p_jam": _pct(float(x["p_jam"][c])), "heard_by": sorted(P, key=lambda nm: -float(P[nm][c]))[:2] if P else [],
                "km_from_start": round(float(dist0[c]) / 1000, 1)}

    out_layers = []
    for x, lw in zip(L, w["layers"]):
        row = {"t": x["t"], "window": lw["risk"] is not None and lw["risk"] <= body.threshold,
               "safe_km2": round(lw["safe_cells"] * km2, 1), "reach_km2": round(float((x["reach"] & sea).sum()) * km2, 1),
               "sea_state": x["env"]["lim"]["sea_state"], "sea_clutter_db": x["clutter"], "hf": x["env"]["space"]["hf"]["status"],
               "radars": x["radars"], "link": x["link"], "best": None}
        if lw["cell"] is not None:
            row["best"] = {**cell_info(lw["k"], lw["cell"]), "risk_over_dwell": _pct(lw["risk"])}
        out_layers.append(row)
    out_w = []
    for wn in w["windows"]:
        k, c = wn["k_best"], wn["cell"]
        info = cell_info(k, c)
        info["verified"] = await _verify(emo_api, here_base, info["at"], sensors if tx else [], c2net, cjams, p, posfs[k], mover, times[k])
        out_w.append({"t_from": wn["t_from"], "t_to": wn["t_to"] + (body.step_min if body.step_min else 0), "t_best": times[k],
                      "risk_over_dwell": _pct(wn["risk"]), **info})
    if w["windows"]:
        kb = w["windows"][0]["k_best"]
    else:
        kb = min(range(K), key=lambda k: w["layers"][k]["risk"] if w["layers"][k]["risk"] is not None else 9.0)
    held = np.where(USE[kb:min(K, kb + nd)].all(axis=0), RISK[kb:min(K, kb + nd)].max(axis=0), np.inf)
    safe = held <= body.threshold
    band = overlay_png(region_masks(safe, (69, 211, 138, 80))) if safe.any() else None
    worst_sea = max((x["sea_state"] or 0) for x in out_layers)
    first = out_w[0] if out_w else None
    text = (f"{len(out_w)} window(s) for {mast['label']} with the mast up {body.dwell_min:g} min at {round(body.threshold * 100)}% "
            "risk or less" + (f"; first T+{first['t_from']:g}, best T+{first['t_best']:g} at {first['at'][0]:.4f}, {first['at'][1]:.4f} "
                              f"({first['risk_over_dwell']}%: radar {first['p_radar']}%, ES {first['p_esm']}%, link {first['p_link']}%)."
                              if first else ": none in the area and time searched."))
    notes = ("Screening grade. Exposure = opposing radar on the raised mast (notional cross-section, sea clutter from the "
             "forecast sea state) and, if it transmits, opposing ES; DF fix shown, not in the risk. A window needs the "
             "same cell clear for the whole dwell and the link at 50% or better; the boat reaches only the water it can "
             f"cover at {body.speed_kmh:g} km/h by each layer. Best cells re-checked with the exact pairwise model. "
             "No bathymetry (all water taken as deep enough), no acoustic, visual or wake detection. "
             + (f"HF: a groundwave screening rule (heard by opposing HF ES out to about {xc.hf_range_km(mast['eirp_dbm']):.0f} km over the sea, "
                "notional); skywave interception by distant ES is not modelled. " if body.mast == "hf" else "")
             + ("Satcom: the satellite is assumed in view and the uplink's upward beam is not modelled. " if body.mast == "satcom" else "")
             + ("Sea state and space weather from the forecast. " if getattr(p, "met", "standard") == "forecast"
                else "Sea clutter and space weather need the forecast chosen (not applied). ")
             + "Notional mast profiles (exposure_core.MASTS).")
    return {"unit": mover["name"], "side": side, "mast": body.mast, "mast_label": mast["label"], "t_min": t_min, "bounds": bounds,
            "centre": list(centre), "start": list(start), "cell_m": round(cell), "dwell_layers": nd, "layers": out_layers,
            "windows": out_w, "band": band, "band_t": times[kb], "eirp_dbm": mast["eirp_dbm"],
            "summary": {"windows": len(out_w), "text": text, "sensors": [x["name"] for x in sensors],
                        "radars": sorted({nm for x in L for nm in x["radars"]}), "c2_jammers": sorted({e["name"] for e in cjams}),
                        "max_sea_state": worst_sea or None},
            "notes": notes}


async def _verify(emo_api, here_base, at, sensors, c2net, cjams, p, pos, mover, t=0.0) -> dict:
    """Exact pairwise check at a window's best cell: detection by each opposing sensor, and the net link there
    (less opposing comms jamming)."""
    from .corridor_api import _p_jam
    pr = lambda m: int(round(50 * (1 + math.erf(m / (p.sigma_db * math.sqrt(2))))))     # noqa: E731
    here = {**here_base, "id": f"{here_base['id']}:v", "updated_at": f"{here_base['updated_at']}|v"}
    at = tuple(at)
    det = []
    for x in sensors:                                          # empty when the mast does not transmit
        if not emo_api.on_air(x, t):
            continue
        if (here_base.get("freq_mhz") or 0) < 20:                # HF: the same groundwave rule as the grid
            from .link_core import haversine_m
            det.append(int(round(100 * float(xc.hf_groundwave_p(haversine_m(*at, *pos(x)) / 1000, xc.hf_range_km(here_base.get("eirp_dbm")))))))
            continue
        det.append(pr(await emo_api.p2p_level(here, at, x, pos(x)) - (x.get("sens_dbm") or p.default_sens)))
    link = jam = None
    if c2net and c2net.get("active", True):
        S = await emo_api.p2p_level(c2net, pos(c2net), here, at)
        link = pr(S - (mover.get("sens_dbm") or c2net.get("sens_dbm") or p.default_sens))
        jam = await _p_jam(emo_api, c2net, here, at, S, [e for e in cjams if e["active"]], pos, p)
        if jam is not None:
            link = int(round(link * (1 - jam / 100)))
    return {"p_detect": max(det) if det else 0, "p_link": link, "p_jam": jam}
