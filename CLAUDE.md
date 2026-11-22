# CyEM Monitor — project notes for Claude Code

> **Status (18 Nov 2026): running on the EVO-X2** (`docs/DEPLOY-EVO.md`) at https://nucbox-evo-x2.tail013324.ts.net/:
> no log-in on the tailnet, username and password from the internet. It was retired on 7 Oct and rebuilt from 18 Nov
> (`docs/REBUILD-PLAN.md`). The trade URLs, ports and paths further down are historical.

Self-hosted cyber + electromagnetic situational awareness dashboard. Replaced the worldmonitor
fork on this host on 2026-09-21. Owner: Neil (Royal Signals / CEMA background); write for a
senior practitioner, British English, no marketing tone.

## Layout
- `app/main.py` FastAPI routes (`/api/status`, `/api/items`, `/api/layers/<name>`, briefs, ask SSE, collectors).
- `app/scheduler.py` asyncio loop: runs collectors on their intervals (staggered, 3 concurrent), fires scheduled briefs, nightly purge.
- `app/collectors/*.py` one `@register(name, interval_s, domain, description)` function per source. Each returns `Result(count, message, ok)`; failures are caught in `run_collector` and shown in Health. Never let a collector raise into the scheduler.
- `app/feeds.py` curated RSS list; `app/tagging.py` keyword tags + severity heuristics; `app/geo.py` country detection (`data/countries.json`).
- `app/llm.py` Ollama client (`/api/chat`, `think:false`), brief context builder, ask context.
- `static/` vanilla JS UI: edit `static/src/*.js`, then `sh static/build.sh` to rebuild `app.js` (concatenation, no bundler).
  Leaflet, marked, DOMPurify and milsymbol are vendored under `static/vendor/`. Model output is cleaned by DOMPurify against an
  allowlist (`sanitize()` in 07-brief.js; check with `python3 tests/ui/sanitize_check.py`); the server sends a CSP with
  script-src 'self', so no inline scripts or inline event handlers.
- Spectrum deconfliction: `app/spectrum_core.py` (pure, stdlib, unit-tested in `tests/`), `app/spectrum_store.py` (tables `wtr`, `planned_emitters`; bulk load on its own connection into `wtr_new` then swap), `app/spectrum_api.py` (router `/api/spectrum/*`), `app/collectors/wtr.py` (Ofcom WTR, daily, ETag). UI is the Plan button (Spectrum tab) + `planned` and `wtr` layers.
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
Runs on the EVO-X2 in the WSL distro CyEM (docs/DEPLOY-EVO.md): https://nucbox-evo-x2.tail013324.ts.net/ on the tailnet and,
through Funnel, on the internet with a log-in. Until 7 Oct 2026 it was on trade at :8443/:8444.

## Conventions and gotchas
- Sources must degrade gracefully without keys; keyed sources use `enabled=lambda: bool(settings.<key>)`.
- RSS fetches send a Chrome-like User-Agent and `Accept: */*` (CISA 403s otherwise). GDELT: one request per 5 s per IP, keep the 30 s pacing. ADS-B: adsb.fi primary, adsb.lol fallback (airplanes.live 403s).
- Ollama runs on the EVO-X2 (`OLLAMA_URL` in `.env`); keep briefs to a few per day, do not add per-item LLM calls (that is what made worldmonitor pin the CPU).
- Item ids are sha1 of source + guid; `upsert_items` ignores existing ids, so re-runs are idempotent.
- The container runs as uid 1000 to match `trade`; keep that if you change the Dockerfile.
- Country/lat-lon on news items are heuristics for map placement, not attribution. Say so in UI text.
- Reference data in `data/emitters.json` is hand-curated with approximate positions; keep the "approx." notes when editing.
- Backups (EVO, since 19 Nov 2026): cron 00:50 UTC `~/bin/cyem-offbox-push.sh` (user cyem) sends a DB snapshot to trade
  `~/cyem-offbox` (key limited to a receive-only forced command; 7 kept), which trade's OneDrive job takes off-site. See docs/DEPLOY-EVO.md.
- Spectrum: open data only; never add MOD/unit/role data. Keep licensee surname/first name out of the WTR load.
  Area-defined WTR rows have NULL lat/lon by design. Conflict logic changes go in `spectrum_core.py` with tests.
- UI tests: tests/ui/run.sh (EMO), and the same docker command with plan_smoke.py or ui_audit.py in place of emo_smoke.py.
- Tests: `docker run --rm -v "$PWD":/src:ro -w /src python:3.12-slim sh -c "pip install -q -r requirements.txt pytest && python -m pytest -q tests"`
  (tests/test_emo_scenarios.py runs every example on synthetic terrain with a throw-away database; about 40 s)
- Work on branches; `main` is what is deployed once merged. A pre-change DB copy is at `data-store/backup/cyem-pre-spectrum.sqlite3`.
- Box-level changes (backup excludes, `~/bin/runbook_gen.py`) must be kept in step with this file and the README.
- Harmonic and IM3 screening live in `spectrum_core` (`harmonic_emitters`, `im3_emitters`, `check_products`); `run_conflicts` takes `harm_order` and `cosite_km`. Keep product severities below fundamental ones except IM3 on own nets.
- Link planner: `link_core.py` stays stdlib-only and tested; terrain via `dem.heights()` (rasterio, lazy import, run in a thread). Saved links own their planned emitters via `link_id`; keep create/delete in step.
- Coverage: `coverage_core.polar_prx` is vectorised Deygout (3 edges) per radial; keep it consistent with `link_core.deygout_loss_db` (depth 1). Cross-check any model change against the link planner on a real path before shipping. Saved sites own their planned emitter via `site_id`.
- Web client (browser; bump `BUILD` in `static/src/00-head.js` (then `sh static/build.sh`), the `?v=` in `index.html` and the cache name in `sw.js` together). After a release, refresh the offline copy on the Mac mini: `git bundle create ~/Backups/cyem-monitor/cyem-monitor-YYYYMMDD.bundle --all`
  plus its `.sha256` (the copy of 18 Nov 2026 is there with a README).
- Keys (AISSTREAM_KEY, OPENCELLID_KEY) live only in `.env`; never log or echo URLs containing them. `.env.*` is ignored except `.env.example`.
- Internet access: Tailscale Funnel requests (header `Tailscale-Funnel-Request`) must sign in (`app/auth.py`: users and sessions
  tables, scrypt, 30-day sessions, 5 tries per address per 15 min, 10 per account then a 15-minute lock). Tailnet requests
  need no log-in. Accounts: `python -m app.cli user add|passwd|signout|del|list`. With no accounts the internet is refused.
- Cross-site guard (`auth.cross_site`, both paths): POST/PUT/PATCH/DELETE sent by another site's page is refused with 403
  (Sec-Fetch-Site, else Origin against Host/X-Forwarded-Host); requests with neither header (scripts, HA) pass. Framing:
  CSP `frame-ancestors 'self'` plus `FRAME_ANCESTORS` (empty by default). No HA panel: added and then removed on
  18 Nov 2026 at Neil's request (`~/ha-review/ha-cyem-panel-20261118.py` on trade recreates it if ever wanted).
- Met (18 Nov 2026): `met_core.py` (pure, stdlib, tested: P.453 refractivity, k, ducts and cut-off, neutral evaporation duct,
  P.840 fog) and `met.py` (Open-Meteo forecast, historical-forecast and marine APIs, table `met_cache`, `/api/met`, CLI `met`).
  RunIn `met`/`met_time`/`k_factor`/`rain_mm_h`/`visibility_m`; `run()` sets the `ATM` contextvar, planning calls outside a
  run use the last run's; `_P2P` and `_COV` keys include the atmosphere signature. Ducts are flagged, never modelled.
- Corridors (phase 5): `corridor_core.py` (Dijkstra from both ends, band, legs; tested) and `corridor_api.py`
  (`POST /api/emo/plan/corridor`). Scheduled runs continue the rebuild from `docs/CONTINUE.md`: keep it current.
- New modules: `omni.py` (search/Ask context), `websearch.py` (SearXNG), `export.py`, `ukfat.py`, `satnogs.py`, `hf_core.py` + `hf_api.py`, `cells.py`, collectors `ais`, `cells`, `air`, `ukfat`, `satnogs`.
- Remote: `origin` is the private GitHub repo neildonaghy-source/cyem-monitor. Work on a branch, open a pull request, merge to
  `main`; `main` is what gets deployed. Run long jobs with nohup and read the logs (tool calls time out).

- Clients: the web app, and native Mac and iPhone apps in `native/` that host the web interface (as the September apps
  did; their source was never found). Do not rebuild web features natively. See native/README.md, docs/NATIVE-PLAN.md.
- EMO (`emo_api.py`): symmetric red/blue ES/EA/EP on terrain; reuses coverage_api._compute (power capped at 70 dBm, offset added for higher EIRP) and link_core.analyse for per-pair paths; heavy work limited by asyncio.Semaphore(3); cyem container cpus 4.0. Notional data only.

## EMO planning layer (added 2026-09-25)
- app/emo_plan.py: score maps (reciprocity coverage grids), tune (power/antenna/channel), joint re-site (verified), MLCOA/MDCOA
  course-of-action generator with revert, timeline (light per-step runs). app/emo_api.py: workspaces (X-CyEM-WS, contextvar WS,
  _LAST is a per-workspace proxy), COAs (emo_coas table), scoreboard, probabilities (sigma_db), radar_picture(), spoofing (ea_mode).
- Operator guide and endpoint list: docs/EMO.md. Browser smoke test: tests/ui/run.sh (private workspace uitest1, ~3 min).
- Conventions: every solver proposes then verifies with the exact pairwise model; stand-off 10 km and own-side rule; civil (grey)
  is located, never targetable; planning answers in Ask bypass the language model.
- After a dependency change: python3 tools/software_inventory.py (updates docs/SOFTWARE.md + software.json, copied into the nightly trade runbook).
- Release: bump BUILD in static/src/00-head.js and run static/build.sh, ?v= in index.html/sw.js, cache name in sw.js; commit; push; docker compose up -d --build cyem.

- ~/Documents/Codex/CyEM on the Mac now holds spectrum policy papers only; the September app source, deploy bundles and
  scratch files there are gone.
- SDR live listen (20 Nov 2026): `sdr_live.py` proxies `/sdr/live/` (HTTP + WS, GET only, settings/login paths refused, own CSP)
  to OpenWebRX+ on trade only while `/api/sdr/mode` asks for live and the node reports it. Trade agent `pi/trade/cyem-sdr-mode`
  (root, polls every 10 s) shares the sweep flock, pauses ecowitt-receiver, cap 120 min, always restores. Never record audio or IQ.
- Phase 4 part 2 (22 Nov 2026): `spacewx_core.py` (pure, tested: HF and GNSS by time step from the SWPC scales),
  `met_core.sea_state/sea_clutter_db/platform_limits` (notional `LIMITS`), `met.met_grid` + `GET /api/met/grid` (met map
  layer, batched Open-Meteo, shares `met_cache`). Space weather applies only with `met="forecast"` (`SPACE` contextvar in
  `emo_api.run`). Corridors take met, limits, clutter and space weather per layer (`corridor_api._env_factory`).
- EMO examples (22 Nov 2026, finding 13): JSON in `data/emo_examples/`, checked by `app/emo_examples.check` on load
  (bad files left out and logged); `tests/test_emo_examples.py` must stay green. Notional values only.
- Amphibious (phase 6 part 1, 22 Nov 2026): corridor domain `amphib` (water to the beach, land only within 1 km of it),
  `met_core.LIMITS["amphib"]`, `breaker_height_m`, `surf` (priced round the landing point per layer; holds allowed),
  summary `beach` (relay check through the craft). Opposing comms EA lowers corridor C2 in every domain. Example 7 Studland.
- Default screen: first run opens on the UK with live layers only; reference layers and notional EMO off (`cyem.layersv` migration).
- Icon source and build script: `native/Icon/` (`build_icons.py` regenerates the Xcode AppIcon set and `static/icons/`).
