"""Classify SDR peaks against public data: individual Ofcom licences nearby (WTR), licence-exempt and class-licensed
bands, public-service bands (with live air/ship/cell context) and government bands. No demodulation.

Band table is reference data from the UK FAT, IR 2030 (licence exemption) and the amateur band plan as understood in
2026: verify against current Ofcom publications before relying on it for anything formal."""
from __future__ import annotations

import math

# (lo_MHz, hi_MHz, category, label)  category: exempt | class | public | government
BANDS = [
    (26.957, 27.283, "exempt", "CB radio 27 MHz / ISM 27.12 MHz"),
    (28.0, 29.7, "class", "Amateur 10 m"),
    (40.66, 40.70, "exempt", "ISM / short-range devices 40.68 MHz"),
    (49.82, 49.98, "exempt", "Short-range devices (e.g. baby monitors)"),
    (50.0, 52.0, "class", "Amateur 6 m"),
    (70.0, 70.5, "class", "Amateur 4 m"),
    (87.5, 108.0, "public", "FM broadcast"),
    (108.0, 117.975, "public", "Aeronautical navigation (VOR/ILS)"),
    (117.975, 137.0, "public", "Aeronautical voice (airband)"),
    (137.0, 138.0, "public", "Weather and space-operation satellites"),
    (144.0, 146.0, "class", "Amateur 2 m"),
    (156.0, 162.05, "public", "Maritime VHF (incl. AIS 161.975/162.025)"),
    (174.0, 240.0, "public", "DAB digital radio (Band III)"),
    (225.0, 380.0, "government", "Military UHF (NATO)"),
    (380.0, 400.0, "government", "Emergency services TETRA"),
    (430.0, 440.0, "class", "Amateur 70 cm"),
    (433.05, 434.79, "exempt", "ISM / short-range devices 433 MHz"),
    (446.0, 446.2, "exempt", "PMR446 licence-free radio"),
    (470.0, 694.0, "public", "Digital terrestrial TV"),
    (703.0, 733.0, "public", "Mobile network 700 MHz (uplink)"),
    (758.0, 788.0, "public", "Mobile network 700 MHz (downlink)"),
    (791.0, 821.0, "public", "Mobile network 800 MHz (downlink)"),
    (832.0, 862.0, "public", "Mobile network 800 MHz (uplink)"),
    (863.0, 870.0, "exempt", "Short-range devices 868 MHz (LoRa, alarms, meters)"),
    (880.0, 915.0, "public", "Mobile network 900 MHz (uplink)"),
    (925.0, 960.0, "public", "Mobile network 900 MHz (downlink)"),
    (960.0, 1215.0, "public", "Aeronautical radionavigation (DME, SSR, ADS-B 1090)"),
    (1164.0, 1300.0, "public", "GNSS L2/L5/E6"),
    (1240.0, 1325.0, "class", "Amateur 23 cm"),
    (1452.0, 1492.0, "public", "Mobile network L-band (downlink)"),
    (1559.0, 1610.0, "public", "GNSS L1/E1"),
    (1710.0, 1785.0, "public", "Mobile network 1800 MHz (uplink)"),
]
CAT_TEXT = {"exempt": "Licence-exempt", "class": "Class licence (amateur)", "public": "Public service",
            "government": "Government (not in public licence data)"}


def band_for(f_hz: float) -> tuple[str, str] | None:
    f = f_hz / 1e6
    hits = [b for b in BANDS if b[0] <= f <= b[1]]
    if not hits:
        return None
    b = min(hits, key=lambda x: x[1] - x[0])          # the most specific band wins (e.g. 433 ISM inside 70 cm)
    return b[2], b[3]


def haversine_km(a_lat, a_lon, b_lat, b_lon):
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dl = math.radians(b_lon - a_lon)
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(x))


def bearing(a_lat, a_lon, b_lat, b_lon):
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dl = math.radians(b_lon - a_lon)
    return (math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) + 360) % 360


def verdict(band: tuple[str, str] | None, licences: list) -> tuple[str, str]:
    """Overall status for a peak. Individual licence match wins; then the band category; else unexplained."""
    if licences:
        return "licensed", "Licensed (individual assignment nearby)"
    if band:
        return band[0], CAT_TEXT[band[0]]
    return "unexplained", "Unexplained: no nearby licence and no exempt/public band"
