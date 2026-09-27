"""SDR live receiver opens in an in-app window and Close returns to the app (no page navigation)."""
import sys
from playwright.sync_api import sync_playwright
ok = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 900})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("http://127.0.0.1:3020/")
    pg.wait_for_function("() => !!window.__cyemMap", timeout=60000)
    url0 = pg.url
    pg.click("#btn-sdr"); pg.wait_for_selector("#sdr-live", timeout=30000)
    pg.click("#sdr-live"); pg.wait_for_timeout(1500)
    ok.append(("window opens with the receiver", pg.evaluate("() => !!document.querySelector('#sdr-live-ov iframe')")))
    ok.append(("app page not replaced", pg.url == url0))
    pg.click("#sdr-live-close"); pg.wait_for_timeout(500)
    ok.append(("Close removes it", pg.evaluate("() => !document.getElementById('sdr-live-ov')")))
    pg.click("#sdr-live"); pg.wait_for_timeout(800); pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
    ok.append(("Esc closes it", pg.evaluate("() => !document.getElementById('sdr-live-ov')")))
    ok.append(("no page errors", not errs))
    b.close()
for n, v in ok: print(("PASS " if v else "FAIL ") + n)
sys.exit(0 if all(v for _, v in ok) else 1)
