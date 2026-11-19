"""Reference data (audit of 19 Nov 2026): ids unique, coordinates in range, country words resolve to the right state."""
import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def _load(name):
    d = json.loads((DATA / name).read_text(encoding="utf-8"))
    return d if isinstance(d, list) else d.get("emitters") or d.get("groups") or d


def test_emitters_and_groups_are_well_formed():
    for name in ("emitters.json", "apt_groups.json"):
        recs = _load(name)
        ids = [r["id"] for r in recs]
        assert len(ids) == len(set(ids)), f"duplicate ids in {name}"
        for r in recs:
            if r.get("lat") is not None:
                assert -90 <= r["lat"] <= 90 and -180 <= r["lon"] <= 180, r["id"]
    for g in _load("apt_groups.json"):
        assert g.get("mitre") is None or re.fullmatch(r"G\d{4}", g["mitre"]), g["id"]


def test_country_words_go_to_the_state_people_mean():
    from app import geo
    cases = {"Indian navy": "IN", "Chinese hackers": "CN", "French ministry": "FR", "Norwegian government": "NO",
             "Dominican election": "DO", "American officials": "US", "Hong Kong protest": "HK", "Belgrade talks": "RS"}
    for text, iso in cases.items():
        assert geo.detect_countries(text)[:1] == [iso], text
    _, terms = geo._detector()
    assert not any(v in geo.TERRITORIES for k, v in terms.items()
                   if k in {"Indian", "Chinese", "French", "Norwegian", "American"})
    assert "CS" not in geo.countries()
