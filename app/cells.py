"""OpenCelliD cell sites (UK, MCC 234/235), stored in their own SQLite file so the
large, re-downloadable table stays out of the main database and its backup.
Positions are crowd-sourced estimates of where cells were heard, not surveyed masts."""
from __future__ import annotations

import csv
import gzip
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from .config import settings

router = APIRouter(prefix="/api/cells", tags=["cells"])
OPERATORS = {(234, 10): "O2", (234, 11): "O2", (234, 15): "Vodafone", (234, 20): "Three", (234, 30): "EE",
             (234, 33): "EE", (234, 34): "EE", (234, 50): "JT (Jersey)", (234, 55): "Sure (Guernsey)",
             (234, 58): "Manx Telecom", (235, 94): "Three", (235, 91): "Vodafone", (234, 94): "Three"}


def db_path() -> Path:
    d = settings.data_dir / "cells"
    d.mkdir(parents=True, exist_ok=True)
    return d / "cells.sqlite3"


def load_csv_gz(paths: list[Path]) -> int:
    """Replace the cells table from OpenCelliD MCC CSV.gz files (shadow table swap)."""
    conn = sqlite3.connect(db_path(), timeout=60)
    try:
        conn.execute("DROP TABLE IF EXISTS cells_new")
        conn.execute("CREATE TABLE cells_new (radio TEXT, mcc INT, net INT, area INT, cell INT, lon REAL, lat REAL, "
                     "range_m INT, samples INT, updated INT)")
        n = 0
        batch = []
        for p in paths:
            with gzip.open(p, "rt", newline="", encoding="utf-8", errors="replace") as f:
                for row in csv.reader(f):
                    if not row or row[0] == "radio" or len(row) < 13:
                        continue
                    try:
                        batch.append((row[0], int(row[1]), int(row[2]), int(row[3]), int(row[4]), float(row[6]), float(row[7]),
                                      int(float(row[8] or 0)), int(row[9] or 0), int(row[12] or 0)))
                    except ValueError:
                        continue
                    if len(batch) >= 20000:
                        conn.executemany("INSERT INTO cells_new VALUES (?,?,?,?,?,?,?,?,?,?)", batch); conn.commit(); n += len(batch); batch.clear()
        if batch:
            conn.executemany("INSERT INTO cells_new VALUES (?,?,?,?,?,?,?,?,?,?)", batch); conn.commit(); n += len(batch)
        if n == 0:
            conn.execute("DROP TABLE cells_new"); conn.commit()
            raise RuntimeError("no rows parsed")
        conn.execute("CREATE INDEX idx_cells_new_ll ON cells_new(lat, lon)")
        conn.execute("DROP TABLE IF EXISTS cells")
        conn.execute("ALTER TABLE cells_new RENAME TO cells")
        conn.commit()
        return n
    finally:
        conn.close()


@router.get("")
async def cells(s: float, w: float, n: float, e: float, limit: int = Query(default=4000, ge=1, le=8000)):
    if (n - s) * (e - w) > 0.5:
        raise HTTPException(400, "area too large; zoom in")
    if not db_path().exists():
        return {"total": 0, "rows": [], "loaded": False}
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        q = "FROM cells WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?"
        total = conn.execute(f"SELECT COUNT(*) {q}", (s, n, w, e)).fetchone()[0]
        rows = [dict(r) for r in conn.execute(f"SELECT radio, mcc, net, area, cell, lat, lon, range_m, samples, updated {q} "
                                               "ORDER BY samples DESC LIMIT ?", (s, n, w, e, limit))]
    except sqlite3.OperationalError:
        return {"total": 0, "rows": [], "loaded": False}
    finally:
        conn.close()
    for r in rows:
        r["operator"] = OPERATORS.get((r["mcc"], r["net"]), f"{r['mcc']}-{r['net']}")
    return {"total": total, "returned": len(rows), "rows": rows, "loaded": True}
