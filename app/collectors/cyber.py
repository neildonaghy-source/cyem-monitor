"""Cyber collectors: CISA KEV, NVD critical CVEs + EPSS, ransomware.live victims,
HIBP breaches, Feodo Tracker C2 infrastructure, ThreatFox (optional key)."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from .. import geo
from ..config import settings
from ..db import iso
from ..tagging import enrich, strip_html
from .base import Context, Result, get_json, item_id, parse_dt, register

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
EPSS_URL = "https://api.first.org/data/v1/epss"
RANSOMWARE_URLS = ["https://api.ransomware.live/v2/recentvictims", "https://api.ransomware.live/recentvictims"]
HIBP_URL = "https://haveibeenpwned.com/api/v3/breaches"
FEODO_URL = "https://feodotracker.abuse.ch/downloads/ipblocklist.json"
THREATFOX_URL = "https://threatfox-api.abuse.ch/api/v1/"


def _days_ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


# ---- CISA KEV ---------------------------------------------------------------
@register("kev", interval_s=60 * 60, domain="cyber", description="CISA Known Exploited Vulnerabilities catalogue")
async def collect_kev(ctx: Context) -> Result:
    data = await get_json(ctx, KEV_URL)
    vulns = data.get("vulnerabilities", [])
    cutoff = _days_ago(45).date().isoformat()
    items = []
    vendors_30d: Counter = Counter()
    added_7d = added_30d = 0
    d7 = _days_ago(7).date().isoformat()
    d30 = _days_ago(30).date().isoformat()
    for v in vulns:
        added = v.get("dateAdded", "")
        if added >= d30:
            added_30d += 1
            vendors_30d[v.get("vendorProject", "?")] += 1
        if added >= d7:
            added_7d += 1
        if added < cutoff:
            continue
        cve = v.get("cveID", "")
        ransom = (v.get("knownRansomwareCampaignUse") or "").lower() == "known"
        title = f"KEV: {cve} — {v.get('vendorProject', '')} {v.get('product', '')}".strip()
        summary = strip_html(f"{v.get('vulnerabilityName', '')}. {v.get('shortDescription', '')} "
                             f"Required action: {v.get('requiredAction', '')} Due {v.get('dueDate', '')}.", 900)
        item = {
            "id": item_id("kev", cve),
            "source": "CISA KEV", "domain": "cyber", "kind": "kev",
            "title": title, "url": f"https://nvd.nist.gov/vuln/detail/{cve}",
            "summary": summary, "published_at": parse_dt(added),
            "severity": 5 if ransom else 4,
            "extra": {"cve": cve, "vendor": v.get("vendorProject"), "product": v.get("product"),
                      "due": v.get("dueDate"), "ransomware": ransom, "cwes": v.get("cwes")},
        }
        enrich(item, base_tags=["kev", "vuln"] + (["ransomware"] if ransom else []), default_severity=4)
        item["country"] = None  # vendor names are not locations
        item["lat"] = item["lon"] = None
        items.append(item)
    new = ctx.db.upsert_items(items)
    ctx.db.set_snapshot("kev_stats", {
        "total": len(vulns), "added_7d": added_7d, "added_30d": added_30d,
        "top_vendors_30d": vendors_30d.most_common(8),
        "catalog_version": data.get("catalogVersion"), "date_released": data.get("dateReleased"),
    })
    return Result(new, f"{new} new; {added_7d} added in 7d, {added_30d} in 30d, catalogue {len(vulns)}")


# ---- NVD critical CVEs + EPSS ----------------------------------------------
@register("nvd", interval_s=2 * 60 * 60, domain="cyber", description="NVD CVEs rated CRITICAL in the last 7 days, scored with EPSS")
async def collect_nvd(ctx: Context) -> Result:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    fmt = "%Y-%m-%dT%H:%M:%S.000"
    headers = {"apiKey": settings.nvd_api_key} if settings.nvd_api_key else {}
    params = {"pubStartDate": start.strftime(fmt), "pubEndDate": end.strftime(fmt),
              "cvssV3Severity": "CRITICAL", "resultsPerPage": 200}
    r = await ctx.http.get(NVD_URL, params=params, headers=headers, timeout=90)
    if r.status_code in (403, 503):
        return Result(0, f"NVD unavailable (HTTP {r.status_code}); will retry")
    r.raise_for_status()
    data = r.json()
    cves = []
    for row in data.get("vulnerabilities", []):
        c = row.get("cve", {})
        cve_id = c.get("id")
        if not cve_id:
            continue
        desc = next((d.get("value") for d in c.get("descriptions", []) if d.get("lang") == "en"), "")
        metrics = c.get("metrics", {})
        score = None
        vector = None
        for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30"):
            if metrics.get(key):
                cd = metrics[key][0].get("cvssData", {})
                score, vector = cd.get("baseScore"), cd.get("vectorString")
                break
        cves.append({"id": cve_id, "desc": desc, "score": score, "vector": vector,
                     "published": c.get("published"), "status": c.get("vulnStatus")})
    # EPSS in batches of 100
    epss: dict[str, float] = {}
    for i in range(0, len(cves), 100):
        batch = ",".join(c["id"] for c in cves[i:i + 100])
        try:
            ej = await get_json(ctx, EPSS_URL, params={"cve": batch})
            for d in ej.get("data", []):
                epss[d["cve"]] = float(d.get("epss", 0))
        except Exception:  # noqa: BLE001 - EPSS is enrichment only
            pass
    items = []
    for c in cves:
        e = epss.get(c["id"])
        sev = 4 if (c["score"] or 0) >= 9.0 else 3
        if e is not None and e >= 0.5:
            sev = 5
        elif e is not None and e >= 0.1:
            sev = max(sev, 4)
        title = f"{c['id']} CVSS {c['score'] if c['score'] is not None else '?'}"
        if e is not None:
            title += f" EPSS {e:.2f}"
        item = {
            "id": item_id("cve", c["id"]),
            "source": "NVD", "domain": "cyber", "kind": "cve",
            "title": title, "url": f"https://nvd.nist.gov/vuln/detail/{c['id']}",
            "summary": strip_html(c["desc"], 700), "published_at": parse_dt(c["published"]),
            "severity": sev,
            "extra": {"cve": c["id"], "cvss": c["score"], "vector": c["vector"], "epss": e, "status": c["status"]},
        }
        enrich(item, base_tags=["vuln", "cve"], default_severity=sev)
        item["country"] = None
        item["lat"] = item["lon"] = None
        items.append(item)
    new = ctx.db.upsert_items(items)
    return Result(new, f"{new} new of {len(cves)} critical CVEs in 7d; EPSS for {len(epss)}")


# ---- ransomware.live -------------------------------------------------------
@register("ransomware", interval_s=60 * 60, domain="cyber", description="ransomware.live: recently claimed victims by group and country")
async def collect_ransomware(ctx: Context) -> Result:
    data = None
    last_err = ""
    for url in RANSOMWARE_URLS:
        try:
            data = await get_json(ctx, url)
            break
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
    if data is None:
        raise RuntimeError(f"ransomware.live unreachable: {last_err}")
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise RuntimeError("unexpected ransomware.live payload")
    items = []
    for d in rows:
        victim = d.get("victim") or d.get("post_title") or "Unnamed victim"
        group = d.get("group") or d.get("group_name") or "unknown"
        date = d.get("discovered") or d.get("published") or d.get("attackdate")
        iso2 = geo.resolve(d.get("country"))
        sector = d.get("activity") or d.get("sector") or ""
        desc = strip_html(d.get("description") or "", 400)
        url = d.get("url") or d.get("claim_url") or d.get("website") or "https://www.ransomware.live/"
        if url and not url.startswith("http"):
            url = "https://" + url
        summary = f"Claimed by {group}." + (f" Sector: {sector}." if sector else "") + (f" {desc}" if desc else "")
        item = {
            "id": item_id("ransomware", group, victim, (date or "")[:10]),
            "source": "ransomware.live", "domain": "cyber", "kind": "ransomware",
            "title": f"{group} → {victim}", "url": url, "summary": summary,
            "published_at": parse_dt(date), "country": iso2, "severity": 3,
            "extra": {"group": group, "victim": victim, "sector": sector, "country_raw": d.get("country")},
        }
        enrich(item, base_tags=["ransomware"], default_severity=3)
        item["country"] = iso2 or item.get("country")
        if item["country"]:
            c = geo.centroid(item["country"])
            if c:
                item["lat"], item["lon"] = c
        items.append(item)
    new = ctx.db.upsert_items(items)
    # stats from DB history (30d)
    by_country = ctx.db.group_count("country", kind="ransomware", since_hours=24 * 30, limit=40)
    groups = Counter()
    for it in ctx.db.list_items(kind="ransomware", since_hours=24 * 30, limit=2000):
        groups[it.get("extra", {}).get("group", "unknown")] += 1
    ctx.db.set_snapshot("ransomware_stats", {
        "victims_7d": ctx.db.count_items(kind="ransomware", since_hours=24 * 7),
        "victims_30d": ctx.db.count_items(kind="ransomware", since_hours=24 * 30),
        "by_country_30d": by_country, "top_groups_30d": groups.most_common(12),
    })
    return Result(new, f"{new} new victims of {len(rows)} listed")


# ---- Have I Been Pwned breaches ---------------------------------------------
@register("hibp", interval_s=6 * 60 * 60, domain="cyber", description="Have I Been Pwned: breaches added in the last 60 days")
async def collect_hibp(ctx: Context) -> Result:
    data = await get_json(ctx, HIBP_URL, headers={"User-Agent": settings.user_agent})
    cutoff = _days_ago(60).date().isoformat()
    items = []
    for b in data:
        added = (b.get("AddedDate") or "")[:10]
        if added < cutoff:
            continue
        pwn = int(b.get("PwnCount") or 0)
        sev = 4 if pwn >= 10_000_000 else 3 if pwn >= 1_000_000 else 2
        classes = ", ".join(b.get("DataClasses") or [])
        item = {
            "id": item_id("hibp", b.get("Name")),
            "source": "Have I Been Pwned", "domain": "cyber", "kind": "breach",
            "title": f"Breach: {b.get('Title') or b.get('Name')} ({pwn:,} accounts)",
            "url": f"https://haveibeenpwned.com/Breach/{b.get('Name')}",
            "summary": strip_html(b.get("Description") or "", 500) + (f" Data: {classes}." if classes else ""),
            "published_at": parse_dt(b.get("AddedDate")), "severity": sev,
            "extra": {"breach_date": b.get("BreachDate"), "pwn_count": pwn, "domain": b.get("Domain"),
                      "verified": b.get("IsVerified"), "data_classes": b.get("DataClasses")},
        }
        enrich(item, base_tags=["breach"], default_severity=sev)
        items.append(item)
    new = ctx.db.upsert_items(items)
    return Result(new, f"{new} new of {len(items)} breaches in 60d")


# ---- Feodo Tracker C2 -------------------------------------------------------
@register("c2", interval_s=60 * 60, domain="cyber", description="abuse.ch Feodo Tracker: active botnet C2 servers by country")
async def collect_c2(ctx: Context) -> Result:
    data = await get_json(ctx, FEODO_URL)
    if not isinstance(data, list):
        raise RuntimeError("unexpected Feodo payload")
    by_country: dict[str, dict] = defaultdict(lambda: {"count": 0, "online": 0, "malware": Counter()})
    families: Counter = Counter()
    recent = []
    cutoff = iso(_days_ago(7))
    for e in data:
        iso2 = geo.resolve(e.get("country"))
        if not iso2:
            continue
        fam = e.get("malware") or "unknown"
        entry = by_country[iso2]
        entry["count"] += 1
        entry["online"] += 1 if (e.get("status") or "").lower() == "online" else 0
        entry["malware"][fam] += 1
        families[fam] += 1
        fs = parse_dt(e.get("first_seen"), default_now=False)
        if fs and fs >= cutoff:
            recent.append({"ip": e.get("ip_address"), "port": e.get("port"), "malware": fam, "country": iso2,
                           "as_name": e.get("as_name"), "first_seen": fs, "status": e.get("status")})
    points = []
    for iso2, entry in by_country.items():
        c = geo.centroid(iso2)
        if not c:
            continue
        points.append({"country": iso2, "name": geo.name_of(iso2), "lat": c[0], "lon": c[1],
                       "count": entry["count"], "online": entry["online"],
                       "malware": entry["malware"].most_common(5)})
    points.sort(key=lambda p: -p["count"])
    ctx.db.set_snapshot("c2", {"total": len(data), "families": families.most_common(10), "countries": points,
                               "recent_7d": sorted(recent, key=lambda r: r["first_seen"], reverse=True)[:100]})
    return Result(len(points), f"{len(data)} C2 entries across {len(points)} countries; {len(recent)} new in 7d")


# ---- ThreatFox (optional Auth-Key) ------------------------------------------
@register("threatfox", interval_s=3 * 60 * 60, domain="cyber", description="abuse.ch ThreatFox IOCs (needs ABUSECH_AUTH_KEY)",
          enabled=lambda: bool(settings.abusech_auth_key))
async def collect_threatfox(ctx: Context) -> Result:
    r = await ctx.http.post(THREATFOX_URL, json={"query": "get_iocs", "days": 1},
                            headers={"Auth-Key": settings.abusech_auth_key})
    r.raise_for_status()
    data = r.json().get("data") or []
    fam: Counter = Counter()
    types: Counter = Counter()
    for d in data:
        fam[d.get("malware_printable") or d.get("malware") or "unknown"] += 1
        types[d.get("ioc_type") or "?"] += 1
    ctx.db.set_snapshot("threatfox", {"iocs_24h": len(data), "families": fam.most_common(12), "types": types.most_common(8)})
    return Result(len(data), f"{len(data)} IOCs in 24h")
