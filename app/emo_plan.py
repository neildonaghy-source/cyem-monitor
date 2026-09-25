"""EP/EA siting solver for EMO: search candidate positions over terrain and score them, so the tool can answer
'where do I move this net / put this jammer'. Screening-grade; proposes positions to test, not a solution.

Reuses the EMO terrain path (p2p_level, Deygout). Candidates come from a coarse grid over the scenario, so cost is
(candidates x links) terrain paths, kept small by a coarse grid, a move-radius filter and a concurrency cap."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/emo/plan", tags=["emo-plan"])


def local_grid(center, radius_km, n=11):
    """n x n grid over +/- radius around the unit, clipped to the radius circle."""
    import math
    from .sdr_classify import haversine_km
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.2, math.cos(math.radians(center[0]))))
    pts = [(center[0] - dlat + 2 * dlat * i / (n - 1), center[1] - dlon + 2 * dlon * j / (n - 1)) for i in range(n) for j in range(n)]
    return [c for c in pts if haversine_km(center[0], center[1], c[0], c[1]) <= radius_km]


def allowed(c, own: list, opp: list, standoff_km: float) -> bool:
    """Not within standoff of an opposing ground unit, and nearer own forces' centroid than the opposing centroid."""
    from .sdr_classify import haversine_km
    if any(haversine_km(c[0], c[1], o[0], o[1]) < standoff_km for o in opp):
        return False
    if own and opp:
        oc = (sum(x[0] for x in own) / len(own), sum(x[1] for x in own) / len(own))
        pc = (sum(x[0] for x in opp) / len(opp), sum(x[1] for x in opp) / len(opp))
        return haversine_km(c[0], c[1], *oc) <= haversine_km(c[0], c[1], *pc)
    return True


def grid(bounds, n_lat=9, n_lon=9):
    (s, w), (nn, e) = bounds
    return [(s + (nn - s) * (i + 0.5) / n_lat, w + (e - w) * (j + 0.5) / n_lon)
            for i in range(n_lat) for j in range(n_lon)]


class SiteNetIn(BaseModel):
    net: str
    max_move_km: float = Field(default=30, gt=1, le=100)
    standoff_km: float = Field(default=10, ge=0, le=50)


class SiteEAIn(BaseModel):
    effector: str
    target_net: str
    max_move_km: float = Field(default=40, gt=1, le=100)
    standoff_km: float = Field(default=10, ge=0, le=50)


def _ctx(t_min: float):
    from . import emo_api
    if not emo_api._LAST or abs(emo_api._LAST.get("t", -1) - t_min) > 1e-6:
        raise HTTPException(409, "run the analysis first")
    ents = {e["id"]: e for e in emo_api._all()}
    pos = lambda e: tuple(emo_api._LAST["pos"].get(e["id"], (e["lat"], e["lon"])))  # noqa: E731
    return emo_api, ents, emo_api._LAST["params"], pos


def _ground(ents, pos, side):
    return [pos(e) for e in ents.values() if e["side"] == side and e["h_agl"] < 300 and e.get("fixed_level_dbm") is None]


def _probe(name: str, h: float) -> dict:
    """A receive-only stand-in for 'someone listening at a candidate point'."""
    return {"id": f"probe:{name}", "updated_at": "", "h_agl": h}


def _refine(best: list[dict], bounds, n=3, step_frac=0.35) -> list[tuple]:
    """3x3 local grid around each of the top candidates, spaced at a fraction of the coarse cell."""
    (s, w), (nn, e) = bounds
    dlat, dlon = (nn - s) / 7 * step_frac, (e - w) / 7 * step_frac
    out = []
    for b in best[:n]:
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                if i or j:
                    out.append((b["lat"] + i * dlat, b["lon"] + j * dlon))
    return out


def _describe(c, ref_name, ref_pos) -> str:
    from .sdr_classify import bearing, haversine_km
    d = haversine_km(ref_pos[0], ref_pos[1], c[0], c[1])
    b = bearing(ref_pos[0], ref_pos[1], c[0], c[1])
    pts = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return f"{d:.1f} km {pts[int((b + 22.5) // 45) % 8]} of {ref_name}"


@router.post("/site-net")
async def site_net(body: SiteNetIn, t_min: float = 0):
    """Where to put a net's control station so the net closes, opposing ES does not hear it, and opposing EA does
    not deny it; plus a relay site for any user the best control position still cannot reach."""
    emo_api, ents, p, pos = _ctx(t_min)
    from .sdr_classify import haversine_km
    net = next((e for e in ents.values() if e["name"] == body.net and e["kind"] == "emitter"), None)
    if not net or net.get("fixed_level_dbm") is not None:
        raise HTTPException(404, "net control (terrestrial emitter) not found")
    users = [e for e in ents.values() if e.get("net") == net["id"] and e["kind"] == "receiver"]
    opp = [x for x in ("blue", "red") if x != net["side"]][0] if net["side"] in ("blue", "red") else "red"
    nb = emo_api.band(net)
    sensors = [e for e in ents.values() if e["kind"] == "sensor" and e["side"] == opp and emo_api.overlap(*nb, *emo_api.band(e))]
    jammers = [e for e in ents.values() if e["kind"] == "effector" and e["side"] == opp and e["active"]
               and emo_api.overlap(*nb, *emo_api.band(e))]
    nsens = net.get("sens_dbm") or p.default_sens
    jsreq = net["js_req_db"] if net.get("js_req_db") is not None else p.js_req_db
    # jamming power arriving at each (fixed) user: independent of where the control station goes
    J_user = {}
    for u in users:
        J_user[u["id"]] = max([await emo_api.p2p_level(j, pos(j), u, pos(u)) - emo_api.jam_penalty(j, net) for j in jammers], default=-999)

    async def score(c):
        cand = {**net, "id": "cand-ctrl", "updated_at": ""}
        S = [await emo_api.p2p_level(cand, c, u, pos(u)) for u in users]
        link = min((s - nsens for s in S), default=99.0)
        heard = [await emo_api.p2p_level(cand, c, s, pos(s)) - (s.get("sens_dbm") or p.default_sens) for s in sensors]
        exposure = max(heard, default=-99.0)
        headroom = max(0.0, min((s - nsens for s in S), default=0.0) - 6)        # dB the net could drop and still close
        js_users = [J_user[u["id"]] - S[i] for i, u in enumerate(users)]
        # jamming at the control station, against the weakest user's signal back (reciprocity, user EIRP)
        Jc = max([await emo_api.p2p_level(j, pos(j), _probe("ctrl", net["h_agl"]), c) - emo_api.jam_penalty(j, net) for j in jammers], default=-999)
        back = [S[i] + ((u.get("eirp_dbm") or net["eirp_dbm"]) - net["eirp_dbm"]) for i, u in enumerate(users)]
        js_ctrl = Jc - min(back) if back else -99.0
        worst_js = max(js_users + [js_ctrl], default=-99.0)
        closed = sum(1 for s in S if s - nsens >= 6)
        sc = (10 * closed - 3 * max(0.0, 6 - link) - 1.5 * max(0.0, exposure + 6) - 2 * max(0.0, worst_js - jsreq + 6))
        return {"lat": round(c[0], 4), "lon": round(c[1], 4), "users_closed": closed, "of_users": len(users),
                "link_margin_db": round(link, 1), "exposure_db": round(exposure, 1), "worst_js_db": round(worst_js, 1),
                "heard_by": [sensors[i]["name"] for i, h in enumerate(heard) if h >= 0],
                "power_cut_db": round(headroom, 1),
                "heard_at_min_power": [sensors[i]["name"] for i, h in enumerate(heard) if h - headroom >= 0],
                "exposure_by_sensor": {sensors[i]["name"]: round(h, 1) for i, h in enumerate(heard)},
                "score": round(sc, 1)}

    here = pos(net)
    bounds = emo_api._LAST["bounds"]
    own_g, opp_g = _ground(ents, pos, net["side"]), _ground(ents, pos, opp)
    cands = [c for c in local_grid(here, body.max_move_km) if allowed(c, own_g, opp_g, body.standoff_km)]
    sem = asyncio.Semaphore(3)

    async def g(c):
        async with sem:
            return await score(c)
    res = await asyncio.gather(*[g(c) for c in cands])
    res.sort(key=lambda r: -r["score"])
    res += await asyncio.gather(*[g(c) for c in _refine(res, ((here[0] - 0.3, here[1] - 0.5), (here[0] + 0.3, here[1] + 0.5)))
                                  if haversine_km(here[0], here[1], c[0], c[1]) <= body.max_move_km and allowed(c, own_g, opp_g, body.standoff_km)])
    res.sort(key=lambda r: -r["score"])
    current = await score(here)
    best = res[0] if res else None
    for r in res[:5]:
        r["where"] = _describe((r["lat"], r["lon"]), net["name"] + " (current)", here)
    # relay for users the best control position still cannot reach (a same-band node on a 10 m mast)
    relay = None
    if best and best["users_closed"] < len(users):
        ctrl = (best["lat"], best["lon"])
        cand_ctrl = {**net, "id": "cand-ctrl", "updated_at": ""}
        fail = [u for u in users if await emo_api.p2p_level(cand_ctrl, ctrl, u, pos(u)) - nsens < 6]
        relay_node = {**net, "id": "cand-relay", "updated_at": "", "h_agl": 10}

        async def rscore(r):
            up = await emo_api.p2p_level(cand_ctrl, ctrl, _probe("relay", 10), r) - nsens
            if up < 6:
                return None
            reach = [await emo_api.p2p_level(relay_node, r, u, pos(u)) - nsens for u in fail]
            heard = max([await emo_api.p2p_level(relay_node, r, s, pos(s)) - (s.get("sens_dbm") or p.default_sens) for s in sensors], default=-99.0)
            ok = sum(1 for x in reach if x >= 6)
            return {"lat": round(r[0], 4), "lon": round(r[1], 4), "reaches": ok, "of_failing": len(fail),
                    "uplink_margin_db": round(up, 1), "exposure_db": round(heard, 1),
                    "score": round(10 * ok - 1.5 * max(0.0, heard + 6), 1)}

        rc = await asyncio.gather(*[g2 for g2 in [rscore(c) for c in grid(bounds, 7, 7)]])
        rc = sorted([x for x in rc if x], key=lambda x: -x["score"])
        if rc:
            relay = rc[0]
            relay["where"] = _describe((relay["lat"], relay["lon"]), net["name"] + " (current)", here)
            relay["serves"] = [u["name"] for u in fail]
    return {"net": net["name"], "side": net["side"], "users": [u["name"] for u in users], "candidates": len(res),
            "opp_sensors": [s["name"] for s in sensors], "opp_jammers": [j["name"] for j in jammers],
            "unavoidable": sorted({n for n in (res[0]["heard_at_min_power"] if res else [])}),
            "current": current, "best": res[:5], "relay": relay,
            "notes": "Score: +10 per user whose link closes with 6 dB margin; penalties for weak links, for being heard by an "
                     "opposing sensor on this band (per dB above its sensitivity) and for J/S within 6 dB of the net's "
                     "threshold. Users are scored where they are; control station and relay positions are proposed. "
                     "Screening-grade terrain model: positions to test in the tool, not a solution."}


@router.post("/site-ea")
async def site_ea(body: SiteEAIn, t_min: float = 0):
    """Where to put a jammer to deny an opposing net: most users denied, least exposure to opposing DF, and no
    fratricide against own-side nets on the same band."""
    emo_api, ents, p, pos = _ctx(t_min)
    from .sdr_classify import haversine_km
    y = next((e for e in ents.values() if e["name"] == body.effector and e["kind"] == "effector"), None)
    net = next((e for e in ents.values() if e["name"] == body.target_net and e["kind"] == "emitter"), None)
    if not y or not net:
        raise HTTPException(404, "effector or target net not found")
    users = [e for e in ents.values() if e.get("net") == net["id"] and e["kind"] == "receiver"]
    if not users:
        raise HTTPException(400, "the target net has no users to deny")
    opp = net["side"]
    df = [e for e in ents.values() if e["kind"] == "sensor" and e["side"] == opp and e.get("df_rms_deg")
          and emo_api.overlap(*emo_api.band(y), *emo_api.band(e))]
    jsreq = net["js_req_db"] if net.get("js_req_db") is not None else p.js_req_db
    pen = emo_api.jam_penalty(y, net)
    S_user = {u["id"]: (float(net["fixed_level_dbm"]) if net.get("fixed_level_dbm") is not None
                        else await emo_api.p2p_level(net, pos(net), u, pos(u))) for u in users}
    own_nets = [n for n in ents.values() if n["kind"] == "emitter" and n["side"] == y["side"] and n["active"]
                and n.get("fixed_level_dbm") is None and emo_api.overlap(*emo_api.band(y), *emo_api.band(n))]
    own_users = [(n, u) for n in own_nets for u in ents.values() if u.get("net") == n["id"]]
    S_own = {u["id"]: await emo_api.p2p_level(n, pos(n), u, pos(u)) for n, u in own_users}

    async def score(c):
        cand = {**y, "id": "cand-ea", "updated_at": ""}
        js = [await emo_api.p2p_level(cand, c, u, pos(u)) - pen - S_user[u["id"]] for u in users]
        denied = sum(1 for x in js if x >= jsreq)
        heard = max([await emo_api.p2p_level(cand, c, s, pos(s)) - (s.get("sens_dbm") or p.default_sens) for s in df], default=-99.0)
        frat = 0
        for n, u in own_users:
            jreq = n["js_req_db"] if n.get("js_req_db") is not None else p.js_req_db
            if await emo_api.p2p_level(cand, c, u, pos(u)) - emo_api.jam_penalty(y, n) - S_own[u["id"]] >= jreq:
                frat += 1
        sc = 10 * denied - 1.0 * max(0.0, heard + 6) - 15 * frat + 0.2 * min(js, default=0)
        return {"lat": round(c[0], 4), "lon": round(c[1], 4), "denied": denied, "of_users": len(users),
                "min_js_db": round(min(js), 1) if js else None, "exposure_db": round(heard, 1),
                "heard_by_df": [df[i]["name"] for i in range(len(df))] if heard >= 0 else [],
                "fratricide": frat, "score": round(sc, 1)}

    here = pos(y)
    bounds = emo_api._LAST["bounds"]
    own_g, opp_g = _ground(ents, pos, y["side"]), _ground(ents, pos, opp)
    cands = [c for c in local_grid(here, body.max_move_km) if allowed(c, own_g, opp_g, body.standoff_km)]
    sem = asyncio.Semaphore(3)

    async def g(c):
        async with sem:
            return await score(c)
    res = sorted(await asyncio.gather(*[g(c) for c in cands]), key=lambda r: -r["score"])
    res += await asyncio.gather(*[g(c) for c in _refine(res, ((here[0] - 0.3, here[1] - 0.5), (here[0] + 0.3, here[1] + 0.5)))
                                  if haversine_km(here[0], here[1], c[0], c[1]) <= body.max_move_km and allowed(c, own_g, opp_g, body.standoff_km)])
    res.sort(key=lambda r: -r["score"])
    for r in res[:5]:
        r["where"] = _describe((r["lat"], r["lon"]), y["name"] + " (current)", here)
    return {"effector": y["name"], "target_net": net["name"], "js_req_db": jsreq, "users": [u["name"] for u in users],
            "opp_df": [d["name"] for d in df], "own_nets_same_band": [n["name"] for n in own_nets],
            "current": await score(here), "best": res[:5], "candidates": len(res),
            "notes": "Score: +10 per target user denied; penalties for exposure to opposing DF on this band and heavily for "
                     "fratricide against own nets on the same band. Screening-grade: positions to test in the tool."}


# ---- A1: reciprocity score maps ---------------------------------------------------------------------
# Path loss is symmetric, so the level a candidate control station would deliver to user U equals the level
# received at the candidate from a pseudo-transmitter at U with the net's EIRP. One coverage grid per user,
# sensor and jammer therefore gives link margin, exposure and J/S at EVERY candidate point at once.

class MapIn(BaseModel):
    kind: str = Field(pattern="^(net|ea)$")
    name: str                                       # net control (kind=net) or effector (kind=ea)
    target_net: str | None = None                   # kind=ea
    max_move_km: float = Field(default=30, gt=1, le=60)
    standoff_km: float = Field(default=10, ge=0, le=50)
    px: int = Field(default=72, ge=24, le=120)


def _pseudo(src: dict, at: dict, at_pos, eirp: float, radius_km: float) -> dict:
    """A transmitter at 'at' (its height) radiating on src's frequency with the given EIRP, omni."""
    return {**src, "id": f"rcp:{src['id']}:{at['id']}", "updated_at": f"{src['updated_at']}|{at['updated_at']}",
            "lat": at_pos[0], "lon": at_pos[1], "h_agl": at["h_agl"], "eirp_dbm": eirp, "pattern": "omni",
            "azimuth": None, "beamwidth": None, "radius_km": min(100.0, radius_km)}


def _axes(center, radius_km, px):
    import math
    import numpy as np
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.2, math.cos(math.radians(center[0]))))
    lats = center[0] + dlat - (np.arange(px) + 0.5) / px * 2 * dlat
    lons = center[1] - dlon + (np.arange(px) + 0.5) / px * 2 * dlon
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    return LA, LO, [[center[0] - dlat, center[1] - dlon], [center[0] + dlat, center[1] + dlon]]


def _mask(LA, LO, center, radius_km, own, opp, standoff_km):
    import numpy as np
    from .sdr_classify import haversine_km
    ok = np.ones(LA.shape, bool)
    # vectorised haversine to each opposing ground unit, and to the two centroids
    def dist(lat0, lon0):
        p1, p2 = np.radians(lat0), np.radians(LA)
        dl = np.radians(LO - lon0)
        a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
        return 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    ok &= dist(center[0], center[1]) <= radius_km
    for o in opp:
        ok &= dist(o[0], o[1]) >= standoff_km
    if own and opp:
        oc = (sum(x[0] for x in own) / len(own), sum(x[1] for x in own) / len(own))
        pc = (sum(x[0] for x in opp) / len(opp), sum(x[1] for x in opp) / len(opp))
        ok &= dist(*oc) <= dist(*pc)
    return ok


def _best_points(score, LA, LO, ok, n=5, min_sep_km=4.0):
    """Top-n local maxima with non-maximum suppression."""
    import numpy as np
    from .sdr_classify import haversine_km
    s = np.where(ok, score, -np.inf)
    out = []
    flat = np.argsort(s, axis=None)[::-1]
    for idx in flat:
        if not np.isfinite(s.flat[idx]):
            break
        i, j = np.unravel_index(idx, s.shape)
        la, lo = float(LA[i, j]), float(LO[i, j])
        if all(haversine_km(la, lo, b["lat"], b["lon"]) >= min_sep_km for b in out):
            out.append({"lat": round(la, 4), "lon": round(lo, 4), "score": round(float(s[i, j]), 1), "ij": (int(i), int(j))})
        if len(out) >= n:
            break
    return out


def _heat_png(score, ok):
    """Green (best) through amber to red (worst), transparent where not allowed."""
    import base64
    import numpy as np
    from .coverage_core import _png
    s = np.where(ok, score, np.nan)
    lo, hi = np.nanpercentile(s, 5) if np.isfinite(s).any() else 0, np.nanmax(s) if np.isfinite(s).any() else 1
    t = np.clip((s - lo) / max(1e-6, hi - lo), 0, 1)
    img = np.zeros(s.shape + (4,), np.uint8)
    img[..., 0] = (255 * (1 - t)).astype(np.uint8)
    img[..., 1] = (200 * t + 40 * (1 - t)).astype(np.uint8)
    img[..., 2] = 60
    img[..., 3] = np.where(np.isfinite(s), 150, 0).astype(np.uint8)
    return "data:image/png;base64," + base64.b64encode(_png(img)).decode()


@router.post("/map")
async def plan_map(body: MapIn, t_min: float = 0):
    """Siting score map: heatmap over the reachable area plus the best sites, from reciprocity coverage grids."""
    import numpy as np
    from .ems_core import sample
    emo_api, ents, p, pos = _ctx(t_min)
    from .sdr_classify import haversine_km
    if body.kind == "net":
        net = next((e for e in ents.values() if e["name"] == body.name and e["kind"] == "emitter"), None)
        if not net or net.get("fixed_level_dbm") is not None:
            raise HTTPException(404, "net control not found")
        mover, side = net, net["side"]
    else:
        y = next((e for e in ents.values() if e["name"] == body.name and e["kind"] == "effector"), None)
        net = next((e for e in ents.values() if e["name"] == body.target_net and e["kind"] == "emitter"), None)
        if not y or not net:
            raise HTTPException(404, "effector or target net not found")
        mover, side = y, y["side"]
    opp = "red" if side == "blue" else "blue"
    here = pos(mover)
    R = body.max_move_km
    LA, LO, bounds = _axes(here, R, body.px)
    own_g, opp_g = _ground(ents, pos, side), _ground(ents, pos, opp)
    ok = _mask(LA, LO, here, R, own_g, opp_g, body.standoff_km)
    grids_needed = []

    async def field(src, at, eirp, rx_h):
        """Level raster at every candidate from a pseudo-transmitter at 'at' with 'eirp', received at rx_h."""
        radius = haversine_km(here[0], here[1], *pos(at)) + R + 2
        cov = await emo_api.coverage_for(_pseudo(src, at, pos(at), eirp, radius), pos(at), rx_h)
        return sample(cov, LA, LO)

    users = [e for e in ents.values() if e.get("net") == net["id"] and e["kind"] == "receiver"]
    if body.kind == "net":
        nsens = net.get("sens_dbm") or p.default_sens
        jsreq = net["js_req_db"] if net.get("js_req_db") is not None else p.js_req_db
        nb = emo_api.band(net)
        sensors = [e for e in ents.values() if e["kind"] == "sensor" and e["side"] == opp and emo_api.overlap(*nb, *emo_api.band(e))]
        jammers = [e for e in ents.values() if e["kind"] == "effector" and e["side"] == opp and e["active"] and emo_api.overlap(*nb, *emo_api.band(e))]
        S = [await field(net, u, net["eirp_dbm"], net["h_agl"]) for u in users]          # control -> user, by reciprocity
        link = np.minimum.reduce([s - nsens for s in S]) if S else np.full(LA.shape, 99.0)
        closed = sum((s - nsens >= 6).astype(int) for s in S) if S else np.zeros(LA.shape, int)
        E = [await field(net, x, net["eirp_dbm"], net["h_agl"]) - (x.get("sens_dbm") or p.default_sens) for x in sensors]
        exposure = np.maximum.reduce(E) if E else np.full(LA.shape, -99.0)
        # jamming at the users is fixed; at the control it is J(c) against the weakest user's return signal
        J_user = {}
        for u in users:
            J_user[u["id"]] = max([await emo_api.p2p_level(j, pos(j), u, pos(u)) - emo_api.jam_penalty(j, net) for j in jammers], default=-999)
        js_users = np.maximum.reduce([J_user[u["id"]] - S[i] for i, u in enumerate(users)]) if users and jammers else np.full(LA.shape, -99.0)
        Jc = np.maximum.reduce([sample(await emo_api.coverage_for(j, pos(j), net["h_agl"]), LA, LO) - emo_api.jam_penalty(j, net) for j in jammers]) if jammers else np.full(LA.shape, -999.0)
        back = np.minimum.reduce([S[i] + ((u.get("eirp_dbm") or net["eirp_dbm"]) - net["eirp_dbm"]) for i, u in enumerate(users)]) if users else np.full(LA.shape, 0.0)
        js = np.maximum(js_users, Jc - back)
        headroom = np.maximum(0.0, link - 6)
        score = 10 * closed - 3 * np.maximum(0.0, 6 - link) - 1.5 * np.maximum(0.0, exposure + 6) - 2 * np.maximum(0.0, js - jsreq + 6)
        ok = ok & np.isfinite(score)
        best = _best_points(score, LA, LO, ok)
        for b in best:
            i, j = b.pop("ij")
            b.update({"users_closed": int(closed[i, j]), "of_users": len(users), "link_margin_db": round(float(link[i, j]), 1),
                      "exposure_db": round(float(exposure[i, j]), 1), "worst_js_db": round(float(js[i, j]), 1),
                      "power_cut_db": round(float(headroom[i, j]), 1),
                      "heard_by": [sensors[k]["name"] for k in range(len(sensors)) if E[k][i, j] >= 0],
                      "where": _describe((b["lat"], b["lon"]), net["name"] + " (current)", here)})
        layers = {"score": _heat_png(score, ok), "exposure": _heat_png(-exposure, ok), "link": _heat_png(link, ok)}
        meta = {"opp_sensors": [s["name"] for s in sensors], "opp_jammers": [j["name"] for j in jammers], "users": [u["name"] for u in users],
                "unavoidable": [sensors[k]["name"] for k in range(len(sensors)) if bool(np.all((E[k] - headroom)[ok] >= 0))] if sensors and ok.any() else []}
    else:
        jsreq = net["js_req_db"] if net.get("js_req_db") is not None else p.js_req_db
        pen = emo_api.jam_penalty(y, net)
        S_user = {u["id"]: (float(net["fixed_level_dbm"]) if net.get("fixed_level_dbm") is not None
                            else await emo_api.p2p_level(net, pos(net), u, pos(u))) for u in users}
        JS = [await field(y, u, y["eirp_dbm"], y["h_agl"]) - pen - S_user[u["id"]] for u in users]   # jammer -> user, by reciprocity
        denied = sum((x >= jsreq).astype(int) for x in JS) if JS else np.zeros(LA.shape, int)
        minjs = np.minimum.reduce(JS) if JS else np.full(LA.shape, -99.0)
        df = [e for e in ents.values() if e["kind"] == "sensor" and e["side"] == net["side"] and e.get("df_rms_deg") and emo_api.overlap(*emo_api.band(y), *emo_api.band(e))]
        E = [await field(y, x, y["eirp_dbm"], y["h_agl"]) - (x.get("sens_dbm") or p.default_sens) for x in df]
        exposure = np.maximum.reduce(E) if E else np.full(LA.shape, -99.0)
        own_nets = [n for n in ents.values() if n["kind"] == "emitter" and n["side"] == side and n["active"] and n.get("fixed_level_dbm") is None and emo_api.overlap(*emo_api.band(y), *emo_api.band(n))]
        frat = np.zeros(LA.shape, int)
        for n in own_nets:
            jreq = n["js_req_db"] if n.get("js_req_db") is not None else p.js_req_db
            for u in [u for u in ents.values() if u.get("net") == n["id"]]:
                Sown = await emo_api.p2p_level(n, pos(n), u, pos(u))
                frat += ((await field(y, u, y["eirp_dbm"], y["h_agl"])) - emo_api.jam_penalty(y, n) - Sown >= jreq).astype(int)
        score = 10 * denied - 1.0 * np.maximum(0.0, exposure + 6) - 15 * frat + 0.2 * np.clip(minjs, -30, 30)
        ok = ok & np.isfinite(score)
        best = _best_points(score, LA, LO, ok)
        for b in best:
            i, j = b.pop("ij")
            b.update({"denied": int(denied[i, j]), "of_users": len(users), "min_js_db": round(float(minjs[i, j]), 1),
                      "exposure_db": round(float(exposure[i, j]), 1), "fratricide": int(frat[i, j]),
                      "where": _describe((b["lat"], b["lon"]), y["name"] + " (current)", here)})
        layers = {"score": _heat_png(score, ok), "exposure": _heat_png(-exposure, ok), "denial": _heat_png(denied.astype(float), ok)}
        meta = {"opp_df": [d["name"] for d in df], "own_nets_same_band": [n["name"] for n in own_nets], "users": [u["name"] for u in users]}
    return {"kind": body.kind, "name": mover["name"], "target_net": net["name"] if body.kind == "ea" else None,
            "bounds": bounds, "layers": layers, "best": best, "allowed_km2": round(float(ok.sum()) * (2 * R / body.px) ** 2, 0),
            **meta, "legend": "Heatmap: green = better site, red = worse; blank = outside reach, inside stand-off, or on the other side.",
            "notes": "Reciprocity score map (screening-grade terrain). Users are kept where they are. Positions to test, not a solution."}
