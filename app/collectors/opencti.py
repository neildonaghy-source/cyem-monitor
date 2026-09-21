"""OpenCTI (Filigran) integration — optional, needs OPENCTI_URL and OPENCTI_TOKEN.

Pulls recent Reports (as feed items), recent Indicators and recently modified
Intrusion Sets (as a snapshot for the OpenCTI panel and the brief). Queries are
written against the OpenCTI 6.x GraphQL schema and each one is tolerated
independently, so a schema difference degrades one section rather than the
whole collector."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from ..config import settings
from ..db import iso
from ..tagging import enrich, strip_html
from .base import Context, Result, item_id, parse_dt, register

Q_ABOUT = "query { about { version } }"
Q_REPORTS = """query Reports($first: Int) {
  reports(first: $first, orderBy: published, orderMode: desc) {
    edges { node {
      id name description published modified report_types confidence
      createdBy { name }
      objectMarking { definition }
      objectLabel { value }
      externalReferences { edges { node { url source_name } } }
    } }
  }
}"""
Q_INDICATORS = """query Indicators($first: Int) {
  indicators(first: $first, orderBy: created, orderMode: desc) {
    edges { node {
      id name pattern_type pattern x_opencti_score x_opencti_main_observable_type
      valid_from valid_until revoked indicator_types created
      objectLabel { value }
      createdBy { name }
    } }
  }
}"""
Q_INTRUSION = """query Sets($first: Int) {
  intrusionSets(first: $first, orderBy: modified, orderMode: desc) {
    edges { node { id name aliases description modified objectLabel { value } } }
  }
}"""


def _tlp_severity(markings: list[dict]) -> int:
    defs = " ".join((m.get("definition") or "") for m in markings or []).upper()
    if "TLP:RED" in defs:
        return 4
    if "TLP:AMBER" in defs:
        return 3
    return 2


async def _gql(ctx: Context, query: str, variables: dict | None = None) -> dict:
    url = settings.opencti_url.rstrip("/") + "/graphql"
    r = await ctx.http.post(url, json={"query": query, "variables": variables or {}},
                            headers={"Authorization": f"Bearer {settings.opencti_token}", "Accept": "application/json"}, timeout=60)
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        raise RuntimeError("; ".join(str(e.get("message"))[:120] for e in data["errors"][:3]))
    return data.get("data") or {}


@register("opencti", interval_s=30 * 60, domain="cyber", description="OpenCTI: recent reports, indicators and intrusion sets (needs OPENCTI_URL + OPENCTI_TOKEN)",
          enabled=lambda: bool(settings.opencti_url and settings.opencti_token))
async def collect_opencti(ctx: Context) -> Result:
    about = await _gql(ctx, Q_ABOUT)
    version = (about.get("about") or {}).get("version")
    errors: list[str] = []
    items: list[dict] = []
    base = settings.opencti_url.rstrip("/")
    now = datetime.now(timezone.utc)

    # ---- Reports -> feed items
    reports_out = []
    try:
        data = await _gql(ctx, Q_REPORTS, {"first": 40})
        for edge in ((data.get("reports") or {}).get("edges") or []):
            n = edge.get("node") or {}
            labels = [l.get("value") for l in (n.get("objectLabel") or []) if l.get("value")]
            refs = [e.get("node", {}).get("url") for e in ((n.get("externalReferences") or {}).get("edges") or [])]
            refs = [u for u in refs if u]
            sev = _tlp_severity(n.get("objectMarking") or [])
            published = parse_dt(n.get("published") or n.get("modified"))
            item = {
                "id": item_id("opencti-report", n.get("id")),
                "source": "OpenCTI" + (f" · {n['createdBy']['name']}" if n.get("createdBy") and n["createdBy"].get("name") else ""),
                "domain": "cyber", "kind": "report",
                "title": strip_html(n.get("name") or "Untitled report", 220),
                "url": f"{base}/dashboard/analyses/reports/{n.get('id')}",
                "summary": strip_html(n.get("description") or "", 700) + (f" Labels: {', '.join(labels[:8])}." if labels else ""),
                "published_at": published, "severity": sev,
                "extra": {"report_types": n.get("report_types"), "confidence": n.get("confidence"),
                          "markings": [m.get("definition") for m in (n.get("objectMarking") or [])], "labels": labels, "refs": refs[:5]},
            }
            enrich(item, base_tags=["opencti", "report"] + [l.lower().replace(" ", "-")[:24] for l in labels[:4]], default_severity=sev)
            items.append(item)
            reports_out.append({"id": n.get("id"), "name": item["title"], "published": published, "types": n.get("report_types"),
                                "labels": labels[:6], "url": item["url"]})
    except Exception as e:  # noqa: BLE001
        errors.append(f"reports: {type(e).__name__}: {str(e)[:100]}")

    # ---- Indicators -> snapshot (recent 24h, scored)
    ind_out = []
    types: Counter = Counter()
    labels_c: Counter = Counter()
    try:
        data = await _gql(ctx, Q_INDICATORS, {"first": 200})
        cutoff = iso(now - timedelta(hours=24))
        for edge in ((data.get("indicators") or {}).get("edges") or []):
            n = edge.get("node") or {}
            if n.get("revoked"):
                continue
            created = parse_dt(n.get("created") or n.get("valid_from"), default_now=False)
            if created and created < cutoff:
                continue
            obs = n.get("x_opencti_main_observable_type") or n.get("pattern_type") or "?"
            types[obs] += 1
            for l in (n.get("objectLabel") or []):
                if l.get("value"):
                    labels_c[l["value"]] += 1
            ind_out.append({"id": n.get("id"), "name": (n.get("name") or "")[:160], "type": obs, "score": n.get("x_opencti_score"),
                            "pattern": (n.get("pattern") or "")[:200], "valid_from": n.get("valid_from"), "valid_until": n.get("valid_until"),
                            "labels": [l.get("value") for l in (n.get("objectLabel") or []) if l.get("value")][:5],
                            "created": created, "url": f"{base}/dashboard/observations/indicators/{n.get('id')}"})
        ind_out.sort(key=lambda i: -(i.get("score") or 0))
    except Exception as e:  # noqa: BLE001
        errors.append(f"indicators: {type(e).__name__}: {str(e)[:100]}")

    # ---- Intrusion sets -> snapshot
    sets_out = []
    try:
        data = await _gql(ctx, Q_INTRUSION, {"first": 25})
        for edge in ((data.get("intrusionSets") or {}).get("edges") or []):
            n = edge.get("node") or {}
            sets_out.append({"id": n.get("id"), "name": n.get("name"), "aliases": (n.get("aliases") or [])[:6],
                             "modified": n.get("modified"), "description": strip_html(n.get("description") or "", 240),
                             "labels": [l.get("value") for l in (n.get("objectLabel") or []) if l.get("value")][:5],
                             "url": f"{base}/dashboard/threats/intrusion_sets/{n.get('id')}"})
    except Exception as e:  # noqa: BLE001
        errors.append(f"intrusion sets: {type(e).__name__}: {str(e)[:100]}")

    new = ctx.db.upsert_items(items)
    ctx.db.set_snapshot("opencti", {
        "fetched_at": iso(now), "version": version, "url": base, "errors": errors,
        "reports": reports_out[:40], "reports_24h": sum(1 for r in reports_out if (r.get("published") or "") >= iso(now - timedelta(hours=24))),
        "indicators_24h": len(ind_out), "indicator_types": types.most_common(10), "indicator_labels": labels_c.most_common(12),
        "top_indicators": ind_out[:40], "intrusion_sets": sets_out,
    })
    msg = f"OpenCTI {version}: {len(reports_out)} reports ({new} new items), {len(ind_out)} indicators in 24h, {len(sets_out)} intrusion sets"
    if errors:
        msg += "; errors: " + "; ".join(errors)
    return Result(new, msg, ok=not (errors and not reports_out and not ind_out))
