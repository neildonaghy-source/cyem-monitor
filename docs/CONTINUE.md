# Continuing the CyEM rebuild (hand-off for scheduled runs)

A scheduled task runs this after each usage reset. Each run does **one slice** from "Next" below, end to end, then
updates this file and `docs/REBUILD-PLAN.md`, and stops. Write for Neil: British English, plain, no marketing tone.

## Where things are (20 Nov 2026, 16:10 UTC)

- Native apps 0.5.0 (20 Nov, W5): widget "CyEM status" (Kp and band, NOAA scales, GNSS interference cells, items in 24 h,
  high, latest brief; small and medium, iPhone also Lock Screen). The extension does no networking: the app writes
  `WidgetSnapshot` to its app group on every check (`GET /api/status` added to the Notifier loop, also with notifications
  off) and reloads the widget; it turns amber after 30 minutes without a check. 12 XCTests pass (scheme CyEMTests). Mac
  app replaced in `~/Applications/CyEM.app` on the MacBook (0.4.0 kept at `native/build/CyEM-0.4.0.app`); the extension
  is registered (`pluginkit`) and Settings shows "Widgets updated 15:53" with no error. Not yet placed on a desktop (Neil
  adds it: right-click the desktop > Edit Widgets). iPhone: compiles unsigned; the signed build stopped with "No
  Accounts" in Xcode and the team profile lacks App Groups (see "Waiting for Neil"); the installed 0.4.0 expires 27 Nov.
  No server change. `main` 9a6265e (PR #52) deployed on the EVO (healthy, `/api/status` 200; it already ran 84e957a,
  release 2026-11-20a from another session). No EMO check needed (no server change). Recorded on trade (CHANGELOG,
  runbook 4.2) and on the Mac mini (`cyem-monitor-20261120-main-9a6265e.bundle`, `--all` from the MacBook clone, so
  main is `refs/remotes/origin/main` in it; clone-verified; older bundles kept). The Mac mini bundle for release
  2026-11-20a was not made (mac-mini did not resolve then); this one covers it.

- Native apps 0.4.0 (20 Nov, W3): local notifications for high-severity items (4 and 5) and finished briefs, Share Page,
  Handoff (`native/Shared/Notifier.swift`, `NotifyPlan.swift`, tests `native/Tests`, scheme CyEMTests). Mac app replaced
  in `~/Applications/CyEM.app` on the MacBook (0.3.1 kept at `~/Developer/cyem-monitor/native/build/CyEM-0.3.1.app`); it
  polls the EVO through built-in Tailscale (200s for `/api/items?min_severity=4` and `/api/briefs?limit=1` in the
  container log). iPhone build installed 20 Nov (free team: expires 27 Nov). Delivery of a notification not yet seen:
  macOS and iOS ask once for permission, which needs Neil (see "Waiting for Neil"). No server change; `main` 23141ac
  deployed on the EVO (healthy, the installed Mac app's polls answered 200 after the restart). Recorded on trade
  (CHANGELOG, runbook 4.2) and on the Mac mini (`cyem-monitor-20261120-main-23141ac.bundle`, clone-verified; reach it from
  the MacBook with `ssh -o HostName=neils-mac-mini -o HostKeyAlias=neils-mac-mini.local mac-mini`, as `.local` does not
  resolve). No EMO check was needed (no server change).

- Running on the EVO-X2 (`docs/DEPLOY-EVO.md`), https://nucbox-evo-x2.tail013324.ts.net/ (tailnet, no log-in; internet
  through Funnel with a log-in). `main` is deployed (06760b2, release 2026-11-19f: PR #36
  corridors through time plus PR #38's map pick fix from another session). Mac mini copy
  `cyem-monitor-20261119-main-06760b2.bundle` (older bundles kept, not deleted). Phases 1 to 3 done; phase 4 part 1 (met)
  done; phase 5 part 1 done: `app/corridor_core.py` (Dijkstra both ways, band, legs), `app/corridor_api.py`
  (`POST /api/emo/plan/corridor`: ground, sea, low-level air; ES detection, DF fix, radar track and own C2 from
  reciprocity grids; transmit or silent per cell; each leg re-checked with the exact pairwise model; each leg carries
  its own `path`) and the Corridor card in the EMO dock (`static/src/18-emo-dock.js`, also reached from a row in the
  EMO panel).
- Phase 5 part 2 done 19 Nov (PR #36): `corridor_core.corridor_time` (time layers, holding allowed, one label per cell
  and layer), `CorridorIn.step_min/layers/wait/wait_cost/gnss`, GNSS denial cost (opposing nav jammers against the
  satellite level), duct flags on legs (`_duct_note`), hold legs with T+. Worked vignettes in the `corridor` field of
  examples `bg-vignette`, `solent-maritime` (red X-band radar added) and new `uas-gnss` (6); "Worked vignette" button in
  the Corridor card. Live check: all three plan in 9 to 16 s on the EVO (private workspace corrlive1, emptied).
- Browser check for corridors: `tests/ui/corridor_check.py [base-url] [png]` (private workspace `corrcheck2`, emptied
  at the end; it also loads example 6 from the panel and plans its worked vignette). On trade run it with `PW_CHROME=~/.cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell`
  and `~/ha-review/venv/bin/python` (the venv's Playwright wants build 1243, which is not installed). The map uses the
  canvas renderer, so checks read `document.body.dataset.corrLegs` rather than counting SVG paths.
- Off-box copy of the database since 19 Nov (Neil approved): EVO cron 00:50 UTC pushes a snapshot to trade
  `~/cyem-offbox` (7 kept), off-site with trade's OneDrive job; details in `docs/DEPLOY-EVO.md`.
- Native apps 0.3.1: Mac and iPhone shells around the web interface with built-in Tailscale (`native/`, clone on the
  MacBook in `~/Developer/cyem-monitor`, TailscaleKit built into `native/Vendor/`). Mac app in `~/Applications/CyEM.app`;
  iPhone app installed and trusted (19 Nov). Both carry the tagged key ki8d2qz29K11CNTRL (tag:cyem-app, reusable, ephemeral, 90 days to
  17 Feb 2027) and join as cyem-app-<id>; the tailnet policy (hosts cyem-evo, grant tag:cyem-app to cyem-evo tcp:443,
  allow-all narrowed to autogroup:member, a policy test) was saved on 19 Nov. Renew the key before 17 Feb 2027. Free-team iPhone builds expire after 7 days: reinstall from the MacBook.
- Internet log-in: cyem-team's password was reset on 19 Nov at Neil's request and given to him in chat (stored nowhere else).
- Inside the container the app listens on 8080 (3020 is the host port).
- Keyed feeds live since 19 Nov: AISSTREAM_KEY, OPENCELLID_KEY and CLOUDFLARE_API_TOKEN in `/home/cyem/cyem/.env` (600;
  previous copy `.env.bak-20261119-keys`). First collects: ais 182 vessels, cloudflare 2 outages and 50 hijacks, cells 147,292.
- No Home Assistant panel (removed at Neil's request). Never add one back unasked.
- Internet log-in: one shared account, `cyem-team` (created 18 Nov at Neil's request; the password went to him in chat
  and is stored nowhere else). Change it with `docker exec -it cyem python -m app.cli user passwd cyem-team`.

## Next, in order (tick off here when merged and deployed)

1. [x] **Corridor UI** (done 19 Nov, PRs #16 to #18) in the EMO panel (`static/src/18-emo-dock.js`): a Corridor row with unit (blue or red entity),
   domain (ground, sea, air with height), speed, EMCON (auto, transmit, silent), silent price, and "Pick destination"
   (next map click). Draw the band (`band` PNG over `bounds`), the path coloured by leg EMCON (transmit amber, silent
   green), and a legs table (km, minutes, EMCON, detect, fix, radar, C2, verified, heard by). Clear button. Release
   bump (BUILD in `00-head.js`, `?v=` in `index.html`, `sw.js` ?v= and cache name), `sh static/build.sh`.
   Browser check in a private workspace (see "Live checks").
2. [x] **Corridor vignettes and time** (done 19 Nov, PR #36): corridors through time (time layers from the timeline, waiting allowed) and
   three worked vignettes in the examples: the battlegroup on Salisbury Plain (ground), Vestfjord or the Solent
   (maritime, with the evaporation duct from met), a UAS transit with GNSS jamming (air). Tests on synthetic terrain.
3. [x] **Native apps** (`docs/NATIVE-PLAN.md`): ~~W3 notifications~~ (done 20 Nov, 0.4.0), ~~W5 widgets~~ (done 20 Nov,
   0.5.0; iPhone install waits for Neil). The apps host the web interface; never
   rebuild web features natively (Neil, 19 Nov). Build and look at it on the MacBook (`native/README.md`).
3a. **Audit follow-ups**: closed 20 Nov (PRs #51, #55; release 2026-11-20b). UKFAT 16.30-16.36 MHz is a gap in Ofcom's own
   table (PDF page 22), reported as such. UI checks against the EVO on 20 Nov (from trade, ~/cyemui with the ha-review venv
   and PW_CHROME = the 1228 chrome-headless-shell): emo_smoke 15/15, ui_audit 0 issues, corridor_check all pass,
   plan_smoke 11/12 on a stale title check (fixed in #55). sdr_live_check (rewritten) and plan_smoke not yet re-run on
   2026-11-20b: the MacBook link dropped. Optional: remove the Airspy HF+ and SDRPlay entries from OpenWebRX+ on trade.
4. **Finding 13**: move `app/emo_examples.py` scenarios to JSON files with a schema check and a test that loads them all.
5. **Phase 4 part 2**: met layer on the map (k, rain, visibility, ducts at a glance), HF availability and GNSS
   degradation per time step (space weather), sea clutter factor and platform limits (wind, sea state, cloud base,
   icing) feeding the corridor cost.
6. **Phase 6**: amphibious, sub-surface exposure windows, dismounted and SOF, spectrum (frequency-time), satcom and
   GNSS windows, grey (civil) corridors (`docs/REBUILD-PLAN.md`, corridor table).
7. **Phase 7**: Word corridor brief, Ask answers with positions and legs.

## How to work

- Repo: `neildonaghy-source/cyem-monitor` (private). Attach it with add_repo, clone, branch `rebuild/<slice>`.
- Tests: `python -m pytest -q tests` (needs `pip install -r requirements.txt pytest`; about 2 minutes), `node --check
  static/app.js`, `python3 tests/ui/sanitize_check.py` if `07-brief.js` changes. All must pass before merging.
- Pull request through the REST API (GraphQL is blocked): `gh api repos/neildonaghy-source/cyem-monitor/pulls -f
  title=... -f head=... -f base=main -F body=@file`, then `gh api -X PUT .../pulls/<n>/merge -f merge_method=merge`
  (retry once after a few seconds on 405). Add a fetch refspec for each pushed branch so the stop hook sees it.
- Conventions: `CLAUDE.md` at the repo root (notional data only, never MOD or unit data; pure cores stay tested;
  solvers propose then verify with the exact model; keep `MODEL_CAVEAT` honest).

## Deploying (needs the linked computer; skip and say so if it is not reachable)

- From the linked Mac, through Desktop Commander `start_process`. The EVO's SSH shell is cmd.exe, so never put pipes
  or quotes on its command line: write a bash script to `/tmp` on the Mac and pipe it in:
  `ssh -o BatchMode=yes Neil@100.91.241.55 "wsl.exe -d CyEM -u cyem --cd /home/cyem -- bash -s" < /tmp/script.sh`
- Script body: `cd /home/cyem/cyem && git fetch -q origin main && git merge -q --ff-only origin/main && docker compose
  up -d --build cyem`, then `docker inspect cyem --format '{{.RestartCount}} {{.State.Health.Status}}'` after 10 s.
  Watch restarts for two minutes after a change that could use memory (the container has 5 GB since 19 Nov; 1 GB was OOM-killed by the littoral example).
- Live checks: `docker exec cyem python -m app.cli met 51.25 -1.85`; EMO checks only in a private workspace
  (header `X-CyEM-WS: <name>`, or localStorage `cyem-ws-mode=device`, `cyem-ws=<name>` in a browser), emptied
  afterwards by deleting its entities. Browser checks run on trade (`ssh trade`, `~/ha-review/venv/bin/python`,
  Playwright with the headless shell in `~/.cache/ms-playwright/chromium_headless_shell-1228`).

## Recording (after a deploy)

- trade: append an entry to `~/ha-review/CHANGELOG.md` (copy it to `CHANGELOG.md.bak-<date>-<tag>` first) and keep
  `~/bin/runbook_gen.py` section 4.2 in step (back it up as `runbook_gen.py.before-<date>-<tag>`, then `py_compile`).
- Mac mini: refresh the code copy in `~/Backups/cyem-monitor` (bundle from the EVO clone with `--all`, base64 over
  SSH to the Mac, `shasum -a 256`, copy to `mac-mini`, verify with a clone, update `README.txt`, drop the bundle it
  supersedes).
- Update "Where things are" and tick "Next" above; update the phase table in `docs/REBUILD-PLAN.md`.

## Never without Neil

- New SSH keys, scheduled jobs or other persistence on any box; deleting anything of his; Home Assistant changes;
  API keys; anything that spends money. If the next slice needs one of these, do the preparatory work, write the
  question at the top of this file under "Waiting for Neil", and stop.

## Done 20 Nov: SDR live listen

- Installed on trade by Neil (20 Nov): cyem-sdr-mode.service and container cyem-openwebrx (slechev/openwebrxplus:1.2.130,
  100.124.48.91:8073, created stopped). Checked 16:09 UTC: Listen live (15 min) switched trade in about 20 s, /sdr/live/ page,
  JS, status and WebSocket (waterfall/audio frames) all through CyEM; Stop brought ecowitt-receiver back and stopped the
  container. Nothing is recorded.

## Done 19 Nov: SDR

- Shared sweeps live on trade (Neil installed them 12:43 UTC): timer cyem-sdr-sweep, four a day as node trade-sdr, each
  pauses ecowitt-receiver for about 35 s. First sweep posted 10,980 bins, 28 peaks. rtl_power overflows on spans over
  about 2147 MHz after crop, hence 15% crop for 24-1766 MHz (#47). Remove with `sudo bash ~/cyem-sdr/install-trade-sweep.sh --remove`.

## Waiting for Neil

- Native 0.5.0 on the iPhone: Xcode on the MacBook has no Apple ID signed in at present (Settings > Accounts; the
  signed iPhone build stops with "No Accounts"). The widget also needs the App Groups capability
  (`group.com.neildonaghy.cyem`); a free personal team may refuse it. If it does, the choice is the paid developer
  programme (money: Neil's call) or iPhone without widgets (drop the entitlement on iOS). The 0.4.0 iPhone build expires
  27 Nov. On the Mac, add the widget: right-click the desktop > Edit Widgets > CyEM.

- Native 0.4.0: allow notifications for CyEM when asked (Mac: the prompt on first launch, or System Settings >
  Notifications > CyEM; iPhone: on first open). Then Settings > Notifications > Check now shows the last check; the next
  high-severity item or brief should appear as a notification. Tell the next run if none arrive.

- EMO examples on real sites (0e Corsham, 0d Thorney Island, Boscombe Down): Neil said leave them (19 Nov).
