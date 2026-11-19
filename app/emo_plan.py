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
    return {**src, "id": f"rcp:{src['id']}:{at['id']}:{int(min(100.0, radius_km))}", "updated_at": f"{src['updated_at']}|{at['updated_at']}",
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
    t = np.nan_to_num(np.clip((s - lo) / max(1e-6, hi - lo), 0, 1), nan=0.0)   # NaN outside the allowed area: alpha 0 below
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
                      "heard_at_min_power": [sensors[k]["name"] for k in range(len(sensors)) if E[k][i, j] - headroom[i, j] >= 0],
                      "where": _describe((b["lat"], b["lon"]), net["name"] + " (current)", here)})
        i0, j0 = LA.shape[0] // 2, LA.shape[1] // 2
        current = {"score": round(float(score[i0, j0]), 1), "users_closed": int(closed[i0, j0]), "of_users": len(users),
                   "link_margin_db": round(float(link[i0, j0]), 1), "exposure_db": round(float(exposure[i0, j0]), 1),
                   "worst_js_db": round(float(js[i0, j0]), 1), "power_cut_db": round(float(headroom[i0, j0]), 1),
                   "heard_by": [sensors[k]["name"] for k in range(len(sensors)) if E[k][i0, j0] >= 0],
                   "heard_at_min_power": [sensors[k]["name"] for k in range(len(sensors)) if E[k][i0, j0] - headroom[i0, j0] >= 0]}
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
        i0, j0 = LA.shape[0] // 2, LA.shape[1] // 2
        current = {"score": round(float(score[i0, j0]), 1), "denied": int(denied[i0, j0]), "of_users": len(users),
                   "min_js_db": round(float(minjs[i0, j0]), 1), "exposure_db": round(float(exposure[i0, j0]), 1), "fratricide": int(frat[i0, j0])}
        layers = {"score": _heat_png(score, ok), "exposure": _heat_png(-exposure, ok), "denial": _heat_png(denied.astype(float), ok)}
        meta = {"opp_df": [d["name"] for d in df], "own_nets_same_band": [n["name"] for n in own_nets], "users": [u["name"] for u in users]}
    return {"kind": body.kind, "name": mover["name"], "target_net": net["name"] if body.kind == "ea" else None, "current": current,
            "js_req_db": jsreq,
            "bounds": bounds, "layers": layers, "best": best, "allowed_km2": round(float(ok.sum()) * (2 * R / body.px) ** 2, 0),
            **meta, "legend": "Heatmap: green = better site, red = worse; blank = outside reach, inside stand-off, or on the other side.",
            "notes": "Reciprocity score map (screening-grade terrain). Users are kept where they are. Positions to test, not a solution."}


# ---- A4: red (or blue) course-of-action generator: MLCOA / MDCOA ----------------------------------------------
class CoaIn(BaseModel):
    side: str = Field(default="red", pattern="^(blue|red)$")     # the side that responds
    coa: str = Field(pattern="^(mlcoa|mdcoa)$")


_SNAP: dict = {}     # side -> {entity id: (lat, lon)} before the last COA, for revert


def _hq_net(ents, side):
    """The opposing side's highest-value net: an emitter with outstations; prefer names containing HQ, then most users."""
    nets = [e for e in ents.values() if e["side"] == side and e["kind"] == "emitter" and e.get("fixed_level_dbm") is None
            and any(u.get("net") == e["id"] for u in ents.values())]
    if not nets:
        return None
    return sorted(nets, key=lambda n: (("HQ" not in n["name"]), -sum(1 for u in ents.values() if u.get("net") == n["id"])))[0]


async def _df_site(emo_api, ents, p, pos, sensor, target, partners, max_move, standoff):
    """Best site for a DF sensor to hear 'target' with a good cut angle against its partner DF sites."""
    import numpy as np
    from .ems_core import sample
    from .sdr_classify import bearing
    here = pos(sensor)
    LA, LO, _ = _axes(here, max_move, 60)
    own_g, opp_g = _ground(ents, pos, sensor["side"]), _ground(ents, pos, target["side"])
    ok = _mask(LA, LO, here, max_move, own_g, opp_g, standoff)
    tp = pos(target)
    radius = min(100.0, __import__("app.sdr_classify", fromlist=["haversine_km"]).haversine_km(here[0], here[1], *tp) + max_move + 2)
    E = sample(await emo_api.coverage_for(_pseudo(target, target, tp, target["eirp_dbm"], radius), tp, sensor["h_agl"]), LA, LO) - (sensor.get("sens_dbm") or p.default_sens)
    # cut angle with the nearest partner: bearing from candidate to target vs partner to target
    cut = np.zeros(LA.shape)
    if partners:
        pb = [bearing(pos(q)[0], pos(q)[1], tp[0], tp[1]) for q in partners]
        b = (np.degrees(np.arctan2(np.sin(np.radians(tp[1] - LO)) * np.cos(np.radians(tp[0])),
                                   np.cos(np.radians(LA)) * np.sin(np.radians(tp[0])) - np.sin(np.radians(LA)) * np.cos(np.radians(tp[0])) * np.cos(np.radians(tp[1] - LO)))) + 360) % 360
        cuts = [np.minimum(np.abs((b - x + 180) % 360 - 180), 180 - np.abs((b - x + 180) % 360 - 180)) for x in pb]
        cut = np.maximum.reduce(cuts)
    score = np.minimum(E, 20) - 0.15 * np.abs(cut - 90) if partners else np.minimum(E, 20)
    score = np.where(E >= 0, score, -99)
    ok = ok & np.isfinite(score)
    best = _best_points(score, LA, LO, ok, n=1)
    i0, j0 = LA.shape[0] // 2, LA.shape[1] // 2
    cur = {"score": round(float(score[i0, j0]), 1), "hear_db": round(float(E[i0, j0]), 1), "cut_deg": round(float(cut[i0, j0]), 0)}
    if best:
        i, j = best[0].pop("ij")
        best[0].update({"hear_db": round(float(E[i, j]), 1), "cut_deg": round(float(cut[i, j]), 0)})
    return cur, (best[0] if best else None)


@router.post("/coa")
async def red_coa(body: CoaIn, t_min: float = 0):
    """Generate and APPLY a course of action for one side: MLCOA = modest improvements to the current laydown (few moves,
    short distances, only if clearly better); MDCOA = each jammer and DF site re-sited to hurt the other side's
    highest-value net most. Positions are changed in the scenario; /coa/revert restores them."""
    emo_api, ents, p, pos = _ctx(t_min)
    side, opp = body.side, ("blue" if body.side == "red" else "red")
    ml = body.coa == "mlcoa"
    max_move, standoff, gain_needed, max_moves = (15.0, 10.0, 8.0, 2) if ml else (40.0, 10.0, 0.5, 99)
    target = _hq_net(ents, opp)
    if not target:
        raise HTTPException(400, f"{opp} has no net to target")
    if len(_SNAP) >= 80:
        _SNAP.pop(next(iter(_SNAP)))
    _SNAP[(emo_api.WS.get(), side)] = {e["id"]: (e["lat"], e["lon"]) for e in ents.values() if e["side"] == side}
    moves = []
    # units on a track are left alone: moving the start point would redraw the route and change the timeline
    # (same rule as the joint re-site)
    tracked = lambda e: bool(e.get("track")) and bool(e.get("speed_kmh"))  # noqa: E731
    # jammers: against the opposing net they can affect, preferring the HQ net
    for y in [e for e in ents.values() if e["side"] == side and e["kind"] == "effector" and e["active"] and not tracked(e)]:
        nets = [n for n in ents.values() if n["side"] == opp and n["kind"] == "emitter" and emo_api.overlap(*emo_api.band(y), *emo_api.band(n))
                and any(u.get("net") == n["id"] for u in ents.values())]
        if not nets:
            continue
        tgt = target if target in nets else sorted(nets, key=lambda n: -sum(1 for u in ents.values() if u.get("net") == n["id"]))[0]
        m = await plan_map(MapIn(kind="ea", name=y["name"], target_net=tgt["name"], max_move_km=max_move, standoff_km=standoff, px=48), t_min=t_min)
        if m["best"] and m["best"][0]["score"] - m["current"]["score"] >= gain_needed:
            b = m["best"][0]
            moves.append({"entity": y["name"], "id": y["id"], "kind": "effector", "from": pos(y), "to": (b["lat"], b["lon"]),
                          "where": b["where"], "against": tgt["name"], "gain": round(b["score"] - m["current"]["score"], 1),
                          "detail": f"denies {b['denied']}/{b['of_users']} (was {m['current']['denied']}), exposure {b['exposure_db']:+} dB"})
    # DF sites: hear the opposing HQ net best with a good cut angle against the other DF sites
    dfs = [e for e in ents.values() if e["side"] == side and e["kind"] == "sensor" and e.get("df_rms_deg") and e["h_agl"] < 300
           and emo_api.overlap(*emo_api.band(target), *emo_api.band(e))]
    for d in [q for q in dfs if not tracked(q)]:          # tracked DF sites still count for the cut angle, but stay put
        cur, best = await _df_site(emo_api, ents, p, pos, d, target, [q for q in dfs if q is not d], max_move, standoff)
        if best and best["score"] - cur["score"] >= gain_needed:
            moves.append({"entity": d["name"], "id": d["id"], "kind": "sensor", "from": pos(d), "to": (best["lat"], best["lon"]),
                          "where": _describe((best["lat"], best["lon"]), d["name"] + " (current)", pos(d)), "against": target["name"],
                          "gain": round(best["score"] - cur["score"], 1),
                          "detail": f"hears {target['name']} at {best['hear_db']:+} dB (was {cur['hear_db']:+}), cut {best['cut_deg']:.0f} deg (was {cur['cut_deg']:.0f})"})
    moves.sort(key=lambda m: -m["gain"])
    moves = moves[:max_moves]
    from .db import get_db, now_iso
    with get_db().tx() as c:
        for m in moves:
            c.execute("UPDATE emo_entities SET lat=?, lon=?, updated_at=? WHERE id=?", (m["to"][0], m["to"][1], now_iso(), m["id"]))
    before = emo_api._LAST.get("score")
    res = await emo_api.run(emo_api.RunIn(**{k: v for k, v in emo_api._LAST["params"].model_dump().items()}), t_min=t_min)
    return {"side": side, "coa": body.coa, "target": target["name"], "moves": moves, "score_before": before, "score_after": res["score"],
            "notes": ("MLCOA: at most two moves within 15 km, each only if clearly better. " if ml else
                      "MDCOA: every jammer and DF site re-sited within 40 km for greatest effect on the other side's highest-value net. ")
                     + "Units on a track are not moved. Applied to the scenario; use revert to restore."}


@router.post("/coa/revert")
async def coa_revert(side: str = "red", t_min: float = 0):
    emo_api, ents, p, pos = _ctx(t_min)
    snap = _SNAP.pop((emo_api.WS.get(), side), None)
    if not snap:
        raise HTTPException(404, "nothing to revert")
    from .db import get_db, now_iso
    with get_db().tx() as c:
        for eid, (la, lo) in snap.items():
            c.execute("UPDATE emo_entities SET lat=?, lon=?, updated_at=? WHERE id=?", (la, lo, now_iso(), eid))
    res = await emo_api.run(emo_api.RunIn(**emo_api._LAST["params"].model_dump()), t_min=t_min)
    return {"reverted": len(snap), "score": res["score"]}


# ---- A3/A6: timeline of the EM fight: advantage windows and route survivability -----------------------------
class TimelineIn(BaseModel):
    step_min: float = Field(default=10, ge=1, le=120)
    max_steps: int = Field(default=24, ge=2, le=60)
    net: str | None = None            # net to report advantage windows for (control station name)


@router.post("/timeline")
async def timeline(body: TimelineIn):
    """Step the scenario in time with the light analysis (pairwise only) and record, for every emitter and net user,
    whether it was heard, targetable or denied at each step. Windows: intervals when the chosen net's control
    station is undetected and none of its users is denied."""
    from . import emo_api
    ents = {e["id"]: e for e in emo_api._all()}
    if not ents:
        raise HTTPException(400, "no entities")
    if not emo_api._LAST:
        raise HTTPException(409, "run the analysis first")
    p = emo_api._LAST["params"]
    horizon = max([emo_api.track_minutes(e) for e in ents.values()] + [0.0])
    steps = [round(i * body.step_min, 1) for i in range(body.max_steps) if i * body.step_min <= horizon + body.step_min]
    rows = {}
    for e in ents.values():
        if e["kind"] in ("emitter", "effector", "receiver") and e.get("fixed_level_dbm") is None:
            rows[e["name"]] = {"side": e["side"], "kind": e["kind"], "tracked": bool(e.get("track")), "heard": [], "targetable": [], "denied": [], "heard_by": []}
    board = []
    for tm in steps:
        r = await emo_api.run(p, t_min=tm, light=True, keep=False)
        heard = {}
        for d in r["detections"]:
            if d["detected"] and d["sensor_side"] != "grey":
                heard.setdefault(d["target"], []).append(d["sensor"])
        tgt = {f["target"] for f in r["fixes"] if f["targetable"]}
        den = {j["victim"] for j in r["jamming"] if j["status"] == "denied"}
        for name, row in rows.items():
            row["heard"].append(name in heard)
            row["heard_by"].append(heard.get(name, []))
            row["targetable"].append(name in tgt)
            row["denied"].append(name in den)
        m = r.get("met") or {}
        board.append({"t": tm, **{sd: r["score"][sd] for sd in ("blue", "red")},
                      "met": {"valid_time": m.get("valid_time"), **(m.get("used") or {}), "refraction": m.get("refraction"),
                              "ducts": len(m.get("ducts") or []) + (1 if (m.get("evap_duct") or {}).get("height_m", 0) >= 4 else 0)}})
    windows = None
    if body.net and body.net in rows:
        ctrl = rows[body.net]
        net_id = next(e["id"] for e in ents.values() if e["name"] == body.net)
        users = [n for n, e in ((x["name"], x) for x in ents.values()) if e.get("net") == net_id and n in rows]
        good = [not ctrl["heard"][i] and not any(rows[u]["denied"][i] for u in users) for i in range(len(steps))]
        undetected = [not ctrl["heard"][i] for i in range(len(steps))]
        undenied = [not any(rows[u]["denied"][i] for u in users) for i in range(len(steps))]
        def spans(flags):
            out, start = [], None
            for i, f in enumerate(flags + [False]):
                if f and start is None:
                    start = i
                if not f and start is not None:
                    out.append({"from_min": steps[start], "to_min": steps[min(i, len(steps) - 1)], "steps": i - start}); start = None
            return out
        windows = {"net": body.net, "users": users, "advantage": spans(good), "undetected": spans(undetected), "undenied": spans(undenied),
                   "summary": f"{sum(good)}/{len(steps)} steps with the control station undetected and no outstation denied; "
                              f"{sum(undetected)}/{len(steps)} undetected; {sum(undenied)}/{len(steps)} with no outstation denied."}
    return {"steps": steps, "step_min": body.step_min, "horizon_min": round(horizon, 1), "rows": rows, "board": board, "windows": windows,
            "notes": "Light analysis per step (pairwise terrain paths, no map rasters). Detected = detected by the other side's ES; "
                     "target-quality fix = DF fix within the targeting threshold; denied = a jammer beats the user's own net at that step. "
                     "With the forecast chosen, each step uses the met for its own hour (k-factor, rain, fog)."}


# ---- A5: more decision variables: power, antenna azimuth, channel, joint re-siting -------------------------------
class TuneIn(BaseModel):
    net: str


@router.post("/tune")
async def tune(body: TuneIn, t_min: float = 0):
    """Non-positional EP options for a net at its current position: minimum power, best sector antenna, and
    channels outside the opposing jammers' bands. Uses the pairwise terrain paths already computed (cheap)."""
    emo_api, ents, p, pos = _ctx(t_min)
    net = next((e for e in ents.values() if e["name"] == body.net and e["kind"] == "emitter"), None)
    if not net or net.get("eirp_dbm") is None:
        raise HTTPException(404, "net control not found")
    users = [e for e in ents.values() if e.get("net") == net["id"] and e["kind"] == "receiver"]
    opp = "red" if net["side"] == "blue" else "blue"
    nb = emo_api.band(net)
    sensors = [e for e in ents.values() if e["kind"] == "sensor" and e["side"] == opp and emo_api.overlap(*nb, *emo_api.band(e))]
    jammers = [e for e in ents.values() if e["kind"] == "effector" and e["side"] == opp and e["active"]]
    nsens = net.get("sens_dbm") or p.default_sens
    omni = {**net, "pattern": "omni"}
    S = {u["id"]: await emo_api.p2p_level(omni, pos(net), u, pos(u)) for u in users}          # omni levels at users
    E = {x["id"]: await emo_api.p2p_level(omni, pos(net), x, pos(x)) - (x.get("sens_dbm") or p.default_sens) for x in sensors}
    # 1. power: cut by the weakest user's spare margin
    headroom = max(0.0, min((s - nsens for s in S.values()), default=0.0) - 6)
    power = {"current_eirp_dbm": net["eirp_dbm"], "recommended_eirp_dbm": round(net["eirp_dbm"] - headroom, 1), "cut_db": round(headroom, 1),
             "heard_by_after": [x["name"] for x in sensors if E[x["id"]] - headroom >= 0],
             "heard_by_now": [x["name"] for x in sensors if E[x["id"]] >= 0]}
    # 2. antenna: sector azimuth and beamwidth, scored on users kept and sensors dropped
    from .coverage_core import sector_atten_db
    from .link_core import bearing_deg
    import numpy as np
    best = None
    here = pos(net)
    for bw in (60, 90, 120):
        for az in range(0, 360, 10):
            def att(target_pos):
                off = abs((bearing_deg(here[0], here[1], target_pos[0], target_pos[1]) - az + 180) % 360 - 180)
                return float(sector_atten_db(np.array([off]), bw)[0])
            closed = sum(1 for u in users if S[u["id"]] - att(pos(u)) - nsens >= 6)
            heard = [x["name"] for x in sensors if E[x["id"]] - att(pos(x)) >= 0]
            worst = max((E[x["id"]] - att(pos(x)) for x in sensors), default=-99.0)
            sc = 10 * closed - 1.5 * max(0.0, worst + 6) - 0.02 * bw
            if best is None or sc > best["score"]:
                best = {"azimuth": az, "beamwidth": bw, "users_closed": closed, "of_users": len(users), "heard_by": heard,
                        "worst_exposure_db": round(worst, 1), "score": round(sc, 1)}
    omni_state = {"users_closed": sum(1 for u in users if S[u["id"]] - nsens >= 6), "heard_by": [x["name"] for x in sensors if E[x["id"]] >= 0],
                  "worst_exposure_db": round(max(E.values(), default=-99.0), 1)}
    # 3. channel: same band class, outside every opposing jammer's band
    lo_c, hi_c = (30.0, 88.0) if nb[0] < 88e6 else (225.0, 400.0) if nb[0] < 400e6 else (nb[0] / 1e6 * 0.9, nb[1] / 1e6 * 1.1)
    cands = []
    for f in [round(lo_c + i * (hi_c - lo_c) / 40, 2) for i in range(41)]:
        fb = (f * 1e6 - (net["bw_khz"] or 25) * 500, f * 1e6 + (net["bw_khz"] or 25) * 500)
        jam = [j["name"] for j in jammers if emo_api.overlap(*fb, *emo_api.band(j))]
        sens = [x["name"] for x in ents.values() if x["kind"] == "sensor" and x["side"] == opp and emo_api.overlap(*fb, *emo_api.band(x))]
        cands.append({"freq_mhz": f, "jammed_by": jam, "sensed_by": sens})
    clear = [c for c in cands if not c["jammed_by"]]
    channel = {"current_mhz": net["freq_mhz"], "current_jammed_by": [j["name"] for j in jammers if emo_api.overlap(*nb, *emo_api.band(j))],
               "clear_of_jammers": [c["freq_mhz"] for c in clear][:12], "still_sensed_by": sorted({s for c in clear for s in c["sensed_by"]}),
               "note": "Channel changes avoid jammer bands; ES receivers usually cover the whole band, so a channel change rarely hides the net."}
    return {"net": net["name"], "power": power, "antenna": {"omni_now": omni_state, "best_sector": best}, "channel": channel,
            "notes": "Computed at the current position from the pairwise terrain paths. Power cut keeps 6 dB user margin. Antenna "
                     "uses the model's sector pattern (front-to-back about 25 dB). Screening-grade."}


class ApplyIn(BaseModel):
    net: str
    eirp_dbm: float | None = None
    azimuth: float | None = None
    beamwidth: float | None = None
    freq_mhz: float | None = None


@router.post("/tune/apply")
async def tune_apply(body: ApplyIn, t_min: float = 0):
    emo_api, ents, p, pos = _ctx(t_min)
    net = next((e for e in ents.values() if e["name"] == body.net and e["kind"] == "emitter"), None)
    if not net:
        raise HTTPException(404, "net control not found")
    from .db import get_db, now_iso
    users = [e for e in ents.values() if e.get("net") == net["id"]]
    with get_db().tx() as c:
        if body.eirp_dbm is not None:
            c.execute("UPDATE emo_entities SET eirp_dbm=?, updated_at=? WHERE id=?", (body.eirp_dbm, now_iso(), net["id"]))
        if body.azimuth is not None:
            c.execute("UPDATE emo_entities SET pattern='sector', azimuth=?, beamwidth=?, updated_at=? WHERE id=?",
                      (body.azimuth, body.beamwidth or 90, now_iso(), net["id"]))
        if body.freq_mhz is not None:
            for e in [net] + users:
                c.execute("UPDATE emo_entities SET freq_mhz=?, updated_at=? WHERE id=?", (body.freq_mhz, now_iso(), e["id"]))
    return {"applied": body.model_dump(exclude_none=True), "users_retuned": len(users) if body.freq_mhz is not None else 0}


class JointIn(BaseModel):
    net: str
    user_move_km: float = Field(default=10, gt=1, le=40)
    ctrl_move_km: float = Field(default=30, gt=1, le=60)
    standoff_km: float = Field(default=10, ge=0, le=50)


@router.post("/joint")
async def joint(body: JointIn, t_min: float = 0):
    """Greedy joint re-siting of a net: each static user moves to its best nearby site (link from the control station,
    its own exposure, jamming), then the control station is re-sited with the score map. Moves are APPLIED; the
    result lists them with before/after scoreboards. Use a COA snapshot first if you want to compare."""
    import numpy as np
    from .ems_core import sample
    from .sdr_classify import haversine_km
    emo_api, ents, p, pos = _ctx(t_min)
    net = next((e for e in ents.values() if e["name"] == body.net and e["kind"] == "emitter"), None)
    if not net or net.get("fixed_level_dbm") is not None:
        raise HTTPException(404, "net control not found")
    opp = "red" if net["side"] == "blue" else "blue"
    nb = emo_api.band(net)
    nsens = net.get("sens_dbm") or p.default_sens
    sensors = [e for e in ents.values() if e["kind"] == "sensor" and e["side"] == opp and emo_api.overlap(*nb, *emo_api.band(e))]
    jammers = [e for e in ents.values() if e["kind"] == "effector" and e["side"] == opp and e["active"] and emo_api.overlap(*nb, *emo_api.band(e))]
    users = [e for e in ents.values() if e.get("net") == net["id"] and e["kind"] == "receiver" and not e.get("track")]
    own_g, opp_g = _ground(ents, pos, net["side"]), _ground(ents, pos, opp)
    from .db import get_db, now_iso
    before = emo_api._LAST.get("score")
    bad_before = {j["victim"] for j in emo_api._LAST["jamming"] if j["net"] == net["name"] and j["status"] in ("denied", "no link")}
    moves = []
    ctrl = pos(net)
    for u in users:
        here = pos(u)
        R = body.user_move_km
        LA, LO, _ = _axes(here, R, 48)
        ok = _mask(LA, LO, here, R, own_g, opp_g, body.standoff_km)
        rad = min(100.0, haversine_km(here[0], here[1], *ctrl) + R + 2)
        link = sample(await emo_api.coverage_for(_pseudo(net, net, ctrl, net["eirp_dbm"], rad), ctrl, u["h_agl"]), LA, LO) - nsens
        exp = np.full(LA.shape, -99.0)
        if u.get("eirp_dbm") is not None:
            for x in sensors:
                r2 = min(100.0, haversine_km(here[0], here[1], *pos(x)) + R + 2)
                exp = np.maximum(exp, sample(await emo_api.coverage_for(_pseudo(u, x, pos(x), u["eirp_dbm"], r2), pos(x), u["h_agl"]), LA, LO) - (x.get("sens_dbm") or p.default_sens))
        js = np.full(LA.shape, -99.0)
        for j in jammers:
            js = np.maximum(js, sample(await emo_api.coverage_for(j, pos(j), u["h_agl"]), LA, LO) - emo_api.jam_penalty(j, net) - (link + nsens))
        jsreq = net["js_req_db"] if net.get("js_req_db") is not None else p.js_req_db
        score = 10 * (link >= 6) - 3 * np.maximum(0.0, 6 - link) - 1.5 * np.maximum(0.0, exp + 6) - 2 * np.maximum(0.0, js - jsreq + 6)
        ok = ok & np.isfinite(score)
        i0, j0 = LA.shape[0] // 2, LA.shape[1] // 2
        best = _best_points(score, LA, LO, ok, n=1, min_sep_km=1.0)
        if best and best[0]["score"] - float(score[i0, j0]) >= 5:
            b = best[0]; i, j = b.pop("ij")
            with get_db().tx() as c:
                c.execute("UPDATE emo_entities SET lat=?, lon=?, updated_at=? WHERE id=?", (b["lat"], b["lon"], now_iso(), u["id"]))
            moves.append({"entity": u["name"], "from": here, "to": (b["lat"], b["lon"]), "where": _describe((b["lat"], b["lon"]), u["name"] + " (current)", here),
                          "detail": f"link {float(link[i, j]):+.1f} dB (was {float(link[i0, j0]):+.1f}), exposure {float(exp[i, j]):+.1f} dB (was {float(exp[i0, j0]):+.1f}), J/S {float(js[i, j]):+.1f} dB"})
    # control station last, against the users' new positions
    await emo_api.run(emo_api.RunIn(**emo_api._LAST["params"].model_dump()), t_min=t_min)
    m = await plan_map(MapIn(kind="net", name=net["name"], max_move_km=body.ctrl_move_km, standoff_km=body.standoff_km, px=60), t_min=t_min)
    if m["best"] and m["best"][0]["score"] - m["current"]["score"] >= 5:
        b = m["best"][0]
        with get_db().tx() as c:
            c.execute("UPDATE emo_entities SET lat=?, lon=?, updated_at=? WHERE id=?", (b["lat"], b["lon"], now_iso(), net["id"]))
        moves.append({"entity": net["name"], "from": ctrl, "to": (b["lat"], b["lon"]), "where": b["where"],
                      "detail": f"{b['users_closed']}/{b['of_users']} outstations linked, exposure {b['exposure_db']:+} dB (was {m['current']['exposure_db']:+}), J/S {b['worst_js_db']:+} dB"})
    # verify with the exact pairwise model: no user of this net may end up newly denied or without signal
    def bad(r):
        return {j["victim"] for j in r["jamming"] if j["net"] == net["name"] and j["status"] in ("denied", "no link")}
    res = await emo_api.run(emo_api.RunIn(**emo_api._LAST["params"].model_dump()), t_min=t_min)
    rejected = []
    newly = bad(res) - bad_before
    if newly and moves and moves[-1]["entity"] == net["name"]:
        m = moves.pop()
        with get_db().tx() as c:
            c.execute("UPDATE emo_entities SET lat=?, lon=?, updated_at=? WHERE id=?", (m["from"][0], m["from"][1], now_iso(), net["id"]))
        rejected.append(f"{net['name']} move rejected: {', '.join(sorted(newly))} would be denied or lose signal")
        res = await emo_api.run(emo_api.RunIn(**emo_api._LAST["params"].model_dump()), t_min=t_min)
        newly = bad(res) - bad_before
    if newly and moves:
        with get_db().tx() as c:
            for m in moves:
                c.execute("UPDATE emo_entities SET lat=?, lon=?, updated_at=? WHERE id=?", (m["from"][0], m["from"][1], now_iso(), next(e["id"] for e in ents.values() if e["name"] == m["entity"])))
        rejected.append(f"all moves reverted: {', '.join(sorted(newly))} would be denied or lose signal")
        moves = []
        res = await emo_api.run(emo_api.RunIn(**emo_api._LAST["params"].model_dump()), t_min=t_min)
    return {"net": net["name"], "moves": moves, "rejected": rejected, "score_before": before, "score_after": res["score"],
            "notes": "Greedy: users first (static ones only), then the control station; each move only if clearly better (5 points), "
                     "then verified with the exact pairwise model. Applied to the scenario."}
