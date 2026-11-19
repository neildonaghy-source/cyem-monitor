# Native apps: plan (19 Nov 2026)

The September Mac and iPhone apps loaded the CyEM web interface (CLAUDE.md: they "loaded
https://trade.tail013324.ts.net:8443"); their source was never found. A first attempt on 19 Nov rebuilt screens natively
(N1 to N4) and lost what the web client has (milsymbol APP-6 symbols, the full map layer panel, the EMO dock and panel,
spectrum, link planner, coverage, HF, SDR, briefs, Ask). Neil rejected it the same day. The apps now do what the
originals did: a native shell around the web interface, so they always match the web client.

| Slice | Work | State |
| --- | --- | --- |
| W1 Shell | SwiftUI app for Mac and iPhone hosting the web interface (WKWebView): persistent cookies and localStorage (internet log-in, EMO workspace choice), downloads (Mac: Downloads folder; iPhone: share sheet), file picker, JavaScript dialogs, external links in the browser, native page when the server cannot be reached, server setting, Reload/Back/Forward/Home | Done 19 Nov: Mac app checked against the live server |
| W2 iPhone install | Development profile from Neil's Apple ID in Xcode; install from the MacBook (`native/README.md`) | Installed 19 Nov (0.3.0); Neil trusts the developer profile on the iPhone once |
| W3 Native extras | Notifications for high-severity items and finished briefs (local, polling `/api/items` and `/api/briefs/state` in the background), Share from the page, Handoff | |
| W4 Embedded Tailscale | As the September apps: each app is its own tailnet node (TailscaleKit from libtailscale `dacde75`, built by `native/scripts/build-tailscalekit.sh` into `native/Vendor/`), a pre-approved tagged ephemeral key bundled at build time (`native/Config/tailnet.json`, not in git) so nobody signs in to Tailscale (Neil, 19 Nov: others must be able to use it); without a key the app uses the device's network | Code done 19 Nov (0.3.1); waiting for the key and the tailnet policy |
| W5 Widgets | Kp, GNSS interference, item counts, latest brief time (WidgetKit, uses `APIClient` and `Models.swift`) | |

Each slice: code in `native/`, build both targets on the MacBook (`native/README.md`), run the Mac app and look at it,
install on the iPhone when Xcode has an account and the phone is unlocked, merge, record in `docs/CONTINUE.md`.
