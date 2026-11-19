# CyEM rebuild plan

Started 18 Nov 2026. CyEM was retired on 7 Oct 2026 and removed from trade on 17 Oct. This plan brings it back on the
new rack, adds an EM manoeuvre corridor planner across all domains, and puts meteorology into the propagation and
the planning. Notional data only, as before.

## Decisions

| Item | Decision | Status |
| --- | --- | --- |
| Host | The EVO-X2: a dedicated WSL2 distro (Ubuntu 24.04) running Docker Engine, kept up at boot by a scheduled task; Ollama is local there. The MS-A2 had no RAM to spare for a VM (24 of 29 GB allocated) | Decided 18 Nov |
| Access | Tailnet without log-in; the internet through Tailscale Funnel with a username and password (`app/auth.py`, accounts via `python -m app.cli user`). Password only, no second factor | Decided 18 Nov |
| Language model | Ollama on the EVO-X2 for briefs and Ask | Decided |
| SDR | The RTL-SDR on the MS-A2 is passed to trade for the Ecowitt weather receiver; CyEM sweeps wait for a second dongle or the Pi | Open |
| Clients | Web app first (installable since 18 Nov). Native Mac and iPhone apps: the source is on the Mac they were built on in September, which Neil still has; he is checking it on 19 Nov. Then repoint to the EVO URL and re-sign (about one session) | Source located 18 Nov |
| Code copy off GitHub | `~/Backups/cyem-monitor` on the Mac mini (bundle, SHA-256, README); refresh after merges | Done 18 Nov |

## Phases

| Phase | Work | Sessions | State |
| --- | --- | --- | --- |
| 1. Fix | Audit findings 1 to 12 (13 moves to phase 5); Pillow 13.0.0; DOMPurify and CSP; scenario tests on synthetic terrain | 1 | Merged 18 Nov (PR #4) |
| 2. Redeploy | EVO WSL distro, Docker, internet log-in, data re-download (Copernicus tiles on demand, Ofcom WTR, UKFAT), new API keys (aisstream, OpenCelliD, Cloudflare), tailnet routes, backups, runbook (HA panel dropped 18 Nov: not needed) | 2 | Running on the EVO since 18 Nov (docs/DEPLOY-EVO.md); cross-site guard and frame-ancestors 'self' added 18 Nov; still to do: off-box data copy, API keys |
| 3. Clients | Installable web app on Mac and iPhone; native apps if the source turns up (repoint and re-sign: 1 session; rebuild from scratch: 2 to 3) | 1 | Web app done 18 Nov: installable from the tailnet and the internet (manifest and icons outside the log-in; README "Install as an app"). Native apps wait for the source |
| 4. Met | `met_core` (refractivity, k-factor, ducts, hydrometeor and gas attenuation), Open-Meteo collector, met per time step in EMO runs and the timeline, met layer and caveat | 2 | Part 1 done 18 Nov: `met_core`, `met.py` (Open-Meteo, cached), k, rain and fog per run, timeline step and export phase, duct flags, Met card, caveat. Part 2: met map layer, sea clutter and platform limits (with phase 5), HF and GNSS by time step |
| 5. Corridors: core | Cost-grid search in space and time, corridor band, legs with EMCON and comms plan, verify by exact pairwise runs; ground, low-level air (rotary and UAS) and maritime surface first; scenarios moved to JSON with a schema check (finding 13) | 3 | Part 1 back end done 18 Nov (`corridor_core`, `POST /api/emo/plan/corridor`, one time step). UI done 19 Nov (Corridor card in the EMO dock: band, legs by EMCON, legs table; `tests/ui/corridor_check.py`). Next: time layers, vignettes, finding 13 (docs/CONTINUE.md) |
| 6. Corridors: other domains | Amphibious, sub-surface exposure windows, dismounted and SOF, spectrum (frequency-time), satcom and GNSS windows, grey (civil) corridors | 2 to 3 | |
| 7. Outputs | Word corridor brief, Ask answers with positions and legs, AR overlay if the apps return | 1 | |

Total about 12 to 13 sessions, one phase per session to stay inside the plan's usage allowance.

## EM manoeuvre corridors

A corridor is a band in space and time (and, for EM manoeuvre itself, in frequency) through which a force can move or
operate while keeping its own C2 and denying the adversary detection, a target-quality fix or a radar track. The
planner proposes, then verifies with the exact pairwise model, as every EMO solver does.

**Method.** Build a cost grid for the scenario area at each time step. Cost per cell is a weighted sum of: probability
of detection by red ES; probability of a target-quality fix; probability of a radar track (air and sea); loss of own
C2 (link margin below zero, or J/S above the net's threshold); and platform limits (slope, land or water, altitude band,
met limits). Search with A* through space and time (waiting is allowed). The corridor is every cell within a set margin
of the best path's cost. Each leg carries an EMCON state, the nets and relays it needs, and the risk on that leg.

| Corridor | What decides it | First vignette |
| --- | --- | --- |
| Ground manoeuvre and convoys | Terrain masking from red ES and DF; own CNR and datalink margin; counter-RCIED jamming bubble against own comms | 1 Battlegroup, Salisbury Plain; 4 A303 GNSS |
| Low-level air: rotary-wing insertion and air assault | Terrain masking from red air defence radar and ES; burn-through; cloud base, visibility, wind and icing | 0 NW Scotland and the Minches; 2 Brecon |
| UAS transit | GNSS jamming and spoofing zones; datalink margin and lost-link legs; radar and C-UAS detection; wind | 5 C-UAS; 0b Suwałki |
| Maritime surface transit through a littoral or strait | EMCON per leg; radar and ESM horizon including ducting; coastal EW sites; AIS and GNSS spoofing; sea state | 0c Vestfjord and Lofoten; 3 Solent |
| Amphibious ship to shore | Shore-based red ES and EA; relay from ship to beach; landing craft limits (sea state, surf); evaporation duct | 0d Sussex coast and the Solent approaches |
| Sub-surface exposure windows | Where and when masts can be raised for HF, UHF or satcom without red radar or ESM detection, including maritime patrol aircraft | 0 NW Scotland (the Minches) |
| Dismounted and SOF infiltration | Personal radio and satcom windows against red ES and DF coverage; terrain masking; leg-by-leg EMCON | 0e Corsham hub; 2 Brecon |
| Spectrum (frequency-time) | Which bands, hop sets and time windows keep a net usable as red jamming moves, deconflicted against own and civil assignments (Ofcom WTR) | 0b Suwałki |
| Satcom and GNSS windows | Satellite visibility against uplink jamming and spoofing; GNSS degradation by leg | 4 A303; 0c Littoral |
| Grey (civil) corridors | Evacuation routes or civil aviation through GNSS-jammed airspace; collateral checks on own EA | 0b Suwałki (Baltic air traffic) |

## Meteorology

Until 18 Nov the model used a fixed 4/3 earth, no rain and no ducting. Now (part 1, docs/EMO.md "Met") a run can take
the forecast's k-factor, rain and fog at the scenario centre and time, and reports ducts with their cut-off frequency.
Still to do: the met layer on the map, sea clutter and platform limits (wind, sea state, cloud base, icing) for the
corridor planner, HF and GNSS degradation per time step, and a parabolic-equation solver for chosen duct paths.

| Effect | What it changes | Data | How it enters |
| --- | --- | --- | --- |
| Refractivity and k-factor (super- and sub-refraction) | Radio horizon; radar, ES and comms ranges | Open-Meteo pressure-level temperature and humidity | N and M profiles per area and hour; k per time step into `link_core` and `coverage_api` |
| Surface, elevated and evaporation ducts | Over-sea VHF to SHF: radar and ESM ranges well beyond the horizon, intercept of own emissions | M profile; evaporation duct height from sea surface temperature, air temperature, humidity and wind (Open-Meteo Marine) | Duct flag, height and cut-off frequency; screening-grade trapped-mode loss for paths inside the duct; parabolic-equation solver later for chosen paths |
| Rain, cloud and fog | SHF and EHF: X, Ku and Ka band radar, satcom, mmWave datalinks | Precipitation rate, cloud liquid water, visibility | ITU-R P.838 rain (in `link_core`), P.840 cloud and fog, P.676 gases (in `link_core`) |
| Ionosphere and space weather | HF skywave (MUF and LUF), GNSS accuracy and scintillation, UHF satcom | Existing HF now-cast (ionosondes, D-RAP); NOAA SWPC Kp and alerts | HF availability per time step; GNSS degradation flag on legs |
| Sea state and wind | Radar sea clutter and small-craft detection; landing craft and small boat limits; UAS endurance | Open-Meteo Marine waves; forecast wind | Platform limits and a clutter factor on maritime radar |
| Cloud base, visibility, icing | Low-level rotary and UAS corridors | Cloud cover by level, visibility, freezing level | Altitude-band and go/no-go limits per leg |
| Temperature | Battery endurance for dismounted users and UAS | Forecast temperature | Endurance factor per leg |

Open-Meteo is the default source: free, no key, hourly to 16 days ahead and an archive for exercise replays. The Met
Office DataHub is an option for UK models (needs a key). Met is cached per scenario area and valid time; the timeline
steps through it. With no met data the run falls back to the standard atmosphere and says so.

## Open questions for Neil

- The native app source: answered 18 Nov (Neil has the September Mac; checking on 19 Nov).
- Host size and access as assumed above?
- Which vignette first for the corridor planner? (Proposed: the battlegroup on Salisbury Plain for ground, then
  Vestfjord for maritime with ducting.)
