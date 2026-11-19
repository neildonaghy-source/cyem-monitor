"""Collector plumbing: registry, shared HTTP client, id hashing, date parsing."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx
from dateutil import parser as dtparser

from ..config import settings
from ..db import Database, iso

log = logging.getLogger("cyem.collect")


@dataclass
class Context:
    db: Database
    http: httpx.AsyncClient


@dataclass
class Result:
    count: int = 0
    message: str = "ok"
    ok: bool = True


CollectorFn = Callable[[Context], Awaitable[Result]]


@dataclass
class Collector:
    name: str
    fn: CollectorFn
    interval_s: int
    domain: str
    description: str
    enabled: Callable[[], bool] = lambda: True


REGISTRY: dict[str, Collector] = {}


def register(name: str, *, interval_s: int, domain: str, description: str,
             enabled: Callable[[], bool] = lambda: True):
    def deco(fn: CollectorFn) -> CollectorFn:
        REGISTRY[name] = Collector(name, fn, interval_s, domain, description, enabled)
        return fn
    return deco


def make_http() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout, connect=15),
        headers={"User-Agent": settings.user_agent, "Accept": "*/*"},
        follow_redirects=True,
        limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
    )


def item_id(*parts: Any) -> str:
    h = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8", "ignore")).hexdigest()
    return h[:24]


def parse_dt(value: Any, default_now: bool = True) -> str | None:
    """Best-effort parse of any date string or struct_time into ISO-8601 UTC."""
    if value is None or value == "":
        return iso(datetime.now(timezone.utc)) if default_now else None
    try:
        if hasattr(value, "tm_year"):  # time.struct_time from feedparser
            import calendar
            return iso(datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc))
        if isinstance(value, (int, float)):
            return iso(datetime.fromtimestamp(float(value), tz=timezone.utc))
        if isinstance(value, datetime):
            return iso(value)
        dt = dtparser.parse(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return iso(dt)
    except (ValueError, OverflowError, TypeError):
        return iso(datetime.now(timezone.utc)) if default_now else None


async def get_json(ctx: Context, url: str, **kw) -> Any:
    r = await ctx.http.get(url, **kw)
    r.raise_for_status()
    return r.json()


async def get_text(ctx: Context, url: str, **kw) -> str:
    r = await ctx.http.get(url, **kw)
    r.raise_for_status()
    return r.text


RUN_TIMEOUT_S = 600          # the slowest source (OSM radars) takes about a minute


async def run_collector(ctx: Context, name: str) -> Result:
    col = REGISTRY[name]
    ctx.db.start_run(name)
    started = asyncio.get_event_loop().time()
    try:
        if not col.enabled():
            res = Result(0, "disabled (missing API key)")
            ctx.db.finish_run(name, True, res.message, 0, 0.0)
            return res
        # A hung source (slow-drip body, stuck socket) must not hold a scheduler slot for ever.
        res = await asyncio.wait_for(col.fn(ctx), timeout=RUN_TIMEOUT_S)
        ctx.db.finish_run(name, res.ok, res.message, res.count, asyncio.get_event_loop().time() - started)
        log.info("%s: %s (%d)", name, res.message, res.count)
        return res
    except asyncio.TimeoutError:
        msg = f"timed out after {RUN_TIMEOUT_S} s"
        ctx.db.finish_run(name, False, msg, 0, asyncio.get_event_loop().time() - started)
        log.warning("%s failed: %s", name, msg)
        return Result(0, msg, ok=False)
    except Exception as e:  # noqa: BLE001 - collectors must never take the app down
        msg = f"{type(e).__name__}: {str(e)[:300]}"
        ctx.db.finish_run(name, False, msg, 0, asyncio.get_event_loop().time() - started)
        log.warning("%s failed: %s", name, msg)
        return Result(0, msg, ok=False)
