"""Browser check for the EMO Spectrum card (phase 6 part 4), in a private workspace that it empties afterwards.
Usage: python tests/ui/spectrum_check.py [base-url] [screenshot.png]   (default http://127.0.0.1:3020/); PW_CHROME=<browser binary> if Playwright's own is missing"""
import asyncio, os, sys, time
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3020/"
SHOT = sys.argv[2] if len(sys.argv) > 2 else "spectrum.png"
WS = "speccheck1"
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
        await ctx.request.post(BASE + "api/emo/examples/bg-vignette", headers={"X-CyEM-WS": WS}, data={})
        await pg.goto(BASE)
        chip = await wait_js(pg, "() => { const c = document.getElementById('emo-chip')?.textContent || ''; return c.startsWith('EMO T+') && !c.includes('updating') && c; }", 300)
        rec("scenario runs", bool(chip), chip or "")
        await pg.click("[data-dock=spectrum]")
        nets = await pg.evaluate("() => [...document.querySelectorAll('#spec-net option')].map(o => o.textContent)")
        rec("card lists nets", "Blue BG Main HQ" in nets and not any("GPS" in n for n in nets), ", ".join(nets[:4]))
        await pg.select_option("#spec-net", label="Blue BG Main HQ")
        await pg.fill("#spec-hor", "40")
        await pg.click("#spec-go")
        out = await wait_js(pg, "() => { const t = document.getElementById('spec-out')?.textContent || ''; return /Best:/.test(t) && t; }", 240)
        rec("channels assessed", bool(out), (out or "")[:160].replace("\n", " "))
        n = int(await pg.evaluate("() => document.body.dataset.specChannels || 0"))
        rows = await pg.evaluate("() => document.querySelectorAll('#spec-out table tr').length")
        rec("a row per channel plus own and hop set", n >= 40 and rows >= n + 3, f"{n} channels, {rows} rows")
        await pg.screenshot(path=SHOT)
        await pg.click("#spec-clear")
        rec("clear empties the card", int(await pg.evaluate("() => document.body.dataset.specChannels || 0")) == 0)
        rec("no page errors", not errs, "; ".join(errs)[:200])
        n = await pg.evaluate("""async () => { const r = await (await fetch('/api/emo')).json();
            for (const e of r.entities) await fetch('/api/emo/' + encodeURIComponent(e.id), {method: 'DELETE'});
            return (await (await fetch('/api/emo')).json()).entities.length; }""")
        rec(f"workspace {WS} emptied", n == 0)
        await b.close()
    sys.exit(1 if fails else 0)


asyncio.run(main())
