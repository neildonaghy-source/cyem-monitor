# CyEM Monitor

> **Status (18 Nov 2026): running on the EVO-X2** (`docs/DEPLOY-EVO.md`) at https://nucbox-evo-x2.tail013324.ts.net/:
> no log-in on the tailnet, username and password from the internet. It was retired on 7 Oct and rebuilt from 18 Nov
> (`docs/REBUILD-PLAN.md`). The trade URLs, ports and paths further down are historical.

Self-hosted cyber and electromagnetic (CyEM) situational awareness: a dark map with
live layers, a feed rail, space-weather and HF status, and Ollama-generated
intelligence briefs. Replaces worldmonitor on the trade box. No accounts, no
upsell, no cloud dependencies beyond the public data sources themselves.

## Where it runs

* Since 18 Nov 2026: the EVO-X2, WSL distro `CyEM`, container `cyem` from `/home/cyem/cyem/docker-compose.yml`,
  listening on `127.0.0.1:3020` (`docs/DEPLOY-EVO.md`). Until 7 Oct 2026 it ran on trade.
* `https://nucbox-evo-x2.tail013324.ts.net/`: Tailscale serve on the tailnet (no log-in) and Funnel on the internet
  (username and password). Home Assistant shows it in the admin-only "CyEM Monitor" panel; the CSP's
  `frame-ancestors` allows this site and the HA origins in `FRAME_ANCESTORS`, and nothing else may frame it.
* Data: SQLite in `data-store/cyem.sqlite3` (items, snapshots, briefs, collector health, accounts, EMO work).
* LLM: Ollama on the EVO-X2 (`OLLAMA_URL`, `OLLAMA_MODEL` in `.env`), thinking disabled.

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

The "CyEM Monitor" panel (dashboard `cyem-panel`, storage mode, admin only) is one panel view with an iframe card
pointing at `https://nucbox-evo-x2.tail013324.ts.net/`. It loads on tailnet devices; the internet log-in cannot work
inside HA's iframe (the session cookie is SameSite=Lax), so off the tailnet open CyEM directly instead. If HA is
reached from a new address, add that origin to `FRAME_ANCESTORS` or the frame stays blank.
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

## Clients and copies (updated 2026-09-23)

- **Mac app:** Safari "Add to Dock" web app `~/Applications/CyEM OSINT Platform.app` on Neil's Mac, pointing at
  https://trade.tail013324.ts.net:8443/. It loads the live site, so it updates itself; static assets carry
  `?v=<BUILD>` so a stale cache cannot persist. Confirm the build shown at the top of the layers panel.
  To force a refresh, quit and reopen the app.
- **Deploy bundles:** `~/Documents/Codex/CyEM/cyem-deploy/cyem-monitor-v14.tgz` on the Mac is `git archive` of `main` at 154f3b1
  (code only: no `.env`, database, Ofcom CSV or DEM tiles). v13 was the 21 Sep initial import.
- **Version control:** local git on the trade box only (no remote). Off-box copies are the OneDrive home backup
  and the Mac deploy bundles. Work on branches; merge to `main` with fast-forward.

## Added 2026-09-23 (second pass)

**Home-screen search and Ask AI** (top bar, `/` to focus). Search covers feed items, Ofcom licences (name, licence
number or frequency), planned emitters, links, coverage sites, UKFAT allocations and satellite downlinks; "near
<place>" geocodes via OpenStreetMap Nominatim (cached) and filters licences to 30 km. Ask AI answers under fixed
headings: From CyEM data; From web search (unverified), only when Web is ticked; General knowledge (not from CyEM
data). Model: shared qwen3.5:4b on CPU, about 2 minutes per answer. Code: `app/omni.py`, `/api/search`, `/api/ask`.

**Web search** uses a self-hosted SearXNG container (`cyem-searxng`, internal Docker network only, no published
port, 256 MB). Settings with the secret key: `searxng/settings.yml` (git-ignored, mode 600). Web results are
cited [W1] and labelled unverified. Code: `app/websearch.py`.

**Plan export**: Spectrum panel, Export plan (Word): emitters, conflicts, links, coverage, sources and limits.
Code: `app/export.py` (python-docx).

**Ships (AIS)**: aisstream.io websocket sampled 45 s every 5 min, UK waters; static data cached across runs.
Key `AISSTREAM_KEY` in `.env`. **All aircraft (ADS-B)**: adsb.fi (adsb.lol fallback), 250 nm of UK, every 2 min;
degraded GNSS flagged at NIC 1 to 6 (NACp was too noisy), emergency squawks flagged. **Mobile cells**:
OpenCelliD MCC 234 weekly bulk download (free tier allows 2 downloads per file per day; a fresh local copy is
reused), separate DB `data-store/cells/cells.sqlite3` (not backed up). Key `OPENCELLID_KEY` in `.env`; errors never
echo the URL (it carries the key).

**UKFAT**: Ofcom UK Frequency Allocation Table parsed from the PDF's tables (text extraction scrambled footnotes and
was rejected) into `data-store/ofcom/ukfat.json`: about 574 bands and 334 UK footnotes; monthly check, re-parsed only
when the PDF changes. Used by search and Ask AI. Code: `app/ukfat.py`, collector `ukfat`.

**Satellites**: SatNOGS DB active downlinks (weekly, about 2,900) in search and Ask AI within +/-50 kHz; pass
prediction over the map centre from CelesTrak TLEs and SGP4 (`/api/sat/passes`). Code: `app/satnogs.py`.

**HF skywave now-cast** (HF button): hops, control points, foF2 / MUF(3000) / hmF2 by inverse-distance weighting of
fresh ionosondes (KC2G/GIRO), hop MUF by secant-law scaling of each station's MUF(3000), FOT = 0.85 x MUF, lower
limit from NOAA D-RAP (space weather only; normal daytime absorption not modelled). Checked: Chichester to Berlin
994 km MUF 14.3 MHz; NVIS 102 km MUF 7.1 MHz (about foF2). Code: `app/hf_core.py` (tested), `app/hf_api.py`.

**Coverage fine sampling**: optional 1,000 samples per radial (about 3x slower).

**Git remote**: private `neildonaghy-source/cyem-monitor`, pushed from the box with deploy key `~/.ssh/cyem_github`
(host alias `github-cyem`). `.env`, all `.env.*` except the example, data and SearXNG settings are git-ignored.
Release routine: branch, test (`pytest tests`), merge fast-forward to `main`, `git push origin main`, bump BUILD in
`static/app.js` with the `?v=` in `index.html` and the cache name in `sw.js`, refresh the Mac bundle.

## EMO: red / blue electromagnetic operations (added 2026-09-25)

EMO button (and phone Tools sheet). Notional scenarios only. Symmetric model: both sides sense, attack and protect.
- **ES**: each side's sensors against the other side's radiating entities (emitters, effectors, net users with EIRP),
  per-pair terrain paths at both heights (airborne ES works), detection margin, DF lines of bearing, fix from the best
  two bearings with error = range x DF sigma combined over the cut angle; fixes within 1 km flagged TARGETABLE.
- **EA**: effectors against the other side's nets: J/S at each receiver, jammer power scaled to the victim channel
  (10 log Bj/Bv), per-net fail threshold (VHF 0 dB, datalink 6 dB, GNSS 35 dB); denial zones inside net coverage.
- **EP**: EMCON on/off per emitter; siting, antenna sector and power. Drag units at T+0 to move them and re-run.
- Tracks and a time slider with Play; APP-6 symbols via milsymbol (MIT, vendored in static/vendor); editable SIDCs.
- Radar is modelled as an emitter for ES only (no radar detection or radar-jamming J/S). Screening grade.
- Examples: battlegroup vignette (30 entities), Brecon siting, Solent maritime, A303 GNSS, C-UAS vs datalink.
- Performance: first run of the vignette about 48 s (terrain grids and paths computed 3 at a time; cyem container
  raised to 4 CPUs), later steps 10 to 20 s; results cached per position.
Code: `app/emo_api.py`, `app/emo_examples.py`, `app/ems_core.py`; tests `tests/test_emo.py`.

- **Focus (added 2026-09-25):** tap a symbol to see only that entity: its footprint in strength bands against the opposing sensors, who picks it up (margin, DF), what it hears, what it jams or is jammed by, and its fix. Whole-picture washes are off by default (tick boxes in the panel). Footprints stop at the entity compute radius (Edit to change).
- **Footprint radius (2026-09-25):** up to 100 km; blank = automatic (airborne 100, HF/VHF 80, UHF 60, 1 GHz+ 40 km). Pairwise detections and DF fixes are computed along full terrain paths at any range; only the map footprints use the radius. Same compute cost (fixed 600 samples per radial, coarser steps at long range). DEM keeps up to 40 tiles open.
- **Batch 2 (2026-09-25):** frequency hopping (hopset width) and processing gain per net; on-air windows (timeline); scenario save/load; 17 generic emitter templates; scenario targetable threshold (tactical 1 km, MDO example 5 km); Ask AI on the scenario (pre-sorted facts to a small model, about 1 minute); EMO briefing export to Word, one section per phase with a schematic (no basemap) and tables (Pillow added). Map washes are for ground receivers; airborne results are in cards and tables.
- **SDR nodes (2026-09-25):** Raspberry Pi 5 + RTL-SDR Blog V4 on the tailnet (pi/setup.sh, pi/README.md): OpenWebRX+ live receiver behind tailscale serve, and a sweep agent posting 24-1766 MHz spectra to /api/sdr/ingest (Bearer SDR_INGEST_TOKEN in .env). SDR panel: node status, spectrum, peaks labelled from UKFAT, open live receiver, set position from the phone. UKFAT parse has 8 gaps (incl. 87.5-108 MHz) to fix.

## Planning area (2026-09-26)

The four planners now live in one place: the **Plan** button (top bar) or **Tools → Planning** on the phone opens a
modal with a tab strip: Spectrum (deconfliction, plan export), Links (point-to-point), Coverage (omni / sector /
P2MP) and HF (skywave now-cast). The sections below still describe each tool; only the entry point changed. The
strip remembers the last tab. The old Spectrum / Links / Coverage / HF buttons remain in the page, hidden, so
keyboard shortcuts in the Mac app and older links keep working.

Dependencies upgraded 2026-09-26 (fastapi 0.141, starlette 1.7, uvicorn 0.54, pydantic 2.13, numpy 2.5, rasterio 1.5, pillow 12, python-docx 1.2, pdfplumber 0.11.10, feedparser 6.0.14, h3 4.5, sgp4 2.27): unit tests, the three UI suites and a full EMO run passed on the new stack before the switch.

Audit 2026-09-26: `tests/ui/plan_smoke.py` (12 checks: tabs, link, coverage and HF calculations, spectrum panel)
and `tests/ui/ui_audit.py` (every button, pill, layer group and basemap on desktop; Tools sheet, layers sheet,
views and overflow on a phone viewport) run the same way as `tests/ui/run.sh`. Findings fixed: SDR panel logged a
404 before the first sweep (now a plain "no sweeps yet" message with the node's state), phone top bar squeezed the
search box (now wraps to a full-width row), long example lists overflowed the EMO panel on phones, three unused
variables and two unused imports (pyflakes clean apart from the collector registration imports).

## Software library

The definitive list of everything the app runs on (packages with versions, front-end libraries, containers, hosts, native app toolchain, Pi node) and the line counts is docs/SOFTWARE.md, generated by `python3 tools/software_inventory.py` on the box. Re-run it after any dependency change; the nightly trade runbook copies the same tables from docs/software.json.

## Start-up default (2026-09-27)

Map layers > **Save this setup as the start-up default** stores the layers and their options, basemap, EMO on/off, panels and map view on the box (`/data/startup.json`, `GET/PUT /api/prefs/startup`). Every app start on any device (Mac, iPhone, browser) opens with it; changes during a session stand until the app is closed. Phones keep their own panel layout. With no saved view and EMO on, the app opens on the loaded scenario.

## SDR receiver position

SDR panel: type a UK postcode, place name or `lat, lon` and press **Set position**, use **Pick on map**, or **Use this device** (browser location, often blocked on managed Wi-Fi). what3words was tried and dropped (its free plan does not convert words to coordinates); postcodes use postcodes.io and places use Nominatim, no key.

## UI tests

`tests/ui/`: `emo_smoke.py` (15 checks), `plan_smoke.py` (12), `layer_click.py [emo]` (clicks a GNSS hex, a submarine cable, an Ofcom site and an aircraft and expects each pop-up), `dock_check.py` (phone dock labels), `startup_check.py` (start-up default applied, then restored). The map uses one shared canvas renderer: a second canvas stacks on top and swallows clicks for every vector layer beneath it.
