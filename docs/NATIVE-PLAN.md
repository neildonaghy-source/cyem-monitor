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
| W3 Native extras | Notifications for high-severity items and finished briefs (local, polling `/api/items` and `/api/briefs` in the background), Share from the page, Handoff | Done 20 Nov (0.4.0): `Notifier.swift`, `NotifyPlan.swift` (pure, 7 XCTests in `native/Tests`), Share Page (Mac File menu, Shift-Cmd-S; iPhone overflow menu), Handoff of the page shown. Mac app installed and polling the EVO through built-in Tailscale; iPhone installed. Neil allows notifications once on each device |
| W4 Embedded Tailscale | As the September apps: each app is its own tailnet node (TailscaleKit from libtailscale `dacde75`, built by `native/scripts/build-tailscalekit.sh` into `native/Vendor/`), a pre-approved tagged ephemeral key bundled at build time (`native/Config/tailnet.json`, not in git) so nobody signs in to Tailscale (Neil, 19 Nov: others must be able to use it); without a key the app uses the device's network | Code done 19 Nov (0.3.1); waiting for the key and the tailnet policy |
| W5 Widgets | Kp, GNSS interference, item counts, latest brief time (WidgetKit, uses `APIClient` and `Models.swift`) | Done 20 Nov (0.5.0): extension `Widget/CyEMWidget.swift` (small, medium; iPhone also Lock Screen) reads a snapshot the app writes to its app group on every check (`WidgetSnapshot.swift`, 5 XCTests). Mac app installed and writing the snapshot. iPhone: builds unsigned; the signed build needs Neil (Xcode account, and the free team may refuse App Groups) |

Each slice: code in `native/`, build both targets on the MacBook (`native/README.md`), run the Mac app and look at it,
install on the iPhone when Xcode has an account and the phone is unlocked, merge, record in `docs/CONTINUE.md`.
