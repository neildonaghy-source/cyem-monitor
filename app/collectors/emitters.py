"""EM emitter and platform layers.

  radars   OSM features tagged as radar towers / military radar / ground stations (Overpass, weekly)
  milair   Military aircraft broadcasting ADS-B (adsb.fi with adsb.lol fallback, every 2 min),
           classified into ISR / EW / AEW / MPA / tanker / transport / other
  sats     GNSS, military and SBAS satellites from Celestrak TLEs, positions via SGP4 (every 2 min)
"""
from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timezone

from .. import geo
from ..db import iso
from .base import Context, Result, get_text, register

OVERPASS_URLS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
OVERPASS_QUERY = """[out:json][timeout:300];
(
  nwr["tower:type"="radar"];
  nwr["military"="radar"];
  nwr["man_made"="radar"];
  nwr["man_made"="ground_station"];
);
out center tags;"""
ADSB_URLS = ["https://opendata.adsb.fi/api/v2/mil", "https://api.adsb.lol/v2/mil"]
CELESTRAK = "https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"
SAT_GROUPS = ["gnss", "military", "sbas"]
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36 CyEM-Monitor/0.1"


# ---- OSM radar sites ------------------------------------------------------------
_MIL = re.compile(r"air ?force|navy|naval|army|\bmod\b|ministry of defen|bundeswehr|nato|military|arm[ée]e|luftwaffe|\braf\b|\brrh\b|usaf|"
                  r"defen[cs]e|air defen|early warning|voronezh|daryal|bmews|pave paws|space force|marine|missile|\bsam\b|garrison", re.I)
_WX = re.compile(r"weather|met office|meteorolog|\bdwd\b|m[ée]t[ée]o|nexrad|\bnws\b|precip|wetter|knmi|smhi|\bfmi\b|niederschlag|wsr-88|"
                 r"doppler|regenradar|rain radar|climat", re.I)
_AVI = re.compile(r"\batc\b|airport|aerodrome|aviation|\bnats\b|\bdfs\b|\bfaa\b|eurocontrol|\bssr\b|\basr\b|approach|surveillance radar|"
                  r"\barsr\b|\bpsr\b|flughafen|a[ée]roport|air traffic|skyguide|enav|\bena\b|avinor|naviair|lfv", re.I)
_MAR = re.compile(r"coast|\bvts\b|port|harbou?r|maritime|k[üu]sten|vessel traffic|marina|lighthouse|pilot", re.I)
_SPACE = re.compile(r"space|satellite|ground station|deep space|tracking station|\bdsn\b|estrack|earth station|telemetry|\bttc\b|radio telescope|radar research", re.I)


def _classify_osm(tags: dict) -> str:
    text = " ".join(str(v) for k, v in tags.items() if k in ("name", "operator", "description", "note", "radar:type", "military",
                                                              "man_made", "tower:type", "owner", "brand", "official_name", "alt_name"))
    if tags.get("man_made") == "ground_station" or _SPACE.search(text):
        return "space"
    if tags.get("military") or _MIL.search(text):
        return "military"
    if _WX.search(text):
        return "weather"
    if _AVI.search(text):
        return "aviation"
    if _MAR.search(text):
        return "maritime"
    return "other"


@register("radars", interval_s=7 * 24 * 60 * 60, domain="em", description="Radar sites and ground stations from OpenStreetMap (Overpass, weekly)")
async def collect_radars(ctx: Context) -> Result:
    last_err = ""
    data = None
    for url in OVERPASS_URLS:
        try:
            r = await ctx.http.post(url, data={"data": OVERPASS_QUERY}, timeout=330)
            if r.status_code == 200:
                data = r.json()
                break
            last_err = f"HTTP {r.status_code} from {url}"
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {str(e)[:100]} ({url})"
    if data is None:
        raise RuntimeError(f"Overpass unavailable: {last_err}")
    sites = []
    classes: Counter = Counter()
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        if el.get("type") == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            c = el.get("center") or {}
            lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            continue
        cls = _classify_osm(tags)
        classes[cls] += 1
        sites.append({
            "id": f"{el.get('type', 'n')[0]}{el.get('id')}", "lat": round(lat, 4), "lon": round(lon, 4), "cls": cls,
            "name": tags.get("name") or tags.get("official_name") or tags.get("alt_name") or "",
            "operator": tags.get("operator") or tags.get("owner") or "",
            "kind": tags.get("radar:type") or tags.get("tower:type") or tags.get("man_made") or tags.get("military") or "",
            "desc": (tags.get("description") or tags.get("note") or "")[:160],
            "height": tags.get("height") or tags.get("tower:height") or "",
        })
    ctx.db.set_snapshot("radars", {"fetched_at": iso(datetime.now(timezone.utc)), "count": len(sites), "classes": classes.most_common(),
                                   "sites": sites, "attribution": "© OpenStreetMap contributors (ODbL), via Overpass API"})
    return Result(len(sites), f"{len(sites)} sites: " + ", ".join(f"{k} {v}" for k, v in classes.most_common()))


# ---- Military ADS-B ---------------------------------------------------------------
ROLE_BY_TYPE = {
    # Unambiguous ISR / SIGINT / ELINT airframes
    "R135": "isr", "RC135": "isr", "U2": "isr", "RQ4": "isr", "Q4": "isr", "MQ9": "isr", "MQ4": "isr", "MQ1": "isr", "E8": "isr",
    # AEW / airborne C2
    "E3CF": "aew", "E3TF": "aew", "E3": "aew", "E7": "aew", "E767": "aew", "E2": "aew", "E2C": "aew", "E2D": "aew", "A50": "aew",
    "E4B": "c2", "E6": "c2", "E6TL": "c2", "IL80": "c2", "E11": "c2",
    # EW
    "EA18": "ew", "EA6B": "ew", "EC13": "ew", "EA37": "ew",
    # Maritime patrol
    "P8": "mpa", "P3": "mpa", "P1": "mpa", "ATL2": "mpa", "IL38": "mpa", "CP14": "mpa",
    # Tankers
    "K35R": "tanker", "K35E": "tanker", "KC46": "tanker", "K46": "tanker", "KC10": "tanker", "DC10": "tanker", "IL78": "tanker",
    "A332": "tanker", "A333": "tanker", "MRTT": "tanker", "B762": "tanker", "A310": "tanker", "L101": "tanker", "KC1": "tanker",
    # Transport / liaison (turboprops and bizjets default here unless the description says otherwise)
    "C130": "transport", "C30J": "transport", "A400": "transport", "C17": "transport", "C5M": "transport", "C5": "transport",
    "C27J": "transport", "C160": "transport", "AN26": "transport", "AN72": "transport", "AN24": "transport", "IL76": "transport",
    "TU54": "transport", "B742": "transport", "B744": "transport", "B752": "transport", "B763": "transport", "B737": "transport",
    "B738": "transport", "CL60": "transport", "C56X": "transport", "GLF4": "transport", "GLF3": "transport", "GLF5": "transport",
    "GLF6": "transport", "GLEX": "transport", "GL5T": "transport", "A319": "transport", "A320": "transport", "A321": "transport",
    "BE20": "transport", "B350": "transport", "B300": "transport", "C560": "transport", "LJ35": "transport", "PC12": "transport",
    "DHC8": "transport", "DH8D": "transport", "CN35": "transport", "C295": "transport", "E145": "transport", "G550": "transport",
    "DHC6": "transport", "C12": "transport", "UC35": "transport", "CRJ2": "transport", "F900": "transport", "FA7X": "transport",
    "FA50": "transport", "GLF2": "transport", "LJ45": "transport", "H25B": "transport", "SF34": "transport", "AT72": "transport",
    # Bombers / strike / fighters (de-emphasised)
    "B52": "strike", "B1": "strike", "B2": "strike", "TU95": "strike", "TU16": "strike", "TU22": "strike", "TU60": "strike",
    "F16": "fighter", "F15": "fighter", "F35": "fighter", "F22": "fighter", "EUFI": "fighter", "TYPH": "fighter", "RFAL": "fighter",
    "GRIP": "fighter", "F18H": "fighter", "F18S": "fighter", "F18": "fighter", "TOR": "fighter", "SU27": "fighter", "SU30": "fighter",
    "SU35": "fighter", "MG29": "fighter", "MG31": "fighter", "A10": "fighter", "F4": "fighter", "F5": "fighter", "M2K": "fighter",
    "HAWK": "trainer", "TEX2": "trainer", "T38": "trainer", "T6": "trainer", "PC21": "trainer", "PC9": "trainer", "TUCA": "trainer",
    "M346": "trainer", "CL41": "trainer", "T7": "trainer", "G120": "trainer", "SF26": "trainer", "T45": "trainer", "L39": "trainer",
    "C172": "trainer", "PC7": "trainer", "TWR": "trainer", "DA40": "trainer", "DA42": "trainer", "T34": "trainer", "SR22": "trainer",
    "H60": "heli", "H64": "heli", "H47": "heli", "EC45": "heli", "EC35": "heli", "AS65": "heli", "A119": "heli", "A109": "heli",
    "B212": "heli", "B412": "heli", "EC25": "heli", "H1": "heli", "S61": "heli", "S92": "heli", "NH90": "heli", "TIGR": "heli",
    "PUMA": "heli", "LYNX": "heli", "AW19": "heli", "AW39": "heli", "AW09": "heli", "V22": "heli", "EC75": "heli", "H500": "heli",
    "MI8": "heli", "MI17": "heli", "MI24": "heli", "EH10": "heli", "AS50": "heli", "AS32": "heli", "B06": "heli", "R44": "heli",
    "UH1": "heli", "H53": "heli", "S70": "heli", "EC30": "heli", "A139": "heli", "A169": "heli", "H160": "heli",
}
ROLE_ORDER = ["isr", "ew", "aew", "c2", "mpa", "tanker", "transport", "strike", "fighter", "heli", "trainer", "other"]
# Callsign prefixes that reliably indicate ISR / AEW tasking.
_ISR_CALL = re.compile(r"^(JAKE|HOMER|TOPCAT|FORTE|SNTRY|NATO\d|UAVGH|COBRA|OLIVE|DRAGN|PYTHON)", re.I)
ISR_DESC = ("RC-135", "RIVET", "RC-12", "GUARDRAIL", "MC-12", "LIBERTY", "SENTINEL", "ASTOR", "SIGINT", "RECON", " ISR", "SURVEILLANCE",
            "GLOBAL HAWK", "REAPER", "TRITON", "E-8", "JSTARS", "ARTEMIS", "ARES ", "SHADOW R", "U-2", "DRAGON LADY", "U-28", "MC-130",
            "CN-235 MP", "RC-26", "OC-135", "WC-135", "CONSTANT PHOENIX", "AIRSEEKER", "GLOBAL 6000 ISR", "PC-12 ISR", "ISR")
AEW_DESC = ("WEDGETAIL", "AWACS", "SENTRY", "E-3", "E-7", "E-2", "A-50", "ERIEYE", "GLOBALEYE", "E-767", "HAWKEYE", "AEW")
EW_DESC = ("GROWLER", "EA-18", "EA-6", "COMPASS CALL", "EC-130", "EC-37", "EA-37", "ELECTRONIC WARFARE", "ELECTRONIC ATTACK")
C2_DESC = ("E-4", "E-6", "MERCURY", "NIGHTWATCH", "TACAMO", "IL-80", "E-11", "BACN")
MPA_DESC = ("POSEIDON", "ORION", "P-8", "P-3", "P-1 ", "ATLANTIQUE", "MARITIME PATROL", "IL-38", "CP-140", "AURORA", "P-1A", "SEAGUARDIAN")
TANKER_DESC = ("TANKER", "STRATOTANKER", "PEGASUS", "VOYAGER", "MRTT", "KC-", "EXTENDER", "IL-78")


def _role(t: str | None, desc: str | None, flight: str | None) -> str:
    t = (t or "").upper()
    d = " " + (desc or "").upper() + " "
    for role, kws in (("ew", EW_DESC), ("aew", AEW_DESC), ("c2", C2_DESC), ("isr", ISR_DESC), ("mpa", MPA_DESC), ("tanker", TANKER_DESC)):
        if any(k in d for k in kws):
            return role
    if flight and _ISR_CALL.match(flight.strip()):
        return "isr"
    if t in ROLE_BY_TYPE:
        return ROLE_BY_TYPE[t]
    if any(k in d for k in ("HELICOPTER", "ROTOR", "COPTER")):
        return "heli"
    if any(k in d for k in ("TRAINER", "TEXAN", "HAWK T", "TUTOR", "TUCANO")):
        return "trainer"
    if any(k in d for k in ("GLOBEMASTER", "HERCULES", "ATLAS", "TRANSPORT", "SPARTAN", "KING AIR", "HURON", "GULFSTREAM", "GLOBAL", "CITATION", "LEARJET", "FALCON", "CHALLENGER")):
        return "transport"
    return "other"


@register("milair", interval_s=120, domain="em", description="Military aircraft on ADS-B (adsb.fi / adsb.lol), classified ISR / EW / AEW / MPA / tanker")
async def collect_milair(ctx: Context) -> Result:
    data = None
    last_err = ""
    for url in ADSB_URLS:
        try:
            r = await ctx.http.get(url, headers={"User-Agent": BROWSER_UA}, timeout=40)
            if r.status_code == 200:
                data = r.json()
                src = url.split("/")[2]
                break
            last_err = f"HTTP {r.status_code} from {url}"
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {str(e)[:80]} ({url})"
    if data is None:
        raise RuntimeError(f"ADS-B sources unavailable: {last_err}")
    out = []
    roles: Counter = Counter()
    for a in data.get("ac", []):
        lat, lon = a.get("lat"), a.get("lon")
        if lat is None or lon is None:
            continue
        seen = a.get("seen_pos")
        if seen is not None and seen > 900:
            continue
        role = _role(a.get("t"), a.get("desc"), a.get("flight"))
        roles[role] += 1
        alt = a.get("alt_baro")
        out.append({
            "hex": a.get("hex"), "flight": (a.get("flight") or "").strip(), "reg": a.get("r"), "type": a.get("t"), "desc": a.get("desc"),
            "role": role, "lat": round(lat, 4), "lon": round(lon, 4), "alt": alt if isinstance(alt, (int, float)) else None,
            "alt_txt": "ground" if alt == "ground" else None, "gs": a.get("gs"), "track": a.get("track"), "squawk": a.get("squawk"),
            "seen": seen, "cat": a.get("category"),
        })
    priority = {r: i for i, r in enumerate(ROLE_ORDER)}
    out.sort(key=lambda p: priority.get(p["role"], 99))
    ctx.db.set_snapshot("milair", {"fetched_at": iso(datetime.now(timezone.utc)), "source": src, "count": len(out),
                                   "roles": [[r, roles[r]] for r in ROLE_ORDER if roles[r]], "aircraft": out})
    hi = sum(roles[r] for r in ("isr", "ew", "aew", "c2", "mpa"))
    return Result(len(out), f"{len(out)} military aircraft ({hi} ISR/EW/AEW/C2/MPA) via {src}")


# ---- Satellites (Celestrak + SGP4) ------------------------------------------------
def _gmst_deg(jd: float, fr: float) -> float:
    t = ((jd - 2451545.0) + fr) / 36525.0
    gmst = 67310.54841 + (876600.0 * 3600 + 8640184.812866) * t + 0.093104 * t * t - 6.2e-6 * t ** 3
    return (gmst / 240.0) % 360.0  # seconds of time -> degrees


def _teme_to_geodetic(x: float, y: float, z: float, gmst_deg: float) -> tuple[float, float, float]:
    g = math.radians(gmst_deg)
    xe = x * math.cos(g) + y * math.sin(g)
    ye = -x * math.sin(g) + y * math.cos(g)
    ze = z
    a, f = 6378.137, 1 / 298.257223563
    e2 = f * (2 - f)
    lon = math.degrees(math.atan2(ye, xe))
    r = math.hypot(xe, ye)
    lat = math.atan2(ze, r)
    for _ in range(5):
        sl = math.sin(lat)
        c = a / math.sqrt(1 - e2 * sl * sl)
        lat = math.atan2(ze + c * e2 * sl, r)
    sl = math.sin(lat)
    c = a / math.sqrt(1 - e2 * sl * sl)
    alt = r / math.cos(lat) - c
    return math.degrees(lat), lon, alt


@register("sat_tle", interval_s=12 * 60 * 60, domain="em", description="Celestrak TLEs for GNSS, military and SBAS satellites (12h)")
async def collect_sat_tle(ctx: Context) -> Result:
    groups = {}
    for g in SAT_GROUPS:
        text = await get_text(ctx, CELESTRAK.format(group=g), timeout=60)
        lines = [l.rstrip() for l in text.splitlines() if l.strip()]
        tles = []
        for i in range(0, len(lines) - 2, 3):
            name, l1, l2 = lines[i].strip(), lines[i + 1], lines[i + 2]
            if l1.startswith("1 ") and l2.startswith("2 "):
                tles.append([name, l1, l2])
        groups[g] = tles
    total = sum(len(v) for v in groups.values())
    if total == 0:
        raise RuntimeError("no TLEs parsed")
    ctx.db.set_snapshot("sat_tle", {"fetched_at": iso(datetime.now(timezone.utc)), "groups": groups})
    return Result(total, ", ".join(f"{g} {len(v)}" for g, v in groups.items()))


@register("sats", interval_s=120, domain="em", description="Satellite sub-points from the cached TLEs (SGP4, every 2 min)")
async def collect_sats(ctx: Context) -> Result:
    from sgp4.api import Satrec, jday
    tle, _ = ctx.db.get_snapshot("sat_tle")
    if not tle:
        return Result(0, "no TLEs yet (sat_tle has not run)")
    now = datetime.now(timezone.utc)
    jd, fr = jday(now.year, now.month, now.day, now.hour, now.minute, now.second + now.microsecond / 1e6)
    gmst = _gmst_deg(jd, fr)
    pts = []
    bad = 0
    for group, tles in tle.get("groups", {}).items():
        for name, l1, l2 in tles:
            try:
                s = Satrec.twoline2rv(l1, l2)
                e, r, v = s.sgp4(jd, fr)
                if e != 0:
                    bad += 1
                    continue
                lat, lon, alt = _teme_to_geodetic(r[0], r[1], r[2], gmst)
                pts.append({"name": name, "norad": s.satnum, "group": group, "lat": round(lat, 2), "lon": round(lon, 2),
                            "alt_km": round(alt), "period_min": round(2 * math.pi / s.no_kozai) if s.no_kozai else None})
            except Exception:  # noqa: BLE001
                bad += 1
    ctx.db.set_snapshot("sats", {"computed_at": iso(now), "tle_fetched_at": tle.get("fetched_at"), "count": len(pts), "sats": pts})
    return Result(len(pts), f"{len(pts)} satellites positioned" + (f", {bad} failed" if bad else ""))


# ---- Curated strategic emitters (static) --------------------------------------------
def emitters_reference(path) -> list[dict]:
    import json
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for e in data:
        e["country_name"] = geo.name_of(e.get("country"))
    return data
