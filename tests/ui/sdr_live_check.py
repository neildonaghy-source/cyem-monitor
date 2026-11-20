"""SDR panel (20 Nov 2026): opens as a side sheet beside the map, shows the Listen live box for a live-capable node,
and closes with Escape. Does not start live listening (that pauses trade's weather receiver)."""
import os
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3020/"
ok = []
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("PW_CHROME") or None)
    pg = b.new_page(viewport={"width": 1400, "height": 900})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BASE)
    pg.wait_for_function("() => !!window.__cyemMap", timeout=60000)
    pg.click("#btn-sdr"); pg.wait_for_selector("#sdr-sheet.open", timeout=30000)
    ok.append(("SDR opens as a sheet, not the modal", pg.evaluate("() => !document.getElementById('modal').classList.contains('show')")))
    ok.append(("Listen live box shown", pg.wait_for_selector("#sdr-listen", timeout=15000) is not None))
    ok.append(("says nothing is recorded", "nothing is recorded" in pg.inner_text("#sdr-livebox").lower()))
    ok.append(("map still usable beside it", pg.evaluate("() => { const r = document.getElementById('sdr-sheet').getBoundingClientRect();"
                                                         " const e = document.elementFromPoint(r.left / 2, 450); return !!e && !!e.closest('#map'); }")))
    pg.click("#btn-health"); pg.wait_for_timeout(800)
    ok.append(("one sheet at a time", pg.evaluate("() => document.querySelectorAll('.sheet.open').length") == 1))
    pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
    ok.append(("Esc closes it", pg.evaluate("() => document.querySelectorAll('.sheet.open').length") == 0))
    ok.append(("no page errors", not errs))
    b.close()
for n, v in ok: print(("PASS " if v else "FAIL ") + n)
sys.exit(0 if all(v for _, v in ok) else 1)
