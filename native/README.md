# CyEM native apps (Mac and iPhone)

Started 19 Nov 2026. As the September apps did, they host the CyEM web interface in a native shell (SwiftUI and
WKWebView, one source tree `Shared/` for both platforms), so the apps always have everything the web client has.
Plan and progress: `docs/NATIVE-PLAN.md`.

## Build

Once per Mac (and to take a newer libtailscale): `sh native/scripts/build-tailscalekit.sh` (needs Go; builds TailscaleKit
for macOS and iOS into `native/Vendor/`, which is not in git).

On the MacBook (Xcode 27.2, XcodeGen 2.46, Apple Development certificate for team 747JXF57MZ):

```
cd ~/Developer/cyem-monitor/native
xcodegen                                       # writes CyEM.xcodeproj from project.yml (the project is not in git)
xcodebuild -project CyEM.xcodeproj -scheme CyEM-macOS -destination platform=macOS -derivedDataPath build -allowProvisioningUpdates build
open build/Build/Products/Debug/CyEM.app
```

iPhone (paired, unlocked, Developer Mode on):

```
xcrun devicectl list devices                   # find the iPhone's identifier
xcodebuild -project CyEM.xcodeproj -scheme CyEM-iOS -destination 'id=<iPhone id>' -derivedDataPath build \
  -allowProvisioningUpdates -allowProvisioningDeviceRegistration build
xcrun devicectl device install app --device <iPhone id> build/Build/Products/Debug-iphoneos/CyEM.app
```

The iPhone build needs an Apple ID in Xcode (Settings > Accounts) to make the development profile; without one xcodebuild
stops with "No Accounts". With a free (personal) team the iPhone build expires after 7 days: rebuild and reinstall. Xcode renews the profile only near its expiry; to get a full 7 days now, move the old
profile out of `~/Library/Developer/Xcode/UserData/Provisioning Profiles` first (23 Nov: kept in `Provisioning Profiles.bak-20261123`). Compile check without signing:
`-destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO`.

## How it works

- `WebView.swift`: one WKWebView on the server (default `https://nucbox-evo-x2.tail013324.ts.net/`, Settings or Cmd-,).
  Persistent website data, so the internet log-in (30-day cookie) and the web app's localStorage (EMO workspace, layer
  choices) survive restarts. Same-host links stay in the app; other sites open in the browser.
- Downloads (Word briefings and annexes): Mac to the Downloads folder (shown in Finder); iPhone to the share sheet.
- If the server cannot be reached the app shows why (Tailscale off, wrong server) with Try again.
- Built-in Tailscale (`Tailnet.swift`): the app runs its own Tailscale node with TailscaleKit, so nobody needs a Tailscale
  account or the Tailscale app. The build carries a pre-approved, tagged, reusable, ephemeral auth key in
  `native/Config/tailnet.json` (`{"authKey": "tskey-auth-..."}`, git-ignored, bundled when present). Each install joins
  as `cyem-app-<id>`; ephemeral nodes drop out of the admin console when the app stops. When the node is Running the web
  view uses its local SOCKS5 proxy (`WKWebsiteDataStore.proxyConfigurations`). Without the file the app uses the
  device's own network (the Tailscale app, or from the internet the CyEM log-in). Settings > Tailscale shows state.
- Tailnet policy for the key (admin console > Access controls), so app nodes reach the CyEM server's HTTPS and nothing
  else: `"tagOwners": {"tag:cyem-app": ["autogroup:admin"]}` and a grant
  `{"src": ["tag:cyem-app"], "dst": ["<CyEM host or tag>"], "ip": ["tcp:443"]}`. If the policy still has the default
  allow-all rule, tagged nodes reach every device; narrow it first. Anyone holding the app can reach CyEM without a
  password (tailnet requests need no CyEM log-in), and the key can be read out of the app: treat the app like the key.
  Auth keys last at most 90 days: make a new one and rebuild before it expires.
- Safari > Develop can inspect the page (`isInspectable`).
- Notifications (`Notifier.swift`, 0.4.0): local only, no push service. Every 5 minutes while the app runs (on the Mac
  also with its window closed) and, on the iPhone, when iOS grants a background refresh (`BGAppRefreshTask`
  `com.neildonaghy.cyem.refresh`, at iOS's discretion, nothing after a force-quit), the app asks
  `GET /api/items?min_severity=4&hours=24` and `GET /api/briefs?limit=1` through the built-in Tailscale proxy (or the
  device's network, with the web view's cookies for the internet log-in). `NotifyPlan.swift` decides what to say: the first
  check against a server only records what is there; more than 3 new items give one summary; turning a kind off still
  records, so nothing old replays. Tapping an item opens its source page in the browser; tapping a brief opens CyEM.
  Settings > Notifications has the switches, last check and Check now. The first launch asks for permission.
- Share Page (Mac: File menu, Shift-Cmd-S; iPhone: the ... menu) shares the address of the page shown. Handoff: the page
  shown can be continued in CyEM on the other device signed in to the same Apple ID (`NSUserActivityTypes` in `Info/`).
- Widgets (`Widget/CyEMWidget.swift`, 0.5.0): "CyEM status", small and medium (iPhone also Lock Screen): Kp and its
  band, NOAA scales, GNSS interference cells, items in the last 24 hours (all, cyber, EM, high), latest brief. The
  extension never asks the server (it cannot use the app's built-in Tailscale node): on every check the app takes
  `GET /api/status`, writes `WidgetSnapshot` to the shared app group (Mac `747JXF57MZ.com.neildonaghy.cyem`, iPhone
  `group.com.neildonaghy.cyem`) and asks WidgetKit to redraw. The widget shows the age of the snapshot and turns amber
  ("Stale") after 30 minutes, i.e. when the app is not running or cannot reach the server. Settings shows "Widgets
  updated". Add it from the desktop (Mac: right-click the desktop > Edit Widgets) or the Home Screen.
- iPhone 0.6.0 (23 Nov): no notifications and no widget on the iPhone (Neil asked for no notifications; the free team's
  profile carries no App Groups, which the widget needs). The Mac app keeps both. `Notifier` is not started on iOS, the
  background refresh keys are gone from `Info/iOS.plist`, and the iOS target no longer embeds `CyEMWidget-iOS`.
- AR view (iPhone, 0.6.0; menu > AR view): `ARScreen.swift` runs ARKit with its world aligned to gravity and true north
  (`.gravityAndHeading`: +x east, +y up, -z north) and CoreLocation for the phone's position, and asks
  `GET /api/emo/ar` (the web app's workspace, read from its localStorage) for every unit where it is at the last run's
  time, what the run found (heard by, jamming status, denies, target-quality fix) and the last planned corridor. Each
  frame the units are placed by bearing, distance and height (`ARGeo.swift`, pure, tested: local tangent plane plus the
  earth's curve, far points pulled in to 200 m along their direction) and drawn as labels over the camera; the corridor
  as a dashed line (amber transmit, green silent). Filters: sides, range 1-100 km. Accuracy is the compass's (a few
  degrees; close and reopen to realign) and the GPS's; no terrain on the phone, heights are above local ground.
- `APIClient.swift` and `Models.swift` serve notifications, widgets and the AR view; the web interface does not use them.
- Tests: `xcodebuild -project CyEM.xcodeproj -scheme CyEMTests -destination platform=macOS -derivedDataPath build test`
  (NotifyPlan and WidgetSnapshot: no app host, no TailscaleKit).

## Conventions

- App icon: source `Icon/cyem-icon.svg` (simplified mark `Icon/cyem-icon-small.svg` for 16-64 px). `python3 native/Icon/build_icons.py`
  regenerates `Shared/Assets.xcassets/AppIcon.appiconset` (macOS set and iOS 1024) and the web icons in `static/icons/`.

- Swift 6 language mode. The interface belongs to the web app: change it there (static/src), not here.
- Same rules as the web app: notional data only, keyword positions are placement not attribution, British English.
- Bundle ids `com.neildonaghy.cyem` (iPhone) and `com.neildonaghy.cyem.mac` (Mac, sandboxed: network client and server
  (the Tailscale proxy listens on 127.0.0.1), Downloads, user-chosen files).
- iPhone: a development build; Settings > General > VPN & Device Management > trust the developer once per install
  profile.
