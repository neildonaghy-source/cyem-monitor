"""Browser check for the EMO Sat/GNSS windows card (phase 6 part 3), in a private workspace that it empties afterwards.
Usage: python tests/ui/windows_check.py [base-url] [screenshot.png]   (default http://127.0.0.1:3020/); PW_CHROME=<browser binary> if Playwright's own is missing"""
import asyncio, os, sys, time
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3020/"
SHOT = sys.argv[2] if len(sys.argv) > 2 else "windows.png"
WS = "wincheck1"
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
        b = await p.chromium.launch(executable_path=os.environ.get("PW_CHROME") or None)
        ctx = await b.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_init_script(f"localStorage.setItem('cyem-ws-mode','device'); localStorage.setItem('cyem-ws','{WS}'); localStorage.setItem('cyem-coach','1'); localStorage.setItem('cyem-emo-on','1');")
        pg = await ctx.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await ctx.request.post(BASE + "api/emo/examples/littoral-a2ad", headers={"X-CyEM-WS": WS}, data={})
        await pg.goto(BASE)
        chip = await wait_js(pg, "() => { const c = document.getElementById('emo-chip')?.textContent || ''; return c.startsWith('EMO T+') && !c.includes('updating') && c; }", 300)
        rec("scenario runs", bool(chip), chip or "")
        await pg.click("[data-dock=windows]")
        terms = await pg.evaluate("() => [...document.querySelectorAll('#win-term option')].map(o => o.textContent)")
        rec("card lists satcom terminals, not radars", "Blue raid SATCOM" in terms and not any("radar" in t for t in terms), ", ".join(terms[:4]))
        await pg.select_option("#win-term", label="Blue raid SATCOM")
        await pg.fill("#win-hor", "120")
        await pg.click("#win-go")
        out = await wait_js(pg, "() => { const t = document.getElementById('win-out')?.textContent || ''; return /Windows:/.test(t) && t; }", 180)
        rec("windows found", bool(out), (out or "")[:160].replace("\n", " "))
        rows = int(await pg.evaluate("() => document.body.dataset.winRows || 0"))
        rec("satcom and GNSS rows drawn", rows >= 3, f"{rows} rows")
        line = await pg.evaluate("() => !!document.querySelector('#map path.leaflet-interactive[stroke-dasharray]') || document.querySelectorAll('#map canvas').length > 0")
        rec("bearing to the satellite drawn", bool(line))
        await pg.screenshot(path=SHOT)
        await pg.click("#win-clear")
        rec("clear empties the card", int(await pg.evaluate("() => document.body.dataset.winRows || 0")) == 0)
        rec("no page errors", not errs, "; ".join(errs)[:200])
        n = await pg.evaluate("""async () => { const r = await (await fetch('/api/emo')).json();
            for (const e of r.entities) await fetch('/api/emo/' + encodeURIComponent(e.id), {method: 'DELETE'});
            return (await (await fetch('/api/emo')).json()).entities.length; }""")
        rec(f"workspace {WS} emptied", n == 0)
        await b.close()
    sys.exit(1 if fails else 0)


asyncio.run(main())
