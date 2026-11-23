"""EM manoeuvre corridor for one unit through the current EMO scenario (phase 5: one time step, or time layers).

The unit moves from where it is at T+t to a chosen point, on the ground, at sea or low-level in the air. For every
cell of a grid over the area the planner works out, with the same reciprocity coverage grids as the siting tools:
the chance any opposing ES sensor hears the unit if it transmits, the chance two or more DF sensors fix it, the chance
an opposing radar tracks it (air and sea), and the chance it keeps its own C2. The cost of a cell is the cheaper of
transmitting (risk) and staying silent (a set price per cell for losing two-way C2), so EMCON falls out leg by leg.
Ground and foot routes avoid the sea and steep slopes; sea routes keep to water. Civil (grey) units count only jamming. The best route, the band of routes within a
margin of it, and legs are returned, and each leg's worst point is checked with the exact pairwise model.
With step_min set, the picture is worked out every step_min minutes (other units move on their tracks, emitters keep
their on-air schedules) and the search runs through space and time, holding in place allowed. GNSS denial by opposing
jammers is a cost too (heaviest for air). Screening grade, the run's atmosphere; ducts flagged, not modelled.
With the forecast chosen (phase 4 part 2), each layer also takes the met and space weather for its own time: platform
limits (wind, gusts, sea state, cloud base, icing, visibility) price the layer and set the speed, sea clutter lowers the
radar term over sea cells, and storms lower the J/S at which the unit's GNSS fails.
Amphibious ship to shore (phase 6 part 1, domain "amphib"): a landing craft keeps to water until the beach (land within
1 km of the landing point is allowed for the beach and its exits), with tighter sea-state and wind limits; surf at the
beach is priced on the cells round the landing point layer by layer, so with time layers the craft may hold offshore
for the surf to drop. Opposing communications jammers lower the unit's C2 in every domain (J/S against the net's
threshold, as in the run). The beach report gives the craft's C2 there and whether the beach party on the same net
hears the ship direct or needs the craft as a relay (exact pairwise model).
"""
from __future__ import annotations

import math

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import met_core
from .corridor_core import corridor_time, legs, phi, straight_cost

router = APIRouter(prefix="/api/emo/plan", tags=["emo-plan"])
SPEED = {"ground": 20.0, "sea": 25.0, "air": 150.0, "amphib": 15.0, "foot": 4.0}
SLOPE = {"ground": 30.0, "foot": 60.0}                       # default slope limits (%)
W_DET, W_FIX, W_RADAR, W_C2 = 1.0, 2.0, 2.0, 1.0
W_GNSS, W_GNSS_AIR = 0.5, 1.5                                  # loss of GNSS: worse for an uncrewed aircraft
W_JAM = 1.0                                                    # own C2 lost to opposing comms EA (multiplies the C2 term)
W_LIM = 1.0                                                    # platform limits: marginal 0.3, no-go 3 per cell (met_core.LIMIT_COST)


class CorridorIn(BaseModel):
    mover: str                                                  # entity name: the unit that moves
    to_lat: float = Field(ge=-85, le=85)
    to_lon: float = Field(ge=-180, le=180)
    domain: str = Field(default="ground", pattern="^(ground|sea|air|amphib|foot)$")   # foot: dismounted and SOF
    speed_kmh: float | None = Field(default=None, gt=0, le=1000)
    alt_m: float | None = Field(default=None, ge=1, le=1000)   # air: height above ground (low level)
    emcon: str = Field(default="auto", pattern="^(auto|emit|silent)$")
    silent_cost: float = Field(default=0.6, ge=0, le=10)       # price per cell of moving without transmitting
    max_slope_pct: float | None = Field(default=None, gt=0, le=100)   # ground 30, on foot 60 when blank
    margin: float = Field(default=0.15, ge=0, le=1)
    cell_m: float = Field(default=500, ge=100, le=5000)
    step_min: float = Field(default=0, ge=0, le=120)           # 0: one time step; else time layers this far apart
    layers: int = Field(default=6, ge=1, le=8)
    wait: bool = True                                          # holding in place between layers is allowed
    wait_cost: float = Field(default=0.3, ge=0, le=10)         # price per cell-crossing time of holding (plus the cell's cost)
    gnss: bool = True                                          # count GNSS denial by opposing nav jammers


def _grid(a, b, cell_m):
    """Cell-centre lat/lon rasters over the box round a and b, padded by a quarter of the distance (at least 5 km)."""
    from .link_core import haversine_m
    d = haversine_m(a[0], a[1], b[0], b[1])
    pad = max(5000.0, 0.25 * d)
    s, n = min(a[0], b[0]) - pad / 111_195, max(a[0], b[0]) + pad / 111_195
    k = 111_195 * max(0.2, math.cos(math.radians((s + n) / 2)))
    w, e = min(a[1], b[1]) - pad / k, max(a[1], b[1]) + pad / k
    cell = max(cell_m, max((n - s) * 111_195, (e - w) * k) / 160)          # at most 160 cells a side
    H, W = max(3, int(round((n - s) * 111_195 / cell))), max(3, int(round((e - w) * k / cell)))
    lats = n - (np.arange(H) + 0.5) * (n - s) / H
    lons = w + (np.arange(W) + 0.5) * (e - w) / W
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    return LA, LO, [[s, w], [n, e]], cell


def _cell(LA, LO, pt):
    i = int(np.argmin(np.abs(LA[:, 0] - pt[0])))
    j = int(np.argmin(np.abs(LO[0, :] - pt[1])))
    return i, j


@router.post("/corridor")
async def plan_corridor(body: CorridorIn, t_min: float = 0):
    """Plan a corridor and keep it as this workspace's last corridor (for the Word brief and Ask)."""
    from . import emo_api
    res = await _plan_corridor(body, t_min)
    emo_api._LAST["corridor"] = {"in": body.model_dump(), "t_min": t_min, "res": res}
    return res


@router.get("/corridor/brief.docx")
async def corridor_brief():
    """The workspace's last planned corridor as a Word brief (no re-planning)."""
    from datetime import datetime, timezone
    from fastapi.responses import StreamingResponse
    from . import corridor_brief as cb
    from . import emo_api
    c = emo_api._LAST.get("corridor")
    if not c:
        raise HTTPException(409, "plan a corridor first (Corridor in the EMO dock)")
    data = cb.brief_docx(c, emo_api._all(), emo_api._LAST.get("pos") or {}, emo_api.met_line(emo_api._LAST.get("met")),
                         emo_api.MODEL_CAVEAT)
    name = f"CyEM-corridor-{c['res'].get('unit', 'unit').replace(' ', '-')[:30]}-{datetime.now(timezone.utc):%Y%m%d-%H%MZ}.docx"
    return StreamingResponse(iter([data]), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


async def _plan_corridor(body: CorridorIn, t_min: float = 0):
    from . import dem
    from .emo_plan import _ctx, _pseudo
    from .ems_core import overlay_png, region_masks, sample
    from .link_core import haversine_m
    emo_api, ents, p, pos = _ctx(t_min)
    mover = next((e for e in ents.values() if e["name"] == body.mover), None)
    if not mover:
        raise HTTPException(404, "unit not found")
    side = mover["side"]
    grey = side == "grey"                                      # civil: either side's GNSS and comms jamming; not hiding
    opp = "red" if side == "blue" else "blue"
    opp_sides = {"red", "blue"} if grey else {opp}
    start, goal = tuple(pos(mover)), (body.to_lat, body.to_lon)
    LA, LO, bounds, cell = _grid(start, goal, body.cell_m)
    s_ij, g_ij = _cell(LA, LO, start), _cell(LA, LO, goal)

    # platform limits
    hts = dem.grid_sampler(bounds[0][0], bounds[0][1], bounds[1][0], bounds[1][1])(LA, LO).astype(float)
    sea = hts <= 0.5
    slope_lim = body.max_slope_pct or SLOPE.get(body.domain, 30.0)
    if body.domain in ("ground", "foot"):
        gy, gx = np.gradient(hts, cell)
        ok = ~sea & (np.hypot(gx, gy) * 100 <= slope_lim)
    elif body.domain == "sea":
        ok = sea.copy()
    elif body.domain == "amphib":                              # water, then the beach and its exits within 1 km of the landing point
        near_goal = _dist_m(goal, LA, LO) <= max(1000.0, 1.5 * cell)
        ok = sea | near_goal
    else:
        ok = np.ones(LA.shape, bool)
    for c in (s_ij, g_ij):
        ok[c] = True                                           # a harbour, a beach or a landing site
    h = body.alt_m if body.domain == "air" else mover["h_agl"]
    h = h or (150.0 if body.domain == "air" else 2.0)
    unit = {**mover, "h_agl": h}
    sig = p.sigma_db
    nominal = body.speed_kmh or SPEED[body.domain]
    direct = haversine_m(*start, *goal) / 1000
    env_at = _env_factory(emo_api, p, body.domain, h, _bearing(start, goal), nominal)

    def n_layers(v):
        return max(1, min(body.layers, int(direct * 1.5 / v * 60 // body.step_min) + 2)) if body.step_min else 1

    # platform limits set the speed (the slowest layer the trip is likely to cross), then the time layers follow
    K = n_layers(nominal)
    factor = min([(await env_at(t_min + k * body.step_min))["lim"]["speed_factor"] for k in range(K)])
    speed = round(nominal * factor, 1)
    K = n_layers(speed)
    mpc = cell / 1000 / speed * 60                             # minutes to cross one cell
    emits = mover.get("eirp_dbm") is not None and mover.get("fixed_level_dbm") is None
    ub = emo_api.band(mover)
    sensors = [] if grey else [x for x in ents.values() if x["kind"] == "sensor" and x["side"] == opp and emo_api.overlap(*ub, *emo_api.band(x))]
    ctl = ents.get(mover.get("net") or "")
    users = [u for u in ents.values() if u.get("net") == mover["id"] and u["kind"] == "receiver"]
    nav = next((e for e in ents.values() if e["side"] == side and e.get("category") == "nav" and e.get("fixed_level_dbm") is not None), None)
    jams = [e for e in ents.values() if e["kind"] == "effector" and e["side"] in opp_sides and e.get("category") == "nav"
            and e.get("eirp_dbm") is not None] if body.gnss else []
    zero = np.zeros(LA.shape)
    beach_zone = (_dist_m(goal, LA, LO) <= max(1000.0, 1.5 * cell)) if body.domain == "amphib" else None
    c2net = ctl if (ctl and ctl.get("eirp_dbm") is not None and ctl.get("fixed_level_dbm") is None) else None
    cjams = [e for e in ents.values() if e["kind"] == "effector" and e["side"] in opp_sides and e.get("category") in ("comms", "datalink")
             and e.get("eirp_dbm") is not None and c2net and emo_api.overlap(*emo_api.victim_band(c2net), *emo_api.band(e))]

    async def fields(tk, posk):
        env = await env_at(tk)
        sea_f = sea.astype(float)
        async def level_from(src, at, eirp, rx_h):
            a = posk(at)                                       # reach the grid's farthest corner (capped at 100 km)
            radius = max(haversine_m(a[0], a[1], LA[r, c], LO[r, c]) for r, c in ((0, 0), (0, -1), (-1, 0), (-1, -1))) / 1000 + 2
            cov = await emo_api.coverage_for(_pseudo(src, at, a, eirp, radius), a, rx_h)
            return sample(cov, LA, LO)

        def reach(e):
            """The emitter with its compute radius stretched to the grid's farthest corner (capped at 100 km): its own
            footprint radius would cut a jammer or radar off at 30 to 40 km, while the run's pairwise paths go any distance."""
            a = posk(e)
            r = max(haversine_m(a[0], a[1], LA[i, j], LO[i, j]) for i, j in ((0, 0), (0, -1), (-1, 0), (-1, -1))) / 1000 + 2
            r = min(100.0, max(r, e.get("radius_km") or 0))
            return e if r <= (e.get("radius_km") or 0) else {**e, "id": f"{e['id']}:reach{int(r)}", "radius_km": r}

        # ES: the unit's own emissions heard by opposing sensors (reciprocity), DF fixes from two or more bearings
        P = {}
        if emits:
            for x in [x for x in sensors if emo_api.on_air(x, tk)]:        # sensors keep their on-station schedules
                lv = await level_from(mover, x, mover["eirp_dbm"], h)
                P[x["name"]] = phi((np.nan_to_num(lv, nan=-999, neginf=-999) - (x.get("sens_dbm") or p.default_sens)) / sig)
        p_det = 1 - np.prod([1 - v for v in P.values()], axis=0) if P else zero
        dfp = [P[x["name"]] for x in sensors if x.get("df_rms_deg") and x["name"] in P]
        if len(dfp) >= 2:
            none = np.prod([1 - v for v in dfp], axis=0)
            one = sum(v * np.prod([1 - w for k, w in enumerate(dfp) if k != i], axis=0) for i, v in enumerate(dfp))
            p_fix = 1 - none - one
        else:
            p_fix = zero

        # radar (air and sea units): echo margin from the one-way level, as in the run's radar picture
        p_trk, clut_max = zero, 0.0
        if body.domain in ("air", "sea", "amphib"):
            rcs = mover.get("rcs_m2") or emo_api._default_rcs({**unit, "sidc": "xxA" if body.domain == "air" else "xxS"})
            tr = []
            for rd in [e for e in ents.values() if e.get("category") == "radar" and e["kind"] == "emitter" and e["side"] == opp
                       and not grey and emo_api.on_air(e, tk) and e.get("eirp_dbm") is not None]:
                one = np.nan_to_num(sample(await emo_api.coverage_for(reach(rd), posk(rd), h), LA, LO), nan=-999, neginf=-999)
                R = np.maximum(200.0, _dist_m(posk(rd), LA, LO))
                lam = 3e8 / (rd["freq_mhz"] * 1e6)
                fspl = 20 * np.log10(R) + 20 * math.log10(rd["freq_mhz"] * 1e6) - 147.55
                excess = np.maximum(0.0, rd["eirp_dbm"] - one - fspl)
                clutter = met_core.sea_clutter_db(env["lim"]["sea_state"], rd["freq_mhz"], h)
                clut_max = max(clut_max, clutter)
                echo = (rd["eirp_dbm"] + (rd.get("radar_gain_dbi") or 30.0) + 10 * math.log10(rcs * lam * lam / (4 * math.pi) ** 3)
                        - 40 * np.log10(R) - 2 * excess - clutter * sea_f)            # sea clutter over sea cells only
                tr.append(phi((echo - (rd.get("radar_mds_dbm") or -100.0)) / sig))
            if tr:
                p_trk = 1 - np.prod([1 - v for v in tr], axis=0)

        # own C2: a net user hears its control; a control station reaches its weakest user
        p_c2, c2_what, p_jam, jon = np.ones(LA.shape), "no net", zero, []
        if c2net and emo_api.on_air(ctl, tk):
            lv = np.nan_to_num(sample(await emo_api.coverage_for(ctl, posk(ctl), h), LA, LO), nan=-999, neginf=-999)
            sens = mover.get("sens_dbm") or ctl.get("sens_dbm") or p.default_sens
            p_c2, c2_what = phi((lv - sens) / sig), f"hears {ctl['name']}"
            # opposing comms EA at the unit: J/S against the net's threshold (spot against a hopper diluted, as in the run)
            jon = [e for e in cjams if emo_api.on_air(e, tk)]
            if jon:
                mw = 0.0
                for e in jon:
                    jl = np.nan_to_num(sample(await emo_api.coverage_for(reach(e), posk(e), h), LA, LO), nan=-999, neginf=-999)
                    mw = mw + 10 ** ((jl - emo_api.jam_penalty(e, ctl)) / 10)
                jsreq = ctl["js_req_db"] if ctl.get("js_req_db") is not None else p.js_req_db
                p_jam = phi((10 * np.log10(np.maximum(mw, 1e-30)) - lv - jsreq) / sig)
                p_c2 = p_c2 * (1 - W_JAM * p_jam)
        elif users and emits:
            worst = None
            for u in users:
                lv = np.nan_to_num(await level_from(mover, u, mover["eirp_dbm"], h), nan=-999, neginf=-999) - (u.get("sens_dbm") or mover.get("sens_dbm") or p.default_sens)
                worst = lv if worst is None else np.minimum(worst, lv)
            p_c2, c2_what = phi(worst / sig), f"reaches its {len(users)} users"

        # GNSS: opposing jammers (or spoofers) against the satellite level, power-summed; J/S over the threshold denies
        p_gnss, GJ = zero, {}
        on = [e for e in jams if emo_api.on_air(e, tk)]
        if on:
            mw = 0.0
            S = nav["fixed_level_dbm"] if nav else -128.0
            req = ((nav or {}).get("js_req_db") or 35.0) - env["space"]["gnss"]["loss_db"]
            for e in on:
                lv = np.nan_to_num(sample(await emo_api.coverage_for(reach(e), posk(e), h), LA, LO), nan=-999, neginf=-999)
                mw = mw + 10 ** (lv / 10)
                GJ[e["name"]] = phi((lv - S - req) / sig)            # this jammer alone: who denies the route (collateral)
            p_gnss = phi((10 * np.log10(np.maximum(mw, 1e-30)) - S - req) / sig)

        # EMCON per cell: transmit (risk) or stay silent (two-way C2 lost, priced per cell); radar and GNSS either way
        c_emit = W_DET * p_det + W_FIX * p_fix + W_C2 * (1 - p_c2)
        c_sil = np.full(LA.shape, body.silent_cost + W_C2 * 0.5 * (1 - p_c2))
        if not emits:                                          # receive-only: only C2 (and radar, GNSS) matter
            emit, c = np.zeros(LA.shape, bool), W_C2 * (1 - p_c2)
        elif body.emcon == "emit":
            emit, c = np.ones(LA.shape, bool), c_emit
        elif body.emcon == "silent":
            emit, c = np.zeros(LA.shape, bool), c_sil
        else:
            emit = c_emit <= c_sil
            c = np.where(emit, c_emit, c_sil)
        w_gnss = W_GNSS_AIR if body.domain == "air" else W_GNSS
        cost = c + W_RADAR * p_trk + w_gnss * p_gnss + W_LIM * env["lim"]["cost"]
        if beach_zone is not None:                             # surf at the beach, this layer
            cost = cost + W_LIM * env["surf"]["cost"] * beach_zone
        risk = np.maximum(np.where(emit, np.maximum(p_det, p_fix), 0.0), np.maximum(p_trk, p_gnss))
        return {"P": P, "p_det": p_det, "p_fix": p_fix, "p_trk": p_trk, "p_c2": p_c2, "p_gnss": p_gnss, "emit": emit,
                "cost": cost, "risk": risk, "c2": c2_what, "jams": [e["name"] for e in on], "env": env, "clutter": clut_max,
                "p_jam": p_jam, "c2_jams": [e["name"] for e in jon], "GJ": GJ}

    layers, posfs = [], []
    for k in range(K):
        tk = t_min + k * body.step_min
        posk = pos if k == 0 else (lambda e, tk=tk: tuple(emo_api.position_at(e, tk)))
        posfs.append(posk)
        layers.append(await fields(tk, posk))
    st = lambda name: np.stack([L[name] for L in layers])                                    # noqa: E731
    COST, EMIT, RISK = st("cost"), st("emit"), st("risk")
    PD, PF, PT, PC, PG, PJ = st("p_det"), st("p_fix"), st("p_trk"), st("p_c2"), st("p_gnss"), st("p_jam")

    lay = body.step_min / mpc if body.step_min else 1e9
    r = corridor_time(COST, ok, s_ij, g_ij, lay, body.margin, wait=body.wait and K > 1, wait_cost=body.wait_cost)
    if not r["states"]:
        raise HTTPException(422, f"no {body.domain} route between the two points (sea, slope or the area edge in the way)")
    S_, T_ = r["states"], r["times"]
    N = len(S_)
    q = lambda n: (S_[n][2], S_[n][0], S_[n][1])                                              # noqa: E731
    cl = lambda n: S_[n][:2]                                                                  # noqa: E731
    at_t = lambda n: round(t_min + T_[n] * mpc, 1)                                           # noqa: E731

    def mk_leg(a, b, hold=False):
        idx = list(range(a, b + 1))
        km = 0.0 if hold else (sum(_seg_km(LA, LO, cl(n), cl(n + 1)) for n in idx[:-1]) or cell / 1000)
        w = max(idx, key=lambda n: COST[q(n)])
        tx = bool(EMIT[q(a)])
        P = layers[S_[w][2]]["P"]
        names = sorted(P, key=lambda nm: -float(P[nm][cl(w)]))[:2] if P and EMIT[q(w)] else []
        lg = {"from": _ll(LA, LO, cl(a)), "to": _ll(LA, LO, cl(b)), "km": round(km, 1),
              "minutes": round((T_[b] - T_[a]) * mpc if hold else km / speed * 60, 1), "t_from": at_t(a), "t_to": at_t(b),
              "emcon": "transmit" if tx else "silent", "hold": hold,
              "p_detect": _pct(max(float(PD[q(n)]) for n in idx) if tx else 0.0),
              "p_fix": _pct(max(float(PF[q(n)]) for n in idx) if tx else 0.0),
              "p_radar": _pct(max(float(PT[q(n)]) for n in idx)), "p_gnss": _pct(max(float(PG[q(n)]) for n in idx)),
              "p_c2": _pct(min(float(PC[q(n)]) for n in idx)), "p_jam": _pct(max(float(PJ[q(n)]) for n in idx)), "heard_by": names, "worst": _ll(LA, LO, cl(w)),
              "over_sea": bool(any(sea[cl(n)] for n in idx)), "_k": S_[w][2],
              "jammed_by": sorted(nm for nm, gj in layers[S_[w][2]]["GJ"].items() if max(float(gj[cl(n)]) for n in idx) >= 0.5),
              "limits": layers[S_[w][2]]["env"]["lim"]["status"], "sea_clutter_db": layers[S_[w][2]]["clutter"],
              "gnss_space_db": layers[S_[w][2]]["env"]["space"]["gnss"]["loss_db"],
              "path": [_ll(LA, LO, cl(a))] * 2 if hold else _thin(LA, LO, [cl(n) for n in range(max(0, a - 1), b + 1)])}
        return lg

    segs, cur, n = [], 0, 1                                    # moving runs and holds, in order
    while n < N:
        if cl(n) == cl(n - 1):
            m = n
            while m + 1 < N and cl(m + 1) == cl(m):
                m += 1
            if n - 1 > cur:
                segs.append(("move", cur, n - 1))
            segs.append(("hold", n - 1, m))
            cur, n = m, m + 1
        else:
            n += 1
    if cur < N - 1 or not segs:
        segs.append(("move", cur, N - 1))
    emit_s = np.array([[bool(EMIT[q(n)]) for n in range(N)]])
    risk_s = np.array([[float(RISK[q(n)]) for n in range(N)]])
    out_legs = []
    for kind, a, b in segs:
        if kind == "hold":
            out_legs.append(mk_leg(a, b, hold=True))
            continue
        sub = [(0, n) for n in range(a, b + 1)]
        for x, y in legs(sub, emit_s, risk_s):
            out_legs.append(mk_leg(a + x, a + y))
    await _verify(emo_api, mover, unit, out_legs, sensors, ctl, p, emits, posfs, cjams)
    duct = _duct_note(emo_api._LAST.get("met") or {}, mover, h, body.domain, ents, opp, emits)
    for lg in out_legs:
        lg.pop("_k", None)
        if duct and (lg["over_sea"] or duct["anywhere"]):
            lg["duct"] = duct["text"]
    km = sum(x["km"] for x in out_legs)
    hold_min = sum(x["minutes"] for x in out_legs if x["hold"])
    moving = [x for x in out_legs if not x["hold"]] or out_legs
    band = r["band"]
    layer = overlay_png(region_masks(band, (69, 211, 138, 70))) if band.any() else None
    straight = straight_cost(COST[0], s_ij, g_ij)
    summary = {"km": round(km, 1), "direct_km": round(direct, 1), "minutes": round(km / speed * 60 + hold_min), "speed_kmh": speed,
               "hold_min": round(hold_min), "arrive_t": at_t(N - 1), "layers": K, "step_min": body.step_min,
               "transmit_pct": round(100 * sum(x["km"] for x in moving if x["emcon"] == "transmit") / max(km, 1e-6)),
               "max_p_detect": max(x["p_detect"] for x in out_legs), "max_p_fix": max(x["p_fix"] for x in out_legs),
               "max_p_radar": max(x["p_radar"] for x in out_legs), "max_p_gnss": max(x["p_gnss"] for x in out_legs),
               "min_p_c2": min(x["p_c2"] for x in out_legs), "max_p_jam": max(x["p_jam"] for x in out_legs),
               "c2_jammers": sorted({nm for L in layers for nm in L["c2_jams"]}),
               "cost": round(r["cost"], 1), "direct_cost": round(straight, 1), "cell_m": round(cell),
               "band_km2": round(float(band.sum()) * (cell / 1000) ** 2, 1), "c2": layers[0]["c2"], "sensors": [x["name"] for x in sensors],
               "gnss_jammers": sorted({nm for L in layers for nm in L["jams"]}), "duct": duct["text"] if duct else None,
               "nominal_speed_kmh": nominal, "speed_factor": factor, **_env_summary(layers, sorted({S_[n][2] for n in range(N)}), t_min, body.step_min)}
    if body.domain == "amphib":
        summary["beach"] = await _beach(emo_api, mover, unit, ents, ctl, p, layers, S_[N - 1][2], posfs, _ll(LA, LO, cl(N - 1)),
                                        float(PC[q(N - 1)]), at_t(N - 1), cjams)
        if summary["beach"]["surf"] == "no-go":
            summary["limits_warning"] = ((summary.get("limits_warning") or "") + " Surf at the beach is outside the landing "
                                         f"craft's limits at T+{at_t(N - 1):g} ({summary['beach']['breaker_m']:g} m).").strip()
    when = (f"through {K} time layers {body.step_min:g} min apart from T+{t_min:g} (other units move on their tracks; "
            + ("holding allowed" if body.wait else "no holding") + "), with the last run's atmosphere") if K > 1 else \
        "at one time step with the last run's atmosphere; other units frozen at T+t"
    return {"unit": mover["name"], "side": side, "domain": body.domain, "t_min": t_min, "bounds": bounds,
            "path": [_ll(LA, LO, cl(n)) for n in range(0, N, max(1, N // 200))] + [_ll(LA, LO, cl(N - 1))],
            "band": layer, "legs": out_legs, "summary": summary, "met": (emo_api._LAST.get("met") or {}).get("used"),
            "notes": f"Screening grade, {when}. Corridor = cells on routes within {round(body.margin * 100)}% of the best "
                     "route's cost (each cell at the time the unit would reach it). Transmit or silent is chosen per cell "
                     "(silent costs two-way C2). Each leg's worst point is re-checked with the exact pairwise model "
                     "(verified values). GNSS: opposing jammers against the satellite level and the receivers' J/S "
                     "threshold. Ducts are flagged, not modelled. "
                     + ("Met and space weather per layer from the forecast: platform limits price each layer and set the "
                        "speed, sea clutter lowers the radar term over sea cells, storms lower the GNSS failure J/S (notional "
                        "generic limits, met_core.LIMITS). " if getattr(p, "met", "standard") == "forecast" else
                        "Platform limits, sea clutter and space weather need the forecast chosen (not applied). ")
                     + "Opposing communications jammers lower own C2 (J/S against the net's threshold). "
                     + ("Amphibious: the landing craft keeps to water until the beach (land within 1 km of the landing "
                        "point allowed); surf at the beach (breaker height from the offshore waves, Komar and Gaudet, no "
                        "bathymetry) is priced on the cells round it per layer, so holding offshore for the surf to drop "
                        "is allowed. " if body.domain == "amphib" else "")
                     + ("Civil unit: only jamming by either side and its own C2 are counted (it is not hiding from ES or "
                        "radar); each leg names the GNSS jammers that deny it on their own (collateral). " if grey else "")
                     + "Ground and foot routes avoid sea and slopes over "
                     f"{slope_lim:g}%; sea routes keep to water; air routes fly a set height above ground"
                     + (f" ({h:g} m)." if body.domain == "air" else "."),
            **({"collateral": _collateral(out_legs, ents)} if grey or any(lg["jammed_by"] for lg in out_legs) else {})}


def _collateral(out_legs, ents) -> dict:
    """GNSS jammers that deny the route on their own, by side, with the legs they deny."""
    side_of = {e["name"]: e["side"] for e in ents.values()}
    out: dict[str, dict[str, list[int]]] = {}
    for i, lg in enumerate(out_legs, 1):
        for nm in lg.get("jammed_by") or []:
            out.setdefault(side_of.get(nm, "?"), {}).setdefault(nm, []).append(i)
    return {sd: [{"effector": nm, "legs": v} for nm, v in d.items()] for sd, d in out.items()}


def _bearing(a, b) -> float:
    p1, p2, dl = math.radians(a[0]), math.radians(b[0]), math.radians(b[1] - a[1])
    return (math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) + 360) % 360


def _env_factory(emo_api, p, domain, h, track_deg, speed_kmh):
    """Met, space weather and platform limits for a time layer, memoised. With the forecast chosen the met is fetched
    for the layer's own hour at the run's met point (cached), otherwise the last run's (standard) state is used."""
    from datetime import timedelta
    from . import met as metmod
    from . import spacewx_core
    from .db import get_db
    last = emo_api._LAST.get("met") or metmod.standard()
    forecast = getattr(p, "met", "standard") == "forecast"
    t0 = emo_api._parse_time(getattr(p, "met_time", None))
    lat, lon = last.get("lat", 0.0), last.get("lon", 0.0)
    sw = get_db().get_snapshot("spaceweather")[0] if forecast else None
    memo = {}

    async def env_at(tk):
        if tk not in memo:
            when = t0 + timedelta(minutes=tk)
            st = await metmod.met_state(lat, lon, when) if forecast else last
            memo[tk] = {"t": tk, "met": st, "space": spacewx_core.at_time(sw, when, lat, lon),
                        "lim": met_core.platform_limits(domain, st, h, track_deg, speed_kmh), "surf": met_core.surf(st)}
        return memo[tk]
    return env_at


def _env_summary(layers, used, t_min, step_min) -> dict:
    """Worst platform-limit status on the layers the route uses, the reasons, sea state and space weather per layer."""
    rank = {"unknown": -1, "go": 0, "marginal": 1, "no-go": 2}
    envs = [layers[k]["env"] for k in used]
    worst = max((e["lim"]["status"] for e in envs), key=lambda x: rank[x])
    reasons = list(dict.fromkeys(r for e in envs for r in e["lim"]["reasons"]))
    per = [{"t": e["t"], "limits": e["lim"]["status"], "speed_factor": e["lim"]["speed_factor"], "sea_state": e["lim"]["sea_state"],
            "hf": e["space"]["hf"]["status"], "gnss_space_db": e["space"]["gnss"]["loss_db"], "sea_clutter_db": layers[k]["clutter"]}
           for k, e in zip(used, envs)]
    out = {"limits": worst, "limit_reasons": reasons[:8], "env_layers": per,
           "max_sea_clutter_db": max(x["sea_clutter_db"] for x in per), "gnss_space_db": max(x["gnss_space_db"] for x in per),
           "space": envs[0]["space"]["text"]}
    if worst == "no-go":
        out["limits_warning"] = ("Outside the platform's limits on at least one layer the route uses: "
                                 + "; ".join(r for r in reasons if r.startswith("no-go")) + ".")
    return out


def _duct_note(met: dict, mover: dict, h: float, domain: str, ents: dict, opp: str, emits: bool) -> dict | None:
    """Whether a duct the met reports could carry the unit's emissions or an opposing radar beyond the ranges shown:
    the evaporation duct over the sea for antennas up to 50 m, a surface-based duct anywhere below its top."""
    out, anywhere = [], False
    radars = [e for e in ents.values() if e["side"] == opp and e.get("category") == "radar" and e["kind"] == "emitter"]
    ev = met.get("evap_duct") or {}
    cand = [("evaporation", ev.get("height_m") or 0, ev.get("cutoff_ghz"))] if ev.get("height_m", 0) >= 4 and domain != "ground" and h <= 50 else []
    cand += [(f"{d['kind']} {d['base_m']}-{d['top_m']} m", d["top_m"], d.get("cutoff_ghz")) for d in met.get("ducts") or []
             if d.get("kind") == "surface-based" and h <= d.get("top_m", 0)]
    for what, height, cut in cand:
        if not cut:
            continue
        hit = [e["name"] for e in radars if e["freq_mhz"] / 1000 >= cut and e["h_agl"] <= max(50, height)]
        if emits and mover["freq_mhz"] / 1000 >= cut:
            hit.insert(0, f"own {mover['freq_mhz']:g} MHz emissions")
        if hit:
            out.append(f"{what} duct ({height:g} m, traps {cut:g} GHz and above): {', '.join(hit[:4])} may reach beyond the ranges shown")
            anywhere = anywhere or what != "evaporation"
    return {"text": "; ".join(out) + ".", "anywhere": anywhere} if out else None


async def _verify(emo_api, mover, unit, out_legs, sensors, ctl, p, emits, posfs, cjams=()):
    """Exact pairwise check at each leg's worst point, with the other units where they are at that time: detection
    by each sensor, and own C2 there (less the chance an opposing comms jammer denies it)."""
    pr = lambda m: int(round(50 * (1 + math.erf(m / (p.sigma_db * math.sqrt(2))))))     # noqa: E731
    for lg in out_legs:
        pos = posfs[lg["_k"]]
        at = tuple(lg["worst"])
        here = {**unit, "id": f"corr:{mover['id']}", "updated_at": f"{mover['updated_at']}|corr"}
        det = []
        if emits and lg["emcon"] == "transmit":
            for x in sensors:
                lv = await emo_api.p2p_level(here, at, x, pos(x))
                det.append(pr(lv - (x.get("sens_dbm") or p.default_sens)))
        c2 = jam = None
        if ctl and ctl["active"] and ctl.get("eirp_dbm") is not None and ctl.get("fixed_level_dbm") is None:
            S = await emo_api.p2p_level(ctl, pos(ctl), here, at)
            c2 = pr(S - (mover.get("sens_dbm") or ctl.get("sens_dbm") or p.default_sens))
            jam = await _p_jam(emo_api, ctl, here, at, S, [e for e in cjams if e["active"]], pos, p)
            if jam is not None:
                c2 = int(round(c2 * (1 - W_JAM * jam / 100)))
        lg["verified"] = {"p_detect": max(det) if det else 0, "p_c2": c2, "p_jam": jam}


async def _p_jam(emo_api, ctl, here, at, S, jams, pos, p) -> int | None:
    """Chance (%) the opposing comms jammers deny the net at a point: power-summed J (after the hop or bandwidth
    penalty) over the signal S there, against the net's J/S threshold. None when no jammer applies."""
    if not jams:
        return None
    mw = 0.0
    for e in jams:
        mw += 10 ** ((await emo_api.p2p_level(e, pos(e), here, at) - emo_api.jam_penalty(e, ctl)) / 10)
    jsreq = ctl["js_req_db"] if ctl.get("js_req_db") is not None else p.js_req_db
    m = 10 * math.log10(max(mw, 1e-30)) - S - jsreq
    return int(round(50 * (1 + math.erf(m / (p.sigma_db * math.sqrt(2))))))


async def _beach(emo_api, mover, unit, ents, ctl, p, layers, k, posfs, at, p_c2_grid, t_arr, cjams=()) -> dict:
    """Ship to shore at the landing point, at the arrival layer: surf, the craft's C2 there (exact, less the chance an
    opposing comms jammer denies it), and for each receiver of the same net within 3 km of the beach (the beach party)
    whether it hears the control direct or needs the craft as a relay (the craft hears the control and is within 3 km).
    Jamming is applied to the direct path at the party; the relay hop is on the same net, so it is jammed too."""
    from .link_core import haversine_m
    env = layers[k]["env"]
    pos = posfs[k]
    out = {"at": at, "t": t_arr, "surf": env["surf"]["status"], "breaker_m": env["surf"]["breaker_m"],
           "surf_reason": env["surf"]["reason"], "p_c2_grid": _pct(p_c2_grid), "control": ctl["name"] if ctl else None,
           "party": [], "text": ""}
    if not (ctl and ctl.get("eirp_dbm") is not None and ctl.get("fixed_level_dbm") is None):
        out["text"] = "No control station for the craft's net: beach C2 not assessed."
        return out
    sens = lambda u: u.get("sens_dbm") or ctl.get("sens_dbm") or p.default_sens                      # noqa: E731
    pr = lambda m: int(round(50 * (1 + math.erf(m / (p.sigma_db * math.sqrt(2))))))              # noqa: E731
    here = {**unit, "id": f"corr:{mover['id']}:beach", "updated_at": f"{mover['updated_at']}|beach"}
    jams = [e for e in cjams if emo_api.on_air(e, t_arr)]
    S = await emo_api.p2p_level(ctl, pos(ctl), here, tuple(at))
    craft = pr(S - sens(mover))
    jc = await _p_jam(emo_api, ctl, here, tuple(at), S, jams, pos, p)
    if jc is not None:
        craft = int(round(craft * (1 - W_JAM * jc / 100)))
    out["p_c2"], out["p_jam"] = craft, jc
    party = [u for u in ents.values() if u.get("net") == ctl["id"] and u["kind"] == "receiver" and u["id"] != mover["id"]
             and haversine_m(*pos(u), *at) <= 3000]
    for u in party:
        Su = await emo_api.p2p_level(ctl, pos(ctl), u, pos(u))
        ju = await _p_jam(emo_api, ctl, u, pos(u), Su, jams, pos, p)
        cut = 1 - W_JAM * (ju or 0) / 100
        direct = int(round(pr(Su - sens(u)) * cut))
        relay = None
        if mover.get("eirp_dbm") is not None:
            Sr = await emo_api.p2p_level(here, tuple(at), u, pos(u))
            jr = await _p_jam(emo_api, ctl, u, pos(u), Sr, jams, pos, p)
            relay = int(round(pr(Sr - sens(u)) * (1 - W_JAM * (jr or 0) / 100)))
        out["party"].append({"name": u["name"], "direct_pct": direct, "via_craft_pct": relay,
                             "needs_relay": direct < 50 and (relay or 0) >= 50})
    bits = [f"Landing craft hears {ctl['name']} at the beach: {craft}%"
            + (f" (jamming denies it {jc}% of the time)." if jc else ".")]
    for x in out["party"]:
        if x["direct_pct"] >= 50:
            bits.append(f"{x['name']} hears it direct ({x['direct_pct']}%).")
        elif x["needs_relay"]:
            bits.append(f"{x['name']} does not hear it direct ({x['direct_pct']}%): relay through the craft "
                        f"({x['via_craft_pct']}% from the beach, the craft {craft}% to the ship).")
        else:
            bits.append(f"{x['name']} does not hear it direct ({x['direct_pct']}%) and the craft is no relay "
                        f"({x['via_craft_pct'] if x['via_craft_pct'] is not None else 'receive only'}).")
    bits.append(env["surf"]["reason"][0].upper() + env["surf"]["reason"][1:] + ".")
    out["text"] = " ".join(bits)
    return out


def _dist_m(a, LA, LO):
    p1, p2 = math.radians(a[0]), np.radians(LA)
    dl = np.radians(LO - a[1])
    x = np.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * 6_371_008.8 * np.arcsin(np.sqrt(np.clip(x, 0, 1)))


def _seg_km(LA, LO, a, b):
    from .link_core import haversine_m
    return haversine_m(LA[a], LO[a], LA[b], LO[b]) / 1000


def _ll(LA, LO, c):
    return [round(float(LA[c]), 5), round(float(LO[c]), 5)]


def _thin(LA, LO, cells, most=60):
    """A leg's cells as lat/lon for the map, at most about `most` points, ends kept."""
    return [_ll(LA, LO, q) for q in cells[:-1:max(1, len(cells) // most)]] + [_ll(LA, LO, cells[-1])]


def _pct(x: float) -> int:
    return int(round(100 * x))
