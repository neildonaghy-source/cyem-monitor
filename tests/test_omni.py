from app.omni import parse_freqs


def test_parse_freqs():
    assert parse_freqs("who uses 446.2125?") == [446.2125e6]
    assert parse_freqs("18 GHz links near Chichester") == [18e9]
    assert parse_freqs("clashes at 12.5 kHz spacing") == [12.5e3]
    assert parse_freqs("GNSS jamming in 2026 Baltic") == []
    assert parse_freqs("compare 150.0 and 150.1 MHz") == [150.0e6, 150.1e6]


def test_place_regex():
    from app.omni import _PLACE, _STOP
    names = [m.group(1) for m in _PLACE.finditer("jamming in GNSS near Chichester and around Newcastle upon Tyne")]
    assert "Chichester" in names and "Newcastle upon Tyne" in names
    assert names[0].split()[0] in _STOP
