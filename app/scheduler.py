"""Background loop: runs collectors on their intervals (staggered, bounded
concurrency), triggers scheduled briefs, and purges old rows nightly."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import llm
from .collectors import REGISTRY, Context, make_http, run_collector
from .config import settings
from .db import Database, iso

log = logging.getLogger("cyem.sched")

# Initial run order: cheap structured sources first so the map fills quickly.
BOOT_ORDER = ["spaceweather", "hf", "drap", "aurora", "hfmap", "sat_tle", "sats", "milair", "kev", "ransomware", "c2", "ioda", "gpsjam", "rss", "hibp",
              "nvd", "cables", "gdelt", "launches", "cloudflare", "threatfox", "opencti", "radars"]


class Scheduler:
    def __init__(self, db: Database):
        self.db = db
        self.http = make_http()
        self.ctx = Context(db=db, http=self.http)
        self.running: set[str] = set()
        self.sem = asyncio.Semaphore(3)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.tz = ZoneInfo(settings.tz)
        self.last_purge: datetime | None = None
        self.next_due: dict[str, datetime] = {}

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="cyem-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
        await self.http.aclose()

    def _last_finished(self, name: str) -> datetime | None:
        r = self.db.one("SELECT finished_at, ok FROM runs WHERE name=?", (name,))
        if not r or not r.get("finished_at"):
            return None
        try:
            return datetime.strptime(r["finished_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    async def _run(self, name: str) -> None:
        if name in self.running:
            return
        self.running.add(name)
        try:
            async with self.sem:
                res = await run_collector(self.ctx, name)
            col = REGISTRY[name]
            # Failed runs retry sooner (but never more often than every 5 minutes).
            delay = col.interval_s if res.ok else max(300, min(col.interval_s, 1800))
            self.next_due[name] = datetime.now(timezone.utc) + timedelta(seconds=delay)
        finally:
            self.running.discard(name)

    def trigger(self, name: str) -> bool:
        if name not in REGISTRY or name in self.running:
            return False
        asyncio.create_task(self._run(name))
        return True

    async def _loop(self) -> None:
        await asyncio.sleep(2)
        now = datetime.now(timezone.utc)
        # Seed next_due from last finished runs so restarts do not hammer sources.
        order = [n for n in BOOT_ORDER if n in REGISTRY] + [n for n in REGISTRY if n not in BOOT_ORDER]
        for i, name in enumerate(order):
            last = self._last_finished(name)
            col = REGISTRY[name]
            if last and (now - last).total_seconds() < col.interval_s and not (settings.collect_on_start and name in ("spaceweather", "hf")):
                self.next_due[name] = last + timedelta(seconds=col.interval_s)
            else:
                self.next_due[name] = now + timedelta(seconds=i * 4 if settings.collect_on_start else col.interval_s)
        log.info("scheduler started; %d collectors; brief hours %s %s", len(REGISTRY), settings.brief_hours, settings.tz)
        while not self._stop.is_set():
            try:
                now = datetime.now(timezone.utc)
                for name, due in list(self.next_due.items()):
                    if now >= due and name not in self.running:
                        asyncio.create_task(self._run(name))
                        self.next_due[name] = now + timedelta(seconds=REGISTRY[name].interval_s)  # provisional; _run resets
                # Scheduled brief
                local = now.astimezone(self.tz)
                slot = llm.brief_due(self.db, local)
                if slot and not llm.state.generating and local.minute < 20:
                    self.db.set_snapshot("brief_last_slot", slot)
                    asyncio.create_task(llm.generate_brief(self.db, kind="scheduled"))
                # Nightly purge
                if self.last_purge is None or (now - self.last_purge) > timedelta(hours=24):
                    n = self.db.purge(settings.retention_days)
                    self.last_purge = now
                    if n:
                        log.info("purged %d items older than %d days", n, settings.retention_days)
            except Exception as e:  # noqa: BLE001
                log.exception("scheduler tick failed: %s", e)
            await asyncio.sleep(20)

    def status(self) -> list[dict]:
        runs = {r["name"]: r for r in self.db.runs()}
        out = []
        for name, col in REGISTRY.items():
            r = runs.get(name, {})
            out.append({
                "name": name, "domain": col.domain, "description": col.description, "interval_s": col.interval_s,
                "enabled": col.enabled(), "running": name in self.running,
                "last_started": r.get("started_at"), "last_finished": r.get("finished_at"), "ok": r.get("ok"),
                "message": r.get("message"), "count": r.get("count"), "duration_s": r.get("duration_s"),
                "next_due": iso(self.next_due.get(name)) if self.next_due.get(name) else None,
            })
        return out
