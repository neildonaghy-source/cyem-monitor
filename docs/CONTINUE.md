# Continuing the CyEM rebuild (hand-off for scheduled runs)

A scheduled task runs this after each usage reset. Each run does **one slice** from "Next" below, end to end, then
updates this file and `docs/REBUILD-PLAN.md`, and stops. Write for Neil: British English, plain, no marketing tone.

## Where things are (19 Nov 2026, 06:30 UTC)

- Running on the EVO-X2 (`docs/DEPLOY-EVO.md`), https://nucbox-evo-x2.tail013324.ts.net/ (tailnet, no log-in; internet
  through Funnel with a log-in). `main` is deployed (release 2026-11-19c). Phases 1 to 3 done; phase 4 part 1 (met)
  done; phase 5 part 1 done: `app/corridor_core.py` (Dijkstra both ways, band, legs), `app/corridor_api.py`
  (`POST /api/emo/plan/corridor`: ground, sea, low-level air; ES detection, DF fix, radar track and own C2 from
  reciprocity grids; transmit or silent per cell; each leg re-checked with the exact pairwise model; each leg carries
  its own `path`) and the Corridor card in the EMO dock (`static/src/18-emo-dock.js`, also reached from a row in the
  EMO panel).
- Browser check for corridors: `tests/ui/corridor_check.py [base-url] [png]` (private workspace `corrcheck2`, emptied
  at the end). On trade run it with `PW_CHROME=~/.cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell`
  and `~/ha-review/venv/bin/python` (the venv's Playwright wants build 1243, which is not installed). The map uses the
  canvas renderer, so checks read `document.body.dataset.corrLegs` rather than counting SVG paths.
- Off-box copy of the database since 19 Nov (Neil approved): EVO cron 00:50 UTC pushes a snapshot to trade
  `~/cyem-offbox` (7 kept), off-site with trade's OneDrive job; details in `docs/DEPLOY-EVO.md`.
- Native apps 0.3.1: Mac and iPhone shells around the web interface with built-in Tailscale (`native/`, clone on the
  MacBook in `~/Developer/cyem-monitor`, TailscaleKit built into `native/Vendor/`). Mac app in `~/Applications/CyEM.app`;
  iPhone app installed and trusted (19 Nov). Both carry the tailnet key and join as ephemeral cyem-app-<id> nodes, so
  nobody signs in to Tailscale. Free-team iPhone builds expire after 7 days: reinstall from the MacBook.
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
2. **Corridor vignettes and time**: corridors through time (time layers from the timeline, waiting allowed) and
   three worked vignettes in the examples: the battlegroup on Salisbury Plain (ground), Vestfjord or the Solent
   (maritime, with the evaporation duct from met), a UAS transit with GNSS jamming (air). Tests on synthetic terrain.
3. **Native apps** (`docs/NATIVE-PLAN.md`): W3 notifications, then W5 widgets. The apps host the web interface; never
   rebuild web features natively (Neil, 19 Nov). Build and look at it on the MacBook (`native/README.md`).
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

## Waiting for Neil

- Tailnet policy for the apps' key. The key Neil made on 19 Nov is in the apps (`native/Config/tailnet.json` on the
  MacBook) and works, but it carries no tag: app nodes (cyem-app-<id>) join as Neil's own devices with his access. Fix:
  Access controls > JSON editor, add `"tagOwners": {"tag:cyem-app": ["autogroup:admin"]}` and a rule letting
  `tag:cyem-app` reach only the EVO-X2 on tcp:443 (and narrow any allow-all rule), save; then generate a new key with
  tag:cyem-app ticked (reusable, ephemeral, pre-approved), revoke the 19 Nov key, rebuild and reinstall both apps.
