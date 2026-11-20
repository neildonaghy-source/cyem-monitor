"""Nightly purge ages items by their published time, falling back to the fetched time when the published time is
missing, unreadable or in the future (audit of 19 Nov 2026). Retention itself is unchanged."""
from datetime import timedelta

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    from app import config, db as dbm
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    d = dbm.Database(str(tmp_path / "t.sqlite3"))
    yield d
    d._conn.close()


def _put(db, iid, published, fetched):
    with db.tx() as c:
        c.execute("INSERT INTO items (id, source, domain, kind, title, published_at, fetched_at) VALUES (?,?,?,?,?,?,?)",
                  (iid, "test", "cyber", "news", iid, published, fetched))
        c.execute("INSERT INTO items_fts (id, title, summary) VALUES (?,?,?)", (iid, iid, ""))


def _ids(db):
    return {r["id"] for r in db.query("SELECT id FROM items")}, {r["id"] for r in db.query("SELECT id FROM items_fts")}


def test_purge_by_published_time(db):
    from app.db import iso, utcnow
    now = utcnow()
    ago = lambda d: iso(now - timedelta(days=d))   # noqa: E731
    _put(db, "old-pub-new-fetch", ago(200), ago(1))        # back catalogue fetched yesterday: goes
    _put(db, "recent", ago(5), ago(5))                      # stays
    _put(db, "recent-pub-old-fetch", ago(10), ago(150))     # stays: aged by publication
    _put(db, "null-pub-old-fetch", None, ago(150))          # no published time: aged by fetch, goes
    _put(db, "null-pub-new-fetch", None, ago(3))            # stays
    _put(db, "future-pub-old-fetch", iso(now + timedelta(days=30)), ago(150))   # bad clock: aged by fetch, goes
    _put(db, "future-pub-new-fetch", iso(now + timedelta(days=30)), ago(2))     # stays
    _put(db, "junk-pub-old-fetch", "sometime last week", ago(150))              # unreadable: aged by fetch, goes
    _put(db, "offset-pub", (now - timedelta(days=130)).strftime("%Y-%m-%dT%H:%M:%S+01:00"), ago(1))   # goes
    n = db.purge(120)
    items, fts = _ids(db)
    keep = {"recent", "recent-pub-old-fetch", "null-pub-new-fetch", "future-pub-new-fetch"}
    assert items == keep and fts == keep and n == 5


def test_upsert_skips_items_already_past_retention(db, monkeypatch):
    """Otherwise the purge deletes them each night and the next fetch puts them back as new."""
    from app import config
    from app.db import iso, utcnow
    monkeypatch.setattr(config.settings, "retention_days", 120)
    now = utcnow()
    base = {"source": "t", "domain": "cyber", "kind": "news"}
    n = db.upsert_items([
        {**base, "id": "a", "title": "old", "published_at": iso(now - timedelta(days=200))},
        {**base, "id": "b", "title": "new", "published_at": iso(now - timedelta(days=2))},
        {**base, "id": "c", "title": "undated", "published_at": None},
        {**base, "id": "d", "title": "future", "published_at": iso(now + timedelta(days=3))},
    ])
    assert n == 3 and _ids(db)[0] == {"b", "c", "d"}
    assert db.purge(120) == 0
