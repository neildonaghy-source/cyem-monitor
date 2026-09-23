# CyEM Monitor

Self-hosted cyber and electromagnetic (CyEM) situational awareness: a dark map with
live layers, a feed rail, space-weather and HF status, and Ollama-generated
intelligence briefs. Replaces worldmonitor on the trade box. No accounts, no
upsell, no cloud dependencies beyond the public data sources themselves.

## Where it runs

* Container `cyem` from `~/cyem/docker-compose.yml`, listening on `127.0.0.1:3020`.
* Tailnet URLs (Tailscale serve): `https://trade.tail013324.ts.net:8443` (and `:8444`,
  kept for the Home Assistant iframe). No X-Frame-Options are sent, so no proxy is needed.
* Data: SQLite in `~/cyem/data-store/cyem.sqlite3` (items, snapshots, briefs, collector health).
* LLM: the existing `trading-bot-ollama-1` container, reached as `http://ollama:11434`
  over the shared `trading-bot_default` network. Model `qwen3.5:4b`, thinking disabled.

## Operating it

```bash
cd ~/cyem
docker compose up -d --build          # (re)build and start
docker compose logs -f --tail 100     # watch collectors and brief generation
docker compose exec cyem python -m app.cli status          # collector health
docker compose exec cyem python -m app.cli collect all     # run every collector once
docker compose exec cyem python -m app.cli collect gpsjam  # one collector
docker compose exec cyem python -m app.cli brief           # generate a brief now (prints it)
docker compose exec cyem python -m app.cli context         # see exactly what the model is shown
docker compose exec cyem python -m app.cli ask "what is affecting GNSS in the Baltic?"
```

The UI has the same controls: **Health** (top right) shows every collector and any
failing RSS feed with a "Run all collectors now" button; **Regenerate** in the brief
panel; the ask box streams answers.

## Data sources (all keyless unless stated)

| Domain | Source | Cadence |
|---|---|---|
| Cyber | CISA KEV catalogue | 1h |
| Cyber | NVD critical CVEs (7d) with FIRST EPSS scores | 2h |
| Cyber | ransomware.live recent victims | 1h |
| Cyber | Have I Been Pwned breaches | 6h |
| Cyber | abuse.ch Feodo Tracker C2 list | 1h |
| Cyber | abuse.ch ThreatFox IOCs, optional `ABUSECH_AUTH_KEY` | 3h |
| Cyber | OpenCTI (GraphQL): recent reports into the feed, new indicators and intrusion sets into the OpenCTI panel and brief, optional `OPENCTI_URL` + `OPENCTI_TOKEN` | 30m |
| EM | NOAA SWPC: Kp, R/S/G scales, GOES flares, F10.7, solar wind, alerts | 15m |
| EM | NOAA D-RAP global HF absorption grid (highest affected frequency), rendered as a map overlay | 15m |
| EM | NOAA OVATION aurora probability grid (30-40 min forecast), rendered as a map overlay | 15m |
| EM | KC2G real-time MUF(3000) contours and GIRO ionosonde foF2 / MUF / hmF2 / TEC values | 15m |
| EM | hamqsl.com HF/VHF band conditions | 1h |
| EM | gpsjam.org GNSS interference hexes (ADS-B derived, daily) | 6h |
| EM | Launch Library 2 upcoming launches | 6h |
| EM | Military aircraft on ADS-B (adsb.fi, adsb.lol fallback), classified ISR / EW / AEW / C2 / MPA / tanker / transport | 2m |
| EM | Celestrak TLEs for GNSS, military and SBAS satellites; sub-points computed with SGP4 | TLE 12h, positions 2m |
| EM | Radar sites and ground stations from OpenStreetMap (tower:type=radar, military=radar, man_made=radar / ground_station) via Overpass | 7d |
| EM | Strategic emitter reference layer (`data/emitters.json`: BMEWS/LPAR/OTH/ABM radars, VLF/HF, SIGINT and SATCOM stations, GNSS ground segment, deep-space antennas), positions approximate | static |
| Infra | IODA outage alerts (24h) | 30m |
| Infra | TeleGeography submarine cable geometry | 7d |
| Infra | Cloudflare Radar outages, attack origins, BGP hijacks, optional `CLOUDFLARE_API_TOKEN` | 1h |
| OSINT | GDELT DOC 2.0 articles for cyber / GNSS-EW / connectivity / space themes, placed by country detected in the headline (GDELT's GEO API was retired) | 2h |
| All | ~45 curated RSS feeds (NCSC, CISA, CERT-EU, The Record, C4ISRNET EW, RNTF, Breaking Defense, TeleGeography, RUSI, Google News topic queries ...) | 20m |

Feeds are defined in `app/feeds.py`; tag rules and severity heuristics in `app/tagging.py`;
country detection in `app/geo.py`. Edit, then `docker compose up -d --build`.

## Briefs

Scheduled at 06:00, 12:00, 18:00 and 00:00 Europe/London (`BRIEF_HOURS`), plus on demand.
The model is given a structured status block (space weather, HF, GNSS hexes, outages,
KEV/ransomware/C2 statistics, GDELT) and up to ~45 recent items, numbered, and is
instructed to cite them. A brief takes roughly 2 to 5 minutes on the i5-8500T; four a day
is a small fraction of what worldmonitor's 15-minute classifier used.

## Map

Basemap defaults to Esri World Dark Gray (no key). Esri imagery, OpenStreetMap and CARTO dark
are selectable in the layer panel; CARTO started overlaying "API required" on keyless tiles, which
is why it is no longer the default. Layers are grouped: Basemap, EM / spectrum, Cyber,
Infrastructure, OSINT / reference, each with all / none toggles; choices persist in the browser.
Live layers (military aircraft, satellites) refresh every two minutes. The HF / ionosphere group adds
the "fourth dimension": a day/night terminator with the grey-line band (recomputed every minute),
MUF contours and ionosonde points, D-RAP absorption and the aurora oval as Mercator-correct raster
overlays, and a click on any satellite draws its ground track for the next hour. The layer panel shows
the actual map symbols per layer and can be resized by dragging its bottom-right corner.

## Optional keys (`.env`)

* `CLOUDFLARE_API_TOKEN`: create at dash.cloudflare.com → API Tokens → custom token with
  permission *Account → Radar → Read* (free). Enables the Cloudflare outages layer, attack
  origin percentages and BGP hijack items.
* `NVD_API_KEY`: free from nvd.nist.gov; only raises the rate limit.
* `ABUSECH_AUTH_KEY`: free from auth.abuse.ch; enables ThreatFox IOC statistics.
* `OPENCTI_URL` + `OPENCTI_TOKEN`: any OpenCTI instance you can reach (profile → API access token).
  Adds an OpenCTI pill with reports / indicators / intrusion sets and feeds the brief. Do not host
  OpenCTI on this box: it needs Elastic/OpenSearch, RabbitMQ, MinIO and Redis (8–16 GB RAM alone).

## Reading the status strip

`HF SFI 101 · geomag inactive`: SFI is the 10.7 cm solar flux (about 70 = solar minimum, 150+ = lively
high bands); "geomag inactive / quiet" is hamqsl's geomagnetic field state and means calm conditions,
which is good for HF and GNSS. "unsettled / active / storm" turn the pill amber.

## Home Assistant

Point the existing iframe card at `https://trade.tail013324.ts.net:8444/` (unchanged URL).
On a phone the feed and brief panels become full-screen views via the bottom bar.

## Decommissioning record (2026-09-21)

worldmonitor was removed outright: compose stack down with volumes, the three
`worldmonitor*` images plus `nginx:alpine` and `redis:7-alpine`, `~/worldmonitor` (2.6 GB fork),
the four cron entries (seeders, fast/slow lanes, gpsjam refresh; crontab backup in
`~/crontab.pre-cyem.bak`), and the trading-bot link (`WORLDMONITOR_STRESS_URL` and
`WORLDMONITOR_REDIS_TOKEN` blanked in `~/trading-bot/.env`, backup `.env.bak-20260921`;
`ai_strategy.fetch_stress_index` returns None when the URL is empty). Tailscale serve
8443 and 8444 now proxy to `127.0.0.1:3020`. Docker build cache was pruned (4.3 GB).

## Attribution

Map tiles © OpenStreetMap contributors © CARTO. GNSS data derived from ADS-B via gpsjam.org.
Cable geometry © TeleGeography (CC BY-SA 4.0). Space weather: NOAA SWPC. HF: hamqsl.com (N0NBH).
Outages: IODA, Georgia Tech. Threat data: CISA, NVD, FIRST, abuse.ch, ransomware.live, HIBP, GDELT.

## Spectrum deconfliction (added 2026-09-23)

Top-bar **Spectrum** button. Enter planned emitters (frequency, bandwidth, power, position, optional UTC
window) and they are checked against the Ofcom licensed baseline and against each other.

- **Baseline:** Ofcom Wireless Telegraphy Register, `WTR.csv` from the spectrum information portal
  (https://www.ofcom.org.uk/spectrum/frequencies/spectrum-information-portal). Collector `wtr`, daily,
  conditional GET. Around 206k rows collapse to about 183k unique assignments. Cached CSV in
  `data-store/ofcom/` (excluded from OneDrive; re-downloadable). Published by Ofcom under s.31 Wireless
  Telegraphy Act 2006 and the EIR 2004; check re-use terms before sharing anything derived from it.
- **Not loaded:** rows with no frequency (about 3,700, mainly AIS).
- **Area-defined licences** (mostly BR Area Defined, about 3,400) have no position. They are checked on
  frequency only and reported as "area".
- **Privacy:** licensee surname and first-name columns are dropped at ingest, and a company field that looks
  like a personal name (title, or two or three plain words with no organisation term) is withheld
  (`spectrum_core.looks_personal`, about 6,400 assignments). It errs towards masking, so a few small
  organisations show as "Licensee withheld".
- **Conflict rule:** guarded overlap `|f1-f2| < (bw1+bw2)/2 + guard` within the radius (default 50 km);
  planned/planned pairs also need overlapping time windows. Severity: high = occupied bands overlap and
  within a third of the radius; medium = other overlap in radius or area licence; low = guard band only.
  T and R rows of one licence/frequency/site count once.
- **Harmonics and IM3 (screening, added 2026-09-23):** each planned emitter's harmonics up to order N
  (default 3; set 0 to disable) occupy n*f with width n*bw and are checked against licences, area licences
  and other planned emitters within the radius. Co-sited planned pairs (default within 1 km; 0 disables) with
  intersecting windows produce IM3 at 2f1-f2 and 2f2-f1, width 2*bw1+bw2, from their midpoint. Severity:
  IM3 on one of our own nets within a third of the radius = high; H2 or IM3 on a nearby licence = medium;
  everything else = low; a product never counts against its own sources. The victim net also lists the hit.
- **Not modelled yet:** transmit power, filtering and suppression levels, receiver selectivity, fifth-order
  and higher intermodulation, terrain. Treat product results as a list to check, not a prediction.
- **Band plan:** `data/uk_bandplan.json`, simplified display context only; UKFAT is authoritative.
- **Ollama note:** narrates the computed conflict set only (qwen3.5:4b, 1-2 min). Always check it
  against the table; small models still paraphrase loosely.
- **Scope:** open data only. No MOD, unit or role data is to be entered.

API: `/api/spectrum/{status,products,bandplan,wtr,planned,conflicts,view/<id>,brief}`; see `/api/docs`.
Code: `app/spectrum_core.py` (pure logic, tested), `app/spectrum_store.py` (SQLite, shadow-table load),
`app/spectrum_api.py` (routes, brief), `app/collectors/wtr.py`. Tests:

```
docker run --rm -v "$PWD":/src:ro -w /src python:3.12-slim sh -c "pip install -q pytest && python -m pytest -q tests"
```

Next increment: propagation-aware distance (terrain and power) or fifth-order IM; the GNSS interference layer already exists (gpsjam method).

## Link planner, point-to-point (added 2026-09-23)

Top-bar **Links** button. Two ends (pick on map), mast heights, band preset or your own equipment data.
Returns a terrain profile, first Fresnel zone clearance, diffraction, link budget, fade margin and, from
5 GHz, rain fade and annual availability. Verdict: go / marginal / no-go. Saved links create planned emitters
at both ends (go and optional return frequency), so they are deconflicted automatically; deleting a link
removes them.

- **Terrain:** Copernicus GLO-30 surface model (30 m, AWS open data), tiles downloaded on first use to
  `data-store/dem/` (excluded from OneDrive). Surface model, so some tree and building canopy is included.
- **Models:** effective earth radius k (default 4/3); Deygout diffraction limited to 3 edges with ITU-R P.526 J(v)
  (more edges over-estimate the loss: 6 edges gave 63 dB against 49 dB on the Chichester to Petersfield path); free-space
  loss; coarse sea-level gas table; ITU-R P.838-3 rain coefficients (tabulated from memory, verify for
  design use) with ITU-R P.530 path reduction and percentage scaling, valid 99.0 to 99.999%.
- **Not modelled:** clutter, multipath and ducting fades, antenna patterns and alignment, interference.
  Presets are typical values, not equipment data.
- Code: `app/link_core.py` (pure maths, tested in `tests/test_link_core.py`), `app/dem.py`, `app/link_api.py`
  (router `/api/links/*`, table `planned_links`, `planned_emitters.link_id`). Needs `rasterio` and `libexpat1`.

## Coverage: omni, sector, P2MP hub (added 2026-09-23)

Top-bar **Coverage** button. Site (pick on map), mast height, frequency, power, antenna gain, omni or sector
(azimuth, beamwidth; 3GPP-style pattern with 25 dB front-to-back), radius up to 60 km, receiver height, gain,
sensitivity and required margin. Computes received level on 360 radials at about 50 m steps (capped at 600
samples, so about 83 m at 50 km) in 1 to 5 s, and shows a map overlay: strong (margin + 10 dB), adequate
(required margin) and marginal (above sensitivity). Stats: adequate and marginal areas, furthest adequate range,
and the interference footprint above the site threshold.

- **Model:** free space + Deygout diffraction limited to 3 edges (same method as the link planner) + gases, on
  the Copernicus 30 m surface model with earth radius factor k. Cross-check: valley site to Petersfield, coverage
  -109.5 dBm against the link planner -114.4 dBm; the 5 dB difference is the coarser coverage sampling. Earlier
  single-edge and Bullington versions were 35 and 19 dB optimistic and were replaced before release.
- **Deconfliction:** a saved site creates a planned emitter (`planned_emitters.site_id`). For that emitter the
  fixed radius is replaced by the site radius, and a licence only counts as a clash if the predicted level of our
  signal at its location reaches the interference threshold (default -120 dBm). The conflict table shows that
  predicted level. Severity: high if 20 dB or more above threshold with occupied-band overlap, medium otherwise.
- **Not modelled:** clutter and buildings, antenna tilt and vertical pattern, receiver antenna pattern,
  multipath and time variability. Screening grade.
- Code: `app/coverage_core.py` (numpy; tests in `tests/test_coverage_core.py`), `app/coverage_api.py`
  (router `/api/coverage/*`, table `coverage_sites`, polar grid stored compressed), `dem.grid_sampler()`.

Next options: export of the plan (frequencies, conflicts, links, coverage) to a document; finer coverage sampling
on demand; HF skywave planning using the existing MUF layer.
