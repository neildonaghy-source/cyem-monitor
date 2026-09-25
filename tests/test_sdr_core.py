from app.sdr_core import find_peaks, noise_floor


def _spectrum():
    import random
    random.seed(1)
    db = [-100 + random.uniform(-2, 2) for _ in range(2000)]
    for i in range(500, 504):          # a 4-bin signal at 20 dB SNR
        db[i] = -80
    db[1500] = -60                     # a narrow strong carrier
    return db


def test_floor_ignores_carriers():
    fl = noise_floor(_spectrum())
    assert -102 < fl[500] < -98 and -102 < fl[1500] < -98


def test_peaks_found_merged_and_sorted():
    p = find_peaks(100e6, 25e3, _spectrum(), snr_db=10)
    assert len(p) == 2
    assert abs(p[0]["f_hz"] - (100e6 + 1500 * 25e3)) < 1 and p[0]["snr_db"] > 35
    assert p[1]["width_hz"] == 4 * 25e3 and 99.9e6 + 500 * 25e3 < p[1]["f_hz"] < 100.1e6 + 504 * 25e3


def test_band_classification():
    from app.sdr_classify import band_for, verdict
    assert band_for(433.92e6)[0] == "exempt"            # ISM wins over the wider 70 cm amateur band
    assert band_for(145.5e6)[0] == "class"
    assert band_for(1090e6)[1].startswith("Aeronautical radionavigation")
    assert band_for(390e6)[0] == "government"
    assert band_for(460e6) is None
    assert verdict(None, [])[0] == "unexplained"
    assert verdict(band_for(460e6), [{"x": 1}])[0] == "licensed"
