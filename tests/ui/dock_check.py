from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    for name, vp in (("portrait", (390, 844)), ("landscape", (844, 390))):
        c = b.new_context(viewport={"width": vp[0], "height": vp[1]}, is_mobile=True, has_touch=True, device_scale_factor=2)
        c.add_init_script("localStorage.setItem('cyem-emo-on','1');")   # a first run starts with EMO off
        pg = c.new_page()
        pg.goto("http://127.0.0.1:3020/")
        pg.wait_for_selector("#emo-dock", timeout=60000)
        pg.wait_for_timeout(2500)
        clipped = pg.evaluate("""() => [...document.querySelectorAll('#emo-dock button')].filter(b => b.offsetParent && b.scrollWidth > b.clientWidth + 1).map(b => b.textContent)""")
        offscreen = pg.evaluate("""() => [...document.querySelectorAll('#emo-dock button')].filter(b => { const r = b.getBoundingClientRect(); return r.right > innerWidth + 1 || r.left < -1; }).map(b => b.textContent)""")
        print(name, "clipped:", clipped, "offscreen:", offscreen)
        pg.screenshot(path=f"/out/dock_{name}.png")
        c.close()
    b.close()
