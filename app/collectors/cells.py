"""OpenCelliD UK cell download (weekly). Key: OPENCELLID_KEY in .env. Free accounts get a
small number of downloads a day, so this runs weekly and skips when the table is fresh."""
from __future__ import annotations

import asyncio
import os

from ..cells import db_path, load_csv_gz
from ..config import settings
from .base import Context, Result, register

URL = "https://opencellid.org/ocid/downloads"
FILES = ["234.csv.gz"]          # MCC 235 is sparse and the free tier allows 2 downloads per file per day


@register("cells", interval_s=7 * 24 * 3600, domain="em",
          description="OpenCelliD cell sites, UK (MCC 234/235), weekly bulk download")
async def collect_cells(ctx: Context) -> Result:
    key = os.environ.get("OPENCELLID_KEY", "").strip()
    if not key:
        return Result(0, "no OPENCELLID_KEY set")
    d = settings.data_dir / "cells"
    d.mkdir(parents=True, exist_ok=True)
    paths = []
    import time
    for fn in FILES:
        out = d / fn
        if out.exists() and time.time() - out.stat().st_mtime < 6 * 86400:
            paths.append(out)                     # fresh copy: do not spend a daily download
            continue
        async with ctx.http.stream("GET", URL, params={"token": key, "type": "mcc", "file": fn}, timeout=300) as r:
            if r.status_code == 404:              # no file for this MCC (e.g. 235): skip
                continue
            if r.status_code >= 400:              # never echo the URL: it carries the key
                raise RuntimeError(f"OpenCelliD {fn}: HTTP {r.status_code}")
            first = b""
            with open(out.with_suffix(".part"), "wb") as f:
                async for chunk in r.aiter_bytes(1 << 20):
                    if not first:
                        first = chunk[:200]
                    f.write(chunk)
        if not first.startswith(b"\x1f\x8b"):  # not gzip: OpenCelliD returns a text error instead
            out.with_suffix(".part").unlink(missing_ok=True)
            raise RuntimeError(f"OpenCelliD refused {fn}: {first[:120].decode(errors='replace').replace(key, '***')}")
        out.with_suffix(".part").replace(out)
        paths.append(out)
    if not paths:
        raise RuntimeError("no OpenCelliD files available")
    n = await asyncio.to_thread(load_csv_gz, paths)
    ctx.db.set_snapshot("cells", {"rows": n, "files": FILES, "source": "OpenCelliD (CC BY-SA 4.0)", "db": str(db_path())})
    return Result(n, f"{n} UK cells loaded")
