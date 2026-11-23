# CyEM EMO: operator's guide

Screening-grade electromagnetic operations planning on public terrain (Copernicus 30 m, a surface model). Everything
below is computed on the box; positions and effects are proposals to test, not solutions.

## The model in one page

| Element | What it computes |
|---|---|
| Emitters (nets, radars, SATCOM, GNSS) | Terrain coverage (Deygout 3-edge) at ground height; nets have users with sensitivity and a J/S failure threshold |
| ES sensors | Detection margin per emitter at the sensor's height; DF bearings; fixes (best pair, or least squares for 3+ bearings); targetable if the fix error is inside the scenario threshold |
| EA effectors | J/S at every user of every overlapping net (bandwidth, hopping and processing-gain penalties); denied, degraded, unaffected, no link (no usable signal), or deceived (EA mode `spoof`, accepted at 3-30 dB over the true signal) |
| Radars | Range equation per opposing air or sea platform (RCS default by platform, gain, minimum detectable echo, two-way terrain loss); radar EA with mainlobe, self-screening or sidelobe noise and burn-through range |
| Grey (civil) | Heard by both sides; jamming them counts as collateral; their fixes read "located", not targetable |
| Probabilities | Every margin becomes a probability with a combined 9 dB uncertainty (`sigma_db`) |
| Scoreboard | Per side: net availability, emitters heard, mean exposure, fixed, targetable, denial, spoofed, collateral, area denied, radar tracks held, own platforms screened |

Near-terminal clutter: within 150 m of each antenna the surface model is capped at ground level on the pairwise paths.

## Met (18 Nov 2026)

The panel's **Met** row chooses the atmosphere for every run, the timeline and the Word export:

| Setting | What the model uses |
|---|---|
| Standard atmosphere (default) | k = 4/3, no rain, no fog |
| Forecast at the scenario centre | Open-Meteo for the hour of T+0 (empty time: now; up to 16 days ahead; older dates from archived forecasts). k from the refractivity gradient in the lowest kilometre (ITU-R P.453), rain at the hourly rate (P.838 with the P.530 path reduction), fog from visibility (P.840) |
| What-if k, rain, visibility | Overrides on either setting, e.g. k 4 for strong super-refraction, 25 mm/h for a heavy shower |

Each timeline step and each export phase uses the met for its own hour. The run's **Met** card shows k and refraction
class, rain, visibility and fog water, wind, cloud base, freezing level, air, sea state, the evaporation duct over
nearby sea (neutral Paulus-Jeske), any ducts in the forecast profile with their cut-off frequency, Kp, and the
entities a duct could carry ("In a duct: ..."). Ducts are flagged, not modelled: ranges shown are the k-factor model's.
One met state covers the whole scenario. `python -m app.cli met <lat> <lon> [time]` and `GET /api/met` give the same
state for any place; it is cached per 0.05 degree square and day (`met_cache`, 3 hours for recent days).

Phase 4 part 2 (22 Nov 2026):

- **Met layer** (Map layers > EM / spectrum, off by default, zoom 5+): Open-Meteo at up to 25 points on a fixed
  0.25 to 4 degree lattice over the view, for the nearest hour: k and refraction class (colour), rain, fog, any duct
  (with its cut-off), wind arrow (downwind) and speed; tap a point for cloud base, freezing level and sea state.
  `GET /api/met/grid?s=&w=&n=&e=&time=`; one batched request per view, sharing the `met_cache` with runs.
- **Space weather by time step** (`app/spacewx_core.py`, tested), only with the forecast chosen so standard runs stay
  reproducible: from the SWPC scales now (within 6 hours) or the 3-day forecast, and the sun's elevation at the
  scenario centre for that step. HF: R1-R2 degrade and R3+ black out the sunlit side, S1+ polar cap absorption
  poleward of 60 degrees, G3+ depress the MUF, storms add night-time auroral absorption at high latitude. GNSS: the J/S
  at which a nav receiver fails falls 1, 2, 3, 5 and 8 dB for G1 to G5 (half as much again poleward of 55 degrees),
  plus 3 dB in daylight during R3+. Notional screening values. The run has a **Space weather** card, nav nets show
  `space_weather_db`, the timeline board has `space` per step (HF, GNSS loss, HF nets affected), Ask and the Word export
  say what was applied.
- **Corridors**: with the forecast chosen each time layer takes the met and space weather for its own time. Platform
  limits (`met_core.platform_limits`, generic notional values in `met_core.LIMITS`): air (small UAS or helicopter at
  low level) wind, gusts, rain, visibility, cloud base against the flying height, icing (freezing level at or near the
  flying height with visible moisture), ground speed from the headwind along the track; sea (small craft) wind, sea
  state (Douglas, from wave height; speed 0.9 to 0.3 of nominal from sea state 3), visibility; ground heavy rain, snow
  and fog slow but never stop. Marginal adds 0.3 and no-go 3 to every cell of the layer, so the route avoids the bad
  hours where it can; the speed is set by the slowest layer. A no-go on any layer used is reported. Sea clutter
  (`met_core.sea_clutter_db`: 2.5 dB per sea state above 1, more at X band, fading above 50 m) lowers the radar term
  over sea cells for sea and low-level air routes. Storms lower the GNSS failure J/S. All of it appears in the
  Corridor card (limits line, Limits column, space weather) and the summary (`limits`, `env_layers`).

## Workflow

1. **Load** a scenario or build one, then Run. Examples: 0 NW Scotland and the Minches (operational MDO), 0b Suwałki Gap,
   0c Vestfjord and Lofoten (littoral A2/AD), 0d Sussex coast (AR), 0e Corsham hub (AR), 1 Battlegroup vignette
   (Salisbury Plain), 2 Brecon siting, 3 Solent maritime, 4 A303 GNSS jamming, 5 C-UAS against a datalink.
2. **Save the baseline as a COA** (panel: Courses of action).
3. **Understand:** tap a symbol for its footprint and who hears, fixes or jams it. *Compare with others* and add from the list to see a jammer's denial zone over a net, or where a sensor hears an emitter. Run the **timeline** for advantage windows and route survivability.
4. **Plan (EP):** focus a net control station. *Find a better site* draws the score map (green good). *Tune* gives the power cut, best sector antenna and clear channels, each with Apply. *Joint re-site* moves users then control, verified with the exact model.
5. **Plan (EA):** focus a jammer, pick the target net, *Best site to deny it*.
6. **Stress-test:** panel, *Other side's response*: **MLCOA** (at most two modest moves) or **MDCOA** (every jammer and DF site re-sited against your highest-value net). Compare COAs; **Revert**.
7. **Ask:** the bar on the map. Route questions (corridor, route, transit, infiltration, ingress, egress, "path to", "get to", "which way", "best way") are answered straight from the last planned corridor: summary, start and destination in lat/lon and degrees-minutes, every leg with T+, positions, EMCON and the verified checks (no language model). Siting questions with a selection return a computed plan (no language model); other questions get a Qwen summary of the facts, which now include the planned corridor's legs (treat the prose as a summary, the tables as authority).
8. **Brief:** Export (Word) from the panel.

Scenario space: *Shared (all devices)* or *This device only* (private per device, its own analyses and COAs).

## Rules the solvers apply

- Stand-off of 10 km from the other side's ground units; stay on your own side of the line (nearer own centroid).
- MLCOA moves within 15 km and only if clearly better; MDCOA within 40 km.
- A jammer site is penalised for fratricide against own nets on the same band and for exposure to opposing DF.
- Joint re-site: every move verified with the exact model; a move that would deny any user of the net is rejected.
- Ask names sensors that no site or power cut can avoid and points to EMCON windows, directional antennas or another bearer.

## Endpoints (all under /api/emo, workspace via X-CyEM-WS header)

| Endpoint | Purpose |
|---|---|
| POST /run?t_min= (light=, keep=) | Full analysis; light mode = pairwise only, used by the timeline |
| GET /focus/{id}, GET /pair?a=&b= | Footprint of one entity; interaction overlay of two |
| POST /plan/map {kind: net or ea, name, target_net} | Score-map siting: heatmap layers and best sites |
| POST /plan/tune {net}, POST /plan/tune/apply | Power, antenna, channel options and apply |
| POST /plan/joint {net} | Greedy joint re-siting, verified |
| POST /plan/coa {side, coa: mlcoa or mdcoa}, POST /plan/coa/revert | Other side's response, applied and reversible |
| POST /plan/timeline {step_min, net} | Per-step strips, advantage windows, scoreboard per step |
| POST /plan/corridor {mover, to_lat, to_lon, domain, step_min, wait, gnss, ...} | EM manoeuvre corridor: band, legs (EMCON, holds, T+), verified worst points |
| POST /plan/windows {terminal, sat_lon, side, step_min, horizon_min} | Satcom and GNSS windows: look angle, terrain horizon, uplink jamming; each GNSS user by step |
| POST /plan/spectrum {net, lo_mhz, hi_mhz, step_khz, hop, step_min, horizon_min, wtr_km} | Spectrum by frequency and time: each channel, the net's own and a hop set across the band, step by step against opposing jamming; own, civil and Ofcom WTR clashes; best channels |
| GET /plan/corridor/brief.docx | The last planned corridor as a Word brief: task, summary, environment, beach and collateral where they apply, route schematic, legs table |
| GET /ar | For the iPhone AR view: every entity at the last run's time (T+0 if not run), on air or not, what the run found for it, and the last corridor's legs |
| POST /plan/exposure {mover, mast, dwell_min, radius_km, speed_kmh, step_min, layers, threshold, ...} | Sub-surface exposure windows: risk per time layer, windows (T+, best cell, verified), clear-water overlay |
| GET/POST /coas, POST /coas/{id}/load, DELETE /coas/{id} | Courses of action |
| POST /ask {question, selected} | Computed plan for siting questions, else Qwen summary |

## Tests

- Unit and scenario: `docker run --rm -v "$PWD":/src:ro -w /src python:3.12-slim sh -c "pip install -q -r requirements.txt pytest; python -m pytest -q tests --ignore=tests/ui"`
  (scenario tests run every example on synthetic terrain with a throw-away database; no network needed)
- Examples (finding 13, 22 Nov 2026): one JSON file per example in `data/emo_examples/<id>.json` (`id` matches the file
  name, `order` sets the place in the list, `net` names another entity in the same file, optional `params` and
  `corridor`). `app/emo_examples.py` checks each file on load; a file that fails is left out (logged) rather than
  breaking the list. `tests/test_emo_examples.py` fails on any error and runs every entity through `EntityIn`. Notional
  values only. To add one: copy a file, edit, run the tests.
- Sanitiser (headless Chromium, no server): `python3 tests/ui/sanitize_check.py`
- Browser smoke (on the box, private workspace, ~3 min): `bash tests/ui/run.sh`

## Corridors (phase 5, 18 to 19 Nov 2026)

`POST /api/emo/plan/corridor` plans one blue or red unit's route to a point on the ground, at sea or at low level in
the air. Cost per cell: detection and DF fix of its own emissions by opposing ES (reciprocity grids), radar track (air
and sea), loss of own C2, and GNSS denial by opposing nav jammers (J/S against the satellite level and the receivers'
threshold; weighted more heavily for air). Transmit or silent is chosen per cell. With `step_min` set, the picture is
worked out every `step_min` minutes for up to `layers` layers (other units move on their tracks, emitters keep their
schedules) and the search runs through space and time; with `wait` the unit may hold in place until the next layer
(`wait_cost` per cell-crossing time plus the cell's cost). One label per cell and layer: without holds the search does
not mark time by moving to and fro. Each leg's worst point is re-checked with the exact pairwise model, with the other
units where they are at that time. Ducts the met reports are flagged on the legs (evaporation duct over the sea for
antennas up to 50 m; surface-based ducts anywhere below their top), not modelled.

Worked vignettes (the `corridor` field of an example; "Worked vignette" in the Corridor card fills it in): 1 Salisbury
Plain (B Coy to a blocking position, ground, 10-minute layers), 3 Solent (the ship out by the Needles Channel past an
X-band radar; choose the forecast atmosphere to see the evaporation duct flag), 6 UAS transit through GNSS jamming
(air at 120 m, 5-minute layers, a moving jammer), 7 Studland Bay (amphibious, the landing craft from the ship to the
beach, 10-minute layers).

### Amphibious ship to shore (phase 6 part 1, 22 Nov 2026)

`domain: "amphib"`: a landing craft (nominal 15 km/h) keeps to water until the beach; land within 1 km of the landing
point (1.5 cells at coarse grids) is allowed for the beach and its exits. Radar, sea clutter and the evaporation duct
flag apply as at sea. With the forecast chosen: tighter limits than small craft (`met_core.LIMITS["amphib"]`: wind
10/15 m/s, sea state 3/4, visibility 500 m; speed 90, 70 and 50% at sea states 2 to 4) and surf at the beach
(`met_core.surf`: breaker height from the offshore wave height and period by Komar and Gaudet, kept within 0.5 to 1.5
times the offshore height as there is no bathymetry; marginal 1.0 m, no-go 1.5 m, notional). Surf is priced on the
cells round the landing point layer by layer, so with time layers and holding the craft can wait offshore for the surf
to drop; a landing in no-go surf is warned. The summary's `beach` gives the surf, the craft's C2 at the beach (exact
pairwise) and, for each receiver on the same net within 3 km of the beach (the beach party), whether it hears the
control direct or needs the craft as a relay.

In every domain, opposing communications and datalink jammers (effectors overlapping the net's band or hopset) now lower
the unit's C2: power-summed J after the hop or bandwidth penalty against the control's signal and the net's J/S
threshold, as in the run (`p_jam` per leg, `c2_jammers` and `max_p_jam` in the summary; the verified C2 includes it).
Only when the unit hears a control station; a control station's own users are not re-assessed.

### Dismounted and civil corridors (22 Nov 2026)

- **On foot** (`domain: foot`): dismounted and SOF, 4 km/h, slopes up to 60%, leg-by-leg EMCON against red ES and DF
  as for vehicles. With the forecast chosen, cold lowers battery endurance (`met_core.battery_factor`, notional: 2%
  per degree below 20 C, not under 40%; also reported for UAS), and heavy rain or snow slow the move.
- **Civil (grey)** units can plan: only jamming by either side (GNSS, and comms against their own net) and their own C2
  count; a civil unit is not hiding from ES or radar. Every leg names the GNSS jammers that deny it on their own
  (`jammed_by`); `collateral` groups them by side and leg, which is the collateral check on own EA.
- GNSS and comms jammers and radars in corridors now reach the grid's far corner (up to 100 km) instead of stopping at
  their footprint radius, as the sensors already did.
- Worked vignettes: 2 Brecon (the patrol on foot), 0b Suwałki (a notional civil air ambulance at 600 m through
  two-sided GNSS jamming; the road below is masked by terrain, so a road evacuation shows nothing).

### Sub-surface exposure windows (phase 6 part 2, 22 Nov 2026)

`POST /api/emo/plan/exposure` (`app/exposure_api.py`, pure helpers in `app/exposure_core.py`), the Exposure button in the
EMO dock. For one blue or red unit (a submarine), over the water within `radius_km` of it (or of `centre_lat/lon`),
every `step_min` minutes for `layers` layers: the chance opposing radar (ship, shore or maritime patrol aircraft, with
their tracks and on-station schedules) tracks the raised mast (notional cross-section, sea clutter at the mast's height
from the forecast sea state), and if the mast transmits the chance opposing ES hears it and two or more DF sensors fix it
(sensors keep their schedules too). Risk = radar or ES. The link the mast is raised for: `uhf` the unit's net control
station (less opposing comms jamming); `satcom` assumed (satellite in view, uplink beam not modelled); `hf` from the
space weather (normal 95%, degraded 60%, blackout 10%); `periscope` transmits nothing. A cell is usable when it is
water, the boat can reach it by then at `speed_kmh`, and the link is 50% or better. A window is a layer where some
usable cell stays at or under `threshold` for the whole dwell (the same cell held across layers when the dwell is longer
than a step); consecutive layers merge, and each window's best cell is re-checked with the exact pairwise model.

Mast profiles (`exposure_core.MASTS`, notional): periscope 1.5 m, 0.1 m²; UHF 250 MHz 40 dBm; UHF satcom 300 MHz,
20 dBm towards the horizon; HF 8 MHz 47 dBm; masts 2 m, 0.5 m². `eirp_dbm` overrides the profile's power (power control as EP; "power" in the card). The coverage model starts at 20 MHz, so HF interception
is a screening rule: heard by opposing HF ES out to about 250 km over the sea at 47 dBm, the range halving per 10 dB
less power (`hf_groundwave_p`, `hf_range_km`); skywave interception
by distant ES is not modelled. No bathymetry (all water is taken as deep enough), no acoustic, visual, wake or
radar-periscope-detection modes beyond the radar term. Vignette 8, the North Minch (`subsurface-minches`): an MPA on
station T+0 to T+60 and from T+120, a frigate working west across the southern North Minch and an ES/DF ship off
Rubha Reidh. At 26 dBm the MPA's gap opens a window to the north-east (on synthetic sea); at the profile's 40 dBm none.

Corridors now respect sensors' on-station schedules too (an airborne ES off station no longer hears the unit).

### Satcom and GNSS windows (phase 6 part 3, 22 Nov 2026)

**Sat/GNSS** in the EMO dock (`POST /api/emo/plan/windows`, `app/satwin_core.py` pure and tested, `app/satwin_api.py`)
steps through time from T+t (units move on their tracks, emitters keep their schedules):

- **Satcom** for a chosen terminal: the geostationary look angle (the slot the antenna points at, or one given), the
  terrain horizon on that bearing from the surface model over 20 km (the satellite must clear it by 0.5 degree), and
  uplink jamming: opposing jammers in the terminal's band that can themselves see the slot give J/S at the satellite
  from the EIRP difference and the two slant ranges, diluted by the terminal's hopping or spreading, against the
  terminal's J/S threshold. Status per step: clear, degraded, denied, blocked (terrain) or off air; a pointing warning
  if the antenna's azimuth misses the slot. Not modelled: spot-beam isolation or nulling at the satellite, downlink
  jamming.
- **GNSS** for every user of the side's GNSS nets: J/S from opposing jammers (power-summed) and spoofers on exact
  terrain paths at each step, by the run's rules (a spoofer between 3 and 30 dB deceives), with the space weather for
  each step's time when the forecast is chosen.
- **Windows**: runs of steps where the link or fix holds (clear or degraded), drawn as a strip per row.
- Worked vignettes: 0c Vestfjord (the raid force's X-band satcom at about 14 degrees elevation, a notional red uplink
  jammer on the coast off the air T+40 to T+70; the fighters' and landing craft's GNSS), 4 A303 (each GNSS user as
  the jammer drives east and the spoofer sits west of Stonehenge).

### Spectrum by frequency and time (phase 6 part 4, 22 Nov 2026)

**Spectrum** in the EMO dock (`POST /api/emo/plan/spectrum`, `app/fqt_core.py` pure and tested, `app/fqt_api.py`) takes
one net's control station and steps through time from T+t (units on their tracks, emitters on their schedules):

- Candidate channels across the net's band (default the generic band it sits in: 30-88 MHz VHF, 225-400 MHz UHF, else
  plus or minus 10%; at most 48 channels, ends kept), the net's own channel (with its hopping), and a hop set across
  the whole band.
- At each step the control station's level at each user and every opposing comms or datalink jammer's level there are
  worked out once on exact terrain paths at the net's own frequency (path loss varies little across one band). On a
  channel a jammer counts only where its band overlaps it, diluted as in the run. The net is denied on a channel at a
  step if any user's J/S reaches the net's threshold; degraded within 6 dB of it.
- Deconfliction per channel: own nets and civil emitters in the scenario on it, and Ofcom WTR licences within 30 km of
  the net (UK only, advisory; examples on hover). Best channels: most steps usable, clear of own and civil emitters,
  lowest worst J/S, fewest licences.
- Worked vignettes: 1 Salisbury Plain (the battlegroup net against the 40-60 MHz barrage and a spot jammer closing on
  its channel; WTR round the Plain), 0b Suwałki (the Bowman hopping division net against a 35-55 MHz barrage).
- Browser checks: `tests/ui/windows_check.py` (Sat/GNSS, private workspace wincheck1) and `tests/ui/spectrum_check.py`
  (private workspace speccheck1), each emptied at the end.

### Corridor brief and Ask (phase 7, 23 Nov 2026)

- Every corridor plan is kept as the workspace's last corridor (`_LAST["corridor"]`; cleared when an example or
  scenario is loaded). **Word brief** in the Corridor card (`GET /api/emo/plan/corridor/brief.docx`,
  `app/corridor_brief.py`): task, summary, the met, space weather and limits lines, beach and GNSS collateral where they
  apply, a route schematic (legs by EMCON over the units, no basemap) and the legs table. Nothing is re-planned.
- Ask answers route questions from the same plan, with positions and legs, and says how to plan one if none exists.
- Downloads can name their workspace with `?ws=` (a plain link cannot send `X-CyEM-WS`); the header wins when both are
  sent. Before this, the briefing and COA exports from a private workspace came from the shared one.

## Known limits

- Net availability counts a user only if it holds its own control station (in range, control on air) and is not
  denied or deceived; users out of range or with the control off air are listed under *links* in the run and in the export.
- Model limits, in one place: `MODEL_CAVEAT` in `app/emo_api.py` (shown in run notes and both Word exports).
- Met: the forecast model's pressure levels are about 250 m apart near the ground, so thin elevated ducts are missed;
  the evaporation duct is the neutral-stability estimate (the card says when the air is stable); rain is the hourly
  mean, not the peak of a shower.
- Platform limits, sea clutter and space-weather effects are screening heuristics with notional values, at the run's
  met point only (one place per time layer, not per cell); propagation itself still uses the run's atmosphere.

- Surface-model terrain; clutter clearance only on pairwise paths, not on the map rasters (a few dB difference at 1 km pixels).
- Air and space paths use the standard analysis with earth curvature, not ITU-R P.528; within 100 km at aircraft heights this is line of sight anyway.
- Users are scored where they are unless Joint re-site moves them; tracked units are never moved by the solvers.
- Qwen (4B, CPU) summarises facts and verdicts; it still misreads details. Planning answers bypass it.
- One scenario per workspace; loading a scenario replaces it (save a COA first).

## Map-first controls (2026-09-26)

The dock on the map is the working surface; the panel is for editing entities, examples, scenarios and the full tables.

| Dock | What it does |
|---|---|
| Blue / Red | Your viewpoint: scoreboard puts your side first, the adversary card defaults to the other side, Ask answers for your commander |
| Undo | Restores the scenario to before the last change (move, EMCON, edit, EP measure, joint re-site, adversary COA, load); five levels |
| Overlays | EMO overlays (coverage, detected, denied, civil lines). The top-left panel is the map's data layers |
| Score | Both sides' measures with the change since the previous run |
| Time | Shows or hides the time scrubber (T+0 to the horizon, play) |
| COA | Save the current state as a course of action; compare saved COAs; Word annex |
| Adv COA | MLCOA or MDCOA for the other side, applied with revert |
| Timeline | Per-entity strips over time and windows of EM advantage for a chosen net |
| Shared / Device | Which scenario space this device uses; loading an example into the shared space asks twice |
| Panel | The full dashboard |

After any change the results are stale: an amber banner says so and re-runs the analysis after five seconds unless cancelled.
The status chip shows an estimate from the last run of a scenario of the same size.

## Units and symbols

Every entity carries an APP-6 symbol with a function icon chosen from its role (HQ, mechanised, infantry, recce, artillery,
air defence, signals, intelligence for ES/DF, electronic warfare for jammers; fixed wing, UAV, AEW, rotary; surface combatant,
merchant). The Suwałki and NW Scotland scenarios use notional NATO and Russian-style units named by open-source equipment
(Bowman, Reacher, Watchkeeper, Sky Sabre, Cobra, E-7, Typhoon, RC-135, LEWT, ORCUS; R-168, Borisoglebsk-2, Krasukha-2/-4,
Pole-21, Buk 9S18M1, Zoopark-1, Orlan-10, Il-22PP, Monolit-B, Steregushchiy). Values remain notional.

## AR view (iPhone)

> Not available since the September iPhone app was lost (19 Nov 2026): `/api/ar` and `/api/insight/ar` remain on the
> server, but no client calls them. The new native apps host the web interface and have no AR view yet.

Tap a label for its sheet: details, who detects it, status, EMCON, Move here, Undo and Ask. The sheet stays open while the
analysis re-runs and then says what changed ("now detected by 1, was 3"). Filters: source, Detected only, range 5/10/30 km.
Recalibrate restarts the AR session when the compass has drifted. The nearest 25 labels are drawn; the count beyond is shown.

## Audit items applied (2026-09-26, build f)

- **Cancel.** While the analysis is computing, the chip reads "… tap to cancel"; tapping it aborts the request and keeps the previous results (marked stale, no auto re-run). EP siting search and EP measures show a Cancel button. Adversary COA, joint re-site and other actions that change the scenario are not cancellable; use Undo instead. The box finishes the abandoned calculation in the background.
- **Focus card.** Buttons are grouped: Act (EMCON, Edit), Plan (EP siting, EP measures, Re-site net; EA siting with target net for effectors) and Compare (With others). × clears focus.
- **Symbols.** The information line under each symbol starts with the side letter (B, R, G) so side is readable in AR and for colour-blind viewers; names follow the scenario ORBAT (NATO and Russian unit names, APP-6 frames and function icons).
- **Phone Tools sheet.** When EMO is running, the sheet leads with EMO panel and AR view, then Map layers, then the other tools in a compact grid.
- **Phone layers.** The layer list opens as a bottom sheet (Tools → Map layers, or the "show" link); collapsed it stays a small pill top-left.
- **Estimate.** "of about N s" is shown only once a scenario has been computed uncached; cached re-runs do not overwrite the estimate.
- **Deploying UI changes.** `static/` is baked into the image: after `static/build.sh`, run `docker compose up -d --build cyem` (a plain `docker restart` serves the old bundle) and bump `?v=` in `index.html` and `CACHE` in `sw.js`.

## EMO on / off, Re-run and Play (2026-09-26, build h)

- **EMO button (top bar)** is a switch, like Feed and Brief, and lights up while EMO is showing. Off clears the symbols, overlays, chip, dock and cards from this device and stays off across reloads; the scenario itself stays on the box (and on other devices). On brings it back and re-runs; if the workspace is empty it opens the panel to load a scenario. Phone: Tools → Hide EMO; the panel itself is Tools → EMO panel, the chip or the dock.
- **Re-run** (panel): recompute at the chosen T+. Rarely needed now: the analysis re-runs on its own after any change (stale banner, 5 s), and dragging the T+ slider re-runs on release.
- **Play time** (panel) and ▶ on the map scrubber: step T+ forward through the scenario horizon, re-running at each step, so you can watch units move along their tracks and on-air windows open and close (detections, fixes and denial change with them). Stop halts it; the slider stays where it stopped.

## Ground reflection for low antennas (2026-09-27)

Before this, footprints and point-to-point levels were free-space loss plus 3-edge Deygout diffraction over the Copernicus surface. For antennas a few metres off the ground that is far too optimistic at VHF/UHF: a 5 W, 50 MHz manpack at 2 m came out at -100 dBm 80 km away, so every overview wash filled its whole calculation radius and drew as a disc.

The loss is now the larger of (free space + terrain diffraction) and the plane-earth two-ray asymptote, 40 log d - 20 log(h1e h2e), for 30 MHz and above:

- effective heights are the antenna's height above the mean terrain of the path, so a hilltop site gets credit, floored at sqrt(h_agl^2 + h_min^2);
- h_min is Bullington's minimum effective height for vertical polarisation (land: er 15, sigma 0.005 S/m, about 3.8 m at 50 MHz and 0.5 m at 400 MHz; sea, where most of the path is at or below 1 m: er 70, sigma 5 S/m, about 40 m at 50 MHz, so sea paths carry further);
- HF (below 30 MHz) is unchanged: surface wave is not modelled.

Same rule in the map footprints (`coverage_core.polar_prx`) and EMO point-to-point levels (`emo_api._p2p_sync`), so washes, detections, fixes and J/S agree. The Coverage planner uses the same footprint code and now gives smaller, terrain-shaped areas for low antennas; the Link planner (`link_core.analyse`, engineered links on masts) is unchanged.

Effect on Corsham: net coverage and "red can hear blue" washes fell from about 99% of the disc to 25 to 50% and now follow ridges and valleys. Washes that include a radar or an airborne emitter can still fill the area: those really are detectable to the horizon. For the picture of one unit use its focus card; for two, With others.

Overview DF fixes: the map shows target-quality fixes and fixes within 2 km; coarser fixes (and fixes on civil emitters unless Lines to civil emitters is on) appear only when a unit is selected, as thin dashed outlines.

Deletes use a two-tap confirm (button turns red, "Confirm", 4 s): the Mac and iPhone app web views do not show window.confirm(), which returned false, so no delete ever ran there.
