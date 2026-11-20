#!/bin/bash
# Installs the shared CyEM sweep on trade (run once by Neil):  sudo bash ~/cyem-sdr/install-trade-sweep.sh
# Reads the ingest token from ~trade/cyem-sdr/token (copied from the EVO .env) and moves it to /etc/cyem-sweep.env (root,
# 600). Timer: four sweeps a day at about 02:20, 08:20, 14:20 and 20:20 UK time (up to 20 min later at random); each stops
# the Ecowitt receiver for about three minutes. Remove: sudo bash ~/cyem-sdr/install-trade-sweep.sh --remove
#
# Live listening (Nov 2026): also installs cyem-sdr-mode.service (pi/trade/cyem-sdr-mode), which polls CyEM every 10 s and,
# when someone presses Listen live, pauses the Ecowitt receiver and starts the OpenWebRX+ container created here
# (cyem-openwebrx, not started now, restart=no). It listens on trade's tailnet address only, port 8073, for the EVO's
# proxy; users never reach it directly. Settings live in the volume cyem-openwebrx-settings. No recording.
# Update OpenWebRX+: pick a newer tag from hub.docker.com/r/slechev/openwebrxplus/tags and re-run with
#   sudo OWRX_IMAGE=slechev/openwebrxplus:<tag> bash ~/cyem-sdr/install-trade-sweep.sh   (the container is recreated,
# the settings volume kept), then change OWRX_IMAGE below to match in the repo.
set -euo pipefail
OWRX_IMAGE=${OWRX_IMAGE:-slechev/openwebrxplus:1.2.130}
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
SRC=/home/trade/cyem-sdr
if [[ "${1:-}" == "--remove" ]]; then
  systemctl disable --now cyem-sdr-sweep.timer cyem-sdr-mode.service 2>/dev/null || true
  docker rm -f cyem-openwebrx >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/cyem-sdr-sweep.{service,timer} /etc/systemd/system/cyem-sdr-mode.service \
        /usr/local/sbin/cyem-sdr-sweep /usr/local/sbin/cyem-sdr-mode /etc/cyem-sweep.env
  rm -rf /opt/cyem-sweep; systemctl daemon-reload; systemctl start ecowitt-receiver.service
  echo "removed (OpenWebRX+ settings kept: docker volume rm cyem-openwebrx-settings to delete them)"; exit 0
fi
if [[ -f "$SRC/token" ]]; then TOKEN=$(tr -d '\n' < "$SRC/token")
elif [[ -f /etc/cyem-sweep.env ]]; then TOKEN=$(sed -n 's/^SDR_INGEST_TOKEN=//p' /etc/cyem-sweep.env)   # re-run: keep it
else TOKEN=""; fi
[[ -n "$TOKEN" ]] || { echo "no token in $SRC/token or /etc/cyem-sweep.env"; exit 1; }
install -d -m 755 /opt/cyem-sweep
install -m 644 "$SRC/cyem_sweep.py" /opt/cyem-sweep/cyem_sweep.py
install -m 755 "$SRC/cyem-sdr-sweep" /usr/local/sbin/cyem-sdr-sweep
install -m 755 "$SRC/cyem-sdr-mode" /usr/local/sbin/cyem-sdr-mode
umask 077
cat > /etc/cyem-sweep.env <<ENV
SDR_INGEST_TOKEN=$TOKEN
CYEM_URL=https://nucbox-evo-x2.tail013324.ts.net
NODE=trade-sdr
F_LO=24M
F_HI=1766M
BIN=250k
GAIN=30
ENV
rm -f "$SRC/token"
cat > /etc/systemd/system/cyem-sdr-sweep.service <<UNIT
[Unit]
Description=CyEM spectrum sweep on the shared RTL-SDR (pauses the Ecowitt receiver for one pass)
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/cyem-sdr-sweep
TimeoutStartSec=900
UNIT
cat > /etc/systemd/system/cyem-sdr-sweep.timer <<UNIT
[Unit]
Description=CyEM shared spectrum sweeps, four a day
[Timer]
OnCalendar=*-*-* 02,08,14,20:20:00 Europe/London
RandomizedDelaySec=20min
Persistent=false
[Install]
WantedBy=timers.target
UNIT
cat > /etc/systemd/system/cyem-sdr-mode.service <<'UNIT'
[Unit]
Description=CyEM live listening on the shared RTL-SDR (switches between the Ecowitt receiver and OpenWebRX+)
After=network-online.target docker.service tailscaled.service
Wants=network-online.target
Requires=docker.service
[Service]
EnvironmentFile=/etc/cyem-sweep.env
ExecStartPre=-/usr/bin/docker stop cyem-openwebrx
ExecStart=/usr/bin/python3 -I -B /usr/local/sbin/cyem-sdr-mode
# whatever happened, the weather receiver comes back (unless a sweep holds the dongle: its own trap restarts it)
ExecStopPost=/bin/sh -c 'docker stop cyem-openwebrx >/dev/null 2>&1; flock -n /run/cyem-sdr-sweep.lock systemctl start ecowitt-receiver.service || true'
Restart=on-failure
RestartSec=30
[Install]
WantedBy=multi-user.target
UNIT
# OpenWebRX+ container: created, not started. Bound to trade's tailnet address only (the EVO proxies to it).
TSIP=$(tailscale ip -4 2>/dev/null | head -1); TSIP=${TSIP:-100.124.48.91}
docker pull "$OWRX_IMAGE"
docker rm -f cyem-openwebrx >/dev/null 2>&1 || true
docker create --name cyem-openwebrx --restart no --device /dev/bus/usb -p "$TSIP:8073:8073" \
  -v cyem-openwebrx-settings:/var/lib/openwebrx --tmpfs /tmp/openwebrx "$OWRX_IMAGE" >/dev/null
echo "OpenWebRX+ container cyem-openwebrx created from $OWRX_IMAGE on $TSIP:8073 (not started)"
systemctl daemon-reload
systemctl enable cyem-sdr-mode.service; systemctl restart cyem-sdr-mode.service     # restart: a re-run picks up a new script
systemctl enable --now cyem-sdr-sweep.timer
echo "installed; first sweep now (about 3 minutes, weather receiver paused):"
systemctl start cyem-sdr-sweep.service || true
journalctl -u cyem-sdr-sweep.service -n 5 --no-pager
systemctl is-active ecowitt-receiver.service cyem-sdr-mode.service
systemctl list-timers cyem-sdr-sweep.timer --no-pager | head -3
