# CyEM native apps (Mac and iPhone)

Started 19 Nov 2026. Nothing was left of the September apps (no source, no project history), so these are new: SwiftUI,
one source tree (`Shared/`) for both platforms, native screens on the CyEM API (no web view). Plan and progress:
`docs/NATIVE-PLAN.md`.

## Build

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

With a free (personal) team the iPhone build expires after 7 days: rebuild and reinstall. Compile check without signing:
`-destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO`.

## How it connects

- Server: Settings, default `https://nucbox-evo-x2.tail013324.ts.net/`.
- On the tailnet (Tailscale app on the device) no log-in. From the internet (Funnel) the server answers 401 and the app
  shows a sign-in sheet; `POST /login` sets the 30-day session cookie, kept in the app's cookie store.
- POSTs from the app carry no `Origin` or `Sec-Fetch-Site`, so the server's cross-site guard lets them through.

## Conventions

- Swift 6 language mode; `AppModel` is `@MainActor @Observable`; wire models decode leniently (optional fields).
- Same rules as the web app: notional data only, keyword positions are placement not attribution, British English.
- Bundle ids `com.neildonaghy.cyem` (iPhone) and `com.neildonaghy.cyem.mac` (Mac, sandboxed, network client only).
