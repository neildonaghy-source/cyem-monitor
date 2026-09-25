# CyEM SDR node (Raspberry Pi 5 + RTL-SDR Blog V4)

Live receiver (OpenWebRX+) and background spectrum sweeps posted to CyEM, reachable only on the tailnet.
Reception and display of spectrum occupancy only. Do not listen to non-broadcast, non-amateur traffic
(Wireless Telegraphy Act 2006 s48); use the waterfall to see presence, not content.

## You need
- Raspberry Pi 5 (4 GB), 27 W USB-C supply, case with cooler, 32 GB microSD
- RTL-SDR Blog V4 dongle, dipole kit, 0.5 m USB extension (keep the dongle away from the Pi)
- A Tailscale auth key: reusable, pre-approved, tagged `tag:cyem-sdr` (add tagOwners for it, as for tag:cyem-client)
- The ingest token: on the trade box, `grep SDR_INGEST_TOKEN ~/cyem/.env` (keep it out of chats)

## 1. Flash the card (Mac, Raspberry Pi Imager)
Device Raspberry Pi 5, OS "Raspberry Pi OS Lite (64-bit)". Edit settings: hostname `cyem-sdr`, a username,
home Wi-Fi, locale Europe/London; Services: enable SSH with your Mac's public key.

## 2. First boot and setup
Insert the card, fit the cooler and case, plug the dongle in via the extension, power on, wait two minutes.
Copy this `pi/` folder to the Pi as `~/cyem-pi`, SSH in, then run setup.sh as root with four variables:
TS_AUTHKEY, SDR_INGEST_TOKEN, HOTSPOT_SSID (your iPhone hotspot name) and HOTSPOT_PSK.
Then create the receiver admin user: `docker exec -it openwebrx openwebrx admin adduser <name>` (as root).

## 3. Tailscale policy
Allow `tag:cyem-sdr` to reach `trade:8443` (to post sweeps), and `tag:cyem-client` plus your own devices to
reach `tag:cyem-sdr:443` (the live receiver).

## 4. Use it
CyEM, Tools, SDR: node status, latest spectrum with peaks labelled from the UK Frequency Allocation Table,
"Open live receiver", and "Set receiver position to this device". In the field turn on the iPhone Personal
Hotspot; the Pi joins it automatically and reconnects to the tailnet.

## Checks and troubleshooting
- `rtl_test -t` should report "RTL-SDR Blog V4 Detected". If not, re-seat the dongle and re-run setup.sh.
- `journalctl -u cyem-sweep -f` shows each sweep posted (1 to 2 minutes per full 24 to 1766 MHz pass).
- If OpenWebRX+ does not see the V4, run the host driver as a network source: `rtl_tcp -a 0.0.0.0 -p 1234`,
  then add an "RTL-SDR (rtl_tcp)" device at 172.17.0.1:1234 in the OpenWebRX+ settings.
- Sweeps pause while anyone has the live receiver open, and resume on the next interval.
