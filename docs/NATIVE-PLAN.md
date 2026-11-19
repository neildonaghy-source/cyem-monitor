# Native apps: plan (19 Nov 2026)

Neil chose a fully native UI (SwiftUI, MapKit) for Mac and iPhone, installed from Xcode on the MacBook (cable or Wi-Fi;
no TestFlight). The web app stays the reference; the apps use the same API and add nothing to the server unless a slice
says so. Source: `native/` in this repo (see `native/README.md`).

| Slice | Work | State |
| --- | --- | --- |
| N1 Skeleton | XcodeGen project (iOS and macOS targets), API client with tailnet and internet sign-in, Overview tiles (space weather, HF, GNSS, counts, brief, sources), Feed (domain, window, search, detail, share), Map of placed items, Settings | Done 19 Nov: builds for both; Mac app checked against the live server |
| N2 Map layers | Layer picker; GNSS interference, aircraft (ADS-B), AIS, outages, cables, radars, satellites, HF MUF contours, aurora; clustering; feed grouping (one row for a burst such as 50 BGP hijacks) | |
| N3 EMO view | Workspace choice (shared or this device), entities on the map with side colours and simple APP-6 style frames, run at T+, scoreboard, unit card, time scrubber | |
| N4 EMO tools | Corridor (as the web Corridor card), COAs list and load, adversary COA, timeline; edit and move units | |
| N5 Spectrum and links | Spectrum deconfliction query, link planner (profile chart), coverage overlay | |
| N6 Brief and Ask | Latest brief (Markdown), generate, Ask with streaming answer; Word exports through the share sheet | |
| N7 Polish | App icon, widgets (Kp, GNSS, items), notifications for high-severity items, offline cache, iPad layout, accessibility | |

Each slice: code in `native/`, build both targets on the MacBook (`xcodebuild`, see the README), run the Mac app against
the live server and look at it, install on the iPhone when it is paired and unlocked, merge, record in `docs/CONTINUE.md`.
