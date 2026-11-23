"""Phase 7: the Word corridor brief and Ask answers with positions and legs (no language model), plus downloads naming
their workspace with ?ws=."""
import asyncio
import io
import json

import pytest

from tests.test_emo_scenarios import _flat, emo  # noqa: F401  (fixture)


def _plan(emo, name="uas-gnss"):
    from app import corridor_api
    from app.emo_examples import EXAMPLES
    v = EXAMPLES[name]["corridor"]

    async def go():
        await emo.load_example(name)
        await emo.run(emo.RunIn(), light=True)
        body = {k: v[k] for k in ("mover", "domain", "step_min", "alt_m", "speed_kmh") if k in v}
        return await corridor_api.plan_corridor(corridor_api.CorridorIn(**body, to_lat=v["to"][0], to_lon=v["to"][1], cell_m=1000))
    return asyncio.run(go())


async def _ask(emo, q):
    r = await emo.emo_ask(emo.AskIn(question=q))
    out = ""
    async for chunk in r.body_iterator:
        for line in (chunk if isinstance(chunk, str) else chunk.decode()).splitlines():
            if line.startswith("data: "):
                d = json.loads(line[6:])
                out += d.get("t", "")
    return out


def test_corridor_is_kept_and_cleared_with_the_scenario(emo, monkeypatch):
    _flat(monkeypatch)
    res = _plan(emo)
    c = emo._LAST.get("corridor")
    assert c and c["res"] is res and c["in"]["mover"] == "Blue UAV"
    asyncio.run(emo.load_example("a303-gnss"))
    assert emo._LAST.get("corridor") is None


def test_ask_answers_from_the_planned_corridor(emo, monkeypatch):
    _flat(monkeypatch)
    res = _plan(emo)
    text = asyncio.run(_ask(emo, "What is the best route for the UAV?"))
    assert text.startswith("**Computed corridor** for Blue UAV")
    assert f"{res['summary']['km']} km" in text and text.count("- Leg ") == len(res["legs"])
    lg = res["legs"][0]
    assert f"{lg['from'][0]:.4f}, {lg['from'][1]:.4f}" in text and "N " in text      # lat/lon and degrees-minutes
    ctx = emo.scenario_context()
    assert "CORRIDOR PLANNED: Blue UAV" in ctx and "LEG 1 T+" in ctx


def test_ask_without_a_corridor_says_how(emo, monkeypatch):
    _flat(monkeypatch)

    async def go():
        await emo.load_example("uas-gnss")
        await emo.run(emo.RunIn(), light=True)
        return await _ask(emo, "Which route should the UAV take?")
    assert "No corridor planned yet" in asyncio.run(go())


def test_word_brief(emo, monkeypatch):
    from docx import Document
    from app import corridor_api
    from fastapi import HTTPException
    _flat(monkeypatch)

    async def none():
        await emo.load_example("uas-gnss")
        try:
            await corridor_api.corridor_brief()
        except HTTPException as e:
            return e.status_code
    assert asyncio.run(none()) == 409
    res = _plan(emo)

    async def go():
        r = await corridor_api.corridor_brief()
        body = b""
        async for chunk in r.body_iterator:
            body += chunk if isinstance(chunk, bytes) else chunk.encode()
        return r, body
    r, body = asyncio.run(go())
    assert "CyEM-corridor-Blue-UAV" in r.headers["content-disposition"]
    doc = Document(io.BytesIO(body))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "CyEM corridor brief: Blue UAV" in text and "Schematic, no basemap" in text and doc.inline_shapes
    legs = doc.tables[-1]
    assert len(legs.rows) == len(res["legs"]) + 1 and legs.rows[0].cells[0].text == "Leg"
    assert any("N " in cell.text for cell in doc.tables[0].columns[1].cells)


def test_download_names_its_workspace(emo, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    seen = {}
    real = emo.WS.get

    @app.get("/api/emo/_wsprobe")
    async def probe():
        seen["ws"] = real()
        return {}
    try:
        c.get("/api/emo/_wsprobe?ws=wsq1")
        assert seen["ws"] == "wsq1"
        c.get("/api/emo/_wsprobe?ws=bad%20id!")
        assert seen["ws"] == "default"
        c.get("/api/emo/_wsprobe?ws=wsq1", headers={"X-CyEM-WS": "hdr1"})
        assert seen["ws"] == "hdr1"                                          # the header wins
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/api/emo/_wsprobe"]
