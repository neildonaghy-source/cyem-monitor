"""Keyword tagging and severity heuristics (done in code so the LLM is not needed
for every item). Tags are stable slugs the UI filters on."""
from __future__ import annotations

import html
import re

from . import geo

# tag -> regex (case-insensitive). Order matters only for readability.
TAG_RULES: list[tuple[str, str]] = [
    ("ransomware", r"\bransomware\b|\bextortion\b|\bdata leak site\b|\bLockBit\b|\bCl0p\b|\bClop\b|\bAkira\b|\bQilin\b|\bRansomHub\b"),
    ("apt", r"\bAPT\d{1,2}\b|\bstate-sponsored\b|\bstate-backed\b|\bstate-linked\b|\bstate-aligned\b|\bstate actors?\b|\bnation-state\b|\bespionage\b|\b(China|Russia|Iran|North Korea|Pakistan|India)[- ](linked|backed|aligned|nexus)\b|\bTyphoon\b|\bBlizzard\b|\bSandworm\b|\bLazarus\b|\bTurla\b|\bFancy Bear\b|\bCozy Bear\b|\bKimsuky\b|\bMuddyWater\b|\bCharming Kitten\b"),
    ("zero-day", r"\bzero[- ]day\b|\b0[- ]day\b|\bactively exploited\b|\bin the wild\b|\bexploited in\b"),
    ("vuln", r"\bCVE-\d{4}-\d{4,7}\b|\bvulnerabilit(y|ies)\b|\bpatch(es|ed)?\b|\bremote code execution\b|\bRCE\b|\bCVSS\b"),
    ("malware", r"\bmalware\b|\bbotnet\b|\btrojan\b|\bbackdoor\b|\binfostealer\b|\bloader\b|\bwiper\b|\bC2\b|\bcommand[- ]and[- ]control\b"),
    ("breach", r"\bbreach(ed|es)?\b|\bleak(ed|s)?\b|\bexfiltrat|\bstolen data\b|\bcredentials\b"),
    ("ddos", r"\bDDoS\b|\bdenial[- ]of[- ]service\b|\bvolumetric\b"),
    ("phishing", r"\bphishing\b|\bspear[- ]phishing\b|\bsmishing\b|\bsocial engineering\b"),
    ("supply-chain", r"\bsupply[- ]chain\b|\bthird[- ]party\b|\bnpm\b|\bPyPI\b|\bSolarWinds\b"),
    ("ics", r"\bICS\b|\bSCADA\b|\bOT\b|\boperational technology\b|\bPLC\b|\bindustrial control\b|\bcritical national infrastructure\b|\bCNI\b|\bcritical infrastructure\b"),
    ("cloud", r"\bAzure\b|\bAWS\b|\bGoogle Cloud\b|\bMicrosoft 365\b|\bEntra\b|\bOkta\b|\bidentity provider\b"),
    ("gnss", r"\bGNSS\b|\bGPS\b|\bGalileo\b|\bGLONASS\b|\bBeiDou\b|\bPNT\b|\bposition(ing)?, navigation\b|\bspoof(ing|ed)?\b|\bjamm(ing|ed|er|ers)\b"),
    ("ew", r"\belectronic warfare\b|\bEW\b|\bEMSO\b|\belectromagnetic\b|\bEMS\b|\bspectrum\b|\bSIGINT\b|\bELINT\b|\bCOMINT\b|\bradar\b|\bEMP\b|\bdirected energy\b|\bHPM\b|\bhigh[- ]power microwave\b|\bcounter[- ]drone\b|\bC-UAS\b"),
    ("satcom", r"\bSATCOM\b|\bsatellite communications?\b|\bStarlink\b|\bOneWeb\b|\bViasat\b|\bIntelsat\b|\bInmarsat\b|\bSES\b|\bKA-SAT\b|\bground station\b"),
    ("space", r"\bsatellite(s)?\b|\borbit(al)?\b|\bLEO\b|\bGEO\b|\blaunch(es|ed)?\b|\bspace domain\b|\bSpace Force\b|\bSpace Command\b|\bASAT\b|\bdebris\b"),
    ("space-weather", r"\bsolar (flare|storm|wind)\b|\bgeomagnetic\b|\bCME\b|\bcoronal mass\b|\bKp\b|\bK-index\b|\bX-class\b|\bM-class\b|\bradio blackout\b|\baurora\b|\bionospher"),
    ("hf", r"\bHF\b|\bshortwave\b|\bskywave\b|\bNVIS\b|\bpropagation\b"),
    ("5g", r"\b5G\b|\b6G\b|\bO-RAN\b|\bOpen RAN\b|\btelecoms?\b|\bmobile network\b|\bHuawei\b|\bEricsson\b|\bNokia\b"),
    ("cable", r"\bsubsea\b|\bundersea\b|\bsubmarine cable\b|\bsubsea cable\b|\bcable (cut|damage|fault|break)\b|\bcable-cutting\b"),
    ("outage", r"\boutage(s)?\b|\bdowntime\b|\bdisrupt(ed|ion)\b|\bconnectivity\b|\binternet shutdown\b|\bblackout\b"),
    ("bgp", r"\bBGP\b|\broute (leak|hijack)\b|\bprefix hijack\b|\bRPKI\b"),
    ("dns", r"\bDNS\b|\bdomain hijack\b|\bregistrar\b"),
    ("drone", r"\bdrone(s)?\b|\bUAS\b|\bUAV\b|\bFPV\b|\bloitering munition\b"),
    ("defence", r"\bNATO\b|\bMoD\b|\bMinistry of Defence\b|\bDoD\b|\bPentagon\b|\bmilitary\b|\barmed forces\b|\bArmy\b|\bNavy\b|\bAir Force\b|\bRoyal Signals\b"),
    ("ukraine", r"\bUkrain(e|ian)\b|\bKyiv\b|\bDonbas\b|\bCrimea\b|\bBlack Sea\b"),
    ("policy", r"\bregulat(ion|or|ory)\b|\blegislat|\bsanction(s|ed)?\b|\bindict(ed|ment)\b|\bexecutive order\b|\bNIS2\b|\bCyber Security and Resilience Bill\b|\bOfcom\b|\bFCC\b|\bITU\b"),
    ("ai", r"\bAI\b|\bartificial intelligence\b|\bLLM\b|\bmachine learning\b|\bagentic\b"),
    ("uk", r"\bUK\b|\bU\.K\.\b|\bBritain\b|\bBritish\b|\bNCSC\b|\bGCHQ\b|\bEngland\b|\bScotland\b|\bWales\b|\bWhitehall\b|\bMoD\b"),
]
_COMPILED = [(tag, re.compile(rx, re.IGNORECASE)) for tag, rx in TAG_RULES]

# Tags that pull an item towards a domain (used for cross-domain filtering in the UI).
EM_TAGS = {"gnss", "ew", "satcom", "space", "space-weather", "hf", "5g", "drone"}
INFRA_TAGS = {"cable", "outage", "bgp", "dns"}
CYBER_TAGS = {"ransomware", "apt", "zero-day", "vuln", "malware", "breach", "ddos", "phishing", "supply-chain", "ics", "cloud"}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(s: str | None, limit: int = 700) -> str:
    if not s:
        return ""
    s = _TAG_RE.sub(" ", s)
    s = html.unescape(s)
    s = _WS_RE.sub(" ", s).strip()
    if len(s) > limit:
        s = s[: limit - 1].rsplit(" ", 1)[0] + "…"
    return s


def tags_for(text: str, base: list[str] | None = None) -> list[str]:
    found = list(base or [])
    for tag, rx in _COMPILED:
        if tag not in found and rx.search(text):
            found.append(tag)
    return found


def severity_for(text: str, tags: list[str], default: int = 2) -> int:
    """1 (background) .. 5 (act now). Heuristic and deliberately conservative."""
    sev = default
    t = text.lower()
    if "zero-day" in tags or "actively exploited" in t or "in the wild" in t:
        sev = max(sev, 4)
    if re.search(r"\b(critical|emergency|urgent|widespread|nationwide|mass exploitation)\b", t):
        sev = max(sev, 3)
    if "ics" in tags and ("apt" in tags or "ransomware" in tags or "malware" in tags):
        sev = max(sev, 4)
    if "apt" in tags and ("uk" in tags or "defence" in tags):
        sev = max(sev, 3)
    if re.search(r"\b(x-class|g4|g5|severe geomagnetic|extreme)\b", t):
        sev = max(sev, 4)
    if "cable" in tags and re.search(r"\b(cut|damaged|severed|sabotage)\b", t):
        sev = max(sev, 3)
    if re.search(r"\bnational (cyber|security) emergency\b|\bcatastrophic\b", t):
        sev = 5
    return min(5, max(1, sev))


def enrich(item: dict, *, base_tags: list[str] | None = None, default_severity: int = 2) -> dict:
    """Fill tags, severity, country, lat/lon from title + summary when not already set."""
    text = f"{item.get('title', '')}. {item.get('summary', '')}"
    tags = tags_for(text, base_tags)
    item["tags"] = tags
    item["severity"] = item.get("severity") or severity_for(text, tags, default_severity)
    if not item.get("country"):
        cs = geo.detect_countries(text)
        if cs:
            item["country"] = cs[0]
            item.setdefault("extra", {})["countries"] = cs
    if item.get("country") and (item.get("lat") is None or item.get("lon") is None):
        c = geo.centroid(item["country"])
        if c:
            item["lat"], item["lon"] = c
    return item
