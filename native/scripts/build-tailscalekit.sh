#!/bin/sh
# Builds TailscaleKit (Tailscale's embeddable Swift framework, BSD-3-Clause) for macOS and iOS and puts the frameworks in
# native/Vendor/, which project.yml links and embeds. Needs Go and Xcode. The frameworks are not in git (tens of MB):
# run this once on a new Mac, and again to take a newer libtailscale (change REV).
set -eu
REV="${REV:-dacde75}"                                     # libtailscale commit used for CyEM 0.3.0 (19 Nov 2026)
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${SRC:-$HOME/Developer/vendor/libtailscale}"
[ -d "$SRC/.git" ] || git clone -q https://github.com/tailscale/libtailscale.git "$SRC"
cd "$SRC" && git fetch -q origin && git checkout -q "$REV"
cd swift && make macos && make ios
mkdir -p "$HERE/Vendor/macos" "$HERE/Vendor/ios"
rm -rf "$HERE/Vendor/macos/TailscaleKit.framework" "$HERE/Vendor/ios/TailscaleKit.framework"
cp -R build/Build/Products/Release/TailscaleKit.framework "$HERE/Vendor/macos/"
cp -R build/Build/Products/Release-iphoneos/TailscaleKit.framework "$HERE/Vendor/ios/"
echo "TailscaleKit $REV in $HERE/Vendor"
