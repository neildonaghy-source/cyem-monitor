"""Delete works without window.confirm (the native apps' web views never show it): add a planned emitter via the API,
delete it in the Spectrum tab with two taps, check it is gone. Runs with confirm() stubbed to return false, as in the apps."""
import json, sys, urllib.request
from playwright.sync_api import sync_playwright

B = "http://127.0.0.1:3020"
def call(method, path, body=None):
    r = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=20).read() or b"{}")

pe = call("POST", "/api/spectrum/planned", {"name": "delete-check (test)", "freq_mhz": 47.3, "bw_khz": 25, "lat": 50.9, "lon": -1.2})
pid = pe.get("id")
print("created", pid)
ok = False
with sync_playwright() as p:
    b = p.chromium.launch()
    c = b.new_context(viewport={"width": 1400, "height": 900})
    c.add_init_script("window.confirm = () => false; localStorage.setItem('cyem-emo-on','0');")
    pg = c.new_page()
    pg.goto(B + "/")
    pg.wait_for_function("() => !!window.__cyemMap", timeout=60000)
    pg.click("#btn-plan")
    pg.wait_for_selector(f"button[data-del='{pid}']", timeout=30000)
    btn = pg.locator(f"button[data-del='{pid}']")
    btn.click()
    print("after first tap:", btn.text_content())
    btn.click()
    pg.wait_for_timeout(2500)
    left = [x["id"] for x in call("GET", "/api/spectrum/planned")["planned"]]
    ok = pid not in left
    b.close()
if not ok:
    call("DELETE", f"/api/spectrum/planned/{pid}")
print("PASS delete with two taps" if ok else "FAIL delete with two taps")
sys.exit(0 if ok else 1)
