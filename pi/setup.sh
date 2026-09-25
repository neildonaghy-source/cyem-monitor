#!/bin/bash
# CyEM SDR node setup for Raspberry Pi 5 (Raspberry Pi OS Lite 64-bit) + RTL-SDR Blog V4.
# Run on the Pi:  sudo TS_AUTHKEY=tskey-auth-... SDR_INGEST_TOKEN=... HOTSPOT_SSID="Neil's iPhone" HOTSPOT_PSK=... bash setup.sh
# Installs: RTL-SDR Blog drivers (V4 support), Docker, OpenWebRX+ (live receiver), Tailscale (+ HTTPS serve),
# and the cyem-sweep service that posts spectrum sweeps to CyEM. Safe to re-run.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
: "${TS_AUTHKEY:?set TS_AUTHKEY (Tailscale auth key, tag:cyem-sdr)}"
: "${SDR_INGEST_TOKEN:?set SDR_INGEST_TOKEN (from the trade box ~/cyem/.env)}"
HOST=${HOST:-cyem-sdr}
USER_NAME=${SUDO_USER:-pi}

echo "== packages"
apt-get update -qq
apt-get install -y -qq git cmake build-essential pkg-config libusb-1.0-0-dev python3 curl

echo "== RTL-SDR Blog drivers (required for the V4 R828D tuner)"
if ! rtl_power -h 2>&1 | grep -q "rtl_power"; then :; fi
if [[ ! -f /usr/local/lib/librtlsdr.so ]]; then
  rm -rf /tmp/rtl-sdr-blog && git clone --depth 1 https://github.com/rtlsdrblog/rtl-sdr-blog /tmp/rtl-sdr-blog
  cmake -S /tmp/rtl-sdr-blog -B /tmp/rtl-sdr-blog/build -DINSTALL_UDEV_RULES=ON -DDETACH_KERNEL_DRIVER=ON
  make -C /tmp/rtl-sdr-blog/build -j4 && make -C /tmp/rtl-sdr-blog/build install && ldconfig
fi
echo "blacklist dvb_usb_rtl28xxu" > /etc/modprobe.d/blacklist-rtl.conf
modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true

echo "== Docker"
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
usermod -aG docker "$USER_NAME" || true

echo "== OpenWebRX+ (live receiver, local only; published to the tailnet by tailscale serve)"
docker rm -f openwebrx >/dev/null 2>&1 || true
docker run -d --name openwebrx --restart unless-stopped --device /dev/bus/usb \
  -p 127.0.0.1:8073:8073 -v openwebrx-settings:/var/lib/openwebrx -v openwebrx-etc:/etc/openwebrx \
  slechev/openwebrxplus:latest

echo "== Tailscale"
command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --auth-key="$TS_AUTHKEY" --hostname="$HOST" --ssh
tailscale serve --bg --https=443 http://127.0.0.1:8073

echo "== Wi-Fi: iPhone hotspot as a fallback network (home Wi-Fi set in Raspberry Pi Imager stays first)"
if [[ -n "${HOTSPOT_SSID:-}" && -n "${HOTSPOT_PSK:-}" ]]; then
  nmcli connection delete cyem-hotspot >/dev/null 2>&1 || true
  nmcli connection add type wifi con-name cyem-hotspot ssid "$HOTSPOT_SSID" wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$HOTSPOT_PSK" connection.autoconnect yes connection.autoconnect-priority 5 >/dev/null
fi

echo "== cyem-sweep service"
install -d /opt/cyem && install -m 755 "$(dirname "$0")/cyem_sweep.py" /opt/cyem/cyem_sweep.py
umask 077
cat > /etc/cyem-sweep.env <<EOF
SDR_INGEST_TOKEN=$SDR_INGEST_TOKEN
CYEM_URL=https://trade.tail013324.ts.net:8443
NODE=$HOST
F_LO=24M
F_HI=1766M
BIN=250k
INTERVAL=180
GAIN=30
EOF
cat > /etc/systemd/system/cyem-sweep.service <<EOF
[Unit]
Description=CyEM spectrum sweep agent
After=network-online.target docker.service tailscaled.service
Wants=network-online.target
[Service]
EnvironmentFile=/etc/cyem-sweep.env
ExecStart=/usr/bin/python3 /opt/cyem/cyem_sweep.py
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable --now cyem-sweep

echo
echo "Done. Live receiver:  $(tailscale status --json | python3 -c 'import json,sys;print("https://"+json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
echo "Create the OpenWebRX+ admin user:  sudo docker exec -it openwebrx openwebrx admin adduser neil"
echo "Sweep log:  journalctl -u cyem-sweep -f"
