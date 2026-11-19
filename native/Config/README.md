Put the pre-approved tailnet key for the apps' built-in Tailscale here as `tailnet.json`:

    {"authKey": "tskey-auth-..."}

The file is git-ignored and bundled into the apps at build time (see native/README.md for the key settings and the
tailnet policy). Without it the apps use the device's own network.
