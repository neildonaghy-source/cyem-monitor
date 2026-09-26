#!/usr/bin/env python3
"""CyEM sweep agent for a Raspberry Pi + RTL-SDR on the tailnet.

Every INTERVAL seconds, if the dongle is free (OpenWebRX+ not in use), runs one rtl_power sweep across
F_LO..F_HI and posts the power spectrum to CyEM (/api/sdr/ingest). Spectrum occupancy only: nothing is
demodulated or recorded. Config in /etc/cyem-sweep.env (see setup.sh)."""
import csv
import io
import json
import os
import socket
import subprocess
import time
import urllib.request

CYEM = os.environ.get("CYEM_URL", "https://trade.tail013324.ts.net:8443")
TOKEN = os.environ["SDR_INGEST_TOKEN"]
NODE = os.environ.get("NODE", socket.gethostname().lower())
F_LO, F_HI = os.environ.get("F_LO", "24M"), os.environ.get("F_HI", "1766M")
BIN = os.environ.get("BIN", "250k")
INTERVAL = int(os.environ.get("INTERVAL", "180"))
GAIN = os.environ.get("GAIN", "30")


def node_url() -> str | None:
    try:
        st = json.loads(subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=10).stdout)
        return "https://" + st["Self"]["DNSName"].rstrip(".")
    except Exception:  # noqa: BLE001
        return None


def sweep():
    """One rtl_power pass; returns (f0_hz, bin_hz, [dB...]) or None if the dongle is busy."""
    p = subprocess.run(["rtl_power", "-f", f"{F_LO}:{F_HI}:{BIN}", "-g", GAIN, "-i", "2", "-1", "-c", "20%", "-"],
                       capture_output=True, text=True, timeout=900)
    if p.returncode != 0 or not p.stdout.strip():
        return None
    rows = sorted((r for r in csv.reader(io.StringIO(p.stdout)) if len(r) > 6), key=lambda r: float(r[2]))
    f0, step, vals = float(rows[0][2]), float(rows[0][4]), []
    for r in rows:
        vals += [round(float(x), 1) for x in r[6:]]
    return f0, step, vals


def post(f0, step, vals):
    body = json.dumps({"node": NODE, "url": node_url(), "f0_hz": f0, "bin_hz": step, "db": vals,
                       "info": {"range": f"{F_LO}-{F_HI}", "gain": GAIN}}).encode()
    req = urllib.request.Request(CYEM + "/api/sdr/ingest", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def heartbeat(state: str) -> None:
    try:
        body = json.dumps({"node": NODE, "url": node_url(), "state": state}).encode()
        req = urllib.request.Request(CYEM + "/api/sdr/heartbeat", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"})
        urllib.request.urlopen(req, timeout=30)
    except Exception as e:  # noqa: BLE001
        print("heartbeat failed:", e, flush=True)


def openwebrx_busy() -> bool:
    """True if someone is using the live receiver (OpenWebRX+ holds the dongle while clients are connected)."""
    try:
        s = json.load(urllib.request.urlopen("http://127.0.0.1:8073/status.json", timeout=5))
        return any(r.get("users", 0) > 0 for r in s.get("sdrs", []))
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    while True:
        try:
            if openwebrx_busy():
                print("live receiver in use; skipping sweep", flush=True); heartbeat("live receiver in use")
            else:
                subprocess.run(["docker", "stop", "openwebrx"], capture_output=True, timeout=60)
                try:
                    r = sweep()
                finally:
                    subprocess.run(["docker", "start", "openwebrx"], capture_output=True, timeout=60)
                if r:
                    print("posted:", post(*r), flush=True); heartbeat("sweeping")
                else:
                    print("sweep failed (dongle busy or missing)", flush=True); heartbeat("no dongle")
        except Exception as e:  # noqa: BLE001
            print("error:", e, flush=True)
        time.sleep(INTERVAL)
