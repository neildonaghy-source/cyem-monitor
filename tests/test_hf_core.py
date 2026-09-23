import math

from app.hf_core import elevation_deg, hop_muf, idw, max_hop_km, plan, sec_incidence


def test_geometry_textbook_values():
    assert 3000 < max_hop_km(300) < 3700                 # ~3,400 km single F-layer hop at 3 deg
    assert max_hop_km(400) > max_hop_km(250)
    assert math.isclose(elevation_deg(3000, 300), 4.3, abs_tol=0.3)
    assert elevation_deg(100, 300) > 75                  # NVIS: near-vertical
    assert 3.0 < sec_incidence(3000, 300) < 3.6          # classic M(3000) factor range


def test_hop_muf_scaling():
    assert math.isclose(hop_muf(24.0, 3000, 300), 24.0, rel_tol=1e-9)
    nvis = hop_muf(7.0 * sec_incidence(3000, 300), 50, 300)
    assert math.isclose(nvis, 7.0, rel_tol=0.03)         # vertical incidence -> ~foF2
    assert hop_muf(24.0, 1500, 300) < 24.0 < hop_muf(24.0, 3400, 300)


def _st(name, lat, lon, fof2, mufd, h=280.0):
    return {"name": name, "lat": lat, "lon": lon, "fof2": fof2, "mufd": mufd, "hmf2": h}


def test_idw_prefers_nearest():
    s = [_st("near", 51, 0, 8.0, 25.0), _st("far", 60, 20, 4.0, 12.0)]
    v, src = idw(s, 51.1, 0.1, "fof2")
    assert 7.5 < v <= 8.0 and src[0][0] == "near"
    assert idw(s, -40, 150, "fof2")[0] is None


def test_plan_rates_frequencies_and_hops():
    stations = [_st("uk", 51.5, -1.0, 7.0, 23.0), _st("de", 54.6, 13.4, 7.2, 24.0), _st("es", 37.1, -6.7, 8.0, 25.0)]
    r = plan(50.8, -0.8, 52.5, 13.4, stations, [3.5, 7.0, 14.0, 21.0, 28.0])     # Chichester to Berlin, ~1,000 km
    assert r["hops"] == 1 and 900 < r["distance_km"] < 1100
    st = {f["mhz"]: f["status"] for f in r["frequencies"]}
    assert st[28.0] == "above MUF" and st[7.0] == "good"
    long = plan(50.8, -0.8, 40.7, -74.0, stations, [14.0])                          # to New York: several hops
    assert long["hops"] >= 2 and long["coverage_ok"] is False                        # mid-Atlantic has no stations
    assert plan(50.8, -0.8, 51.0, -1.0, stations, [5.0])["mode"] == "NVIS"
