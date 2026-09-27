# CyEM EMO: operator's guide

Screening-grade electromagnetic operations planning on public terrain (Copernicus 30 m, a surface model). Everything
below is computed on the box; positions and effects are proposals to test, not solutions.

## The model in one page

| Element | What it computes |
|---|---|
| Emitters (nets, radars, SATCOM, GNSS) | Terrain coverage (Deygout 3-edge) at ground height; nets have users with sensitivity and a J/S failure threshold |
| ES sensors | Detection margin per emitter at the sensor's height; DF bearings; fixes (best pair, or least squares for 3+ bearings); targetable if the fix error is inside the scenario threshold |
| EA effectors | J/S at every user of every overlapping net (bandwidth, hopping and processing-gain penalties); denied, holds, no signal, or spoofed (EA mode `spoof`, accepted at 3-30 dB over the true signal) |
| Radars | Range equation per opposing air or sea platform (RCS default by platform, gain, minimum detectable echo, two-way terrain loss); radar EA with mainlobe, self-screening or sidelobe noise and burn-through range |
| Grey (civil) | Heard by both sides; jamming them counts as collateral; their fixes read "located", not targetable |
| Probabilities | Every margin becomes a probability with a combined 9 dB uncertainty (`sigma_db`) |
| Scoreboard | Per side: net availability, emitters heard, mean exposure, fixed, targetable, denial, spoofed, collateral, area denied, radar tracks held, own platforms screened |

Near-terminal clutter: within 150 m of each antenna the surface model is capped at ground level on the pairwise paths.

## Workflow

1. **Load** a scenario (examples 0b Suwałki, 0c Littoral, 0 NW Scotland, 1 BG vignette, 2 Brecon, 3 Solent, 4 A303, 5 C-UAS) or build one. Run.
2. **Save the baseline as a COA** (panel: Courses of action).
3. **Understand:** tap a symbol for its footprint and who hears, fixes or jams it. *Compare with others* and add from the list to see a jammer's denial zone over a net, or where a sensor hears an emitter. Run the **timeline** for advantage windows and route survivability.
4. **Plan (EP):** focus a net control station. *Find a better site* draws the score map (green good). *Tune* gives the power cut, best sector antenna and clear channels, each with Apply. *Joint re-site* moves users then control, verified with the exact model.
5. **Plan (EA):** focus a jammer, pick the target net, *Best site to deny it*.
6. **Stress-test:** panel, *Other side's response*: **MLCOA** (at most two modest moves) or **MDCOA** (every jammer and DF site re-sited against your highest-value net). Compare COAs; **Revert**.
7. **Ask:** the bar on the map. Siting questions with a selection return a computed plan (no language model); other questions get a Qwen summary of the facts (treat the prose as a summary, the tables as authority).
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
| GET/POST /coas, POST /coas/{id}/load, DELETE /coas/{id} | Courses of action |
| POST /ask {question, selected} | Computed plan for siting questions, else Qwen summary |

## Tests

- Unit: `docker run --rm -v "$PWD":/src:ro -w /src python:3.12-slim sh -c "pip install -q pytest numpy==2.1.3 fastapi httpx; python -m pytest -q tests --ignore=tests/ui"`
- Browser smoke (on the box, private workspace, ~3 min): `bash tests/ui/run.sh`

## Known limits

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
