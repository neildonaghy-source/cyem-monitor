"""UI audit: open every panel, pill, layer group and the phone layout; report page errors, console errors,
failed requests and 4xx/5xx API responses. Read-only apart from layer toggles in this test context."""
import asyncio, sys, time
from playwright.async_api import async_playwright

async def run(pg, errs, label, fn, settle=1500):
    n0 = len(errs)
    try:
        await fn()
        await pg.wait_for_timeout(settle)
    except Exception as e:
        errs.append(f"[{label}] EXC {str(e)[:160]}")
    new = errs[n0:]
    print(f"{'PASS' if not new else 'FAIL'} {label}" + (": " + " | ".join(x[:150] for x in new[:3]) if new else ""), flush=True)
    return not new

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for name, vp, mobile in [("desktop", {"width": 1440, "height": 900}, False), ("phone", {"width": 390, "height": 844}, True)]:
            print(f"== {name}")
            ctx = await b.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile)
            await ctx.add_init_script("localStorage.setItem('cyem-ws-mode','device'); localStorage.setItem('cyem-ws','uitest2'); localStorage.setItem('cyem-coach','1');")
            pg = await ctx.new_page(); errs = []
            pg.on("pageerror", lambda e: errs.append("PAGEERR " + str(e)[:200]))
            pg.on("console", lambda m: errs.append("CONSOLE " + m.text[:200]) if m.type == "error" else None)
            pg.on("requestfailed", lambda r: errs.append(f"REQFAIL {r.url[-80:]} {r.failure}") if "/api/" in r.url else None)
            pg.on("response", lambda r: errs.append(f"HTTP {r.status} {r.request.method} {r.url[-90:]}") if (r.status >= 400 and "/api/" in r.url) else None)
            await run(pg, errs, "page load", lambda: pg.goto("http://127.0.0.1:3020/", wait_until="networkidle"), 2500)
            if not mobile:
                for bid in ["btn-rail", "btn-side", "btn-health", "btn-sdr", "btn-plan", "btn-emo"]:
                    await run(pg, errs, f"button {bid}", lambda bid=bid: pg.click("#" + bid), 2500)
                    await pg.evaluate("() => document.getElementById('modal').classList.remove('show')")
                pills = await pg.evaluate("() => [...document.querySelectorAll('#pills .pill')].map(p => p.dataset.p)")
                for pl in pills:
                    await run(pg, errs, f"pill {pl}", lambda pl=pl: pg.click(f"#pills .pill[data-p='{pl}']"), 2500)
                    await pg.evaluate("() => document.getElementById('modal').classList.remove('show')")
                await pg.fill("#omni-q", "Brecon")
                await run(pg, errs, "omnibox search", lambda: pg.click("#omni-go"), 5000)
                await pg.evaluate("() => document.getElementById('omni-close')?.click()")
                # every layer group: all on, then all off
                groups = await pg.evaluate("() => [...document.querySelectorAll('#layers .lgroup')].map(g => g.dataset.group)")
                for g in groups:
                    if g == "basemap": continue
                    await run(pg, errs, f"layers {g} all on", lambda g=g: pg.evaluate(f"() => document.querySelector('#layers .lgroup[data-group=\"{g}\"] a[data-all=on]')?.click()"), 6000)
                    await run(pg, errs, f"layers {g} all off", lambda g=g: pg.evaluate(f"() => document.querySelector('#layers .lgroup[data-group=\"{g}\"] a[data-all=off]')?.click()"), 1500)
                bms = await pg.evaluate("() => [...document.querySelectorAll('#layers input[name=basemap]')].map(r => r.value)")
                for bm in bms:
                    await run(pg, errs, f"basemap {bm}", lambda bm=bm: pg.evaluate(f"() => document.querySelector('#layers input[name=basemap][value=\"{bm}\"]').click()"), 2500)
                await pg.evaluate("() => document.querySelector('#layers input[name=basemap][value=\"esri_dark\"]')?.click()")
            else:
                await pg.screenshot(path="/out/audit_phone_map.png")
                await run(pg, errs, "tools sheet", lambda: pg.click("#mob-tools"), 1000)
                await run(pg, errs, "map layers sheet", lambda: pg.click("#modal-body [data-layers]"), 1000)
                print("   layers sheet width px:", await pg.evaluate("() => document.getElementById('layers').getBoundingClientRect().width"))
                await run(pg, errs, "layers hide", lambda: pg.click("#layers-toggle"), 500)
                await run(pg, errs, "tools sheet again", lambda: pg.click("#mob-tools"), 800)
                await run(pg, errs, "planning from sheet", lambda: pg.click("#modal-body button[data-go=btn-plan]"), 2000)
                print("   plan tab buttons:", await pg.evaluate("() => document.querySelectorAll('.plantabs button').length"))
                await pg.evaluate("() => document.getElementById('modal').classList.remove('show')")
                await run(pg, errs, "feed view", lambda: pg.click("#mobnav button[data-view=rail]"), 1500)
                await run(pg, errs, "brief view", lambda: pg.click("#mobnav button[data-view=side]"), 1500)
                await run(pg, errs, "map view", lambda: pg.click("#mobnav button[data-view=map]"), 1000)
                await run(pg, errs, "tools sheet EMO", lambda: pg.click("#mob-tools"), 800)
                await run(pg, errs, "EMO from sheet", lambda: pg.click("#modal-body button[data-go=btn-emo]"), 3000)
                await pg.evaluate("() => document.getElementById('modal').classList.remove('show')"); await pg.wait_for_timeout(800)
                await pg.screenshot(path="/out/audit_phone_emo.png")
                ov = await pg.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
                print("   horizontal overflow:", ov)
                await pg.screenshot(path="/out/audit_phone.png")
            print(f"   {name}: {len(errs)} issues")
            await ctx.close()
        await b.close()

asyncio.run(main())
