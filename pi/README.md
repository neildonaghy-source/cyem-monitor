# CyEM SDR node (Raspberry Pi 5 + RTL-SDR Blog V4)

Live receiver (OpenWebRX+) and background spectrum sweeps posted to CyEM, reachable only on the tailnet.
Reception and display of spectrum occupancy only. Do not listen to non-broadcast, non-amateur traffic
(Wireless Telegraphy Act 2006 s48); use the waterfall to see presence, not content.

## You need
- Raspberry Pi 5 (4 GB), 27 W USB-C supply, case with cooler, 32 GB microSD
- RTL-SDR Blog V4 dongle, dipole kit, 0.5 m USB extension (keep the dongle away from the Pi)
- A Tailscale auth key: reusable, pre-approved, tagged `tag:cyem-sdr` (add tagOwners for it, as for tag:cyem-client)
- The ingest token: on the EVO, `grep SDR_INGEST_TOKEN /home/cyem/cyem/.env` in the CyEM WSL distro (keep it out of chats)
- Or, instead of a Pi: a second RTL-SDR on trade or the EVO running `cyem_sweep.py` with the same token (the first
  dongle on trade is kept by the Ecowitt weather receiver and cannot be shared)

## 1. Flash the card (Mac, Raspberry Pi Imager)
Device Raspberry Pi 5, OS "Raspberry Pi OS Lite (64-bit)". Edit settings: hostname `cyem-sdr`, a username,
home Wi-Fi, locale Europe/London; Services: enable SSH with your Mac's public key.

## 2. First boot and setup
Insert the card, fit the cooler and case, plug the dongle in via the extension, power on, wait two minutes.
Copy this `pi/` folder to the Pi as `~/cyem-pi`, SSH in, then run setup.sh as root with four variables:
TS_AUTHKEY, SDR_INGEST_TOKEN, HOTSPOT_SSID (your iPhone hotspot name) and HOTSPOT_PSK.
Then create the receiver admin user: `docker exec -it openwebrx openwebrx admin adduser <name>` (as root).

## 3. Tailscale policy
Add `"tag:cyem-sdr": ["autogroup:admin"]` to tagOwners and a grant letting `tag:cyem-sdr` reach `cyem-evo` on
tcp:443 (to post sweeps). Your own devices already reach everything; add `tag:cyem-app` to `tag:cyem-sdr` on tcp:443
if the apps should open the live receiver.

## 4. Use it
The SDR button (Tools on the iPhone): node status, latest spectrum with peaks labelled from the UK Frequency
Allocation Table, "Open live receiver", and the receiver position (postcode, place, map pick or "Use this device"). In the field turn on the iPhone Personal
Hotspot; the Pi joins it automatically and reconnects to the tailnet.

## Checks and troubleshooting
- `rtl_test -t` should report "RTL-SDR Blog V4 Detected". If not, re-seat the dongle and re-run setup.sh.
- `journalctl -u cyem-sweep -f` shows each sweep posted (1 to 2 minutes per full 24 to 1766 MHz pass).
- If OpenWebRX+ does not see the V4, run the host driver as a network source: `rtl_tcp -a 0.0.0.0 -p 1234`,
  then add an "RTL-SDR (rtl_tcp)" device at 172.17.0.1:1234 in the OpenWebRX+ settings.
- Sweeps pause while anyone has the live receiver open, and resume on the next interval.

## Shared receiver on trade (19 Nov 2026)

trade's RTL-SDR also feeds the Ecowitt weather receiver (rtl_433), so it cannot sweep continuously. `pi/trade/` holds a
root wrapper (`cyem-sdr-sweep`) that stops `ecowitt-receiver`, runs one `cyem_sweep.py --once` pass (24 to 1766 MHz,
about two minutes), posts it as node `trade-sdr`, and always restarts the weather receiver; a systemd timer runs it four
times a day (02:20, 08:20, 14:20, 20:20 UK, up to 20 minutes later). Install once on trade:
`sudo bash ~/cyem-sdr/install-trade-sweep.sh` (the ingest token is staged in `~/cyem-sdr/token` and moved to
`/etc/cyem-sweep.env`). Sweep now: `sudo systemctl start cyem-sdr-sweep`. Remove: the same script with `--remove`.
Each sweep leaves a gap of about three minutes in the weather data.
