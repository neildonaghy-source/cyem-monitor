"""Unit tests for the 18 Nov 2026 audit fixes (findings 1, 2, 6, 10): pure functions, no terrain or database."""
import math


def _link(rid, side, linked, status="linked"):
    return {"receiver_id": rid, "receiver": rid, "side": side, "linked": linked, "status": status}


def test_link_status_rules():
    from app.emo_api import link_status
    assert link_status(None, None, -110) == ("control off air", False)            # control deleted or missing
    assert link_status({"active": False}, -50.0, -110) == ("control off air", False)
    assert link_status({"active": True}, -120.0, -110) == ("out of range", False)
    assert link_status({"active": True}, None, -110) == ("out of range", False)
    assert link_status({"active": True}, -110.0, -110) == ("linked", True)        # at sensitivity: just holds


def test_net_availability_needs_own_link_as_well_as_no_jamming():
    from app.emo_api import scoreboard
    links = [_link("u1", "blue", True), _link("u2", "blue", False, "out of range"),
             _link("u3", "blue", True), _link("u4", "blue", False, "control off air"), _link("r1", "red", True)]
    jamming = [{"victim_id": "u3", "victim": "u3", "status": "denied", "effector_side": "red", "collateral": False}]
    sc = scoreboard([], [], [], jamming, [], [], links)
    assert sc["blue"]["net_availability_pct"] == 25          # only u1: u2 out of range, u3 denied, u4 control off air
    assert sc["blue"]["net_users_unlinked"] == 2
    assert sc["red"]["net_availability_pct"] == 100 and sc["red"]["denial_achieved"] == 1


def test_scoreboard_old_basis_when_links_absent():
    from app.emo_api import scoreboard
    ents = [{"id": "a", "name": "a", "side": "blue", "kind": "receiver", "active": True},
            {"id": "b", "name": "b", "side": "blue", "kind": "receiver", "active": True}]
    jam = [{"victim_id": "b", "victim": "b", "status": "denied", "effector_side": "red", "collateral": False}]
    assert scoreboard(ents, [], [], jam, [], [])["blue"]["net_availability_pct"] == 50


def test_burnthrough_law_by_jamming_mode():
    from app.emo_api import burnthrough_km
    # self-screening: J/S ~ R^2, so 20 dB at 100 km burns through at 10 km
    assert burnthrough_km(100_000, 20, "self-screening") == 10.0
    # fixed-position jammer (stand-off or main lobe): J/S ~ R^4, so 20 dB at 100 km burns through at 31.6 km
    assert burnthrough_km(100_000, 20, "stand-off (sidelobe)") == 31.6
    assert burnthrough_km(100_000, 20, "mainlobe") == 31.6
    assert burnthrough_km(100_000, 0, "self-screening") is None and burnthrough_km(100_000, -3, "mainlobe") is None
    # the old single law overstated the self-screening range by about 3x at 20 dB
    assert math.isclose(burnthrough_km(100_000, 20, "mainlobe") / burnthrough_km(100_000, 20, "self-screening"), 3.16, abs_tol=0.01)


def test_one_model_caveat_names_what_is_and_is_not_modelled():
    from app.emo_api import MODEL_CAVEAT
    for word in ("hopping", "processing gain", "least squares", "self-screening", "Not modelled", "ducting", "clutter"):
        assert word in MODEL_CAVEAT
    assert "Radar modelled as an emitter for ES only" not in MODEL_CAVEAT


def test_login_redirect_stays_on_site():
    from app.auth import safe_next
    assert safe_next("/") == "/" and safe_next("/emo?x=1") == "/emo?x=1"
    for bad in ("//evil.example", "/\\evil.example", "https://evil.example", "javascript:alert(1)", "", None,
                "/\tx", "/\\", "evil.example"):
        assert safe_next(bad) == "/", bad
