# CyEM Monitor — project notes for Claude Code

Self-hosted cyber + electromagnetic situational awareness dashboard. Replaced the worldmonitor
fork on this host on 2026-09-21. Owner: Neil (Royal Signals / CEMA background); write for a
senior practitioner, British English, no marketing tone.

## Layout
- `app/main.py` FastAPI routes (`/api/status`, `/api/items`, `/api/layers/<name>`, briefs, ask SSE, collectors).
- `app/scheduler.py` asyncio loop: runs collectors on their intervals (staggered, 3 concurrent), fires scheduled briefs, nightly purge.
- `app/collectors/*.py` one `@register(name, interval_s, domain, description)` function per source. Each returns `Result(count, message, ok)`; failures are caught in `run_collector` and shown in Health. Never let a collector raise into the scheduler.
- `app/feeds.py` curated RSS list; `app/tagging.py` keyword tags + severity heuristics; `app/geo.py` country detection (`data/countries.json`).
- `app/llm.py` Ollama client (`/api/chat`, `think:false`), brief context builder, ask context.
- `static/` vanilla JS UI (`app.js`), Leaflet + marked vendored under `static/vendor/`. No build step.
- `data/` reference JSON (emitters, APT groups, countries). `data-store/` bind mount with the SQLite DB (git-ignore worthy, not in the tarball).

## Run / test
```
docker compose up -d --build                      # deploy (image cyem-monitor:latest, container cyem, 127.0.0.1:3020)
docker compose logs -f --tail 100 cyem
docker compose exec cyem python -m app.cli collect <name>|all   # run collectors once, prints OK/ERR per collector
docker compose exec cyem python -m app.cli brief                # generate a brief now (2-5 min on CPU)
docker compose exec cyem python -m app.cli context              # exactly what the model is shown
python3 -m pyflakes app                                          # lint (host python is 3.14; the image is 3.12)
node --check static/app.js
```
Reachable on the tailnet at https://trade.tail013324.ts.net:8443 (and :8444 for the HA iframe).

## Conventions and gotchas
- Sources must degrade gracefully without keys; keyed sources use `enabled=lambda: bool(settings.<key>)`.
- RSS fetches send a Chrome-like User-Agent and `Accept: */*` (CISA 403s otherwise). GDELT: one request per 5 s per IP, keep the 30 s pacing. ADS-B: adsb.fi primary, adsb.lol fallback (airplanes.live 403s).
- Ollama is the trading-bot's container on `trading-bot_default`; keep briefs to a few per day, do not add per-item LLM calls (that is what made worldmonitor pin the CPU).
- Item ids are sha1 of source + guid; `upsert_items` ignores existing ids, so re-runs are idempotent.
- The container runs as uid 1000 to match `trade`; keep that if you change the Dockerfile.
- Country/lat-lon on news items are heuristics for map placement, not attribution. Say so in UI text.
- Reference data in `data/emitters.json` is hand-curated with approximate positions; keep the "approx." notes when editing.
- Backups: `~/bin/onedrive-backup.sh` snapshots the DB to `data-store/backup/cyem-backup.sqlite3` nightly; the live WAL DB is excluded from the sync.
