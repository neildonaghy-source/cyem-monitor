"""Country reference data and lightweight country detection in free text.

Detection is deliberately conservative: word-boundary, case-sensitive matching of
proper nouns (country names, capitals, demonyms and a curated list of shorthand
such as "Kremlin" or "Pentagon"). It is a heuristic for placing news on a map,
not an attribution engine.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from .config import settings

# Extra shorthand -> ISO2. Deliberately limited to terms that are unambiguous in a
# cyber / defence news context.
EXTRA_ALIASES: dict[str, str] = {
    "UK": "GB", "U.K.": "GB", "Britain": "GB", "British": "GB", "England": "GB", "Scotland": "GB",
    "Wales": "GB", "Northern Ireland": "GB", "Whitehall": "GB", "GCHQ": "GB", "NCSC": "GB", "MoD": "GB",
    "Ministry of Defence": "GB", "Royal Navy": "GB", "RAF": "GB",
    "US": "US", "U.S.": "US", "USA": "US", "America": "US", "American": "US", "Pentagon": "US",
    "Washington": "US", "CISA": "US", "FBI": "US", "NSA": "US", "Cyber Command": "US", "White House": "US",
    "Kremlin": "RU", "Moscow": "RU", "Russia-linked": "RU", "Russia-backed": "RU", "GRU": "RU", "FSB": "RU", "SVR": "RU",
    "Beijing": "CN", "PRC": "CN", "PLA": "CN", "China-linked": "CN", "China-backed": "CN",
    "Tehran": "IR", "IRGC": "IR", "Iran-linked": "IR", "Iran-backed": "IR",
    "Pyongyang": "KP", "DPRK": "KP", "North Korea-linked": "KP",
    "Kyiv": "UA", "Kiev": "UA", "Taipei": "TW", "Jerusalem": "IL", "Tel Aviv": "IL", "IDF": "IL",
    "Gaza": "PS", "West Bank": "PS", "Houthi": "YE", "Houthis": "YE", "Hezbollah": "LB",
    "Kaliningrad": "RU", "Crimea": "UA", "Donbas": "UA", "Baltic": "LT", "Nordic": "SE",
    "Seoul": "KR", "Tokyo": "JP", "New Delhi": "IN", "Islamabad": "PK", "Ankara": "TR", "Riyadh": "SA",
    "Abu Dhabi": "AE", "Dubai": "AE", "Doha": "QA", "Cairo": "EG", "Berlin": "DE", "Paris": "FR",
    "Warsaw": "PL", "Brussels": "BE", "Canberra": "AU", "Ottawa": "CA", "Wellington": "NZ",
    "Hong Kong": "HK", "Macau": "MO", "Kosovo": "XK",
}

# Names that collide with common words or given names; matched only via longer forms.
AMBIGUOUS = {"Jordan", "Chad", "Georgia", "Turkey", "Guinea", "Niger", "Jersey", "Palau", "Nauru", "Togo",
             "Mali", "Benin", "Oman", "Cuba", "Peru", "Samoa", "Tonga", "Fiji", "Malta", "Cyprus"}
# Of the ambiguous names, these are common enough in this news domain to keep when capitalised.
KEEP_AMBIGUOUS = {"Turkey", "Georgia", "Jordan", "Cuba", "Peru", "Malta", "Cyprus", "Oman", "Mali", "Niger", "Chad"}


@lru_cache(maxsize=1)
def countries() -> dict[str, dict]:
    with open(settings.ref_dir / "countries.json", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("XK", {"iso2": "XK", "iso3": "XKX", "name": "Kosovo", "lat": 42.6, "lon": 20.9,
                           "capital": "Pristina", "demonym": "Kosovar", "aliases": [], "region": "Europe",
                           "subregion": "Southern Europe"})
    return data


def country(iso2: str | None) -> dict | None:
    if not iso2:
        return None
    return countries().get(iso2.upper())


def centroid(iso2: str | None) -> tuple[float, float] | None:
    c = country(iso2)
    if not c:
        return None
    return float(c["lat"]), float(c["lon"])


def name_of(iso2: str | None) -> str:
    c = country(iso2)
    return c["name"] if c else (iso2 or "")


@lru_cache(maxsize=1)
def _name_index() -> dict[str, str]:
    """Lower-cased country name / alias -> ISO2 (for resolving names from APIs)."""
    idx: dict[str, str] = {}
    for iso2, c in countries().items():
        for n in [c.get("name"), c.get("iso3"), *(c.get("aliases") or [])]:
            if n:
                idx[n.lower()] = iso2
        idx[iso2.lower()] = iso2
    for k, v in EXTRA_ALIASES.items():
        idx.setdefault(k.lower(), v)
    idx.update({"usa": "US", "united states": "US", "uk": "GB", "south korea": "KR", "korea, republic of": "KR",
                "russian federation": "RU", "viet nam": "VN", "czechia": "CZ", "czech republic": "CZ",
                "türkiye": "TR", "turkiye": "TR", "iran": "IR", "syria": "SY", "laos": "LA", "moldova": "MD",
                "bolivia": "BO", "venezuela": "VE", "tanzania": "TZ", "brunei": "BN", "micronesia": "FM",
                "macedonia": "MK", "north macedonia": "MK", "cape verde": "CV", "ivory coast": "CI",
                "cote d'ivoire": "CI", "côte d'ivoire": "CI", "dr congo": "CD", "congo, dem. rep.": "CD",
                "republic of the congo": "CG", "eswatini": "SZ", "swaziland": "SZ", "burma": "MM", "myanmar": "MM",
                "palestine": "PS", "vatican": "VA", "holy see": "VA", "hong kong": "HK", "macao": "MO",
                "netherlands antilles": "AN", "kosovo": "XK", "england": "GB", "scotland": "GB", "wales": "GB"})
    return idx


def resolve(name: str | None) -> str | None:
    """Resolve a country name or code from an API payload to ISO2."""
    if not name:
        return None
    s = str(name).strip()
    if len(s) == 2 and s.isalpha() and s.upper() in countries():
        return s.upper()
    return _name_index().get(s.lower())


@lru_cache(maxsize=1)
def _detector() -> tuple[re.Pattern, dict[str, str]]:
    terms: dict[str, str] = {}
    for iso2, c in countries().items():
        n = c.get("name")
        if n and (n not in AMBIGUOUS or n in KEEP_AMBIGUOUS):
            terms[n] = iso2
        for a in c.get("aliases") or []:
            if a and re.fullmatch(r"[A-Za-z' ,.\-]+", a) and len(a) > 4:
                terms[a] = iso2
        d = c.get("demonym")
        if d and len(d) > 4 and d not in ("Chadian",):
            terms[d] = iso2
        cap = c.get("capital")
        if cap and len(cap) > 4 and cap not in ("Georgetown", "Victoria", "Kingston", "Saint George's", "Road Town",
                                                  "Andorra la Vella", "Santiago", "Georgia", "Washington, D.C."):
            terms[cap] = iso2
    terms.update(EXTRA_ALIASES)
    # Longest first so "Northern Ireland" beats "Ireland", "South Korea" beats "Korea".
    ordered = sorted(terms.keys(), key=len, reverse=True)
    pattern = re.compile(r"(?<![\w-])(" + "|".join(re.escape(t) for t in ordered) + r")(?![\w-])")
    return pattern, terms


def detect_countries(text: str, limit: int = 4) -> list[str]:
    if not text:
        return []
    pattern, terms = _detector()
    found: list[str] = []
    for m in pattern.finditer(text):
        iso2 = terms.get(m.group(1))
        if iso2 and iso2 not in found:
            found.append(iso2)
            if len(found) >= limit:
                break
    return found


def flag(iso2: str | None) -> str:
    if not iso2 or len(iso2) != 2 or not iso2.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(ch.upper()) - ord("A")) for ch in iso2)
