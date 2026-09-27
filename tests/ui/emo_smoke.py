"""Browser smoke test for the EMO flows. Runs against a live CyEM in a private workspace (never the shared one).
Usage (on the box): bash tests/ui/run.sh   (uses the Playwright docker image, ~3 minutes)"""
import asyncio, sys, time
from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:3020/"
results = []


def rec(name, ok, note=""):
    results.append((name, ok, note)); print(("PASS " if ok else "FAIL ") + name + (f": {note}" if note else ""), flush=True)


async def wait_chip(pg, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        c = await pg.evaluate("() => document.getElementById('emo-chip')?.textContent || ''")
        if c.startswith("EMO T+") and "updating" not in c:
            return c
        await pg.wait_for_timeout(2000)
    return None


async def wait_text(pg, sel, needle, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        txt = await pg.evaluate(f"() => document.querySelector('{sel}')?.innerText || ''")
        if needle.lower() in txt.lower():
            return txt
        await pg.wait_for_timeout(1500)
    return None


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_init_script("localStorage.setItem('cyem-ws-mode','device'); localStorage.setItem('cyem-ws','uitest1');")
        pg = await ctx.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE, wait_until="networkidle"); await pg.wait_for_timeout(800)
        await pg.evaluate("() => document.querySelectorAll('#layers .lgroup a[data-all=off]').forEach(a => a.click())")
        # the EMO button is on/off; when a scenario is already showing the panel comes from the dock
        # the shared start-up default may have EMO switched off: switch it on first
        if not await pg.evaluate("() => document.getElementById('btn-emo').classList.contains('active') || !!document.getElementById('emo-dock')"):
            await pg.click("#btn-emo")
        # wait for EMO to finish starting (dock or chip) before using the on/off button, so the click cannot toggle it off
        try: await pg.wait_for_function("() => document.getElementById('emo-dock') || document.getElementById('emo-chip')", timeout=60000)
        except Exception: pass
        await pg.evaluate("() => { const d = document.querySelector('#emo-dock [data-dock=panel]'); (d || document.getElementById('btn-emo')).click(); }"); await pg.wait_for_timeout(2500)
        rec("panel opens", bool(await pg.query_selector("#emo-ex")))
        rec("workspace toggle shows device", (await pg.evaluate("() => document.getElementById('emo-ws')?.value")) == "device")
        await pg.select_option("#emo-ex", "brecon-siting"); await pg.click("#emo-ex-go")
        chip = await wait_chip(pg); rec("scenario loads and runs", bool(chip), chip or "")
        rec("scoreboard rendered", bool(await wait_text(pg, "#emo-results", "Scoreboard", 30)))
        await pg.fill("#emo-tlstep", "40"); await pg.click("#emo-tl")
        rec("timeline renders", bool(await wait_text(pg, "#emo-tlout", "undetected", 200)))
        await pg.fill("#emo-coaname", "smoke"); await pg.click("#emo-coasave")
        rec("COA saved and listed", bool(await wait_text(pg, "#emo-coalist", "smoke", 30)))
        await pg.select_option("#emo-coaside", "red"); await pg.click("#emo-coa-ml")
        rec("MLCOA responds", bool(await wait_text(pg, "#emo-coaout", "MLCOA", 300)))
        await pg.click("#emo-coa-rev"); rec("revert responds", bool(await wait_text(pg, "#emo-coaout", "reverted", 200)))
        await pg.click("#modal-close"); await pg.wait_for_timeout(500)
        rec("ask bar present", bool(await pg.query_selector("#emo-askbar")))
        await pg.evaluate("() => [...document.querySelectorAll('.emo-sym')].find(s => s.textContent.includes('Blue HQ')).click()")
        rec("focus card opens", bool(await wait_text(pg, "#emo-card", "With others", 30)))
        await pg.click("[data-emo-plannet]")
        rec("score map renders", bool(await wait_text(pg, "#emo-planout", "siting", 240)))
        rec("heatmap overlay on map", (await pg.evaluate("() => document.querySelectorAll('.leaflet-image-layer').length")) > 0)
        await pg.click("[data-emo-tune]")
        rec("tune options render", bool(await wait_text(pg, "#emo-planout", "Power:", 120)))
        await pg.click("[data-emo-multi]"); await pg.wait_for_timeout(1000)
        rec("multi-select picker present", bool(await pg.query_selector("[data-emo-add]")))
        await pg.screenshot(path="/out/emo_smoke.png")
        rec("no page errors", not errs, "; ".join(errs)[:300])
        await b.close()
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    sys.exit(1 if bad else 0)

asyncio.run(main())
