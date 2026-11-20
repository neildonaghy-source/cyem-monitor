#!/usr/bin/env python3
"""Build the CyEM app icon: SVG sources and every PNG the native apps and the web client use.

Run from the repository root:  python3 native/Icon/build_icons.py [--sheet out.png]
Needs rsvg-convert (librsvg), Pillow and fontTools, plus Inter Bold for the wordmark (it is converted to
outlines here, so the SVGs carry no font dependency). Writes:
  native/Icon/cyem-icon.svg          full-bleed 1024 source (iOS; web 192/512/apple-touch)
  native/Icon/cyem-icon-mac.svg      macOS rounded square with the standard margin
  native/Icon/cyem-icon-small.svg    simplified mark without the wordmark (16-64 px)
  native/Shared/Assets.xcassets/AppIcon.appiconset/*   macOS set + iOS 1024 + Contents.json
  static/icons/*                     favicon.svg/.ico, favicon-32, apple-touch-icon, icon-192/512, maskable-512
Colours follow static/style.css :root (--bg #0a0e13, --panel #10161e, --cyan #3cc7ff, --amber #f3b23e, --text #d8e0ea).
"""
import io
import json
import subprocess
import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ICON = ROOT / "native/Icon"
APPICON = ROOT / "native/Shared/Assets.xcassets/AppIcon.appiconset"
WEB = ROOT / "static/icons"
FONT = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"

BG_TOP, BG_BOT = "#152131", "#0a0e13"
CYAN, AMBER, TEXT, GRID = "#3cc7ff", "#f3b23e", "#d8e0ea", "#3cc7ff"


def wordmark(text, size, cx, baseline, tracking=-0.01):
    """Outline `text` in Inter Bold, centred on cx; returns (svg path data per glyph, width)."""
    font = TTFont(FONT)
    gs, cmap = font.getGlyphSet(), font.getBestCmap()
    upm = font["head"].unitsPerEm
    scale = size / upm
    names = [cmap[ord(c)] for c in text]
    advs = [font["hmtx"][n][0] + tracking * upm for n in names]
    width = (sum(advs) - tracking * upm) * scale
    x = cx - width / 2
    out = []
    for n, adv in zip(names, advs):
        pen = SVGPathPen(gs)
        gs[n].draw(TransformPen(pen, (scale, 0, 0, -scale, x, baseline)))
        out.append(pen.getCommands())
        x += adv * scale
    return out, width


def defs(uid):
    return f"""<defs>
  <linearGradient id="bg{uid}" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{BG_TOP}"/><stop offset="1" stop-color="{BG_BOT}"/>
  </linearGradient>
  <radialGradient id="glow{uid}" cx="512" cy="430" r="380" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="{CYAN}" stop-opacity="0.22"/><stop offset="1" stop-color="{CYAN}" stop-opacity="0"/>
  </radialGradient>
</defs>"""


def arc(cx, cy, r, a0=-150, a1=-30):
    import math
    p0 = (cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0)))
    p1 = (cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1)))
    return f"M{p0[0]:.1f} {p0[1]:.1f} A{r} {r} 0 0 1 {p1[0]:.1f} {p1[1]:.1f}"


# Spectrum trace: noise floor with a central carrier and two weaker signals; peak tip is the emitter.
EM_X, EM_Y = 512, 432


def trace(y0=596, x0=150, x1=874):
    pts = [(x0, y0), (196, y0 - 6), (232, y0 + 2), (262, y0 - 10), (286, y0 - 58), (308, y0 - 4), (346, y0 - 12),
           (384, y0 + 2), (420, y0 - 14), (452, y0 - 26), (480, y0 - 70), (EM_X, EM_Y + 30), (544, y0 - 70),
           (572, y0 - 26), (604, y0 - 14), (640, y0 + 2), (676, y0 - 8), (708, y0 - 22), (734, y0 - 96),
           (760, y0 - 20), (792, y0 - 4), (830, y0 - 10), (x1, y0)]
    return "M" + " L".join(f"{x} {y}" for x, y in pts)


def artwork(uid, text=True):
    """Full-bleed 1024 artwork group (no outer shape)."""
    grid = "".join(f'<path d="M{v} 0V1024M0 {v}H1024"/>' for v in range(64, 1024, 64))
    # Emission rings: solid near the source, broken (packetised) further out so the motif reads as cyber + EM.
    arcs = "".join(
        f'<path d="{arc(EM_X, EM_Y, r, -166, -14)}" stroke-opacity="{o}"{dash}/>'
        for r, o, dash in ((96, 1.0, ""), (172, 0.8, ""), (248, 0.6, ' stroke-dasharray="58 30"'),
                           (324, 0.38, ' stroke-dasharray="26 34"')))
    g = [f'<rect width="1024" height="1024" fill="url(#bg{uid})"/>',
         f'<g stroke="{GRID}" stroke-opacity="0.07" stroke-width="2" fill="none">{grid}</g>',
         f'<rect width="1024" height="1024" fill="url(#glow{uid})"/>',
         f'<g stroke="{CYAN}" stroke-width="22" stroke-linecap="round" fill="none">{arcs}</g>',
         f'<path d="M150 {596 + 1}H874" stroke="{TEXT}" stroke-opacity="0.18" stroke-width="4"/>',
         f'<path d="{trace()}" stroke="{AMBER}" stroke-width="12" stroke-linejoin="round" stroke-linecap="round" fill="none"/>',
         f'<circle cx="{EM_X}" cy="{EM_Y}" r="30" fill="{TEXT}"/>',
         f'<circle cx="{EM_X}" cy="{EM_Y}" r="30" fill="none" stroke="{CYAN}" stroke-width="10"/>']
    if text:
        glyphs, _ = wordmark("CyEM", 236, 512, 852)
        g.append(f'<path d="{glyphs[0]} {glyphs[1]}" fill="{CYAN}"/>')
        g.append(f'<path d="{glyphs[2]} {glyphs[3]}" fill="{TEXT}"/>')
    return "\n".join(g)


def small_artwork(uid):
    """Simplified mark for 16-64 px: emitter, two heavy arcs, single peak trace. 1024 units."""
    arcs = "".join(f'<path d="{arc(512, 560, r, -168, -12)}" stroke-opacity="{o}"/>'
                   for r, o in ((190, 1.0), (340, 0.7)))
    return "\n".join([
        f'<rect width="1024" height="1024" fill="url(#bg{uid})"/>',
        f'<g stroke="{CYAN}" stroke-width="80" stroke-linecap="round" fill="none">{arcs}</g>',
        f'<path d="M150 800 L380 800 L512 600 L644 800 L874 800" stroke="{AMBER}" stroke-width="72" '
        f'stroke-linejoin="round" stroke-linecap="round" fill="none"/>',
        f'<circle cx="512" cy="560" r="84" fill="{TEXT}"/>'])


def svg(body, uid, size=1024):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 1024 1024">\n'
            f'{defs(uid)}\n{body}\n</svg>\n')


def mac_wrap(inner, uid):
    """Apple macOS grid: 824 body centred on 1024 with radius ~185 and a soft drop shadow."""
    return f"""<defs>
  <clipPath id="sq{uid}"><rect x="100" y="100" width="824" height="824" rx="185"/></clipPath>
  <filter id="sh{uid}" x="-20%" y="-20%" width="140%" height="140%">
    <feGaussianBlur in="SourceAlpha" stdDeviation="14"/><feOffset dy="10"/>
    <feComponentTransfer><feFuncA type="linear" slope="0.45"/></feComponentTransfer>
    <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
</defs>
<g filter="url(#sh{uid})"><g clip-path="url(#sq{uid})">
<g transform="translate(100 100) scale({824 / 1024})">
{inner}
</g>
<rect x="100" y="100" width="824" height="824" rx="185" fill="none" stroke="#ffffff" stroke-opacity="0.08" stroke-width="4"/>
</g></g>"""


def rounded(inner, uid, rx=180):
    return (f'<defs><clipPath id="rr{uid}"><rect width="1024" height="1024" rx="{rx}"/></clipPath></defs>'
            f'<g clip-path="url(#rr{uid})">{inner}</g>')


def maskable(uid):
    """Full-bleed background, content inside the 80% safe circle."""
    return (f'<rect width="1024" height="1024" fill="url(#bg{uid})"/>'
            f'<g transform="translate(512 512) scale(0.72) translate(-512 -512)">{artwork(uid)}</g>')


def render(svg_text, size, out):
    png = subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size)], input=svg_text.encode(),
                         capture_output=True, check=True).stdout
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png)
    if size >= 128:
        dither(out)
    return out


def dither(path):
    """Add +-1 level of noise so the dark gradients do not band in 8-bit."""
    import numpy as np
    im = Image.open(path).convert("RGBA")
    a = np.asarray(im).astype(np.int16)
    rng = np.random.default_rng(1)
    a[..., :3] += rng.integers(-1, 2, size=a.shape[:2] + (1,), dtype=np.int16)
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA").save(path)


def flatten(path):
    """iOS marketing icon: opaque RGB, no alpha channel."""
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGB", im.size, BG_BOT)
    bg.paste(im, mask=im.split()[3])
    bg.save(path)


def main():
    full = svg(artwork("f"), "f")
    mac = svg(mac_wrap(artwork("m"), "m"), "m")
    small = svg(small_artwork("s"), "s")
    mac_small = svg(mac_wrap(small_artwork("ms"), "ms"), "ms")
    fav = svg(rounded(small_artwork("v"), "v", rx=220), "v", size=32)
    mask = svg(maskable("k"), "k")
    for name, text in (("cyem-icon.svg", full), ("cyem-icon-mac.svg", mac), ("cyem-icon-small.svg", small),
                       ("cyem-icon-mac-small.svg", mac_small), ("cyem-icon-maskable.svg", mask)):
        (ICON / name).write_text(text)

    # macOS AppIcon (simplified mark up to 64 px, full artwork from 128 px) and iOS 1024.
    images = []
    for pt in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = pt * scale
            fname = f"mac-{pt}@{scale}x.png"
            render(mac_small if px <= 64 else mac, px, APPICON / fname)
            images.append({"filename": fname, "idiom": "mac", "scale": f"{scale}x", "size": f"{pt}x{pt}"})
    ios = render(full, 1024, APPICON / "ios-1024.png")
    flatten(ios)
    images.insert(0, {"filename": "ios-1024.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"})
    (APPICON / "Contents.json").write_text(json.dumps({"images": images, "info": {"author": "xcode", "version": 1}},
                                                      indent=2) + "\n")
    (APPICON.parent / "Contents.json").write_text(json.dumps({"info": {"author": "xcode", "version": 1}}, indent=2) + "\n")

    # Web client.
    (WEB / "favicon.svg").write_text(fav)
    render(fav, 32, WEB / "favicon-32.png")
    for size, name in ((180, "apple-touch-icon.png"), (192, "icon-192.png"), (512, "icon-512.png")):
        render(full, size, WEB / name)
        flatten(WEB / name)
    render(mask, 512, WEB / "maskable-512.png")
    flatten(WEB / "maskable-512.png")
    frames = [Image.open(io.BytesIO(subprocess.run(["rsvg-convert", "-w", str(s), "-h", str(s)], input=fav.encode(),
                                                   capture_output=True, check=True).stdout)) for s in (16, 32, 48)]
    frames[2].save(WEB / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)], append_images=frames[:2])

    if "--sheet" in sys.argv:
        contact_sheet(Path(sys.argv[sys.argv.index("--sheet") + 1]))


def contact_sheet(out):
    from PIL import ImageDraw
    tiles = [(APPICON / f"mac-{pt}@{s}x.png", f"mac {pt}@{s}x") for pt in (16, 32, 128, 256, 512) for s in (1, 2)]
    tiles += [(APPICON / "ios-1024.png", "iOS 1024"), (WEB / "favicon-32.png", "favicon 32"),
              (WEB / "apple-touch-icon.png", "apple-touch 180"), (WEB / "icon-192.png", "web 192"),
              (WEB / "icon-512.png", "web 512"), (WEB / "maskable-512.png", "maskable 512")]
    cell, cols = 300, 4
    rows = (len(tiles) + cols - 1) // cols + 1
    sheet = Image.new("RGB", (cell * cols, cell * rows), "#2a2f36")
    d = ImageDraw.Draw(sheet)
    for i, (p, label) in enumerate(tiles):
        im = Image.open(p).convert("RGBA")
        if im.width > 256:
            im = im.resize((256, 256), Image.LANCZOS)
        x, y = (i % cols) * cell, (i // cols) * cell
        sheet.paste(im, (x + (cell - im.width) // 2, y + (cell - 24 - im.width) // 2), im)
        d.text((x + 8, y + cell - 20), f"{label} ({Image.open(p).width}px)", fill="#d8e0ea")
    # Actual-size strip on light and dark, plus the maskable safe circle.
    y = (rows - 1) * cell
    d.rectangle((0, y, cell * cols // 2, y + cell), fill="#f2f2f2")
    x = 10
    for p in [APPICON / "mac-16@1x.png", APPICON / "mac-32@1x.png", WEB / "favicon-32.png", APPICON / "mac-32@2x.png",
              APPICON / "mac-128@1x.png"]:
        im = Image.open(p).convert("RGBA")
        sheet.paste(im, (x, y + 60), im)
        sheet.paste(im, (x + cell * cols // 2, y + 60), im)
        x += im.width + 14
    d.text((10, y + 10), "actual size on light", fill="#222")
    d.text((cell * cols // 2 + 10, y + 10), "actual size on dark", fill="#d8e0ea")
    m = Image.open(WEB / "maskable-512.png").convert("RGBA").resize((200, 200), Image.LANCZOS)
    mk = Image.new("L", (200, 200), 0)
    ImageDraw.Draw(mk).ellipse((20, 20, 180, 180), fill=255)
    sheet.paste(m, (cell * cols - 220, y + 60), mk)
    d.text((cell * cols - 220, y + 270), "maskable, 80% circle", fill="#d8e0ea")
    sheet.save(out)
    print(out)


if __name__ == "__main__":
    main()
