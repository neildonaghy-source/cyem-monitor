"""Pure spectrum logic: WTR row parsing and frequency/geographic conflict tests.

Standard library only so it can be unit-tested without the app or a database.

Conflict model (increment 1, deliberately simple):
  - Two assignments overlap in frequency when their occupied bands, each widened
    by a guard band on both edges, intersect:
        |f1 - f2| < (bw1 + bw2) / 2 + guard
  - They are only a conflict if the sites are within a distance threshold.
  - A planned emitter with a time window only conflicts with another planned
    emitter if the windows intersect. Licensed WTR assignments are treated as
    always on.
Not modelled yet: harmonics, intermodulation, adjacent-channel selectivity,
terrain or power. See harmonics() / intermod3() stubs.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable

EARTH_RADIUS_KM = 6371.0088

# WTR CSV columns we keep. Licensee surname / first name are deliberately NOT
# kept: some licensees are private individuals. Company name only.
WTR_COLS = {
    "licence": "Licence Number",
    "freq_hz": "Frequency (Hz)",
    "station_type": "Station Type",
    "bw_hz": "Channel Width (Hz)",
    "erp": "Antenna ERP",
    "erp_unit": "Antenna ERP Unit",
    "ant_height_m": "Antenna Height",
    "height_asl_m": "Height Above Sea Level",
    "azimuth": "Antenna AZIMUTH",
    "emission": "Emission Code",
    "company": "Licencee Company",
    "product": "Product Description",
    "lat": "Latitude(Deg)",
    "lon": "Longitude(Deg)",
    "ngr": "NGR",
}


def _num(v: str | None) -> float | None:
    if v is None:
        return None
    v = v.strip()
    if not v or v == "-":
        return None
    try:
        x = float(v)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def _txt(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return None if not v or v == "-" else v


# ---- privacy: suppress licensee names that look like private individuals ----------------
# The register's surname/first-name fields are dropped outright. Some sole traders' names
# are typed into the company field instead; mask anything that looks like a personal name.
# Deliberately errs towards masking: hiding a small organisation's name costs little.
ORG_WORDS = set("""LTD LIMITED PLC LLP LLC INC CORP CO COMPANY COUNCIL TRUST NHS UNIVERSITY COLLEGE SCHOOL SCHOOLS ACADEMY
AUTHORITY POLICE FIRE RESCUE SERVICE SERVICES CLUB ASSOCIATION SOCIETY GROUP PARTNERSHIP PARTNERS AIRPORT AIRPORTS PORT PORTS
HARBOUR RAILWAY RAILWAYS NETWORK NETWORKS COMMUNICATIONS COMMS TELECOM TELECOMS RADIO RADIOS ENERGY WATER ELECTRIC
ELECTRICITY POWER HOSPITAL HOSPITALS CHURCH CIC FOUNDATION BOARD AGENCY DEPARTMENT MINISTRY GOVERNMENT SECRETARY
OFFICE COMMISSION TRAM TRAMS BUS BUSES COACH COACHES TAXI TAXIS CARS SECURITY HOLDINGS ENTERPRISE ENTERPRISES
INDUSTRIES SYSTEMS SOLUTIONS TECHNOLOGIES TECHNOLOGY INTERNATIONAL UK BRITISH NATIONAL ROYAL ESTATE ESTATES FARM FARMS
HOTEL HOTELS MARINA MARINE YACHT YACHTS LIFEBOAT RNLI CITY COUNTY BOROUGH DISTRICT PARISH SONS BROS BROTHERS AND
EDUCATION TRANSPORT LOGISTICS CONSTRUCTION ENGINEERING MOTORS GARAGE HAULAGE PLANT HIRE EVENTS MEDIA STUDIO STUDIOS
PRODUCTIONS CLEANING SUPPLIES FARMING LEISURE SPORTS SPORT CENTRE CENTER UNIT YSGOL MBC DC CC BC CENTRAL NORTH SOUTH
EAST WEST FISHERIES FISHING SHIPPING FERRIES FERRY BOATS BOAT TOURS TRAVEL CARE HOME HOMES HEALTH MEDICAL AMBULANCE
MUSEUM THEATRE ARENA STADIUM RACECOURSE GOLF RACING MOTORSPORT CIRCUIT QUARRY QUARRIES MINING AGGREGATES CONCRETE
STEEL WORKS MILLS DOCK DOCKS TERMINAL TERMINALS WHARF MARITIME NAVAL ARMY RAF DEFENCE HM HMS MOD REGIMENT BATTALION
COMMUNITY VOLUNTARY CHARITY CHARITABLE MISSION SCOUTS GUIDES CADETS FESTIVAL EXHIBITION SHOW SHOWS AGRICULTURAL
TV TELEVISION BROADCAST BROADCASTING WIRELESS MOBILE TELECOMMUNICATIONS SATELLITE DATA DIGITAL CONSULTING CONSULTANTS
ASSOCIATES CONTRACTORS CONTRACTING ELECTRICAL MECHANICAL SUPPLY TRADING TRADERS STORES SHOP RETAIL PARK PARKS GARDENS
""".split())
ORG_WORDS |= set("""MOSQUE MASJID JAMIA JAMIAT ISLAM ISLAMIC ISLAMIYYAH MADINA MADRASSA MUSLIM IDARA CENTRE GURDWARA TEMPLE
SYNAGOGUE CHAPEL CATHEDRAL ABBEY MINSTER INSTITUTE LABORATORY LABORATORIES BANK CORPORATION FUND FUNDS MANAGEMENT HALL
MEMORIAL PRIMARY SECONDARY INFANT JUNIOR NURSERY UNION FORT CASTLE PALACE MANOR COTTAGE LODGE HOUSE CHEMICALS SALADS FOODS
FOOD LEARNING RESOURCES WALES SCOTLAND ENGLAND IRELAND LONDON VENUE CYMRU HILTON RIVERSIDE CANAL WATERWAYS BRITISHWATERWAYS
LIBRARY GALLERY ZOO AQUARIUM RESERVE NATURE WILDLIFE FOREST FORESTRY PORTAKABIN WAVE REBEL AS AB SA GMBH BV NV SPA AG
""".split())
TITLES = {"MR", "MRS", "MS", "MISS", "DR", "REV", "SIR", "DAME", "LORD", "LADY"}
_NAME_WORD = re.compile(r"^[A-Za-z][A-Za-z'\-]*\.?$")


def looks_personal(company: str | None) -> bool:
    if not company:
        return False
    words = company.replace(",", " ").split()
    up = [w.strip(".").upper() for w in words]
    if up and up[0] in TITLES:
        return True
    if not 2 <= len(words) <= 3 or not all(_NAME_WORD.match(w) for w in words):
        return False
    if up[0] == "THE" or any(u in ORG_WORDS for u in up):
        return False
    if company.upper() != company and any(2 <= len(w) <= 4 and w.isupper() for w in words):
        return False   # acronym in a mixed-case name, e.g. 'Roadphone NRB'
    return True


_EMISSION_MULT = {"H": 1.0, "K": 1e3, "M": 1e6, "G": 1e9}


def bw_from_emission(code: str | None) -> float | None:
    """Necessary bandwidth from an ITU emission designator, e.g. 12K5G7W -> 12500 Hz,
    27M5D7W -> 27.5e6 Hz, 100HA1A -> 100 Hz. Returns None if unparseable."""
    if not code or len(code) < 4:
        return None
    head = code[:4].upper()
    for i, ch in enumerate(head):
        if ch in _EMISSION_MULT:
            digits = head[:i] + "." + head[i + 1:]
            try:
                return float(digits.strip(".")) * _EMISSION_MULT[ch]
            except ValueError:
                return None
    return None


def parse_wtr_row(row: dict) -> dict | None:
    """Normalise one WTR CSV row. Frequencies and bandwidths in Hz. Returns None
    for rows with no usable frequency or position."""
    g = {k: row.get(col) for k, col in WTR_COLS.items()}
    f = _num(g["freq_hz"])
    lat, lon = _num(g["lat"]), _num(g["lon"])
    if f is None or f <= 0:
        return None
    if lat is None or lon is None:
        lat = lon = None          # area-defined or unpublished location
    elif not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    bw = _num(g["bw_hz"])
    bw_src = "wtr"
    if bw is None or bw <= 0:
        bw = bw_from_emission(_txt(g["emission"]))
        bw_src = "emission" if bw else "none"
    return {
        "licence": _txt(g["licence"]) or "?",
        "freq_hz": f,
        "bw_hz": bw or 0.0,
        "bw_src": bw_src,
        "station_type": _txt(g["station_type"]),
        "erp": _num(g["erp"]),
        "erp_unit": _txt(g["erp_unit"]),
        "ant_height_m": _num(g["ant_height_m"]),
        "height_asl_m": _num(g["height_asl_m"]),
        "azimuth": _num(g["azimuth"]),
        "emission": _txt(g["emission"]),
        "company": None if looks_personal(_txt(g["company"])) else _txt(g["company"]),
        "product": _txt(g["product"]) or "Unknown",
        "lat": round(lat, 6) if lat is not None else None,
        "lon": round(lon, 6) if lon is not None else None,
        "ngr": _txt(g["ngr"]),
    }


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def bbox_for_radius(lat: float, lon: float, km: float) -> tuple[float, float, float, float]:
    """Conservative (min_lat, max_lat, min_lon, max_lon) box containing a circle."""
    dlat = math.degrees(km / EARTH_RADIUS_KM)
    c = max(math.cos(math.radians(lat)), 0.01)
    dlon = min(180.0, dlat / c)
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon


def freq_overlap_hz(f1: float, bw1: float, f2: float, bw2: float, guard_hz: float = 0.0) -> float:
    """Amount of overlap in Hz between two guarded channels; <= 0 means clear.
    Positive value is how far the guarded edges intrude into each other."""
    return (bw1 + bw2) / 2.0 + guard_hz - abs(f1 - f2)


def freq_overlaps(f1: float, bw1: float, f2: float, bw2: float, guard_hz: float = 0.0) -> bool:
    return freq_overlap_hz(f1, bw1, f2, bw2, guard_hz) > 0


def windows_intersect(s1: str | None, e1: str | None, s2: str | None, e2: str | None) -> bool:
    """ISO-8601 UTC strings compare lexically. Open ends are unbounded."""
    lo = max((s for s in (s1, s2) if s), default=None)
    hi = min((e for e in (e1, e2) if e), default=None)
    return lo is None or hi is None or lo < hi


def severity(overlap_hz: float, guard_hz: float, co_channel_hz: float, dist_km: float, radius_km: float) -> str:
    """Crude triage. co_channel_hz is the gap between occupied band edges
    (<= 0 means the occupied bands overlap).
      low    only the guard bands intrude
      high   occupied bands overlap and the sites are within a third of the radius
      medium anything else inside the radius"""
    if overlap_hz < guard_hz:
        return "low"
    if co_channel_hz <= 0 and dist_km <= radius_km / 3:
        return "high"
    return "medium"


@dataclass
class Emitter:
    id: str
    name: str
    freq_hz: float
    bw_hz: float
    lat: float
    lon: float
    start: str | None = None
    end: str | None = None
    kind: str = "planned"     # planned | wtr
    meta: dict | None = None


def check_pair(a: Emitter, b: Emitter, *, guard_hz: float, radius_km: float) -> dict | None:
    ov = freq_overlap_hz(a.freq_hz, a.bw_hz, b.freq_hz, b.bw_hz, guard_hz)
    if ov <= 0:
        return None
    d = haversine_km(a.lat, a.lon, b.lat, b.lon)
    if d > radius_km:
        return None
    if a.kind == "planned" and b.kind == "planned" and not windows_intersect(a.start, a.end, b.start, b.end):
        return None
    spacing = abs(a.freq_hz - b.freq_hz)
    co = spacing - (a.bw_hz + b.bw_hz) / 2.0   # <= 0 means occupied bands overlap
    return {
        "a": a.id, "b": b.id, "b_kind": b.kind, "b_name": b.name,
        "b_freq_hz": b.freq_hz, "b_bw_hz": b.bw_hz, "b_lat": b.lat, "b_lon": b.lon,
        "spacing_hz": round(spacing, 1), "overlap_hz": round(ov, 1),
        "co_channel": co <= 0, "dist_km": round(d, 2),
        "severity": severity(ov, guard_hz, co, d, radius_km),
        "b_meta": b.meta or {},
    }


def find_conflicts(planned: Iterable[Emitter], candidates: Iterable[Emitter], *,
                   guard_hz: float = 0.0, radius_km: float = 50.0) -> list[dict]:
    """Check every planned emitter against candidates (WTR rows or other planned
    emitters). Self-pairs and duplicate planned/planned pairs are skipped."""
    planned = list(planned)
    candidates = list(candidates)
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for p in planned:
        for c in candidates:
            if c.kind == "planned":
                if c.id == p.id:
                    continue
                key = tuple(sorted((p.id, c.id)))
                if key in seen:
                    continue
                seen.add(key)
            r = check_pair(p, c, guard_hz=guard_hz, radius_km=radius_km)
            if r:
                out.append(r)
    rank = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda r: (rank[r["severity"]], r["dist_km"], r["spacing_hz"]))
    return out


# ---- later increments ------------------------------------------------------------
def harmonics(f_hz: float, orders: int = 5) -> list[float]:
    """Harmonic frequencies 2f..nf. Not yet used in conflict checks (increment 2+)."""
    return [f_hz * n for n in range(2, orders + 1)]


def intermod3(f1_hz: float, f2_hz: float) -> list[float]:
    """Third-order intermodulation products 2f1-f2 and 2f2-f1. Stub for a later
    co-site analysis increment; not yet used."""
    return [2 * f1_hz - f2_hz, 2 * f2_hz - f1_hz]
