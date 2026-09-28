#!/usr/bin/env python3
"""Definitive software library for CyEM Monitor: writes docs/SOFTWARE.md and docs/software.json.
Run on the trade box from ~/cyem:  python3 tools/software_inventory.py
Reads the running container for exact package versions; falls back to requirements.txt if it is not up.
Line counts: blank lines and comment-only lines excluded; vendored JS and the generated static/app.js excluded."""
import datetime, json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

def sh(cmd, default=""):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60).stdout.strip() or default
    except Exception:
        return default

# ---------------------------------------------------------------- packages
pins = dict(re.findall(r"^([A-Za-z0-9_\[\]-]+)==([^\s]+)", open("requirements.txt").read(), re.M))
frozen = {}
for line in sh("docker exec cyem pip freeze 2>/dev/null").splitlines():
    if "==" in line:
        k, v = line.split("==", 1); frozen[k.lower()] = v
def ver(name):
    return frozen.get(name.lower().replace("[standard]", ""), pins.get(name, "?"))

PY_DIRECT = [  # (package, role)
    ("fastapi", "HTTP API and routing"), ("starlette", "ASGI toolkit under FastAPI (middleware, static files)"),
    ("uvicorn[standard]", "ASGI server"), ("pydantic", "request/response models and validation"),
    ("httpx", "HTTP client for collectors and Ollama"), ("feedparser", "RSS/Atom feed parsing"),
    ("h3", "hex binning for map layers"), ("python-dateutil", "date parsing"),
    ("sgp4", "satellite propagation from TLEs"), ("numpy", "coverage, EMO and score-map rasters"),
    ("rasterio", "Copernicus 30 m DSM tile reads"), ("python-docx", "Word exports (plan, EMO briefing, COA annex)"),
    ("pdfplumber", "UKFAT PDF parsing"), ("pillow", "PNG overlays"), ("python-multipart", "form uploads"),
]
py_rows = [(p, ver(p), role) for p, role in PY_DIRECT]
transitive = sorted((k, v) for k, v in frozen.items() if k not in {p.lower().replace("[standard]", "") for p, _ in PY_DIRECT})

# ---------------------------------------------------------------- front end, containers, hosts
def grep_first(path, pattern, default="?"):
    try:
        m = re.search(pattern, open(path, encoding="utf-8", errors="ignore").read(200000))
        return m.group(1) if m else default
    except Exception:
        return default
fe_rows = [
    ("Leaflet", grep_first("static/vendor/leaflet.js", r"Leaflet (\d+\.\d+\.\d+)"), "map (vendored static/vendor/leaflet.js + css)"),
    ("marked", grep_first("static/vendor/marked.umd.js", r"marked v(\d+\.\d+\.\d+)"), "Markdown rendering of briefs and answers (vendored)"),
    ("milsymbol", grep_first("static/vendor/milsymbol.js", r'version\s*[:=]\s*"(\d+\.\d+\.\d+)"', "3.0.4"), "APP-6 / MIL-STD-2525 symbols (vendored, MIT)"),
    ("Esri / CARTO / OSM tiles", "service", "basemaps by URL, no key"),
    ("Vanilla JS, no build step", "-", "static/src/*.js concatenated by static/build.sh into static/app.js"),
]
def img(name):
    return sh(f"docker inspect {name} --format '{{{{.Config.Image}}}}' 2>/dev/null", "?")
container_rows = [
    ("cyem", "cyem-monitor:latest (built from Dockerfile, python:3.12-slim, " + sh("docker exec cyem python -V 2>/dev/null", "Python 3.12") + ")", "the app; 127.0.0.1:3020 → 8080; 4 CPUs, 768 MB"),
    ("cyem-searxng", img("cyem-searxng"), "self-hosted web search for Ask AI (internal only)"),
    ("trading-bot-ollama-1", img("trading-bot-ollama-1") + " (" + sh("docker exec trading-bot-ollama-1 ollama --version 2>/dev/null | tail -1", "?").replace("ollama version is ", "ollama ") + ")", "local LLM, model " + (sh("grep -o 'OLLAMA_MODEL:-[^}]*' docker-compose.yml | head -1").split("-")[-1] or "qwen3.5:4b")),
    ("UI tests", "mcr.microsoft.com/playwright/python:v1.47.0-jammy (playwright 1.47.0)", "tests/ui/*.py, run on demand"),
]
host_rows = [
    ("Trade box", sh("lsb_release -ds 2>/dev/null", "Ubuntu") + ", kernel " + sh("uname -r"), "Docker " + sh("docker --version").replace("Docker version ", "").split(",")[0] + ", Compose " + sh("docker compose version").replace("Docker Compose version ", "") + ", Tailscale " + sh("tailscale version | head -1") + ", git " + sh("git --version").replace("git version ", "")),
]

# ---------------------------------------------------------------- lines of code
LANG = {".py": "Python", ".js": "JavaScript", ".css": "CSS", ".html": "HTML", ".sh": "Shell", ".yml": "YAML", ".yaml": "YAML",
        ".md": "Markdown", ".swift": "Swift", ".sql": "SQL", ".toml": "TOML", "Dockerfile": "Dockerfile"}
COMMENT = {"Python": "#", "Shell": "#", "YAML": "#", "Dockerfile": "#", "TOML": "#", "JavaScript": "//", "Swift": "//", "SQL": "--"}
SKIP_DIRS = {".git", "node_modules", "data-store", "data", "__pycache__", "out", "build", "build-ios", "ThirdParty", ".pytest_cache", "vendor", "CyEM.xcodeproj", "Assets.xcassets"}
SKIP_FILES = {"static/app.js"}

def count_tree(root, rel_prefix="", by_area=None):
    tot = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            path = os.path.join(dp, fn); rel = os.path.relpath(path, root)
            if rel in SKIP_FILES: continue
            ext = "Dockerfile" if fn == "Dockerfile" else os.path.splitext(fn)[1].lower()
            lang = LANG.get(ext)
            if not lang: continue
            try: lines = open(path, encoding="utf-8", errors="ignore").read().split("\n")
            except Exception: continue
            if lines and lines[-1] == "": lines = lines[:-1]
            c = COMMENT.get(lang)
            code = sum(1 for l in lines if l.strip() and not (c and l.strip().startswith(c)))
            t = tot.setdefault(lang, [0, 0, 0]); t[0] += 1; t[1] += len(lines); t[2] += code
            if by_area is not None:
                area = rel.split(os.sep)[0] if os.sep in rel else "(root)"
                a = by_area.setdefault((area, lang), [0, 0, 0]); a[0] += 1; a[1] += len(lines); a[2] += code
    return tot

def loc_table(tot):
    rows = sorted(tot.items(), key=lambda kv: -kv[1][2])
    out = [(lang, f"{n:,}", f"{total:,}", f"{code:,}") for lang, (n, total, code) in rows]
    out.append(("Total", f"{sum(v[0] for v in tot.values()):,}", f"{sum(v[1] for v in tot.values()):,}", f"{sum(v[2] for v in tot.values()):,}"))
    return out

areas = {}
loc_box = count_tree(ROOT, by_area=areas)
area_rows = [(f"{a}/ {l}", f"{n:,}", f"{t:,}", f"{c:,}") for (a, l), (n, t, c) in sorted(areas.items(), key=lambda kv: -kv[1][2]) if l in ("Python", "JavaScript", "CSS", "HTML", "Swift")]
app_dir = os.environ.get("CYEM_APP_DIR", "")
loc_app = count_tree(app_dir) if app_dir and os.path.isdir(app_dir) else None
if loc_app is None:
    try:
        loc_app = json.load(open("docs/software.json")).get("loc_app_raw")
    except Exception:
        loc_app = None

# ---------------------------------------------------------------- native apps and Pi (facts recorded from the machines; keep in step by hand or via env)
native_rows = json.loads(os.environ.get("CYEM_NATIVE_JSON", "null")) or (json.load(open("docs/software.json")).get("native") if os.path.exists("docs/software.json") else None) or []
pi_rows = json.loads(os.environ.get("CYEM_PI_JSON", "null")) or (json.load(open("docs/software.json")).get("pi") if os.path.exists("docs/software.json") else None) or []

# ---------------------------------------------------------------- write
today = datetime.date.today().isoformat()
def md_table(header, rows):
    w = lambda r: "| " + " | ".join(str(x).replace("|", "\\|") for x in r) + " |"
    return "\n".join([w(header), "|" + "|".join("---" for _ in header) + "|"] + [w(r) for r in rows])

md = [f"# CyEM Monitor: software library\n",
      f"Generated {today} by `tools/software_inventory.py` from the running box. Re-run after any dependency change; "
      "the nightly trade runbook (`~/bin/runbook_gen.py`) copies these tables from `docs/software.json`.\n",
      "## Application (container `cyem`)\n", md_table(["Package", "Version", "Role"], py_rows),
      f"\nTransitive packages in the image: {len(transitive)} (" + ", ".join(f"{k} {v}" for k, v in transitive) + ").\n",
      "## Front end\n", md_table(["Library", "Version", "Role"], fe_rows),
      "\n## Containers and services\n", md_table(["Container", "Image / version", "Role"], container_rows),
      "\n## Hosts\n", md_table(["Host", "OS", "Tooling"], host_rows + pi_rows),
      "\n## Native apps (Mac and iPhone, source `~/Documents/Codex/CyEM/cyem-app` on the Mac)\n", md_table(["Component", "Version", "Role"], native_rows),
      "\n## Lines of code\n", "Blank and comment-only lines excluded; vendored libraries, the generated `static/app.js`, build output and libtailscale excluded.\n",
      "\n**CyEM Monitor (this repository)**\n", md_table(["Language", "Files", "Lines", "Code lines"], loc_table(loc_box)),
      "\n**By area (application code only)**\n", md_table(["Area", "Files", "Lines", "Code lines"], area_rows)]
if loc_app:
    md += ["\n**Native apps (`~/Documents/Codex/CyEM/cyem-app`)**\n", md_table(["Language", "Files", "Lines", "Code lines"], loc_table(loc_app))]
open("docs/SOFTWARE.md", "w").write("\n".join(md) + "\n")
json.dump({"generated": today, "python": py_rows, "transitive": transitive, "frontend": fe_rows, "containers": container_rows,
           "hosts": host_rows, "pi": pi_rows, "native": native_rows, "loc_box": loc_table(loc_box),
           "loc_app": loc_table(loc_app) if loc_app else [], "loc_app_raw": loc_app, "loc_areas": area_rows}, open("docs/software.json", "w"), indent=1)
print("wrote docs/SOFTWARE.md and docs/software.json")
for lang, (n, total, code) in sorted(loc_box.items(), key=lambda kv: -kv[1][2]):
    print(f"{lang:12s} {n:4d} files {total:8,d} lines {code:8,d} code")
