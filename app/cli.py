"""Command-line helpers for operating the monitor inside the container.

  python -m app.cli collect all|<name>     run collectors once
  python -m app.cli brief [hours]          generate a brief now
  python -m app.cli ask "question"         ask the monitor
  python -m app.cli status                 print collector health
  python -m app.cli context                print the brief prompt the model would see
  python -m app.cli user add <name>        create an internet log-in (prompts for the password twice)
  python -m app.cli user passwd <name>     change a password (signs that user out everywhere)
  python -m app.cli user signout <name>    end all of that user's sessions
  python -m app.cli user del <name>        delete a log-in
  python -m app.cli user list              list log-ins, last sign-in, open sessions, locks
  python -m app.cli met <lat> <lon> [time] met for a place and hour (UTC ISO time, default now), as EMO uses it
"""
from __future__ import annotations

import asyncio
import getpass
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


def _ask_password() -> str:
    """Typed twice at a terminal, or one line on stdin when piped (for scripted set-up)."""
    if not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\n")
    a = getpass.getpass("New password: ")
    if a != getpass.getpass("Again: "):
        raise ValueError("the two passwords differ")
    return a


def _user(args: list[str]) -> int:
    from . import auth
    if not args:
        print(__doc__)
        return 1
    op, name = args[0], (args[1] if len(args) > 1 else "")
    try:
        if op == "list":
            for u in auth.list_users():
                lock = "  LOCKED" if u["locked"] else ""
                print(f"{u['username']:20s} created {u['created_at']}  last sign-in {u['last_login'] or '-'}  sessions {u['sessions']}{lock}")
            return 0
        if not name:
            print("name required")
            return 1
        if op == "add":
            auth.add_user(name, _ask_password())
            print(f"user {auth._norm(name)} added")
        elif op == "passwd":
            auth.set_password(name, _ask_password())
            print(f"password changed; {auth._norm(name)} signed out everywhere")
        elif op == "signout":
            print(f"{auth.sign_out_everywhere(name)} session(s) ended")
        elif op == "del":
            print("deleted" if auth.delete_user(name) else f"no user {name}")
        else:
            print(__doc__)
            return 1
    except ValueError as e:
        print(f"error: {e}")
        return 2
    return 0


def _met(args: list[str]) -> int:
    from datetime import datetime, timezone
    from . import met
    if len(args) < 2:
        print("usage: python -m app.cli met <lat> <lon> [time]")
        return 2
    when = None
    if len(args) > 2:
        when = datetime.fromisoformat(args[2])
        when = when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when
    st = asyncio.run(met.met_state(float(args[0]), float(args[1]), when))
    levels = st.pop("levels", [])
    print(json.dumps(st, indent=1, default=str))
    if levels:
        print("profile (m above ground, N, M): " + "; ".join(f"{x['h']} {x['n']} {x['m']}" for x in levels))
    return 0


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
    elif cmd == "user":
        return _user(args)
    elif cmd == "met":
        return _met(args)
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
