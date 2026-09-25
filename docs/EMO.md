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
