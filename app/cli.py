"""Command-line helpers for operating the monitor inside the container.

  python -m app.cli collect all|<name>     run collectors once
  python -m app.cli brief [hours]          generate a brief now
  python -m app.cli ask "question"         ask the monitor
  python -m app.cli status                 print collector health
  python -m app.cli context                print the brief prompt the model would see
"""
from __future__ import annotations

import asyncio
import json
import sys

from . import llm
from .collectors import REGISTRY, Context, make_http, run_collector
from .db import get_db


async def _collect(names: list[str]) -> None:
    db = get_db()
    http = make_http()
    ctx = Context(db=db, http=http)
    try:
        for n in names:
            if n not in REGISTRY:
                print(f"unknown collector: {n}; known: {', '.join(REGISTRY)}")
                continue
            res = await run_collector(ctx, n)
            print(f"{n:14s} {'OK ' if res.ok else 'ERR'} {res.count:5d}  {res.message}")
    finally:
        await http.aclose()


async def _brief(hours: int) -> None:
    db = get_db()
    print("generating brief ...", file=sys.stderr)
    res = await llm.generate_brief(db, kind="manual", hours=hours)
    print(json.dumps(res, indent=1), file=sys.stderr)
    if res.get("ok"):
        print(db.brief()["content"])


async def _ask(q: str) -> None:
    msgs = llm.build_ask_messages(get_db(), q)
    async for tok in llm.chat_stream(msgs):
        print(tok, end="", flush=True)
    print()


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd, args = argv[0], argv[1:]
    if cmd == "collect":
        names = list(REGISTRY) if (not args or args[0] == "all") else args
        asyncio.run(_collect(names))
    elif cmd == "brief":
        asyncio.run(_brief(int(args[0]) if args else 24))
    elif cmd == "ask":
        asyncio.run(_ask(" ".join(args)))
    elif cmd == "status":
        for r in get_db().runs():
            print(f"{r['name']:14s} ok={r['ok']} count={r['count']} {r['finished_at']}  {r['message']}")
    elif cmd == "context":
        msgs, n = llm.build_brief_messages(get_db())
        print(f"# {n} items, {sum(len(m['content']) for m in msgs)} chars\n")
        for m in msgs:
            print(f"--- {m['role']} ---\n{m['content']}\n")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
