"""Space weather by time step (phase 4 part 2)."""
from datetime import datetime, timedelta, timezone

import pytest

from app import spacewx_core as s

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def snap(g=0, r=0, s_=0, pred=None):
    return {"fetched_at": NOW.isoformat().replace("+00:00", "Z"), "kp": {"value": 3.0, "time": NOW.isoformat()},
            "scales": {"now": {"G": {"level": str(g)}, "R": {"level": str(r)}, "S": {"level": str(s_)}},
                       "predicted": pred or {"1": {"date": "2026-11-23", "G": "3", "R_minor_prob": "60", "R_major_prob": "10", "S_prob": "5"}}}}


def test_sun_elevation():
    assert s.sun_elevation_deg(51.5, 0.0, NOW) == pytest.approx(18.4, abs=0.7)          # London, noon, 22 Nov (90-51.5-20.2)
    assert s.sun_elevation_deg(51.5, 0.0, NOW.replace(hour=0)) < -50
    assert s.sun_elevation_deg(0.0, 0.0, datetime(2026, 3, 20, 12, 7, tzinfo=timezone.utc)) > 88


def test_levels_now_forecast_and_unknown():
    assert s.levels_at(None, NOW)["source"] == "none"
    assert s.levels_at(snap(g=2), NOW + timedelta(hours=5))["g"] == 2
    f = s.levels_at(snap(), datetime(2026, 11, 23, 9, tzinfo=timezone.utc))
    assert f["source"] == "forecast 2026-11-23" and (f["g"], f["r"], f["s"]) == (3, 1, 0)
    assert s.levels_at(snap(), NOW + timedelta(days=9))["source"] == "none"


def test_quiet_day_is_normal():
    st = s.at_time(snap(), NOW, 51.2, -1.9)
    assert st["hf"]["status"] == "normal" and st["gnss"]["loss_db"] == 0 and st["sunlit"]


def test_flare_blacks_out_the_sunlit_side_only():
    day = s.at_time(snap(r=3), NOW, 51.2, -1.9)
    night = s.at_time(snap(r=3), NOW.replace(hour=17, minute=30), 51.2, -1.9)
    assert day["hf"]["status"] == "blackout" and day["gnss"]["loss_db"] == 3.0
    assert night["hf"]["status"] == "normal" and night["gnss"]["loss_db"] == 0


def test_storm_degrades_gnss_more_at_high_latitude_and_polar_absorption():
    mid = s.at_time(snap(g=4), NOW, 51.2, -1.9)
    north = s.at_time(snap(g=4, s_=1), NOW, 68.0, 14.0)
    assert mid["gnss"]["loss_db"] == 5.0 and mid["hf"]["status"] == "degraded"
    assert north["gnss"]["loss_db"] == 7.5 and any("polar cap" in n for n in north["hf"]["notes"])
    assert "G4" in mid["text"] and "5 dB lower" in mid["text"]


def test_steps_follow_the_clock():
    out = s.steps(snap(r=2), NOW.replace(hour=15), [0, 90, 150], 51.2, -1.9)
    assert [x["hf"]["status"] for x in out] == ["degraded", "normal", "normal"]           # sunset about 16:05 UTC
    assert out[0]["sunlit"] and not out[1]["sunlit"]
    assert out[0]["source"] == "now"
