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
- Spectrum deconfliction: `app/spectrum_core.py` (pure, stdlib, unit-tested in `tests/`), `app/spectrum_store.py` (tables `wtr`, `planned_emitters`; bulk load on its own connection into `wtr_new` then swap), `app/spectrum_api.py` (router `/api/spectrum/*`), `app/collectors/wtr.py` (Ofcom WTR, daily, ETag). UI is the Spectrum button + `planned` and `wtr` layers in `static/app.js`.
- `data/` reference JSON (emitters, APT groups, countries, `uk_bandplan.json`). `data-store/` bind mount with the SQLite DB (git-ignore worthy, not in the tarball).

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
- Spectrum: open data only; never add MOD/unit/role data. Keep licensee surname/first name out of the WTR load.
  Area-defined WTR rows have NULL lat/lon by design. Conflict logic changes go in `spectrum_core.py` with tests.
- Tests: `docker run --rm -v "$PWD":/src:ro -w /src python:3.12-slim sh -c "pip install -q pytest && python -m pytest -q tests"`
- Work on branches; `main` is what is deployed once merged. A pre-change DB copy is at `data-store/backup/cyem-pre-spectrum.sqlite3`.
- Box-level changes (backup excludes, `~/bin/runbook_gen.py`) must be kept in step with this file and the README.
- Harmonic and IM3 screening live in `spectrum_core` (`harmonic_emitters`, `im3_emitters`, `check_products`); `run_conflicts` takes `harm_order` and `cosite_km`. Keep product severities below fundamental ones except IM3 on own nets.
- Link planner: `link_core.py` stays stdlib-only and tested; terrain via `dem.heights()` (rasterio, lazy import, run in a thread). Saved links own their planned emitters via `link_id`; keep create/delete in step.
- Coverage: `coverage_core.polar_prx` is vectorised Deygout (3 edges) per radial; keep it consistent with `link_core.deygout_loss_db` (depth 1). Cross-check any model change against the link planner on a real path before shipping. Saved sites own their planned emitter via `site_id`.
- Mac client is a Safari web app on Neil's Mac (loads the live site; bump `BUILD` in `static/app.js`, the `?v=` in `index.html` and the cache name in `sw.js` together). After a release, refresh the Mac bundle: `git archive --prefix=cyem/ main` to `~/cyem-deploy/cyem-monitor-vNN.tgz` on the Mac. No git remote exists.
- Keys (AISSTREAM_KEY, OPENCELLID_KEY) live only in `.env`; never log or echo URLs containing them. `.env.*` is ignored except `.env.example`.
- New modules: `omni.py` (search/Ask context), `websearch.py` (SearXNG), `export.py`, `ukfat.py`, `satnogs.py`, `hf_core.py` + `hf_api.py`, `cells.py`, collectors `ais`, `cells`, `air`, `ukfat`, `satnogs`.
- Push after each merge: `git push origin main` (remote alias github-cyem). Tool-call timeouts from the Mac are common: run long jobs with nohup and read logs.

- Clients: native CyEM apps on the Mac and iPhone (source ~/cyem-app on the Mac) embed Tailscale and load https://trade.tail013324.ts.net:8443; keep that URL and the Tailscale serve on 8443 stable.
- EMO (`emo_api.py`): symmetric red/blue ES/EA/EP on terrain; reuses coverage_api._compute (power capped at 70 dBm, offset added for higher EIRP) and link_core.analyse for per-pair paths; heavy work limited by asyncio.Semaphore(3); cyem container cpus 4.0. Notional data only.

## EMO planning layer (added 2026-09-25)
- app/emo_plan.py: score maps (reciprocity coverage grids), tune (power/antenna/channel), joint re-site (verified), MLCOA/MDCOA
  course-of-action generator with revert, timeline (light per-step runs). app/emo_api.py: workspaces (X-CyEM-WS, contextvar WS,
  _LAST is a per-workspace proxy), COAs (emo_coas table), scoreboard, probabilities (sigma_db), radar_picture(), spoofing (ea_mode).
- Operator guide and endpoint list: docs/EMO.md. Browser smoke test: tests/ui/run.sh (private workspace uitest1, ~3 min).
- Conventions: every solver proposes then verifies with the exact pairwise model; stand-off 10 km and own-side rule; civil (grey)
  is located, never targetable; planning answers in Ask bypass the language model.
- Release: bump BUILD in static/app.js, ?v= in index.html/sw.js, cache name in sw.js; commit; push; docker compose up -d --build cyem.
