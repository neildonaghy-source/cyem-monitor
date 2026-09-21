"""Curated RSS sources. Each entry: name, url, domain (cyber | em | infra | osint),
kind (news | advisory), base tags, and a default severity.

Google News query feeds are used where a topic has no good native RSS. They are
tagged 'gnews' so the UI can de-emphasise them if they get noisy."""
from __future__ import annotations


def gnews(q: str) -> str:
    from urllib.parse import quote_plus
    return f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-GB&gl=GB&ceid=GB:en"


FEEDS: list[dict] = [
    # ---- Cyber: official / advisory ---------------------------------------
    {"name": "CISA advisories", "url": "https://www.cisa.gov/cybersecurity-advisories/all.xml",
     "domain": "cyber", "kind": "advisory", "tags": ["advisory"], "severity": 3},
    {"name": "NCSC UK", "url": "https://www.ncsc.gov.uk/api/1/services/v1/all-rss-feed.xml",
     "domain": "cyber", "kind": "advisory", "tags": ["advisory", "uk"], "severity": 3},
    {"name": "NCSC UK reports", "url": "https://www.ncsc.gov.uk/api/1/services/v1/report-rss-feed.xml",
     "domain": "cyber", "kind": "advisory", "tags": ["advisory", "uk"], "severity": 3},
    {"name": "CERT-EU", "url": "https://cert.europa.eu/publications/security-advisories-rss",
     "domain": "cyber", "kind": "advisory", "tags": ["advisory"], "severity": 3},
    {"name": "Canadian Centre for Cyber Security", "url": "https://www.cyber.gc.ca/api/cccs/rss/v1/get?feed=alerts_advisories&lang=en",
     "domain": "cyber", "kind": "advisory", "tags": ["advisory"], "severity": 3},
    # ---- Cyber: news and research -----------------------------------------
    {"name": "The Record", "url": "https://therecord.media/feed", "domain": "cyber", "kind": "news", "tags": [], "severity": 2},
    {"name": "BleepingComputer", "url": "https://www.bleepingcomputer.com/feed/", "domain": "cyber", "kind": "news", "tags": [], "severity": 2},
    {"name": "Krebs on Security", "url": "https://krebsonsecurity.com/feed/", "domain": "cyber", "kind": "news", "tags": [], "severity": 2},
    {"name": "The Hacker News", "url": "https://feeds.feedburner.com/TheHackersNews", "domain": "cyber", "kind": "news", "tags": [], "severity": 2},
    {"name": "SecurityWeek", "url": "https://www.securityweek.com/feed/", "domain": "cyber", "kind": "news", "tags": [], "severity": 2},
    {"name": "Dark Reading", "url": "https://www.darkreading.com/rss.xml", "domain": "cyber", "kind": "news", "tags": [], "severity": 2},
    {"name": "CyberScoop", "url": "https://cyberscoop.com/feed/", "domain": "cyber", "kind": "news", "tags": [], "severity": 2},
    {"name": "Risky Business News", "url": "https://news.risky.biz/feed", "domain": "cyber", "kind": "news", "tags": [], "severity": 2},
    {"name": "Microsoft Security", "url": "https://www.microsoft.com/en-us/security/blog/feed/", "domain": "cyber", "kind": "news", "tags": ["research"], "severity": 2},
    {"name": "Unit 42", "url": "https://unit42.paloaltonetworks.com/feed/", "domain": "cyber", "kind": "news", "tags": ["research"], "severity": 2},
    {"name": "SANS ISC", "url": "https://isc.sans.edu/rssfeed_full.xml", "domain": "cyber", "kind": "news", "tags": ["research"], "severity": 2},
    {"name": "Cisco Talos", "url": "https://blog.talosintelligence.com/rss/", "domain": "cyber", "kind": "news", "tags": ["research"], "severity": 2},
    {"name": "ESET WeLiveSecurity", "url": "https://www.welivesecurity.com/en/rss/feed/", "domain": "cyber", "kind": "news", "tags": ["research"], "severity": 2},
    {"name": "Schneier on Security", "url": "https://www.schneier.com/feed/atom/", "domain": "cyber", "kind": "news", "tags": ["opinion"], "severity": 1},
    {"name": "Google News: UK cyber attack", "url": gnews('("cyber attack" OR cyberattack OR ransomware) UK when:2d'),
     "domain": "cyber", "kind": "news", "tags": ["gnews", "uk"], "severity": 2},
    # ---- EM / spectrum / EW / space ---------------------------------------
    {"name": "C4ISRNET", "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/?outputType=xml", "domain": "em", "kind": "news", "tags": ["defence"], "severity": 2},
    {"name": "C4ISRNET electronic warfare", "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/category/electronic-warfare/?outputType=xml",
     "domain": "em", "kind": "news", "tags": ["defence", "ew"], "severity": 2},
    {"name": "Breaking Defense", "url": "https://breakingdefense.com/feed/", "domain": "em", "kind": "news", "tags": ["defence"], "severity": 2},
    {"name": "Defense News", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml", "domain": "em", "kind": "news", "tags": ["defence"], "severity": 2},
    {"name": "The War Zone", "url": "https://www.twz.com/feed", "domain": "em", "kind": "news", "tags": ["defence"], "severity": 2},
    {"name": "Janes (via Google News)", "url": gnews("site:janes.com when:3d"), "domain": "em", "kind": "news", "tags": ["defence", "gnews"], "severity": 2},
    {"name": "RNT Foundation", "url": "https://rntfnd.org/feed/", "domain": "em", "kind": "news", "tags": ["gnss"], "severity": 2},
    {"name": "GPS World (via Google News)", "url": gnews("site:gpsworld.com when:7d"), "domain": "em", "kind": "news", "tags": ["gnss", "gnews"], "severity": 1},
    {"name": "Inside GNSS", "url": "https://insidegnss.com/feed/", "domain": "em", "kind": "news", "tags": ["gnss"], "severity": 1},
    {"name": "SpaceNews", "url": "https://spacenews.com/feed/", "domain": "em", "kind": "news", "tags": ["space"], "severity": 1},
    {"name": "Google News: GNSS jamming", "url": gnews('("GPS jamming" OR "GNSS jamming" OR "GPS spoofing" OR "GNSS spoofing" OR "GPS interference") when:2d'),
     "domain": "em", "kind": "news", "tags": ["gnews", "gnss"], "severity": 2},
    {"name": "Google News: electronic warfare", "url": gnews('("electronic warfare" OR "signal jamming" OR "radar jamming" OR "spectrum warfare" OR EMSO) when:2d'),
     "domain": "em", "kind": "news", "tags": ["gnews", "ew"], "severity": 2},
    {"name": "Google News: satellite interference", "url": gnews('("satellite jamming" OR "SATCOM" OR "Starlink jamming" OR "satellite interference" OR "anti-satellite") when:3d'),
     "domain": "em", "kind": "news", "tags": ["gnews", "satcom"], "severity": 2},
    {"name": "Google News: space weather", "url": gnews('("solar flare" OR "geomagnetic storm" OR "coronal mass ejection" OR "radio blackout") when:2d'),
     "domain": "em", "kind": "news", "tags": ["gnews", "space-weather"], "severity": 1},
    # ---- Internet infrastructure ------------------------------------------
    {"name": "Submarine Networks", "url": "https://www.submarinenetworks.com/en/?format=feed&type=rss", "domain": "infra", "kind": "news", "tags": ["cable"], "severity": 1},
    {"name": "Submarine Telecoms Forum", "url": "https://subtelforum.com/feed/", "domain": "infra", "kind": "news", "tags": ["cable"], "severity": 1},
    {"name": "Cloudflare blog", "url": "https://blog.cloudflare.com/rss/", "domain": "infra", "kind": "news", "tags": [], "severity": 1},
    {"name": "APNIC blog", "url": "https://blog.apnic.net/feed/", "domain": "infra", "kind": "news", "tags": [], "severity": 1},
    {"name": "Google News: subsea cable", "url": gnews('("undersea cable" OR "subsea cable" OR "submarine cable") (cut OR damaged OR sabotage OR fault OR repair) when:3d'),
     "domain": "infra", "kind": "news", "tags": ["gnews", "cable"], "severity": 2},
    {"name": "Google News: internet outage", "url": gnews('("internet outage" OR "internet shutdown" OR "internet blackout" OR "network outage") when:1d'),
     "domain": "infra", "kind": "news", "tags": ["gnews", "outage"], "severity": 2},
    {"name": "Google News: BGP hijack", "url": gnews('("BGP hijack" OR "route leak" OR "BGP leak" OR "DNS hijack") when:3d'),
     "domain": "infra", "kind": "news", "tags": ["gnews", "bgp"], "severity": 2},
    # ---- OSINT / context ----------------------------------------------------
    {"name": "Bellingcat", "url": "https://www.bellingcat.com/feed/", "domain": "osint", "kind": "news", "tags": ["osint"], "severity": 1},
    {"name": "Google News: hybrid threats", "url": gnews('("hybrid warfare" OR "hybrid threat" OR sabotage OR "grey zone") (NATO OR Europe OR Baltic OR UK) when:2d'),
     "domain": "osint", "kind": "news", "tags": ["gnews"], "severity": 2},
]
