"""Start-up default: a saved setup is applied on a fresh app start (layers, basemap, EMO state, map view).
Saves a test setup through the API, checks a new browser opens with it, then restores whatever was saved before."""
import json, sys, urllib.request
from playwright.sync_api import sync_playwright

B = "http://127.0.0.1:3020"
def call(method, path, body=None):
    r = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=20).read() or b"{}")

before = call("GET", "/api/prefs/startup")
fails = 0
try:
    call("PUT", "/api/prefs/startup", {"ls": {"cyem.layers": json.dumps({"cables": True, "gpsjam": False}), "cyem.basemap": json.dumps("osm") if False else "osm",
                                              "cyem-emo-on": "0"}, "view": {"lat": 50.83, "lon": -0.78, "z": 9}, "device": "test"})
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1400, "height": 900})
        pg.goto(B + "/")
        pg.wait_for_function("() => !!window.__cyemMap", timeout=60000)
        pg.wait_for_timeout(6000)
        st = pg.evaluate("""() => { const m = window.__cyemMap, c = m.getCenter();
          return { lat: c.lat, lon: c.lng, z: m.getZoom(), layers: localStorage.getItem('cyem.layers'), emo: localStorage.getItem('cyem-emo-on'),
                   dock: !!document.getElementById('emo-dock'), msg: (document.getElementById('startup-msg') || {}).textContent }; }""")
        print(st)
        checks = [("view centre", abs(st["lat"] - 50.83) < 0.05 and abs(st["lon"] + 0.78) < 0.05), ("zoom", st["z"] == 9),
                  ("layers applied", json.loads(st["layers"] or "{}").get("cables") is True), ("EMO off", st["emo"] == "0" and not st["dock"]),
                  ("footer shows default", "start-up default" in (st["msg"] or ""))]
        for n, ok in checks:
            print(("PASS " if ok else "FAIL ") + n); fails += 0 if ok else 1
        b.close()
finally:
    if before.get("saved_at"):
        call("PUT", "/api/prefs/startup", {"ls": before.get("ls", {}), "view": before.get("view"), "device": before.get("device", "")})
    else:
        import os
        try: os.remove("/data-startup/startup.json")
        except Exception: pass
print("result:", "all pass" if not fails else f"{fails} failing")
sys.exit(1 if fails else 0)
