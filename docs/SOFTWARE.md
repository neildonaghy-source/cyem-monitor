# CyEM Monitor: software library

Generated 2026-09-26 by `tools/software_inventory.py` from the running box. Re-run after any dependency change; the nightly trade runbook (`~/bin/runbook_gen.py`) copies these tables from `docs/software.json`.

## Application (container `cyem`)

| Package | Version | Role |
|---|---|---|
| fastapi | 0.141.1 | HTTP API and routing |
| starlette | 1.7.0 | ASGI toolkit under FastAPI (middleware, static files) |
| uvicorn[standard] | 0.54.0 | ASGI server |
| pydantic | 2.13.5 | request/response models and validation |
| httpx | 0.28.1 | HTTP client for collectors and Ollama |
| feedparser | 6.0.14 | RSS/Atom feed parsing |
| h3 | 4.5.0 | hex binning for map layers |
| python-dateutil | 2.9.0.post0 | date parsing |
| sgp4 | 2.27 | satellite propagation from TLEs |
| numpy | 2.5.3 | coverage, EMO and score-map rasters |
| rasterio | 1.5.1 | Copernicus 30 m DSM tile reads |
| python-docx | 1.2.0 | Word exports (plan, EMO briefing, COA annex) |
| pdfplumber | 0.11.10 | UKFAT PDF parsing |
| pillow | 12.3.0 | PNG overlays |
| python-multipart | 0.0.32 | form uploads |

Transitive packages in the image: 29 (affine 3.0.1, annotated-doc 0.0.5, annotated-types 0.8.0, anyio 4.15.1, attrs 26.1.0, certifi 2026.7.22, cffi 2.1.1, charset-normalizer 3.5.1, click 8.5.0, cryptography 50.0.1, feedparser-sgmllib 2.1.0, h11 0.16.0, httpcore 1.0.9, httptools 0.8.0, idna 3.20, lxml 6.1.3, pdfminer.six 20260107, pycparser 3.0, pydantic_core 2.46.5, pyparsing 3.3.3, pypdfium2 5.13.0, python-dotenv 1.2.3, pyyaml 6.0.3, six 1.17.0, typing-inspection 0.4.4, typing_extensions 4.16.0, uvloop 0.22.1, watchfiles 1.3.0, websockets 17.1).

## Front end

| Library | Version | Role |
|---|---|---|
| Leaflet | 1.9.4 | map (vendored static/vendor/leaflet.js + css) |
| marked | 15.0.12 | Markdown rendering of briefs and answers (vendored) |
| milsymbol | 3.0.4 | APP-6 / MIL-STD-2525 symbols (vendored, MIT) |
| Esri / CARTO / OSM tiles | service | basemaps by URL, no key |
| Vanilla JS, no build step | - | static/src/*.js concatenated by static/build.sh into static/app.js |

## Containers and services

| Container | Image / version | Role |
|---|---|---|
| cyem | cyem-monitor:latest (built from Dockerfile, python:3.12-slim, Python 3.12.14) | the app; 127.0.0.1:3020 → 8080; 4 CPUs, 768 MB |
| cyem-searxng | searxng/searxng:latest | self-hosted web search for Ask AI (internal only) |
| trading-bot-ollama-1 | ollama/ollama:latest (ollama 0.34.4) | local LLM, model qwen3.5:4b |
| UI tests | mcr.microsoft.com/playwright/python:v1.47.0-jammy (playwright 1.47.0) | tests/ui/*.py, run on demand |

## Hosts

| Host | OS | Tooling |
|---|---|---|
| Trade box | Ubuntu 26.04.1 LTS, kernel 7.0.0-34-generic | Docker 29.8.1, Compose v5.5.1, Tailscale 1.102.4, git 2.53.0 |
| Pi 5 node cyem-sdr (100.77.35.64) | Raspberry Pi OS Lite (Debian 13 trixie), kernel 6.18.50+rpt-rpi-2712, Python 3.13.5 | Docker 29.8.1, Tailscale 1.102.4 (Tailscale SSH), OpenWebRX+ 1.2.125 (slechev/openwebrxplus:latest), librtlsdr (rtl-sdr-blog fork, built from source), pi/cyem_sweep.py (stdlib only) as systemd unit cyem-sweep |

## Native apps (Mac and iPhone, source `~/cyem-app` on the Mac)

| Component | Version | Role |
|---|---|---|
| Swift / SwiftUI / WebKit (WKWebView) | Swift 6.4, Xcode 27.0 (27A266a) on macOS 27.2 | app shell, dashboard web view, AR view (ARKit, CoreLocation), Keychain |
| TailscaleKit (libtailscale) | libtailscale 59d4bb8 (2026-08-31), tailscale.com v1.94.1, built with Go 1.27.1 (GOEXPERIMENT=nojsonv2) | embedded userspace tailnet node; devices cyem-mac, cyem-iphone |
| xcodegen | 2.46.0 | generates CyEM.xcodeproj from project.yml |
| Deployment targets | macOS 15.6, iOS 18.1 | free personal team signing; iPhone build lasts 7 days |

## Lines of code

Blank and comment-only lines excluded; vendored libraries, the generated `static/app.js`, build output and libtailscale excluded.


**CyEM Monitor (this repository)**

| Language | Files | Lines | Code lines |
|---|---|---|---|
| Python | 65 | 11,091 | 9,441 |
| JavaScript | 23 | 2,310 | 2,269 |
| Markdown | 6 | 616 | 501 |
| CSS | 1 | 352 | 327 |
| HTML | 1 | 105 | 99 |
| YAML | 2 | 77 | 69 |
| Shell | 3 | 86 | 69 |
| Dockerfile | 1 | 14 | 14 |
| Total | 102 | 14,651 | 12,789 |

**By area (application code only)**

| Area | Files | Lines | Code lines |
|---|---|---|---|
| app/ Python | 52 | 10,164 | 8,696 |
| static/ JavaScript | 23 | 2,310 | 2,269 |
| tests/ Python | 11 | 688 | 541 |
| static/ CSS | 1 | 352 | 327 |
| tools/ Python | 1 | 139 | 121 |
| static/ HTML | 1 | 105 | 99 |
| pi/ Python | 1 | 100 | 83 |

**Native apps (`~/cyem-app`)**

| Language | Files | Lines | Code lines |
|---|---|---|---|
| Swift | 6 | 859 | 765 |
| YAML | 1 | 67 | 64 |
| Python | 1 | 54 | 46 |
| Shell | 1 | 40 | 29 |
| Markdown | 1 | 40 | 27 |
| Total | 10 | 1,060 | 931 |
