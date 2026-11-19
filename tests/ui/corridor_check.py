"""Browser check for the EMO corridor card, in a private workspace that it empties afterwards.
Usage: python tests/ui/corridor_check.py [base-url] [screenshot.png]   (default http://127.0.0.1:3020/); PW_CHROME=<browser binary> if Playwright's own is missing"""
import asyncio, os, sys, time
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3020/"
SHOT = sys.argv[2] if len(sys.argv) > 2 else "corridor.png"
WS = "corrcheck2"
fails = []


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
        await ctx.add_init_script(f"localStorage.setItem('cyem-ws-mode','device'); localStorage.setItem('cyem-ws','{WS}'); localStorage.setItem('cyem-coach','1');")
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
        card = await (await pg.query_selector("#emo-dockcard")).bounding_box()    # click the map clear of the card
        x = card["x"] + card["width"] + 150 if card["x"] + card["width"] + 150 < 1400 else max(60, card["x"] - 150)
        await pg.mouse.click(x, 330)
        to = await wait_js(pg, "() => { const t = document.getElementById('corr-to')?.textContent; return t && t !== 'none' && t; }", 10)
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
