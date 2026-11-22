"""Notional EMO scenarios, one JSON file each in data/emo_examples/ (finding 13). Generic textbook equipment values
at public locations; editable once loaded. 'net' names another entity in the same file and is resolved on load.
'order' sets the place in the examples list. SIDCs are APP-6B / 2525B letter form.

Each file is checked against SCHEMA on load. A file that fails is left out of EXAMPLES and its errors are kept in
ERRORS (and logged), so one bad edit cannot take the examples list down; tests/test_emo_examples.py fails on any error.
Stdlib only."""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)
DIR = Path(__file__).resolve().parent.parent / "data" / "emo_examples"

NUM = (int, float)
OPT_STR = (str, type(None))
# entity field -> (types,) or (types, lo, hi), bounds inclusive. Mirrors emo_api.EntityIn (the test also runs every
# entity through EntityIn, which stays the authority).
ENTITY = {
    "name": ((str,),), "side": ((str,),), "kind": ((str,),), "category": (OPT_STR,),
    "lat": (NUM, -85, 85), "lon": (NUM, -180, 180), "h_agl": (NUM, 0, 15000), "freq_mhz": (NUM, 1, 100_000),
    "bw_khz": (NUM, 0, 2_000_000), "f_hi_mhz": (NUM + (type(None),), 1, 100_000), "eirp_dbm": (NUM + (type(None),), -30, 120),
    "fixed_level_dbm": (NUM + (type(None),), -180, 0), "sens_dbm": (NUM + (type(None),), -170, 0),
    "js_req_db": (NUM + (type(None),), -30, 80), "df_rms_deg": (NUM + (type(None),), 0, 30),
    "pattern": ((str,),), "azimuth": (NUM + (type(None),), 0, 360), "beamwidth": (NUM + (type(None),), 1, 180),
    "net": (OPT_STR,), "active": ((bool,),), "radius_km": (NUM + (type(None),), 0.5, 100), "sidc": (OPT_STR,),
    "track": ((list, type(None)),), "speed_kmh": (NUM + (type(None),), 0, 2000), "notes": (OPT_STR,),
    "hop_bw_khz": (NUM + (type(None),), 0, 2_000_000), "pg_db": (NUM + (type(None),), 0, 60),
    "schedule": ((list, type(None)),), "rcs_m2": (NUM + (type(None),), 0, 1e6), "ea_mode": (OPT_STR,),
}
REQUIRED = ("name", "side", "kind", "lat", "lon", "freq_mhz")
ENUMS = {"side": ("blue", "red", "grey"), "kind": ("emitter", "receiver", "sensor", "effector"),
         "pattern": ("omni", "sector"), "ea_mode": ("noise", "spoof")}
TOP = {"id": (str,), "order": (int,), "title": (str,), "about": (str,), "centre": (list,), "zoom": (int,),
       "params": (dict,), "corridor": (dict,), "entities": (list,)}
TOP_REQUIRED = ("id", "title", "about", "centre", "zoom", "entities")
CORRIDOR = {"mover": (str,), "to": (list,), "domain": (str,), "step_min": NUM, "alt_m": NUM, "speed_kmh": NUM,
            "note": (str,)}
SCHEMA = {"top": TOP, "entity": ENTITY, "corridor": CORRIDOR}


def _latlon(p) -> bool:
    return (isinstance(p, list) and len(p) == 2 and all(isinstance(x, NUM) and not isinstance(x, bool) for x in p)
            and -85 <= p[0] <= 85 and -180 <= p[1] <= 180)


def _typed(v, types) -> bool:
    if isinstance(v, bool) and bool not in types:
        return False                         # True is an int in Python; not a number here
    return isinstance(v, types)


def check(ex: dict, stem: str | None = None) -> list[str]:
    """Schema and cross-reference errors for one example (empty list if it is sound)."""
    if not isinstance(ex, dict):
        return ["not a JSON object"]
    err = []
    for k in TOP_REQUIRED:
        if k not in ex:
            err.append(f"missing '{k}'")
    for k, v in ex.items():
        if k not in TOP:
            err.append(f"unknown field '{k}'")
        elif not _typed(v, TOP[k]):
            err.append(f"'{k}' has the wrong type")
    if err:
        return err
    if stem is not None and ex["id"] != stem:
        err.append(f"id '{ex['id']}' does not match the file name '{stem}'")
    if not _latlon(ex["centre"]):
        err.append("'centre' must be [lat, lon]")
    if not 1 <= ex["zoom"] <= 18:
        err.append("'zoom' out of range")
    names = {}
    for i, e in enumerate(ex["entities"]):
        where = f"entity {i}"
        if not isinstance(e, dict):
            err.append(f"{where}: not an object")
            continue
        where = f"entity {i} ({e.get('name', '?')})"
        for k in REQUIRED:
            if k not in e:
                err.append(f"{where}: missing '{k}'")
        for k, v in e.items():
            spec = ENTITY.get(k)
            if spec is None:
                err.append(f"{where}: unknown field '{k}'")
                continue
            types, *rng = spec
            if not _typed(v, types):
                err.append(f"{where}: '{k}' has the wrong type")
            elif rng and isinstance(v, NUM) and not isinstance(v, bool) and not rng[0] <= v <= rng[1]:
                err.append(f"{where}: '{k}' = {v} outside {rng[0]} to {rng[1]}")
            elif k in ENUMS and v is not None and v not in ENUMS[k]:
                err.append(f"{where}: '{k}' = '{v}' is not one of {', '.join(ENUMS[k])}")
        if isinstance(e.get("name"), str):
            if not 1 <= len(e["name"]) <= 60:
                err.append(f"{where}: name must be 1 to 60 characters")
            if e["name"] in names:
                err.append(f"{where}: duplicate name")
            names[e["name"]] = e
        for p in e.get("track") or []:
            if not _latlon(p):
                err.append(f"{where}: track points must be [lat, lon]")
                break
        for w in e.get("schedule") or []:
            if not (isinstance(w, list) and len(w) == 2 and all(isinstance(x, NUM) for x in w) and w[0] < w[1]):
                err.append(f"{where}: schedule windows must be [start_min, end_min]")
                break
        if e.get("kind") == "sensor" and isinstance(e.get("f_hi_mhz"), NUM) and e["f_hi_mhz"] < e.get("freq_mhz", 0):
            err.append(f"{where}: f_hi_mhz below freq_mhz")
        if isinstance(e.get("notes"), str) and len(e["notes"]) > 300:
            err.append(f"{where}: notes over 300 characters")
    for n, e in names.items():
        net = e.get("net")
        if net is not None and (net not in names or net == n):
            err.append(f"entity ({n}): net '{net}' is not another entity in this example")
    c = ex.get("corridor")
    if c is not None:
        for k, v in c.items():
            if k not in CORRIDOR:
                err.append(f"corridor: unknown field '{k}'")
            elif not _typed(v, CORRIDOR[k]):
                err.append(f"corridor: '{k}' has the wrong type")
        if c.get("mover") not in names:
            err.append(f"corridor: mover '{c.get('mover')}' is not an entity in this example")
        if not _latlon(c.get("to")):
            err.append("corridor: 'to' must be [lat, lon]")
        if c.get("domain") not in ("ground", "sea", "air"):
            err.append("corridor: domain must be ground, sea or air")
    return err


def load(directory: Path = DIR) -> tuple[dict, dict]:
    """(examples by id in 'order', errors by file name). Invalid files are left out of the examples."""
    good, errors = [], {}
    for f in sorted(Path(directory).glob("*.json")):
        try:
            ex = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            errors[f.name] = [f"unreadable: {e}"]
            continue
        bad = check(ex, f.stem)
        if bad:
            errors[f.name] = bad
            continue
        good.append(ex)
    good.sort(key=lambda x: (x.get("order", 1_000_000), x["id"]))
    for name, bad in errors.items():
        log.warning("EMO example %s left out: %s", name, "; ".join(bad[:5]))
    return {x["id"]: x for x in good}, errors


EXAMPLES, ERRORS = load()
