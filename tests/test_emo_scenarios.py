"""Scenario-level EMO tests on synthetic terrain (audit finding 8).

A throw-away SQLite database and a smooth analytic terrain stand in for the box's DB and the Copernicus tiles, so
these run anywhere with no network. They cover every example (light runs), one full run with the Word export, the
red COA generator's handling of tracked units, workspace scoping and the undo list.
"""
import asyncio
import io
import math

import numpy as np
import pytest


def _hill(la, lo):
    """Rolling hills, 20 to 140 m, wavelength of roughly 10 km."""
    return np.maximum(0.0, 80 + 60 * np.sin(np.asarray(la, float) * 40.0) * np.cos(np.asarray(lo, float) * 30.0))


@pytest.fixture
def emo(tmp_path, monkeypatch):
    from app import config, db as dbm, dem
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(dbm, "_db", dbm.Database(str(tmp_path / "t.sqlite3")))
    monkeypatch.setattr(dem, "heights", lambda pts: [float(_hill(a, b)) for a, b in pts])
    monkeypatch.setattr(dem, "grid_sampler", lambda s, w, n, e, res_deg=1 / 1800: (lambda la, lo: _hill(la, lo).astype(np.float32)))
    from app import emo_api
    emo_api.ensure_emo_schema(dbm.get_db())
    emo_api._P2P.clear(); emo_api._COV.clear(); emo_api._LAST_BY_WS.clear()
    monkeypatch.setattr(emo_api, "_HEAVY", asyncio.Semaphore(3))      # a fresh semaphore for this test's event loop
    yield emo_api
    emo_api._P2P.clear(); emo_api._COV.clear(); emo_api._LAST_BY_WS.clear()
    dbm.get_db()._conn.close()


def _check_consistent(name, r, ents, emo_api):
    assert r["notes"] == emo_api.MODEL_CAVEAT, name
    users = {e["id"] for e in ents if e["kind"] == "receiver" and e.get("net")}
    assert {lk["receiver_id"] for lk in r["links"]} == users, name
    bad = {j["victim_id"] for j in r["jamming"] if j["status"] in ("denied", "no link", "deceived")}
    for sd in ("blue", "red"):
        mine = [lk for lk in r["links"] if lk["side"] == sd]
        sc = r["score"][sd]
        if not mine:
            assert sc["net_availability_pct"] is None, name
            continue
        ok = sum(1 for lk in mine if lk["linked"] and lk["receiver_id"] not in bad)
        assert sc["net_availability_pct"] == round(100 * ok / len(mine), 0), name
        assert sc["net_users_unlinked"] == sum(1 for lk in mine if not lk["linked"]), name
    for lk in r["links"]:
        if lk["status"] == "out of range":
            assert lk["margin_db"] < 0, name
    for f in r["fixes"]:
        assert not (f["target_side"] == "grey" and f["targetable"]), name     # civil is located, never a target
    for d in r["detections"] + r["jamming"]:
        assert 0 <= d["p"] <= 100, name
    for rd in r["radar"]:
        j = rd["jam"]
        if j and j["burnthrough_km"] is not None:
            k = 20 if j["mode"] == "self-screening" else 40
            assert math.isclose(j["burnthrough_km"], rd["range_km"] / 10 ** (j["js_db"] / k), rel_tol=0.02, abs_tol=0.2), name


def test_every_example_runs_and_scores_consistently(emo):
    from app.emo_examples import EXAMPLES

    async def go():
        out = {}
        for name in EXAMPLES:
            await emo.load_example(name)
            assert not emo._LAST, name                  # finding 11: the last scenario's analysis is gone
            r = await emo.run(emo.RunIn(), light=True)
            out[name] = (r, emo._all())
        return out
    res = asyncio.run(go())
    assert len(res) >= 10
    for name, (r, ents) in res.items():
        _check_consistent(name, r, ents, emo)


def _add(emo, **kw):
    base = {"kind": "emitter", "category": "comms", "h_agl": 2, "freq_mhz": 50.0, "bw_khz": 25}
    base.update(kw)
    return emo._upsert(emo.EntityIn(**base), None)


def test_user_out_of_reach_or_with_control_off_air_is_unavailable(emo, monkeypatch):
    """The audit probe: on flat ground a user 100 km from its control, with no jammer anywhere, scored 100%.
    UHF over flat land 100 m up: about -81 dBm at 2 km, about -148 dBm at 100 km, against -110 dBm."""
    from app import dem
    monkeypatch.setattr(dem, "heights", lambda pts: [100.0] * len(pts))
    ctl = _add(emo, name="Blue HQ", side="blue", lat=51.0, lon=-1.0, eirp_dbm=40, freq_mhz=400.0)
    near = _add(emo, name="Blue near", side="blue", kind="receiver", lat=51.02, lon=-1.0, freq_mhz=400.0)
    far = _add(emo, name="Blue far", side="blue", kind="receiver", lat=51.9, lon=-1.0, freq_mhz=400.0)
    with emo.get_db().tx() as c:
        c.execute("UPDATE emo_entities SET net=? WHERE id IN (?, ?)", (ctl["id"], near["id"], far["id"]))

    async def go():
        r1 = await emo.run(emo.RunIn(), light=True)
        await emo.set_active(ctl["id"], on=False)
        r2 = await emo.run(emo.RunIn(), light=True)
        return r1, r2
    r1, r2 = asyncio.run(go())
    st = {lk["receiver"]: lk["status"] for lk in r1["links"]}
    assert st == {"Blue near": "linked", "Blue far": "out of range"}
    assert r1["score"]["blue"]["net_availability_pct"] == 50
    assert {lk["status"] for lk in r2["links"]} == {"control off air"}
    assert r2["score"]["blue"]["net_availability_pct"] == 0


def test_full_run_and_word_export_leave_the_saved_analysis_alone(emo):
    from docx import Document

    async def go():
        await emo.load_example("solent-maritime")
        r = await emo.run(emo.RunIn(df_fix_good_m=800, sigma_db=6))
        saved = (emo._LAST["t"], emo._LAST["params"].model_dump())
        resp = await emo.emo_export(phases="0,20")
        body = b"".join([chunk async for chunk in resp.body_iterator])
        after = (emo._LAST["t"], emo._LAST["params"].model_dump())
        any_id = emo._all()[0]["id"]
        focus = await emo.focus(any_id, t_min=0)                      # planning calls still work (no 409)
        return r, saved, after, body, focus
    r, saved, after, body, focus = asyncio.run(go())
    assert r["layers"] and r["nets"]
    assert saved == after and saved[1]["df_fix_good_m"] == 800        # export used, and kept, the user's own settings
    assert focus["id"]
    text = "\n".join(p.text for p in Document(io.BytesIO(body)).paragraphs)
    assert "Not modelled" in text and "grey circles" in text and "fix within 800 m" in text
    heads = [p.text for p in Document(io.BytesIO(body)).paragraphs if p.style.name.startswith("Heading")]
    assert "Scoreboard" in heads and "Phase T+20 min" in heads


def test_schematic_draws_civil_entities_grey(emo):
    from PIL import Image
    res = {"bounds": [[50.0, -1.0], [51.0, 0.0]], "layers": {}, "jamming": [], "fixes": [], "positions": {"g": (50.5, -0.5), "r": (50.8, -0.8)}}
    ents = [{"id": "g", "side": "grey", "name": "", "lat": 50.5, "lon": -0.5}, {"id": "r", "side": "red", "name": "", "lat": 50.8, "lon": -0.8}]
    img = Image.open(io.BytesIO(emo._schematic_png(res, ents))).convert("RGB")
    W, H = img.size
    gx, gy = int(0.5 * W), int((51.0 - 50.5) / 1.0 * H)
    rx, ry = int(0.2 * W), int((51.0 - 50.8) / 1.0 * H)
    assert img.getpixel((gx, gy)) == (170, 180, 190)                   # grey circle, not a red diamond
    assert img.getpixel((rx, ry)) == (255, 70, 70)


def test_red_coa_leaves_tracked_units_where_they_are(emo, monkeypatch):
    from app import emo_plan
    ctl = _add(emo, name="Blue HQ", side="blue", lat=51.0, lon=-1.0, eirp_dbm=40)
    for i in range(2):
        u = _add(emo, name=f"Blue user {i}", side="blue", kind="receiver", lat=51.05 + i * 0.02, lon=-1.0)
        with emo.get_db().tx() as c:
            c.execute("UPDATE emo_entities SET net=? WHERE id=?", (ctl["id"], u["id"]))
    mover = _add(emo, name="Red jammer (static)", side="red", kind="effector", lat=51.2, lon=-1.1, eirp_dbm=50, bw_khz=2000)
    rolling = _add(emo, name="Red VHF spot", side="red", kind="effector", lat=51.25, lon=-1.2, eirp_dbm=50, bw_khz=25,
                   track=[[51.3, -1.2]], speed_kmh=12)
    calls = []

    async def fake_map(m, t_min=0):
        calls.append(m.name)
        return {"best": [{"score": 20.0, "lat": 51.15, "lon": -1.05, "where": "test point", "denied": 2, "of_users": 2, "exposure_db": 0.0}],
                "current": {"score": 0.0, "denied": 0}}

    async def go():
        await emo.run(emo.RunIn(), light=True)
        monkeypatch.setattr(emo_plan, "plan_map", fake_map)
        return await emo_plan.red_coa(emo_plan.CoaIn(side="red", coa="mlcoa"))
    out = asyncio.run(go())
    assert calls == ["Red jammer (static)"]                          # the tracked jammer is not even considered
    assert [m["entity"] for m in out["moves"]] == ["Red jammer (static)"]
    now = {e["id"]: (e["lat"], e["lon"]) for e in emo._all()}
    assert now[rolling["id"]] == (51.25, -1.2) and now[mover["id"]] == (51.15, -1.05)
    assert "not moved" in out["notes"]


def test_writes_are_scoped_to_the_workspace_and_rejections_leave_no_undo(emo):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    A, B = {"x-cyem-ws": "alpha"}, {"x-cyem-ws": "bravo"}
    body = {"name": "Blue HQ", "side": "blue", "kind": "emitter", "category": "comms", "lat": 51.0, "lon": -1.0,
            "freq_mhz": 50, "eirp_dbm": 40}
    eid = c.post("/api/emo", json=body, headers=A).json()["id"]
    c.post("/api/emo", json={**body, "name": "B2", "lat": 51.1}, headers=B)   # bravo holds something too
    assert c.post(f"/api/emo/{eid}/move", json={"lat": 52.0, "lon": -1.0}, headers=B).status_code == 404
    assert c.post(f"/api/emo/{eid}/active?on=false", headers=B).status_code == 404
    assert c.put(f"/api/emo/{eid}", json={**body, "name": "hijacked"}, headers=B).status_code == 404
    assert c.delete(f"/api/emo/{eid}", headers=B).status_code == 404
    e = c.get("/api/emo", headers=A).json()["entities"][0]
    assert (e["name"], e["lat"], e["active"]) == ("Blue HQ", 51.0, True)
    assert c.get("/api/emo/undo", headers=B).json()["depth"] == 0             # four rejected changes, no undo entries
    assert c.post(f"/api/emo/{eid}/move", json={"lat": 51.2, "lon": -1.0}, headers=A).status_code == 200
    assert c.get("/api/emo/undo", headers=A).json()["depth"] == 1
    assert c.post("/api/emo/deadbeef/move", json={"lat": 51.2, "lon": -1.0}, headers=A).status_code == 404
    assert c.get("/api/emo/undo", headers=A).json()["depth"] == 1
    assert c.put(f"/api/emo/{eid}", json={**body, "name": "Blue HQ (main)"}, headers=A).status_code == 200
    assert c.get("/api/emo/undo", headers=A).json()["depth"] == 2             # an edit can be undone too


def test_pages_carry_a_content_security_policy(emo):
    from fastapi.testclient import TestClient
    from app.main import app
    r = TestClient(app).get("/")
    csp = r.headers.get("content-security-policy", "")
    assert "script-src 'self'" in csp and "base-uri 'none'" in csp and "object-src 'none'" in csp
    assert "unsafe-inline" not in csp.split("script-src", 1)[1].split(";", 1)[0]
    assert "<script>" not in r.text                                           # no inline script for the CSP to block


def test_timeline_steps_through_the_tracks_and_finds_windows(emo):
    from app import emo_plan

    async def go():
        await emo.load_example("bg-vignette")
        await emo.run(emo.RunIn(), light=True)           # planning tools need an analysis first
        ents = emo._all()
        net = next(e["name"] for e in ents if e["side"] == "blue" and e["kind"] == "emitter"
                   and any(u.get("net") == e["id"] for u in ents))
        return net, await emo_plan.timeline(emo_plan.TimelineIn(step_min=10, max_steps=6, net=net))
    net, tl = asyncio.run(go())
    assert tl["steps"][0] == 0 and len(tl["steps"]) <= 6 and tl["horizon_min"] > 0
    assert any(r["tracked"] for r in tl["rows"].values())
    for r in tl["rows"].values():
        assert len(r["heard"]) == len(tl["steps"])
    w = tl["windows"]
    assert w["net"] == net and w["users"] and "steps with the control station undetected" in w["summary"]
