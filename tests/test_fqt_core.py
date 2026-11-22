"""Spectrum by frequency and time: pure helpers (phase 6 part 4)."""
from app import fqt_core as f


def test_default_band():
    assert f.default_band(51.325) == (30.0, 88.0) and f.default_band(252.4) == (225.0, 400.0)
    assert f.default_band(2350.0) == (2115.0, 2585.0)


def test_channels_grid_and_thinning():
    ch = f.channels(30.0, 30.2, 25)
    assert len(ch) == 8 and all(abs(b - a - 0.025) < 1e-9 for a, b in zip(ch, ch[1:]))
    assert ch[0] == 30.0125 and ch[-1] == 30.1875
    big = f.channels(30.0, 88.0, 25)                        # 2320 channels thinned to about 48, ends kept
    assert 40 <= len(big) <= 49 and big[0] == 30.0125 and big[-1] == 87.9875
    assert f.channels(30.0, 30.01, 25) == [30.005]          # narrower than one channel
    assert len(f.channels(225, 400, 25, step_khz=5000)) == 35


def test_overlap_and_status():
    assert f.overlaps(51.325, 25, 40, 60) and not f.overlaps(61.0, 25, 40, 60)
    assert f.overlaps(60.01, 25, 40, 60)                     # half in the barrage
    assert f.net_status([None, None], 0) == ("clear", None)
    assert f.net_status([-20.0, -3.0], 0) == ("degraded", -3.0)
    assert f.net_status([-20.0, 1.0], 0) == ("denied", 1.0)


def test_rank():
    a = {"f_mhz": 31, "usable_steps": 5, "worst_js_db": -20, "conflicts": {"own": [], "civil": [], "wtr": {"count": 3}}}
    b = {"f_mhz": 32, "usable_steps": 5, "worst_js_db": -25, "conflicts": {"own": ["Blue X"], "civil": [], "wtr": {"count": 0}}}
    c = {"f_mhz": 33, "usable_steps": 4, "worst_js_db": None, "conflicts": {}}
    d = {"f_mhz": 34, "usable_steps": 5, "worst_js_db": None, "conflicts": {"own": [], "civil": [], "wtr": {"count": 0}}}
    assert [x["f_mhz"] for x in sorted([a, b, c, d], key=f.rank_key)] == [34, 31, 32, 33]
