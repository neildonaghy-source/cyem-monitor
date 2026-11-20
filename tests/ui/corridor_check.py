"""Browser check for the EMO corridor card, in a private workspace that it empties afterwards.
Usage: python tests/ui/corridor_check.py [base-url] [screenshot.png]   (default http://127.0.0.1:3020/); PW_CHROME=<browser binary> if Playwright's own is missing"""
import asyncio, os, sys, time
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3020/"
SHOT = sys.argv[2] if len(sys.argv) > 2 else "corridor.png"
WS = "corrcheck2"
fails = []

# Points inside #map where the topmost element is the map itself (a tile, the canvas renderer or a pane), at least 40 px
# from any marker icon and not under a control, the layer panel, the pick bar or an EMO card. Nearest the map centre
# first; returns {x, y, more: [[x, y], ...]} or null.
MAP_POINT_JS = """() => {
  const map = document.getElementById('map'), r = map.getBoundingClientRect();
  const icons = [...document.querySelectorAll('.leaflet-marker-icon')].map(e => e.getBoundingClientRect()).filter(b => b.width);
  const blocked = (el) => !el || !map.contains(el) || el.closest('.leaflet-marker-pane, .leaflet-control-container, .leaflet-tooltip-pane, .leaflet-popup-pane, #layers, #legend');
  const gap = (x, y) => icons.reduce((m, b) => Math.min(m, Math.hypot(Math.max(b.left - x, 0, x - b.right), Math.max(b.top - y, 0, y - b.bottom))), 1e9);
  const pts = [];
  for (let y = r.top + 40; y < r.bottom - 40; y += 30) for (let x = r.left + 40; x < r.right - 40; x += 30) {
    if (blocked(document.elementFromPoint(x, y))) continue;
    const g = gap(x, y); if (g >= 40) pts.push([Math.round(x), Math.round(y), g]);
  }
  const cx = (r.left + r.right) / 2, cy = (r.top + r.bottom) / 2;      // near the centre: the scenario area, not a far corner
  pts.sort((a, b) => Math.hypot(a[0] - cx, a[1] - cy) - Math.hypot(b[0] - cx, b[1] - cy));
  return pts.length ? { x: pts[0][0], y: pts[0][1], more: pts.slice(1, 4).map(p => [p[0], p[1]]) } : null;
}"""


def rec(name, ok, note=""):
    print(("PASS " if ok else "FAIL ") + name + (f": {note}" if note else ""), flush=True)
    if not ok:
        fails.append(name)


async def wait_js(pg, js, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = await pg.evaluate(js)
        if v:
            return v
        await pg.wait_for_timeout(1500)
    return None


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=os.environ.get("PW_CHROME") or None)   # trade: the 1228 headless shell
        ctx = await b.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_init_script(f"localStorage.setItem('cyem-ws-mode','device'); localStorage.setItem('cyem-ws','{WS}'); localStorage.setItem('cyem-coach','1'); localStorage.setItem('cyem-emo-on','1');")   # a first run starts with EMO off
        pg = await ctx.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await ctx.request.post(BASE + "api/emo/examples/bg-vignette", headers={"X-CyEM-WS": WS}, data={})   # before the page runs
        await pg.goto(BASE)
        chip = await wait_js(pg, "() => { const c = document.getElementById('emo-chip')?.textContent || ''; return c.startsWith('EMO T+') && !c.includes('updating') && c; }")
        rec("scenario runs", bool(chip), chip or "")
        await pg.click("[data-dock=corridor]")
        units = await pg.evaluate("() => [...document.querySelectorAll('#corr-unit option')].map(o => o.textContent)")
        rec("corridor card lists blue and red units", len(units) > 2, ", ".join(units[:4]))
        await pg.select_option("#corr-unit", label="Blue BG Main HQ")
        rec("plan disabled before a destination", await pg.is_disabled("#corr-go"))
        await pg.click("#corr-pick")
        # pickOnMap (01-map-basemaps.js) shows a "Click the map" bar and listens for a Leaflet map click. The old fixed
        # point (card x - 150, y 330) landed on unit symbols or labels in the marker pane, which take the click
        # themselves (Leaflet markers do not bubble to the map), so no destination was set. Wait for the bar, then click
        # a point where the map container itself (tiles or the canvas) is topmost, clear of markers, controls and cards.
        await pg.wait_for_selector(".emo-trackbar >> text=Click the map", timeout=10000)
        pt = await pg.evaluate(MAP_POINT_JS)
        rec("clear map point found for the pick", bool(pt), str(pt))
        to = None
        for x, y in ([pt["x"], pt["y"]],) + tuple(pt.get("more", [])) if pt else ():
            await pg.mouse.click(x, y)
            to = await wait_js(pg, "() => { const t = document.getElementById('corr-to')?.textContent; return t && t !== 'none' && t; }", 6)
            if to:
                break
            if not await pg.query_selector(".emo-trackbar"):              # the click was taken but not as a pick: start again
                await pg.click("#corr-pick")
                await pg.wait_for_selector(".emo-trackbar >> text=Click the map", timeout=10000)
        rec("map click sets the destination", bool(to), to or "")
        await pg.click("#corr-go")
        out = await wait_js(pg, "() => { const t = document.getElementById('corr-out')?.textContent || ''; return /verified/i.test(t) && t; }", 300)
        if not out:
            out = await pg.evaluate("() => document.getElementById('corr-st')?.innerText")
        rec("corridor planned with a legs table", bool(out) and "verified" in out.lower(), (out or "")[:160].replace("\n", " "))
        legs = int(await pg.evaluate("() => document.body.dataset.corrLegs || 0"))          # canvas renderer: no SVG paths to count
        band = await pg.evaluate("() => [...document.querySelectorAll('img.leaflet-image-layer')].some(i => i.src.startsWith('data:image/png'))")
        rec("route drawn by leg, band shown", legs >= 1 and band, f"{legs} leg(s)")
        await pg.screenshot(path=SHOT)
        await pg.click("#corr-clear")
        left = int(await pg.evaluate("() => document.body.dataset.corrLegs || 0"))
        rec("clear removes the route", left == 0)
        # worked vignette through time (example 6 loaded from the panel, as a user would)
        await pg.evaluate("() => document.getElementById('emo-dockcard')?.remove()")
        await pg.click("[data-dock=panel]")
        await pg.wait_for_selector("#emo-ex", timeout=20000)
        await pg.select_option("#emo-ex", value="uas-gnss")
        await pg.click("#emo-ex-go")
        await wait_js(pg, "() => (document.getElementById('emo-chip')?.textContent || '').startsWith('EMO T+') && document.querySelectorAll('#emo-ex').length", 120)
        await pg.wait_for_timeout(3000)
        await pg.evaluate("() => document.querySelector('.modal-close, #modal-close')?.click()")
        await pg.click("[data-dock=corridor]")
        vig = await pg.query_selector("#corr-vig")
        rec("worked vignette offered for example 6", bool(vig))
        if vig:
            await vig.click()
            await pg.click("#corr-go")
            out = await wait_js(pg, "() => { const t = document.getElementById('corr-out')?.textContent || ''; return /time layers/i.test(t) && /verified/i.test(t) && t; }", 300)
            rec("vignette planned through time layers with GNSS", bool(out) and "GNSS" in out, (out or "")[:200].replace("\n", " "))
            await pg.screenshot(path=SHOT.replace(".png", "-uas.png"))
        rec("no page errors", not errs, "; ".join(errs)[:200])
        n = await pg.evaluate("""async () => { const r = await (await fetch('/api/emo')).json();
            for (const e of r.entities) await fetch('/api/emo/' + encodeURIComponent(e.id), {method: 'DELETE'});
            return (await (await fetch('/api/emo')).json()).entities.length; }""")
        rec(f"workspace {WS} emptied", n == 0)
        await b.close()
    sys.exit(1 if fails else 0)


asyncio.run(main())
