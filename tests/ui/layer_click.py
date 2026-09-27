"""Click real features on map layers and check the right pop-up opens.
Catches layers that draw but cannot be selected (e.g. a canvas stacked on top swallowing clicks).
Run: tests/ui/run.sh-style docker, python layer_click.py [emo]"""
import json, sys
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:3020/"
EMO_ON = len(sys.argv) > 1 and sys.argv[1] == "emo"
LAYERS = {"air": True, "ais": True, "gpsjam": True, "cables": True, "wtr": True, "milair": True, "emitters": True}
# (name, view centre, zoom, popup text that identifies the layer, feature kind)
CASES = [
    ("GNSS interference hex", (56.0, 22.0), 5, "GNSS interference", "polygon"),
    ("Submarine cable", (50.5, -4.0), 6, "Submarine Cable", "polyline"),
    ("Ofcom licence site", (50.84, -0.78), 10, "Ofcom WTR", "circle"),
    ("ADS-B aircraft", (51.5, -1.0), 7, "NIC / NACp", "circle"),
]

FIND = """([text, kind]) => {
  const m = window.__cyemMap, out = [];
  const W = innerWidth, H = innerHeight;
  const text_of = (l) => { const p = l.getPopup && l.getPopup(); if (!p) return ''; let c = p.getContent(); if (typeof c === 'function') { try { c = c(l); } catch (e) { return ''; } } return typeof c === 'string' ? c : (c && c.textContent) || ''; };
  m.eachLayer((l) => {
    if (out.length >= 6) return;
    const isPoly = l instanceof L.Polygon, isLine = l instanceof L.Polyline && !isPoly, isCirc = l instanceof L.CircleMarker;
    if ((kind === 'polygon' && !isPoly) || (kind === 'polyline' && !isLine) || (kind === 'circle' && !isCirc)) return;
    if (!text_of(l).includes(text)) return;
    let ll;
    if (isPoly) ll = l.getCenter();
    else if (isLine) { const pts = l.getLatLngs().flat(3); ll = pts[Math.floor(pts.length / 2)]; }
    else ll = l.getLatLng();
    const pt = m.latLngToContainerPoint(ll), r = m.getContainer().getBoundingClientRect();
    const x = r.left + pt.x, y = r.top + pt.y;
    if (x < 320 || x > W - 120 || y < 170 || y > H - 120) return;
    const hit = document.elementFromPoint(x, y);
    out.push({ x, y, hit: hit ? (hit.tagName + '.' + (hit.className && hit.className.baseVal !== undefined ? hit.className.baseVal : hit.className)).slice(0, 60) : null });
  });
  return out;
}"""

def main():
    fails = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        c = b.new_context(viewport={"width": 1400, "height": 900})
        c.add_init_script(f"""try {{ localStorage.setItem('cyem.layers', JSON.stringify({json.dumps(LAYERS)}));
            localStorage.setItem('cyem-emo-on', '{'1' if EMO_ON else '0'}'); localStorage.setItem('cyem-coach-seen', '1'); }} catch (e) {{}}""")
        pg = c.new_page()
        pg.goto(URL)
        pg.wait_for_function("() => !!window.__cyemMap", timeout=60000)
        pg.wait_for_timeout(8000)
        print("canvases in overlay pane:", pg.evaluate("() => document.querySelectorAll('.leaflet-overlay-pane canvas').length"), "| EMO", "on" if EMO_ON else "off")
        for name, (lat, lon), z, text, kind in CASES:
            pg.evaluate(f"() => {{ window.__cyemMap.closePopup(); window.__cyemMap.setView([{lat}, {lon}], {z}, {{ animate: false }}); }}")
            pg.wait_for_timeout(6000)  # zoom-gated layers (Ofcom) reload on moveend
            cands = pg.evaluate(FIND, [text, kind])
            ok, why = False, "no feature in view"
            for cd in cands:
                pg.evaluate("() => window.__cyemMap.closePopup()")
                pg.mouse.click(cd["x"], cd["y"])
                pg.wait_for_timeout(700)
                pop = pg.evaluate("() => { const e = document.querySelector('.leaflet-popup-content'); return e ? e.textContent : null; }")
                if pop and (text.lower() in pop.lower() or kind == 'circle' and text == 'Ofcom WTR' and 'Ofcom' in pop):
                    ok = True; break
                why = f"click at ({cd['x']:.0f},{cd['y']:.0f}) hit {cd['hit']} -> popup: {(pop or 'none')[:50]!r}"
            print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{len(cands)} candidates; {why}]"))
            fails += 0 if ok else 1
        pg.screenshot(path="/out/layer_click.png")
        b.close()
    print("result:", "all pass" if not fails else f"{fails} failing")
    sys.exit(1 if fails else 0)

main()
