"""Finding 13: the EMO examples are JSON files in data/emo_examples/ with a schema check. Every file must load clean,
every entity must pass EntityIn (the API's own model), and the checker must catch the usual mistakes."""
import copy
import json

import pytest

from app import emo_examples as ee


def test_every_example_file_loads_clean():
    files = sorted(p.stem for p in ee.DIR.glob("*.json"))
    assert ee.ERRORS == {}
    assert sorted(ee.EXAMPLES) == files and len(files) >= 11
    orders = [x["order"] for x in ee.EXAMPLES.values()]
    assert orders == sorted(orders) and len(set(orders)) == len(orders)
    assert list(ee.EXAMPLES)[:2] == ["sussex-coast", "corsham-hub"] and list(ee.EXAMPLES)[-3:] == ["cuas-vs-datalink", "amphib-studland", "subsurface-minches"]
    for k in ("bg-vignette", "solent-maritime", "uas-gnss"):
        assert ee.EXAMPLES[k]["corridor"]["mover"]


def test_every_entity_passes_the_api_model():
    from app.emo_api import EntityIn
    n = 0
    for k, ex in ee.EXAMPLES.items():
        names = {e["name"] for e in ex["entities"]}
        for e in ex["entities"]:
            EntityIn(**{a: b for a, b in e.items() if a != "net"})
            assert e.get("net") is None or e["net"] in names, (k, e["name"])
            n += 1
    assert n >= 300


def _base():
    return copy.deepcopy(ee.EXAMPLES["a303-gnss"])


@pytest.mark.parametrize("mutate, expect", [
    (lambda x: x.pop("title"), "missing 'title'"),
    (lambda x: x.update(colour="red"), "unknown field 'colour'"),
    (lambda x: x.update(zoom="10"), "'zoom' has the wrong type"),
    (lambda x: x.update(centre=[95, 0]), "'centre' must be"),
    (lambda x: x["entities"][0].update(side="green"), "'side' = 'green'"),
    (lambda x: x["entities"][0].update(lat=91), "'lat' = 91 outside"),
    (lambda x: x["entities"][0].update(eirp_dbm=True), "'eirp_dbm' has the wrong type"),
    (lambda x: x["entities"][0].update(power=10), "unknown field 'power'"),
    (lambda x: x["entities"][0].pop("freq_mhz"), "missing 'freq_mhz'"),
    (lambda x: x["entities"][1].update(net="Nobody"), "net 'Nobody' is not another entity"),
    (lambda x: x["entities"].append(copy.deepcopy(x["entities"][0])), "duplicate name"),
    (lambda x: x["entities"][-2].update(track=[[51.1]]), "track points"),
    (lambda x: x.update(corridor={"mover": "Nobody", "to": [51.0, -1.9], "domain": "ground"}), "mover 'Nobody'"),
    (lambda x: x.update(corridor={"mover": "Blue ES/DF north", "to": [51.0, -1.9], "domain": "space"}), "domain must be"),
])
def test_checker_catches_mistakes(mutate, expect):
    x = _base()
    assert ee.check(x, "a303-gnss") == []
    mutate(x)
    errs = ee.check(x, "a303-gnss")
    assert any(expect in e for e in errs), errs


def test_bad_file_is_left_out_not_fatal(tmp_path):
    good = _base()
    (tmp_path / "a303-gnss.json").write_text(json.dumps(good))
    bad = _base()
    bad["id"] = "broken"
    bad["entities"][0]["side"] = "green"
    (tmp_path / "broken.json").write_text(json.dumps(bad))
    (tmp_path / "junk.json").write_text("{not json")
    (tmp_path / "misnamed.json").write_text(json.dumps(good))
    ex, err = ee.load(tmp_path)
    assert list(ex) == ["a303-gnss"]
    assert set(err) == {"broken.json", "junk.json", "misnamed.json"}
    assert "does not match the file name" in err["misnamed.json"][0]
