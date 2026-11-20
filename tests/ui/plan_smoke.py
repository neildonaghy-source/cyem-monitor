"""Planning area smoke test: Plan button, tab strip, link / coverage / HF calculations, spectrum panel. ~2 min."""
import asyncio, sys, time
from playwright.async_api import async_playwright

results = []
def rec(name, ok, note=""):
    results.append((name, ok)); print(f"{'PASS' if ok else 'FAIL'} {name}{(': ' + note) if note else ''}", flush=True)

async def wait_text(pg, sel, needle, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        txt = await pg.evaluate(f"() => document.querySelector('{sel}')?.innerText || ''")
        if needle.lower() in txt.lower():
            return txt
        await pg.wait_for_timeout(1500)
    return ""

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(); ctx = await b.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_init_script("localStorage.setItem('cyem-ws-mode','device'); localStorage.setItem('cyem-ws','uitest2'); localStorage.setItem('cyem-coach','1');")
        pg = await ctx.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append("PAGEERR " + str(e)))
        pg.on("console", lambda m: errs.append("CONSOLE " + m.text) if m.type == "error" else None)
        pg.on("response", lambda r: errs.append(f"HTTP {r.status} {r.url[-70:]}") if r.status >= 500 else None)
        await pg.goto("http://127.0.0.1:3020/", wait_until="networkidle"); await pg.wait_for_timeout(1500)
        await pg.click("#btn-plan"); await pg.wait_for_timeout(1500)
        rec("Plan opens the Planning modal", (await pg.evaluate("() => document.getElementById('modal-title').textContent")) == "Plan")
        rec("tab strip present", (await pg.evaluate("() => document.querySelectorAll('.plantabs button').length")) == 4)
        # Links
        await pg.click(".plantabs button[data-plan=links]"); await pg.wait_for_timeout(1200)
        rec("Links tab renders", bool(await pg.query_selector("#lk-analyse")))
        for k, v in [("name", "smoke link"), ("a_lat", "51.90"), ("a_lon", "-3.40"), ("b_lat", "51.95"), ("b_lon", "-3.20"), ("freq_mhz", "1400"), ("bw_khz", "5000"), ("ptx_dbm", "30"), ("gtx_dbi", "20"), ("grx_dbi", "20"), ("sens_dbm", "-90"), ("req_margin_db", "10")]:
            await pg.fill(f"#lk-{k}", v)
        await pg.click("#lk-analyse")
        rec("link analysis responds", bool(await wait_text(pg, "#lk-out", "dB", 180)))
        rec("tab strip survives re-render", (await pg.evaluate("() => document.querySelectorAll('.plantabs button.active').length")) == 1)
        # Coverage
        await pg.click(".plantabs button[data-plan=cov]"); await pg.wait_for_timeout(1200)
        rec("Coverage tab renders", bool(await pg.query_selector("#cv-analyse")))
        for k, v in [("lat", "51.90"), ("lon", "-3.40"), ("freq_mhz", "60"), ("bw_khz", "25"), ("radius_km", "8"), ("ptx_dbm", "37"), ("gtx_dbi", "2"), ("name", "smoke site")]:
            if await pg.query_selector(f"#cv-{k}"):
                await pg.fill(f"#cv-{k}", v)
        await pg.click("#cv-analyse")
        rec("coverage analysis responds", bool(await wait_text(pg, "#cv-out", "km", 240)))
        # HF
        await pg.click(".plantabs button[data-plan=hf]"); await pg.wait_for_timeout(1200)
        rec("HF tab renders", bool(await pg.query_selector("#hf-go")))
        for k, v in [("alat", "51.9"), ("alon", "-3.4"), ("blat", "57.5"), ("blon", "-4.2"), ("f", "7.1")]:
            await pg.fill(f"#hf-{k}", v)
        await pg.click("#hf-go")
        rec("HF now-cast responds", bool(await wait_text(pg, "#hf-out", "MUF", 120)))
        # Spectrum
        await pg.click(".plantabs button[data-plan=spec]"); await pg.wait_for_timeout(2500)
        rec("Spectrum tab renders", bool(await pg.query_selector("#sp-save")))
        await pg.click("#modal-close"); await pg.wait_for_timeout(300)
        await pg.click("#btn-plan"); await pg.wait_for_timeout(1200)
        rec("Plan reopens on the last tab", bool(await pg.query_selector("#sp-save")))
        await pg.screenshot(path="/out/plan_smoke.png")
        rec("no page errors", not errs, "; ".join(errs)[:300])
        await b.close()
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    sys.exit(1 if bad else 0)

asyncio.run(main())
