"""Spectrum persistence: Ofcom WTR baseline and user-entered planned emitters.

Lives in the main CyEM SQLite file so the existing nightly backup covers it.
The bulk WTR load uses its own short-lived connection and a shadow table swap,
so the app's shared connection (and its lock) is never held for the load.
"""
from __future__ import annotations

import csv
import sqlite3
import uuid
from collections import Counter
from pathlib import Path

from .db import Database, now_iso
from .spectrum_core import Emitter, bbox_for_radius, parse_wtr_row

WTR_COLS_DB = ["licence", "freq_hz", "bw_hz", "bw_src", "station_type", "erp", "erp_unit", "ant_height_m",
               "height_asl_m", "azimuth", "emission", "company", "product", "lat", "lon", "ngr"]

WTR_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {t} (
  id INTEGER PRIMARY KEY,
  licence TEXT NOT NULL, freq_hz REAL NOT NULL, bw_hz REAL NOT NULL, bw_src TEXT,
  station_type TEXT, erp REAL, erp_unit TEXT, ant_height_m REAL, height_asl_m REAL, azimuth REAL,
  emission TEXT, company TEXT, product TEXT NOT NULL, lat REAL, lon REAL, ngr TEXT
);
"""
WTR_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS ux_wtr_dedupe ON wtr(licence, freq_hz, IFNULL(station_type, ''), IFNULL(lat, 999), IFNULL(lon, 999));
CREATE INDEX IF NOT EXISTS idx_wtr_freq ON wtr(freq_hz);
CREATE INDEX IF NOT EXISTS idx_wtr_latlon ON wtr(lat, lon);
CREATE INDEX IF NOT EXISTS idx_wtr_product ON wtr(product);
"""
PLANNED_SQL = """
CREATE TABLE IF NOT EXISTS planned_emitters (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  freq_hz REAL NOT NULL,
  bw_hz REAL NOT NULL,
  power_w REAL,
  lat REAL NOT NULL,
  lon REAL NOT NULL,
  start_at TEXT,
  end_at TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def ensure_schema(db: Database) -> None:
    with db.tx() as c:
        c.executescript(WTR_TABLE_SQL.format(t="wtr") + WTR_INDEX_SQL + PLANNED_SQL)


def band_of(f_hz: float) -> str:
    for lim, name in ((3e6, "MF/LF"), (30e6, "HF"), (300e6, "VHF"), (3e9, "UHF"), (30e9, "SHF")):
        if f_hz < lim:
            return name
    return "EHF"


def load_wtr_csv(db_path: str | Path, csv_path: str | Path, *, min_keep_ratio: float = 0.5) -> dict:
    """Parse the WTR CSV into a shadow table and swap it in atomically.

    Synchronous; call via asyncio.to_thread. Refuses the swap if the new load has
    fewer than min_keep_ratio x the current row count (guards against a truncated
    download wiping the baseline)."""
    conn = sqlite3.connect(str(db_path), timeout=60)
    try:
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("DROP TABLE IF EXISTS wtr_new")
        conn.executescript(WTR_TABLE_SQL.format(t="wtr_new"))
        conn.execute("CREATE UNIQUE INDEX ux_wtr_new_dedupe ON wtr_new(licence, freq_hz, IFNULL(station_type, ''), IFNULL(lat, 999), IFNULL(lon, 999))")
        conn.commit()
        placeholders = ",".join("?" * len(WTR_COLS_DB))
        sql = f"INSERT OR IGNORE INTO wtr_new ({','.join(WTR_COLS_DB)}) VALUES ({placeholders})"
        seen = skipped = 0
        batch: list[tuple] = []
        with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
            for raw in csv.DictReader(f):
                seen += 1
                r = parse_wtr_row(raw)
                if r is None:
                    skipped += 1
                    continue
                batch.append(tuple(r[k] for k in WTR_COLS_DB))
                if len(batch) >= 5000:
                    conn.executemany(sql, batch)
                    conn.commit()
                    batch.clear()
        if batch:
            conn.executemany(sql, batch)
            conn.commit()
        new_n = conn.execute("SELECT COUNT(*) FROM wtr_new").fetchone()[0]
        old_n = conn.execute("SELECT COUNT(*) FROM wtr").fetchone()[0] if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='wtr'").fetchone() else 0
        if old_n and new_n < old_n * min_keep_ratio:
            conn.execute("DROP TABLE wtr_new")
            conn.commit()
            raise RuntimeError(f"refusing swap: new load {new_n} rows vs current {old_n}")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DROP TABLE IF EXISTS wtr")
        conn.execute("ALTER TABLE wtr_new RENAME TO wtr")
        conn.execute("DROP INDEX IF EXISTS ux_wtr_new_dedupe")
        conn.executescript(WTR_INDEX_SQL)   # executescript commits the swap
        stats = {
            "rows_in_file": seen, "rows_loaded": new_n, "rows_skipped": skipped, "duplicates_dropped": seen - skipped - new_n,
            "by_product": dict(conn.execute("SELECT product, COUNT(*) FROM wtr GROUP BY product ORDER BY 2 DESC").fetchall()),
            "bw_source": dict(conn.execute("SELECT bw_src, COUNT(*) FROM wtr GROUP BY bw_src").fetchall()),
            "area_rows": conn.execute("SELECT COUNT(*) FROM wtr WHERE lat IS NULL").fetchone()[0],
        }
        bands: Counter = Counter()
        for (fz,) in conn.execute("SELECT freq_hz FROM wtr"):
            bands[band_of(fz)] += 1
        stats["by_band"] = dict(bands)
        return stats
    finally:
        conn.close()


# ---- WTR queries -----------------------------------------------------------------
_WTR_PUBLIC = "id, licence, freq_hz, bw_hz, bw_src, station_type, erp, erp_unit, ant_height_m, emission, company, product, lat, lon"
# T and R rows for the same licence, frequency and site collapse to one assignment for conflict checks.
_WTR_GROUPED = ("MIN(id) AS id, licence, freq_hz, MAX(bw_hz) AS bw_hz, MAX(bw_src) AS bw_src, "
                "GROUP_CONCAT(DISTINCT station_type) AS station_type, MAX(erp) AS erp, MAX(erp_unit) AS erp_unit, "
                "MAX(ant_height_m) AS ant_height_m, MAX(emission) AS emission, MAX(company) AS company, MAX(product) AS product, lat, lon")


def wtr_in_bbox(db: Database, s: float, w: float, n: float, e: float, *, fmin_hz: float | None = None,
                fmax_hz: float | None = None, products: list[str] | None = None, limit: int = 4000) -> tuple[list[dict], int]:
    where = ["lat BETWEEN ? AND ?", "lon BETWEEN ? AND ?"]
    params: list = [s, n, w, e]
    if fmin_hz is not None:
        where.append("freq_hz + bw_hz/2 >= ?")
        params.append(fmin_hz)
    if fmax_hz is not None:
        where.append("freq_hz - bw_hz/2 <= ?")
        params.append(fmax_hz)
    if products:
        where.append(f"product IN ({','.join('?' * len(products))})")
        params.extend(products)
    w_sql = " AND ".join(where)
    total = db.one(f"SELECT COUNT(*) AS n FROM wtr WHERE {w_sql}", params)["n"]
    rows = db.query(f"SELECT {_WTR_PUBLIC} FROM wtr WHERE {w_sql} ORDER BY freq_hz LIMIT ?", params + [limit])
    return rows, total


def wtr_candidates(db: Database, p: Emitter, *, guard_hz: float, radius_km: float, extra_span_hz: float = 0.0) -> list[Emitter]:
    """WTR rows that could conflict with p: guarded frequency overlap (optionally
    widened for display) within the bounding box of the search radius. The exact
    distance filter is applied afterwards in spectrum_core."""
    lo_lat, hi_lat, lo_lon, hi_lon = bbox_for_radius(p.lat, p.lon, radius_km)
    lo_f = p.freq_hz - p.bw_hz / 2 - guard_hz - extra_span_hz
    hi_f = p.freq_hz + p.bw_hz / 2 + guard_hz + extra_span_hz
    rows = db.query(
        f"SELECT {_WTR_GROUPED} FROM wtr WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? "
        "AND freq_hz + bw_hz/2 > ? AND freq_hz - bw_hz/2 < ? GROUP BY licence, freq_hz, lat, lon LIMIT 5000",
        (lo_lat, hi_lat, lo_lon, hi_lon, lo_f, hi_f))
    return [wtr_to_emitter(r) for r in rows]


def wtr_area_conflicts(db: Database, p: Emitter, *, guard_hz: float) -> list[dict]:
    """Licences with no published location (mostly BR Area Defined). Distance
    cannot be tested, so any guarded frequency overlap is reported: medium if the
    occupied bands overlap, low if only the guard bands touch."""
    from .spectrum_core import freq_overlap_hz
    lo_f, hi_f = p.freq_hz - p.bw_hz / 2 - guard_hz, p.freq_hz + p.bw_hz / 2 + guard_hz
    out = []
    for r in db.query(f"SELECT {_WTR_GROUPED} FROM wtr WHERE lat IS NULL AND freq_hz + bw_hz/2 > ? AND freq_hz - bw_hz/2 < ? "
                      "GROUP BY licence, freq_hz LIMIT 500",
                      (lo_f, hi_f)):
        ov = freq_overlap_hz(p.freq_hz, p.bw_hz, r["freq_hz"], r["bw_hz"], guard_hz)
        if ov <= 0:
            continue
        spacing = abs(p.freq_hz - r["freq_hz"])
        co = spacing - (p.bw_hz + r["bw_hz"]) / 2
        e = wtr_to_emitter(r)
        out.append({"a": p.id, "b": e.id, "b_kind": "wtr_area", "b_name": e.name, "b_freq_hz": e.freq_hz, "b_bw_hz": e.bw_hz,
                    "b_lat": None, "b_lon": None, "spacing_hz": round(spacing, 1), "overlap_hz": round(ov, 1),
                    "co_channel": co <= 0, "dist_km": None, "severity": "medium" if ov >= guard_hz and co <= 0 else "low",
                    "b_meta": e.meta or {}})
    return out


def wtr_to_emitter(r: dict) -> Emitter:
    return Emitter(id=f"wtr:{r['id']}", name=r.get("company") or r["licence"], freq_hz=r["freq_hz"], bw_hz=r["bw_hz"],
                   lat=r["lat"], lon=r["lon"], kind="wtr",
                   meta={k: r.get(k) for k in ("licence", "product", "station_type", "erp", "erp_unit", "emission", "bw_src")})


def wtr_count(db: Database) -> int:
    r = db.one("SELECT COUNT(*) AS n FROM wtr")
    return int(r["n"]) if r else 0


def wtr_products(db: Database) -> list[dict]:
    return db.query("SELECT product, COUNT(*) AS n FROM wtr GROUP BY product ORDER BY n DESC")


# ---- planned emitters -------------------------------------------------------------
def planned_list(db: Database) -> list[dict]:
    return db.query("SELECT * FROM planned_emitters ORDER BY freq_hz, name")


def planned_get(db: Database, pid: str) -> dict | None:
    return db.one("SELECT * FROM planned_emitters WHERE id=?", (pid,))


def planned_upsert(db: Database, data: dict, pid: str | None = None) -> dict:
    now = now_iso()
    pid = pid or uuid.uuid4().hex[:10]
    cols = ["name", "freq_hz", "bw_hz", "power_w", "lat", "lon", "start_at", "end_at", "notes"]
    vals = [data.get(c) for c in cols]
    with db.tx() as c:
        c.execute(
            f"INSERT INTO planned_emitters (id, {','.join(cols)}, created_at, updated_at) VALUES (?,{','.join('?' * len(cols))},?,?) "
            f"ON CONFLICT(id) DO UPDATE SET {','.join(f'{k}=excluded.{k}' for k in cols)}, updated_at=excluded.updated_at",
            [pid, *vals, now, now])
    return planned_get(db, pid)  # type: ignore[return-value]


def planned_delete(db: Database, pid: str) -> bool:
    with db.tx() as c:
        return c.execute("DELETE FROM planned_emitters WHERE id=?", (pid,)).rowcount > 0


def planned_to_emitter(r: dict) -> Emitter:
    return Emitter(id=r["id"], name=r["name"], freq_hz=r["freq_hz"], bw_hz=r["bw_hz"], lat=r["lat"], lon=r["lon"],
                   start=r.get("start_at"), end=r.get("end_at"), kind="planned",
                   meta={"power_w": r.get("power_w"), "notes": r.get("notes")})


def run_conflicts(db: Database, *, guard_hz: float, radius_km: float) -> dict:
    """Planned vs WTR baseline and planned vs planned. Returns results grouped by
    planned emitter plus a flat summary for the brief."""
    from .spectrum_core import find_conflicts
    planned = [planned_to_emitter(r) for r in planned_list(db)]
    by_id: dict[str, list[dict]] = {p.id: [] for p in planned}
    for p in planned:
        by_id[p.id].extend(find_conflicts([p], wtr_candidates(db, p, guard_hz=guard_hz, radius_km=radius_km),
                                          guard_hz=guard_hz, radius_km=radius_km))
        by_id[p.id].extend(wtr_area_conflicts(db, p, guard_hz=guard_hz))
    pmap = {p.id: p for p in planned}
    pp = find_conflicts(planned, planned, guard_hz=guard_hz, radius_km=radius_km)
    for r in pp:
        by_id[r["a"]].append(r)
        a = pmap[r["a"]]   # mirror so both planned emitters show the clash
        by_id[r["b"]].append({**r, "a": r["b"], "b": a.id, "b_name": a.name, "b_freq_hz": a.freq_hz,
                              "b_bw_hz": a.bw_hz, "b_lat": a.lat, "b_lon": a.lon, "b_meta": a.meta or {}})
    rank = {"high": 0, "medium": 1, "low": 2}
    sev_count: Counter = Counter()
    vs_wtr = 0
    for lst in by_id.values():
        lst.sort(key=lambda r: (rank[r["severity"]], r["dist_km"] if r["dist_km"] is not None else 1e9))
        for r in lst:
            if r["b_kind"] in ("wtr", "wtr_area"):
                vs_wtr += 1
                sev_count[r["severity"]] += 1
    for r in pp:   # planned/planned pairs counted once for the totals
        sev_count[r["severity"]] += 1
    return {"generated_at": now_iso(), "guard_hz": guard_hz, "radius_km": radius_km,
            "planned": [{"id": p.id, "name": p.name, "freq_hz": p.freq_hz, "bw_hz": p.bw_hz, "lat": p.lat, "lon": p.lon,
                         "start": p.start, "end": p.end, "power_w": (p.meta or {}).get("power_w"),
                         "conflicts": by_id[p.id]} for p in planned],
            "totals": {"planned": len(planned), "vs_licensed": vs_wtr, "planned_pairs": len(pp),
                       "high": sev_count["high"], "medium": sev_count["medium"], "low": sev_count["low"]}}
