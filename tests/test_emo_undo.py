"""EMO undo: a move, then undo, puts the entity back exactly as it was, in the caller's workspace only.
Throw-away database and a private workspace, as in test_emo_scenarios.py."""
import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import config, db as dbm
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(dbm, "_db", dbm.Database(str(tmp_path / "t.sqlite3")))
    from app import emo_api
    emo_api.ensure_emo_schema(dbm.get_db())
    emo_api._LAST_BY_WS.clear()
    from fastapi.testclient import TestClient
    from app.main import app
    yield TestClient(app)
    emo_api._LAST_BY_WS.clear()
    dbm.get_db()._conn.close()


WS = {"x-cyem-ws": "undo-test"}
OTHER = {"x-cyem-ws": "undo-other"}
BODY = {"name": "Blue HQ", "side": "blue", "kind": "emitter", "category": "comms", "lat": 51.0, "lon": -1.0,
        "freq_mhz": 50, "eirp_dbm": 40, "track": [[51.05, -0.95]], "speed_kmh": 20}


def _get(c, h, eid):
    return next(e for e in c.get("/api/emo", headers=h).json()["entities"] if e["id"] == eid)


def test_move_then_undo_restores_the_entity(client):
    c = client
    eid = c.post("/api/emo", json=BODY, headers=WS).json()["id"]
    rid = c.post("/api/emo", json={**BODY, "name": "Blue relay", "lat": 51.2, "track": None}, headers=WS).json()["id"]
    oid = c.post("/api/emo", json={**BODY, "name": "Other HQ"}, headers=OTHER).json()["id"]
    before = _get(c, WS, eid)
    depth = c.get("/api/emo/undo", headers=WS).json()["depth"]

    assert c.post(f"/api/emo/{eid}/move", json={"lat": 52.5, "lon": -2.5}, headers=WS).status_code == 200
    moved = _get(c, WS, eid)
    assert (moved["lat"], moved["lon"]) == (52.5, -2.5)
    assert c.get("/api/emo/undo", headers=WS).json()["depth"] == depth + 1
    assert c.post(f"/api/emo/{oid}/move", json={"lat": 53.0, "lon": -3.0}, headers=OTHER).status_code == 200

    r = c.post("/api/emo/undo", headers=WS)
    assert r.status_code == 200 and r.json()["depth"] == depth
    assert _get(c, WS, eid) == before                                   # every field back, track and timestamp included
    assert {e["id"] for e in r.json()["entities"]} == {eid, rid}         # nothing lost, nothing added
    assert _get(c, OTHER, oid)["lat"] == 53.0                           # the other workspace is not touched


def test_undo_with_nothing_to_undo_is_404(client):
    assert client.post("/api/emo/undo", headers={"x-cyem-ws": "undo-empty"}).status_code == 404
