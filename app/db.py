"""SQLite persistence. One writer lock, WAL mode, FTS5 for search.

Tables
  items      normalised feed entries, advisories, victims, alerts (one row per event)
  items_fts  full-text index over items (title + summary)
  snapshots  latest structured state per source (space weather, GNSS hexes, cables ...)
  briefs     generated intelligence briefs
  runs       collector health (last run, ok/fail, count)
  feed_state ETag / Last-Modified cache for RSS feeds
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .config import settings

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  domain TEXT NOT NULL,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT,
  summary TEXT,
  published_at TEXT,
  fetched_at TEXT NOT NULL,
  country TEXT,
  lat REAL,
  lon REAL,
  severity INTEGER NOT NULL DEFAULT 2,
  tags TEXT NOT NULL DEFAULT '[]',
  extra TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_items_pub ON items(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_domain_pub ON items(domain, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_kind_pub ON items(kind, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_country ON items(country);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(id UNINDEXED, title, summary, tokenize='porter unicode61');
CREATE TABLE IF NOT EXISTS snapshots (
  key TEXT PRIMARY KEY,
  updated_at TEXT NOT NULL,
  data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS briefs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  model TEXT NOT NULL,
  content TEXT NOT NULL,
  duration_s REAL,
  input_chars INTEGER,
  item_count INTEGER
);
CREATE TABLE IF NOT EXISTS runs (
  name TEXT PRIMARY KEY,
  started_at TEXT,
  finished_at TEXT,
  ok INTEGER,
  message TEXT,
  count INTEGER,
  duration_s REAL
);
CREATE TABLE IF NOT EXISTS feed_state (
  url TEXT PRIMARY KEY,
  etag TEXT,
  modified TEXT,
  last_ok TEXT,
  fail_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    return iso(utcnow())  # type: ignore[return-value]


class Database:
    def __init__(self, path: str | None = None):
        self.path = str(path or settings.db_path)
        self._lock = threading.RLock()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # ---- items -------------------------------------------------------------
    def upsert_items(self, items: list[dict]) -> int:
        """Insert new items; existing ids are left untouched. Returns number inserted."""
        if not items:
            return 0
        inserted = 0
        fetched = now_iso()
        with self.tx() as c:
            for it in items:
                row = (
                    it["id"], it["source"], it["domain"], it["kind"], it["title"][:500],
                    it.get("url"), (it.get("summary") or "")[:2000], it.get("published_at"), fetched,
                    it.get("country"), it.get("lat"), it.get("lon"), int(it.get("severity", 2)),
                    json.dumps(it.get("tags") or [], ensure_ascii=False),
                    json.dumps(it.get("extra") or {}, ensure_ascii=False, default=str),
                )
                cur = c.execute(
                    "INSERT OR IGNORE INTO items (id, source, domain, kind, title, url, summary, published_at, "
                    "fetched_at, country, lat, lon, severity, tags, extra) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    row)
                if cur.rowcount:
                    inserted += 1
                    c.execute("INSERT INTO items_fts (id, title, summary) VALUES (?,?,?)",
                              (it["id"], it["title"][:500], (it.get("summary") or "")[:2000]))
        return inserted

    def update_item_fields(self, item_id: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        vals = [json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else v
                for v in fields.values()]
        with self.tx() as c:
            c.execute(f"UPDATE items SET {cols} WHERE id=?", (*vals, item_id))

    def list_items(self, *, domain: str | None = None, kind: str | None = None, country: str | None = None,
                   tag: str | None = None, since_hours: int | None = None, min_severity: int | None = None,
                   q: str | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
        where, params = [], []
        if q:
            fts = _fts_query(q)
            if fts:
                where.append("items.id IN (SELECT id FROM items_fts WHERE items_fts MATCH ?)")
                params.append(fts)
        if domain and domain != "all":
            where.append("domain=?")
            params.append(domain)
        if kind:
            where.append("kind=?")
            params.append(kind)
        if country:
            where.append("country=?")
            params.append(country.upper())
        if tag:
            where.append("tags LIKE ?")
            params.append(f'%"{tag}"%')
        if since_hours:
            where.append("published_at >= ?")
            params.append(iso(utcnow() - timedelta(hours=since_hours)))
        if min_severity:
            where.append("severity >= ?")
            params.append(int(min_severity))
        sql = "SELECT * FROM items"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY published_at DESC LIMIT ? OFFSET ?"
        params += [int(limit), int(offset)]
        return [_inflate(r) for r in self.query(sql, params)]

    def count_items(self, *, kind: str | None = None, domain: str | None = None, since_hours: int = 24,
                    min_severity: int | None = None) -> int:
        where, params = ["published_at >= ?"], [iso(utcnow() - timedelta(hours=since_hours))]
        if kind:
            where.append("kind=?"); params.append(kind)
        if domain:
            where.append("domain=?"); params.append(domain)
        if min_severity:
            where.append("severity >= ?"); params.append(min_severity)
        r = self.one("SELECT COUNT(*) AS n FROM items WHERE " + " AND ".join(where), params)
        return int(r["n"]) if r else 0

    def group_count(self, column: str, *, kind: str | None = None, since_hours: int = 24 * 30, limit: int = 30) -> list[dict]:
        assert column in ("country", "source", "kind", "domain")
        where, params = ["published_at >= ?", f"{column} IS NOT NULL"], [iso(utcnow() - timedelta(hours=since_hours))]
        if kind:
            where.append("kind=?"); params.append(kind)
        return self.query(
            f"SELECT {column} AS key, COUNT(*) AS n FROM items WHERE {' AND '.join(where)} "
            f"GROUP BY {column} ORDER BY n DESC LIMIT ?", params + [limit])

    def purge(self, days: int) -> int:
        cutoff = iso(utcnow() - timedelta(days=days))
        with self.tx() as c:
            c.execute("DELETE FROM items_fts WHERE id IN (SELECT id FROM items WHERE fetched_at < ?)", (cutoff,))
            cur = c.execute("DELETE FROM items WHERE fetched_at < ?", (cutoff,))
            return cur.rowcount

    # ---- snapshots ---------------------------------------------------------
    def set_snapshot(self, key: str, data: Any) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO snapshots (key, updated_at, data) VALUES (?,?,?) "
                      "ON CONFLICT(key) DO UPDATE SET updated_at=excluded.updated_at, data=excluded.data",
                      (key, now_iso(), json.dumps(data, ensure_ascii=False, default=str)))

    def get_snapshot(self, key: str) -> tuple[Any, str | None]:
        r = self.one("SELECT data, updated_at FROM snapshots WHERE key=?", (key,))
        if not r:
            return None, None
        try:
            return json.loads(r["data"]), r["updated_at"]
        except json.JSONDecodeError:
            return None, r["updated_at"]

    # ---- runs --------------------------------------------------------------
    def start_run(self, name: str) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO runs (name, started_at, finished_at, ok, message, count, duration_s) "
                      "VALUES (?,?,NULL,NULL,'running',NULL,NULL) ON CONFLICT(name) DO UPDATE SET "
                      "started_at=excluded.started_at, message='running'", (name, now_iso()))

    def finish_run(self, name: str, ok: bool, message: str, count: int, duration_s: float) -> None:
        with self.tx() as c:
            c.execute("UPDATE runs SET finished_at=?, ok=?, message=?, count=?, duration_s=? WHERE name=?",
                      (now_iso(), 1 if ok else 0, message[:500], count, round(duration_s, 2), name))

    def runs(self) -> list[dict]:
        return self.query("SELECT * FROM runs ORDER BY name")

    # ---- feed state --------------------------------------------------------
    def feed_state(self, url: str) -> dict | None:
        return self.one("SELECT * FROM feed_state WHERE url=?", (url,))

    def set_feed_state(self, url: str, *, etag: str | None, modified: str | None, ok: bool, error: str | None = None) -> None:
        with self.tx() as c:
            if ok:
                c.execute("INSERT INTO feed_state (url, etag, modified, last_ok, fail_count, last_error) VALUES (?,?,?,?,0,NULL) "
                          "ON CONFLICT(url) DO UPDATE SET etag=excluded.etag, modified=excluded.modified, "
                          "last_ok=excluded.last_ok, fail_count=0, last_error=NULL", (url, etag, modified, now_iso()))
            else:
                c.execute("INSERT INTO feed_state (url, fail_count, last_error) VALUES (?,1,?) "
                          "ON CONFLICT(url) DO UPDATE SET fail_count=fail_count+1, last_error=excluded.last_error",
                          (url, (error or "")[:300]))

    def feed_states(self) -> list[dict]:
        return self.query("SELECT * FROM feed_state ORDER BY url")

    # ---- briefs ------------------------------------------------------------
    def add_brief(self, kind: str, model: str, content: str, duration_s: float, input_chars: int, item_count: int) -> int:
        with self.tx() as c:
            cur = c.execute("INSERT INTO briefs (created_at, kind, model, content, duration_s, input_chars, item_count) "
                            "VALUES (?,?,?,?,?,?,?)", (now_iso(), kind, model, content, round(duration_s, 1), input_chars, item_count))
            return int(cur.lastrowid)

    def briefs(self, limit: int = 20) -> list[dict]:
        return self.query("SELECT id, created_at, kind, model, duration_s, input_chars, item_count, "
                          "substr(content, 1, 160) AS preview FROM briefs ORDER BY id DESC LIMIT ?", (limit,))

    def brief(self, brief_id: int | None = None) -> dict | None:
        if brief_id is None:
            return self.one("SELECT * FROM briefs ORDER BY id DESC LIMIT 1")
        return self.one("SELECT * FROM briefs WHERE id=?", (brief_id,))


def _inflate(r: dict) -> dict:
    for k in ("tags", "extra"):
        try:
            r[k] = json.loads(r.get(k) or ("[]" if k == "tags" else "{}"))
        except json.JSONDecodeError:
            r[k] = [] if k == "tags" else {}
    return r


def _fts_query(q: str) -> str:
    """Turn free text into a tolerant FTS5 query: quoted terms OR'd together."""
    import re
    terms = [t for t in re.findall(r"[\w\-\.]+", q) if len(t) > 1]
    if not terms:
        return ""
    quoted = ['"' + t.replace('"', '') + '"' for t in terms[:12]]
    return " OR ".join(quoted)


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db
