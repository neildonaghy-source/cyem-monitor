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
stops with "No Accounts". With a free (personal) team the iPhone build expires after 7 days: rebuild and reinstall. Compile check without signing:
`-destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO`.

## How it works

- `WebView.swift`: one WKWebView on the server (default `https://nucbox-evo-x2.tail013324.ts.net/`, Settings or Cmd-,).
  Persistent website data, so the internet log-in (30-day cookie) and the web app's localStorage (EMO workspace, layer
  choices) survive restarts. Same-host links stay in the app; other sites open in the browser.
- Downloads (Word briefings and annexes): Mac to the Downloads folder (shown in Finder); iPhone to the share sheet.
- If the server cannot be reached the app shows why (Tailscale off, wrong server) with Try again.
- Built-in Tailscale (`Tailnet.swift`, default): the app runs its own Tailscale node ("cyem-mac", "cyem-iphone") with
  TailscaleKit. First start shows "Sign in to Tailscale" (browser sign-in, no auth key in the app); node state is kept in
  Application Support/tailscale. When the node is Running, the web view's data store uses the node's local SOCKS5 proxy
  (`WKWebsiteDataStore.proxyConfigurations`). Settings > Tailscale switches to the device's own Tailscale app, shows
  state and address, and signs the node out. In the Tailscale admin console the nodes appear as cyem-mac and
  cyem-iphone; disable key expiry there if they should not need a sign-in every 180 days.
- Safari > Develop can inspect the page (`isInspectable`).
- `APIClient.swift` and `Models.swift` are kept for notifications and widgets (W3, W5); the interface does not use them.

## Conventions

- Swift 6 language mode. The interface belongs to the web app: change it there (static/src), not here.
- Same rules as the web app: notional data only, keyword positions are placement not attribution, British English.
- Bundle ids `com.neildonaghy.cyem` (iPhone) and `com.neildonaghy.cyem.mac` (Mac, sandboxed: network client and server
  (the Tailscale proxy listens on 127.0.0.1), Downloads, user-chosen files).
- iPhone: a development build; Settings > General > VPN & Device Management > trust the developer once per install
  profile.
