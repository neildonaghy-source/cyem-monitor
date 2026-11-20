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
              "nvd", "cables", "gdelt", "launches", "cloudflare", "threatfox", "opencti", "radars", "wtr"]


RATE_LIMIT_MIN_BACKOFF_S = 2 * 3600      # a rate-limited source is never retried sooner than this
MAX_BACKOFF_S = 12 * 3600                 # ...and never pushed out further than this (unless its interval is longer)


def _rate_limited(message: str | None) -> bool:
    m = (message or "").lower()
    return "429" in m or "rate limit" in m or "too many requests" in m


def retry_delay_s(interval_s: int, ok: bool, message: str | None, failures: int) -> int:
    """Seconds until the next run of a collector.

    OK runs wait their normal interval. Ordinary failures retry sooner (never more often than
    every 5 minutes, at most 30 minutes, doubling per consecutive failure but never past the
    normal interval). Rate-limited failures (HTTP 429) back off exponentially from at least 2 h:
    the old flat 30-minute retry is what kept GDELT throttling us (2026-10-03).
    """
    if ok:
        return interval_s
    n = max(1, failures)
    if _rate_limited(message):
        base = max(RATE_LIMIT_MIN_BACKOFF_S, interval_s)
        return int(min(base * 2 ** (n - 1), max(MAX_BACKOFF_S, interval_s)))
    base = max(300, min(interval_s, 1800))
    return int(min(base * 2 ** (n - 1), max(base, interval_s)))


BRIEF_RETRY_DELAYS_S = (600, 1200, 2400)   # a failed scheduled brief is tried again after 10, 20 and 40 minutes
BRIEF_BUSY_POLL_S = 30                     # wait this long between looks while another brief is being generated


async def scheduled_brief(db: Database, slot: str, *, generate=None, busy=None, sleep=asyncio.sleep,
                          delays: tuple[int, ...] = BRIEF_RETRY_DELAYS_S) -> dict:
    """Generate the brief for one scheduled slot, retrying a failure (Ollama down or timed out) up to len(delays)
    times with the given back-off. The slot is already marked done, so the loop does not start a second run;
    this is the only retry path. Never starts while another brief (manual or scheduled) is generating."""
    generate = generate or llm.generate_brief
    busy = busy or (lambda: llm.state.generating)
    res: dict = {"ok": False, "error": "not run"}
    for attempt in range(len(delays) + 1):
        if attempt:
            log.warning("scheduled brief %s failed (%s); retry %d of %d in %d min", slot, res.get("error"),
                        attempt, len(delays), delays[attempt - 1] // 60)
            await sleep(delays[attempt - 1])
        while busy():
            await sleep(BRIEF_BUSY_POLL_S)
        res = await generate(db, kind="scheduled")
        if res.get("ok"):
            return res
    log.warning("scheduled brief %s abandoned after %d retries: %s", slot, len(delays), res.get("error"))
    return res


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
        self.failures: dict[str, int] = {}   # consecutive failed runs per collector
        self._brief_task: asyncio.Task | None = None   # the scheduled brief in hand, retries included

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
            if res.ok:
                self.failures.pop(name, None)
            else:
                self.failures[name] = self.failures.get(name, 0) + 1
            delay = retry_delay_s(col.interval_s, res.ok, res.message, self.failures.get(name, 0))
            self.next_due[name] = datetime.now(timezone.utc) + timedelta(seconds=delay)
        finally:
            self.running.discard(name)

    def _spawn(self, coro) -> asyncio.Task:
        """Keep a reference until the task ends: asyncio holds tasks weakly, so an unreferenced one can be collected."""
        if not hasattr(self, "_tasks"):
            self._tasks: set[asyncio.Task] = set()
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    def trigger(self, name: str) -> bool:
        if name not in REGISTRY or name in self.running:
            return False
        self._spawn(self._run(name))
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
                        self._spawn(self._run(name))
                        self.next_due[name] = now + timedelta(seconds=REGISTRY[name].interval_s)  # provisional; _run resets
                # Scheduled brief
                local = now.astimezone(self.tz)
                slot = llm.brief_due(self.db, local)
                brief_busy = self._brief_task is not None and not self._brief_task.done()
                if slot and not brief_busy and not llm.state.generating and local.minute < 20:
                    self.db.set_snapshot("brief_last_slot", slot)
                    self._brief_task = self._spawn(scheduled_brief(self.db, slot))
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
