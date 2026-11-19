#!/bin/bash
# Installs the shared CyEM sweep on trade (run once by Neil):  sudo bash ~/cyem-sdr/install-trade-sweep.sh
# Reads the ingest token from ~trade/cyem-sdr/token (copied from the EVO .env) and moves it to /etc/cyem-sweep.env (root,
# 600). Timer: four sweeps a day at about 02:20, 08:20, 14:20 and 20:20 UK time (up to 20 min later at random); each stops
# the Ecowitt receiver for about three minutes. Remove: sudo bash ~/cyem-sdr/install-trade-sweep.sh --remove
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
SRC=/home/trade/cyem-sdr
if [[ "${1:-}" == "--remove" ]]; then
  systemctl disable --now cyem-sdr-sweep.timer 2>/dev/null || true
  rm -f /etc/systemd/system/cyem-sdr-sweep.{service,timer} /usr/local/sbin/cyem-sdr-sweep /etc/cyem-sweep.env
  rm -rf /opt/cyem-sweep; systemctl daemon-reload; systemctl start ecowitt-receiver.service
  echo "removed"; exit 0
fi
if [[ -f "$SRC/token" ]]; then TOKEN=$(tr -d '\n' < "$SRC/token")
elif [[ -f /etc/cyem-sweep.env ]]; then TOKEN=$(sed -n 's/^SDR_INGEST_TOKEN=//p' /etc/cyem-sweep.env)   # re-run: keep it
else TOKEN=""; fi
[[ -n "$TOKEN" ]] || { echo "no token in $SRC/token or /etc/cyem-sweep.env"; exit 1; }
install -d -m 755 /opt/cyem-sweep
install -m 644 "$SRC/cyem_sweep.py" /opt/cyem-sweep/cyem_sweep.py
install -m 755 "$SRC/cyem-sdr-sweep" /usr/local/sbin/cyem-sdr-sweep
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
systemctl daemon-reload
systemctl enable --now cyem-sdr-sweep.timer
echo "installed; first sweep now (about 3 minutes, weather receiver paused):"
systemctl start cyem-sdr-sweep.service || true
journalctl -u cyem-sdr-sweep.service -n 5 --no-pager
systemctl is-active ecowitt-receiver.service
systemctl list-timers cyem-sdr-sweep.timer --no-pager | head -3
