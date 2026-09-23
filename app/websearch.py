"""Web search for Ask AI via the self-hosted SearXNG container (internal network only)."""
from __future__ import annotations

import os

import httpx

SEARXNG = os.environ.get("SEARXNG_URL", "http://searxng:8080")


async def search(q: str, n: int = 6) -> list[dict]:
    """Top results as {title, url, snippet, engine}. Empty list if SearXNG is unavailable."""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{SEARXNG}/search", params={"q": q, "format": "json", "language": "en-GB"})
            r.raise_for_status()
            res = r.json().get("results", [])
    except Exception:  # noqa: BLE001
        return []
    out, seen = [], set()
    for x in res:
        u = x.get("url")
        if not u or u in seen:
            continue
        seen.add(u)
        out.append({"title": (x.get("title") or "")[:160], "url": u, "snippet": (x.get("content") or "")[:400],
                    "engine": x.get("engine") or ""})
        if len(out) >= n:
            break
    return out
