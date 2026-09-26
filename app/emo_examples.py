"""Notional EMO scenarios: generic textbook equipment values at public locations. Editable once
loaded. SIDCs are generic APP-6 (2525C letter form) frames: friend/hostile, land, air or sea surface;
set exact function codes per entity if wanted. 'net' names another entity and is resolved on load."""

FL, HL = "SFGPU----------", "SHGPU----------"     # land unit
FA, HA = "SFAP-----------", "SHAP-----------"     # air
FS, HS = "SFSP-----------", "SHSP-----------"     # sea surface


def em(name, side, cat, lat, lon, h, f, bw, eirp, **kw):
    return dict(name=name, side=side, kind="emitter", category=cat, lat=lat, lon=lon, h_agl=h, freq_mhz=f, bw_khz=bw,
                eirp_dbm=eirp, sidc=kw.pop("sidc", FL if side == "blue" else HL), **kw)


def rx(name, side, net, lat, lon, h, f, bw, eirp=None, **kw):
    return dict(name=name, side=side, kind="receiver", net=net, lat=lat, lon=lon, h_agl=h, freq_mhz=f, bw_khz=bw,
                eirp_dbm=eirp, sidc=kw.pop("sidc", FL if side == "blue" else HL), **kw)


def es(name, side, lat, lon, h, lo, hi, sens, df=None, **kw):
    return dict(name=name, side=side, kind="sensor", category="df" if df else "es", lat=lat, lon=lon, h_agl=h,
                freq_mhz=lo, f_hi_mhz=hi, bw_khz=25, sens_dbm=sens, df_rms_deg=df,
                sidc=kw.pop("sidc", FL if side == "blue" else HL), **kw)


def ea(name, side, cat, lat, lon, h, f, bw, eirp, **kw):
    return dict(name=name, side=side, kind="effector", category=cat, lat=lat, lon=lon, h_agl=h, freq_mhz=f, bw_khz=bw,
                eirp_dbm=eirp, sidc=kw.pop("sidc", FL if side == "blue" else HL), **kw)


B, R = "blue", "red"
VB, VR = 51.325, 45.200          # notional blue and red VHF net frequencies (MHz)

VIGNETTE = [
    # ---- blue battlegroup (east)
    em("Blue BG Main HQ", B, "comms", 51.205, -1.780, 8, VB, 25, 47, sens_dbm=-110, js_req_db=0, radius_km=30),
    rx("Blue Step-up HQ", B, "Blue BG Main HQ", 51.225, -1.830, 6, VB, 25, 44, radius_km=25,
       track=[[51.235, -1.880]], speed_kmh=20, notes="Jumps forward"),
    rx("Blue A Coy", B, "Blue BG Main HQ", 51.245, -1.920, 3, VB, 25, 40, radius_km=20),
    rx("Blue B Coy", B, "Blue BG Main HQ", 51.200, -1.930, 3, VB, 25, 40, radius_km=20),
    rx("Blue C Coy (reserve)", B, "Blue BG Main HQ", 51.215, -1.850, 3, VB, 25, 40, radius_km=20,
       track=[[51.190, -1.900]], speed_kmh=15, notes="Repositions to block"),
    rx("Blue Recce Tp", B, "Blue BG Main HQ", 51.235, -2.020, 3, VB, 25, 37, radius_km=20,
       track=[[51.230, -1.950]], speed_kmh=25, notes="Screen withdraws"),
    em("Blue UAS GCS", B, "datalink", 51.200, -1.800, 5, 2350, 5000, 40, sens_dbm=-95, js_req_db=6, radius_km=30),
    rx("Blue UAV", B, "Blue UAS GCS", 51.250, -1.970, 600, 2350, 5000, 30, sidc=FA, radius_km=30,
       track=[[51.260, -2.020], [51.240, -2.000], [51.260, -2.020]], speed_kmh=90),
    em("Blue GSR", B, "radar", 51.230, -1.930, 6, 9400, 10000, 85, pattern="sector", azimuth=270, beamwidth=30,
       radius_km=25, notes="Ground surveillance radar, peak EIRP"),
    em("Blue SATCOM", B, "comms", 51.205, -1.785, 3, 7950, 5000, 70, pattern="sector", azimuth=170, beamwidth=3,
       radius_km=20, notes="Pointed at a geostationary satellite; ground exposure via sidelobes"),
    es("Blue ES/DF 1", B, 51.260, -1.860, 10, 30, 3000, -115, df=2),
    es("Blue ES/DF 2", B, 51.170, -1.860, 10, 30, 3000, -115, df=2),
    es("Blue radar ES", B, 51.215, -1.820, 6, 2000, 18000, -80),
    ea("Blue C-UAS", B, "cuas", 51.225, -1.880, 5, 2300, 200000, 50, radius_km=15, notes="2.2-2.4 GHz"),
    em("GPS L1 (space)", B, "nav", 51.215, -1.900, 0, 1575.42, 2046, None, fixed_level_dbm=-128, js_req_db=35,
       sens_dbm=-140, notes="Satellite signal, same level everywhere"),
    rx("Blue fires (GNSS)", B, "GPS L1 (space)", 51.190, -1.840, 2, 1575.42, 2046),
    rx("Blue UAV nav (GNSS)", B, "GPS L1 (space)", 51.250, -1.970, 600, 1575.42, 2046, sidc=FA),
    # ---- red battalion tactical group (west)
    em("Red BTG HQ", R, "comms", 51.225, -2.120, 8, VR, 25, 47, sens_dbm=-110, js_req_db=0, radius_km=30),
    rx("Red Coy 1", R, "Red BTG HQ", 51.240, -2.030, 3, VR, 25, 40, radius_km=20),
    rx("Red Coy 2", R, "Red BTG HQ", 51.200, -2.040, 3, VR, 25, 40, radius_km=20,
       track=[[51.205, -1.980]], speed_kmh=10, notes="Advances"),
    es("Red ES/DF 1", R, 51.270, -2.100, 12, 30, 3000, -115, df=2),
    es("Red ES/DF 2", R, 51.170, -2.120, 12, 30, 3000, -115, df=2),
    es("Red airborne ES", R, 51.230, -2.080, 1500, 30, 18000, -110, df=5, sidc=HA,
       track=[[51.260, -2.080], [51.200, -2.080], [51.260, -2.080]], speed_kmh=120),
    ea("Red VHF barrage", R, "comms", 51.215, -2.060, 8, 50, 20000, 60, radius_km=30, notes="40-60 MHz"),
    ea("Red VHF spot", R, "comms", 51.230, -2.090, 6, VB, 25, 57, radius_km=30,
       track=[[51.220, -2.000]], speed_kmh=12, notes="Tuned to the blue net"),
    ea("Red datalink jammer", R, "datalink", 51.230, -2.050, 6, 2350, 20000, 50, radius_km=25),
    ea("Red GNSS jammer", R, "nav", 51.210, -2.020, 3, 1575.42, 2046, 40, radius_km=20),
    em("Red CB radar", R, "radar", 51.200, -2.150, 6, 3100, 5000, 90, pattern="sector", azimuth=90, beamwidth=90,
       radius_km=30, notes="Counter-battery radar, peak EIRP"),
    em("Red UAS GCS", R, "datalink", 51.225, -2.130, 5, 2200, 5000, 40, sens_dbm=-95, js_req_db=6, radius_km=30),
    rx("Red UAV", R, "Red UAS GCS", 51.230, -1.980, 800, 2200, 5000, 30, sidc=HA, radius_km=30,
       track=[[51.210, -1.920], [51.250, -1.950]], speed_kmh=100),
]

EXAMPLES = {
    "bg-vignette": {
        "title": "1. Battlegroup EMO vignette (Salisbury Plain)",
        "about": "Blue battlegroup in the east, red battalion tactical group in the west. Both sides have ES/DF, EA and "
                 "radars; red adds an airborne ES platform. Scrub the time slider: recce withdraws, C Coy repositions, "
                 "the step-up HQ jumps, red's spot jammer closes and its UAV probes. Drag any unit, or take an emitter "
                 "off-air (EMCON), and re-run to see who can see and fix whom, and whose nets are denied. First run "
                 "computes about 20 coverages (under a minute); later runs reuse them.",
        "centre": [51.22, -1.96], "zoom": 11, "entities": VIGNETTE,
    },
    "brecon-siting": {
        "title": "2. Siting and terrain masking (Brecon Beacons, Sennybridge)",
        "about": "Blue HQ in the Usk valley and a directional hilltop relay; red ES/DF on high ground and in a valley. "
                 "Drag the HQ up the hillside or turn the relay: exposure and fixes change. The EMCON siting lesson.",
        "centre": [51.96, -3.45], "zoom": 10,
        "entities": [
            em("Blue HQ (valley)", B, "comms", 51.947, -3.390, 6, 62.3, 25, 44, sens_dbm=-110, js_req_db=0),
            rx("Blue patrol", B, "Blue HQ (valley)", 51.990, -3.550, 2, 62.3, 25, 37, radius_km=15,
               track=[[51.960, -3.470], [51.930, -3.420]], speed_kmh=5),
            em("Blue hill relay", B, "comms", 51.884, -3.437, 10, 320, 500, 47, pattern="sector", azimuth=0, beamwidth=45),
            es("Red ES/DF (high ground)", R, 52.050, -3.500, 12, 30, 400, -115, df=2),
            es("Red ES/DF (valley)", R, 51.995, -3.800, 8, 30, 400, -115, df=2),
        ],
    },
    "solent-maritime": {
        "title": "3. Maritime ES and EA (Solent and Channel)",
        "about": "Blue ship on a UHF net transits out of Portsmouth; a red ES vessel tracks east along the Channel and a "
                 "red jammer vessel holds offshore. Blue shore ES/DF can fix the jammer. Sea paths give long ranges.",
        "centre": [50.66, -1.40], "zoom": 10,
        "entities": [
            em("Blue ship", B, "comms", 50.780, -1.100, 20, 252.4, 25, 50, sens_dbm=-105, js_req_db=0, sidc=FS,
               track=[[50.720, -1.250], [50.660, -1.600]], speed_kmh=25),
            rx("Blue shore HQ", B, "Blue ship", 50.800, -1.100, 15, 252.4, 25, 47),
            es("Blue shore ES/DF (Portsdown)", B, 50.860, -1.090, 20, 225, 400, -115, df=2),
            es("Blue shore ES/DF (Needles)", B, 50.662, -1.580, 20, 225, 400, -115, df=2),
            es("Red ES vessel", R, 50.550, -1.900, 15, 225, 400, -115, df=3, sidc=HS, track=[[50.580, -1.200]], speed_kmh=18),
            ea("Red jammer vessel", R, "comms", 50.500, -1.400, 15, 252.4, 100, 60, sidc=HS),
        ],
    },
    "a303-gnss": {
        "title": "4. GNSS L1 jamming along a road (A303, Salisbury Plain)",
        "about": "Red GPS L1 jammer in a vehicle heading east along the A303 against blue GNSS users. Satellite signal "
                 "fixed at -128 dBm; blue fails at J/S of 35 dB (a common figure for civil C/A tracking). Blue ES/DF "
                 "sites fix the jammer as it moves.",
        "centre": [51.15, -1.95], "zoom": 10,
        "entities": [
            em("GPS L1 (space)", B, "nav", 51.15, -1.95, 0, 1575.42, 2046, None, fixed_level_dbm=-128, js_req_db=35, sens_dbm=-140),
            rx("Blue GNSS user (airfield)", B, "GPS L1 (space)", 51.152, -1.747, 2, 1575.42, 2046),
            rx("Blue GNSS user (Larkhill)", B, "GPS L1 (space)", 51.200, -1.800, 2, 1575.42, 2046),
            es("Blue ES/DF north", B, 51.230, -1.900, 10, 1000, 2000, -120, df=2),
            es("Blue ES/DF south", B, 51.080, -1.850, 10, 1000, 2000, -120, df=2),
            ea("Red GNSS jammer (vehicle)", R, "nav", 51.130, -2.100, 2, 1575.42, 2046, 40, radius_km=20,
               track=[[51.150, -1.950], [51.170, -1.780]], speed_kmh=80, notes="10 W EIRP"),
        ],
    },
    "cuas-vs-datalink": {
        "title": "5. C-UAS against a UAS datalink (Salisbury Plain)",
        "about": "Red UAV flies an approach towards a blue position; blue C-UAS effector and ES. Watch J/S at the red "
                 "UAV rise as it closes and the blue ES fix its ground station.",
        "centre": [51.22, -1.95], "zoom": 11,
        "entities": [
            em("Red UAS GCS", R, "datalink", 51.225, -2.130, 5, 2200, 5000, 40, sens_dbm=-95, js_req_db=6),
            rx("Red UAV", R, "Red UAS GCS", 51.230, -2.050, 300, 2200, 5000, 30, sidc=HA,
               track=[[51.225, -1.950], [51.220, -1.880]], speed_kmh=80),
            ea("Blue C-UAS", B, "cuas", 51.220, -1.880, 5, 2300, 200000, 50, radius_km=15),
            es("Blue ES/DF 1", B, 51.260, -1.860, 10, 2000, 2500, -110, df=2),
            es("Blue ES/DF 2", B, 51.170, -1.860, 10, 2000, 2500, -110, df=2),
        ],
    },
}


# ---- operational-level MDO vignette: north-west Scotland and the Minches (Joint Warrior-style area) ----
BV, RV = 40.500, 45.200          # notional blue and red VHF nets (MHz)
L16 = 1087.5                     # Link 16 band centre (960-1215 MHz), modelled as one 255 MHz wide channel
MDO = [
    # ---- blue land (south-east)
    em("Blue Bde HQ", B, "comms", 57.600, -4.600, 10, BV, 25, 47, sens_dbm=-110, js_req_db=0, hop_bw_khz=58000,
       notes="Frequency-hopping over 30-88 MHz (EP)"),
    rx("Blue BG 1", B, "Blue Bde HQ", 57.800, -4.850, 3, BV, 25, 44, track=[[57.900, -4.950], [57.960, -5.000]], speed_kmh=15,
       notes="Advances north-west"),
    rx("Blue BG 2", B, "Blue Bde HQ", 57.700, -5.100, 3, BV, 25, 44),
    rx("Blue Recce", B, "Blue Bde HQ", 57.950, -4.950, 3, BV, 25, 40),
    es("Blue ES/DF 1", B, 57.750, -4.400, 15, 20, 3000, -118, df=2),
    es("Blue ES/DF 2", B, 57.550, -5.000, 15, 20, 3000, -118, df=2),
    es("Blue ES/DF 3", B, 57.900, -4.200, 15, 20, 3000, -118, df=2),
    em("Blue GBAD radar", B, "radar", 57.650, -4.700, 8, 9500, 20000, 88, pattern="sector", azimuth=315, beamwidth=120),
    em("Blue CB radar", B, "radar", 57.700, -4.750, 6, 3300, 5000, 88, pattern="sector", azimuth=315, beamwidth=90),
    ea("Blue VHF jammer", B, "comms", 57.850, -4.700, 10, RV, 25, 60, notes="Spot on the red net"),
    em("Blue SATCOM (HQ)", B, "comms", 57.480, -4.220, 3, 7950, 5000, 70, pattern="sector", azimuth=170, beamwidth=3),
    # ---- blue air
    em("Blue AEW radar", B, "radar", 57.600, -3.800, 9000, 1300, 5000, 90, sidc=FA, pattern="sector", azimuth=315, beamwidth=120),
    em("Blue Link 16 (AEW)", B, "datalink", 57.600, -3.800, 9000, L16, 3000, 50, sens_dbm=-100, js_req_db=10, hop_bw_khz=255000,
       sidc=FA, notes="3 MHz hops across 960-1215 MHz"),
    rx("Blue fighter pair", B, "Blue Link 16 (AEW)", 57.950, -5.000, 8000, L16, 3000, 43, sidc=FA,
       track=[[58.150, -5.250], [57.950, -5.450], [57.950, -5.000]], speed_kmh=700),
    es("Blue airborne ES", B, 57.700, -6.100, 10000, 20, 18000, -115, df=3, sidc=FA,
       track=[[58.050, -6.200], [57.600, -6.200], [58.050, -6.200]], speed_kmh=600),
    # ---- blue maritime
    em("Blue frigate radar", B, "radar", 57.750, -5.950, 25, 3000, 10000, 92, sidc=FS, track=[[58.000, -5.900]], speed_kmh=30),
    rx("Blue frigate (Link 16)", B, "Blue Link 16 (AEW)", 57.750, -5.950, 25, L16, 3000, 43, sidc=FS,
       track=[[58.000, -5.900]], speed_kmh=30),
    # ---- space
    em("GPS L1 (space)", B, "nav", 57.800, -5.000, 0, 1575.42, 2046, None, fixed_level_dbm=-128, js_req_db=35, sens_dbm=-140),
    rx("Blue fires (GNSS)", B, "GPS L1 (space)", 57.620, -4.650, 2, 1575.42, 2046),
    rx("Blue frigate (GNSS)", B, "GPS L1 (space)", 57.750, -5.950, 25, 1575.42, 2046, sidc=FS, track=[[58.000, -5.900]], speed_kmh=30),
    rx("Blue fighters (GNSS)", B, "GPS L1 (space)", 57.950, -5.000, 8000, 1575.42, 2046, sidc=FA,
       track=[[58.150, -5.250], [57.950, -5.450], [57.950, -5.000]], speed_kmh=700),
    # ---- red land (north-west)
    em("Red Div HQ", R, "comms", 58.350, -4.950, 10, RV, 25, 47, sens_dbm=-110, js_req_db=0),
    rx("Red Bde 1", R, "Red Div HQ", 57.950, -5.050, 3, RV, 25, 44),
    rx("Red Bde 2", R, "Red Div HQ", 58.100, -4.700, 3, RV, 25, 44, track=[[57.980, -4.550]], speed_kmh=12, notes="Advances south-east"),
    es("Red ES/DF 1", R, 58.450, -5.000, 15, 20, 3000, -118, df=2),
    es("Red ES/DF 2", R, 58.000, -5.400, 15, 20, 3000, -118, df=2),
    es("Red ES/DF 3", R, 58.200, -4.400, 15, 20, 3000, -118, df=2),
    ea("Red VHF jammer", R, "comms", 58.000, -4.850, 12, 45, 20000, 63, notes="Barrage 35-55 MHz, 2 kW EIRP"),
    ea("Red GNSS jammer", R, "nav", 58.300, -5.100, 20, 1575.42, 2046, 50, notes="High ground, 100 W EIRP"),
    ea("Red L-band barrage", R, "datalink", 58.100, -5.150, 15, L16, 255000, 70, notes="Against Link 16, 960-1215 MHz"),
    em("Red SAM radar", R, "radar", 58.150, -5.200, 8, 3000, 10000, 95, pattern="sector", azimuth=150, beamwidth=120),
    em("Red coastal radar", R, "radar", 58.550, -5.000, 30, 9400, 20000, 85, pattern="sector", azimuth=270, beamwidth=180),
    # ---- red air and maritime
    es("Red airborne ES", R, 58.600, -4.500, 9000, 20, 18000, -115, df=3, sidc=HA,
       track=[[58.600, -5.300], [58.600, -4.500]], speed_kmh=550),
    em("Red corvette radar", R, "radar", 58.400, -5.600, 20, 9400, 20000, 85, sidc=HS,
       track=[[58.150, -5.750], [57.950, -5.850]], speed_kmh=25),
    es("Red corvette ES", R, 58.400, -5.600, 20, 20, 18000, -110, df=3, sidc=HS,
       track=[[58.150, -5.750], [57.950, -5.850]], speed_kmh=25),
]

EXAMPLES = {"mdo-operational": {
    "title": "0. Operational-level MDO in the EME (NW Scotland and the Minches)",
    "about": "Notional joint force (south-east) against an opposing force (north-west) across land, maritime, air and space, "
             "about 250 km across in a Joint Warrior-style area. Things to look for: airborne ES out-hears ground ES; radars "
             "are the loudest emitters and are fixed first; the L-band barrage loses about 19 dB against Link 16 "
             "(3 MHz hops over 255 MHz); blue's VHF net hops over 30-88 MHz (about 34 dB against a spot jammer) while red's "
             "single-channel net is denied by blue's spot jammer: the EP lesson; GNSS jamming from high ground reaches aircraft, the frigate and precision fires; blue EA denies the red "
             "VHF net. Tap any symbol to focus on it. First run takes a couple of minutes (new terrain tiles).",
    "centre": [57.95, -5.10], "zoom": 8, "params": {"df_fix_good_m": 5000}, "entities": MDO}, **EXAMPLES}


# ---- operational-level MDO vignette: the Suwalki Gap (notional forces, public geography) ----
BV2, RV2 = 42.300, 47.600
SUW = [
    # ---- blue: defending the corridor (Suwalki - Augustow - Lazdijai - Marijampole)
    em("Blue Div HQ (Augustow)", B, "comms", 53.845, 22.980, 12, BV2, 25, 47, sens_dbm=-110, js_req_db=0, hop_bw_khz=58000,
       notes="Frequency-hopping 30-88 MHz"),
    rx("Blue Bde (Suwalki)", B, "Blue Div HQ (Augustow)", 54.100, 22.930, 6, BV2, 25, 44),
    rx("Blue BG (Lazdijai)", B, "Blue Div HQ (Augustow)", 54.230, 23.510, 3, BV2, 25, 44),
    rx("Blue BG (Marijampole)", B, "Blue Div HQ (Augustow)", 54.560, 23.350, 3, BV2, 25, 44,
       track=[[54.450, 23.100], [54.350, 22.850]], speed_kmh=15, notes="Counter-moves south-west"),
    rx("Blue Recce (border)", B, "Blue Div HQ (Augustow)", 54.330, 22.700, 3, BV2, 25, 40),
    es("Blue ES/DF (Suwalki)", B, 54.120, 22.980, 20, 20, 3000, -118, df=2),
    es("Blue ES/DF (Lazdijai)", B, 54.200, 23.600, 20, 20, 3000, -118, df=2),
    es("Blue ES/DF (Marijampole)", B, 54.580, 23.400, 20, 20, 3000, -118, df=2),
    em("Blue GBAD radar", B, "radar", 54.050, 23.050, 10, 9500, 20000, 88),
    em("Blue CB radar", B, "radar", 54.000, 22.900, 6, 3300, 5000, 88, pattern="sector", azimuth=300, beamwidth=90),
    ea("Blue VHF jammer", B, "comms", 54.250, 22.950, 10, RV2, 25, 60, notes="Spot on the red net"),
    ea("Blue C-UAS", B, "cuas", 54.110, 22.960, 6, 2300, 200000, 50),
    em("Blue UAS GCS", B, "datalink", 54.080, 23.000, 5, 2350, 5000, 40, sens_dbm=-95, js_req_db=6),
    rx("Blue UAV", B, "Blue UAS GCS", 54.300, 22.750, 800, 2350, 5000, 30, sidc=FA,
       track=[[54.400, 22.500], [54.300, 22.750]], speed_kmh=100),
    em("Blue SATCOM (Div)", B, "comms", 53.845, 22.985, 3, 7950, 5000, 70, pattern="sector", azimuth=165, beamwidth=3),
    # ---- blue air and space
    em("Blue AEW radar", B, "radar", 53.900, 21.800, 9000, 1300, 5000, 90, sidc=FA, pattern="sector", azimuth=45, beamwidth=120),
    em("Blue Link 16 (AEW)", B, "datalink", 53.900, 21.800, 9000, 1087.5, 3000, 50, sens_dbm=-100, js_req_db=10, hop_bw_khz=255000, sidc=FA),
    rx("Blue fighter pair", B, "Blue Link 16 (AEW)", 54.300, 22.500, 8000, 1087.5, 3000, 43, sidc=FA,
       track=[[54.450, 22.100], [54.200, 22.300], [54.300, 22.500]], speed_kmh=700),
    es("Blue airborne ES", B, 55.000, 23.800, 10000, 20, 18000, -115, df=3, sidc=FA,
       track=[[55.100, 22.900], [55.000, 23.800]], speed_kmh=600),
    em("GPS L1 (space)", B, "nav", 54.200, 23.000, 0, 1575.42, 2046, None, fixed_level_dbm=-128, js_req_db=35, sens_dbm=-140),
    rx("Blue fires (GNSS)", B, "GPS L1 (space)", 54.020, 22.940, 2, 1575.42, 2046),
    rx("Blue UAV nav (GNSS)", B, "GPS L1 (space)", 54.300, 22.750, 800, 1575.42, 2046, sidc=FA,
       track=[[54.400, 22.500], [54.300, 22.750]], speed_kmh=100),
    rx("Blue fighters (GNSS)", B, "GPS L1 (space)", 54.300, 22.500, 8000, 1575.42, 2046, sidc=FA,
       track=[[54.450, 22.100], [54.200, 22.300], [54.300, 22.500]], speed_kmh=700),
    # ---- red (west flank): notional force beyond the western border
    em("Red Army HQ (west)", R, "comms", 54.600, 22.200, 12, RV2, 25, 50, sens_dbm=-110, js_req_db=0),
    rx("Red Bde (west)", R, "Red Army HQ (west)", 54.400, 22.450, 3, RV2, 25, 44, track=[[54.300, 22.700]], speed_kmh=10,
       notes="Pushes east into the gap"),
    es("Red ES/DF (west)", R, 54.450, 22.300, 20, 20, 3000, -118, df=2),
    ea("Red VHF barrage", R, "comms", 54.450, 22.400, 15, 45, 20000, 63, notes="35-55 MHz, 2 kW EIRP"),
    ea("Red GNSS jammer (west)", R, "nav", 54.650, 22.000, 40, 1575.42, 2046, 55, notes="Mast-mounted, 300 W EIRP"),
    ea("Red L-band barrage", R, "datalink", 54.550, 22.100, 20, 1087.5, 255000, 70, notes="Against Link 16"),
    em("Red SAM radar", R, "radar", 54.600, 21.950, 10, 3000, 10000, 95, pattern="sector", azimuth=90, beamwidth=120),
    es("Red airborne ES", R, 54.800, 21.700, 9000, 20, 18000, -115, df=3, sidc=HA,
       track=[[54.800, 22.300], [54.800, 21.700]], speed_kmh=550),
    # ---- red (south-east flank)
    rx("Red Bde (south-east)", R, "Red Army HQ (west)", 53.700, 23.850, 3, RV2, 25, 44, track=[[53.850, 23.600]], speed_kmh=10,
       notes="Pushes north-west towards the gap"),
    es("Red ES/DF (south-east)", R, 53.800, 23.750, 20, 20, 3000, -118, df=2),
    ea("Red GNSS jammer (south-east)", R, "nav", 53.650, 23.850, 40, 1575.42, 2046, 55),
    em("Red CB radar", R, "radar", 53.750, 23.800, 6, 3100, 5000, 90, pattern="sector", azimuth=330, beamwidth=90),
    em("Red UAS GCS", R, "datalink", 53.720, 23.820, 5, 2200, 5000, 40, sens_dbm=-95, js_req_db=6),
    rx("Red UAV", R, "Red UAS GCS", 53.900, 23.500, 800, 2200, 5000, 30, sidc=HA,
       track=[[54.000, 23.200], [53.900, 23.500]], speed_kmh=100),
]
EXAMPLES = {"suwalki-mdo": {
    "title": "0b. Operational-level MDO: the Suwalki Gap (notional)",
    "about": "Notional blue force holds the corridor between Suwalki, Augustow, Lazdijai and Marijampole against a notional "
             "red force pressing from the western and south-eastern flanks. Two-sided GNSS jamming from masts squeezes the "
             "corridor; an L-band barrage targets Link 16; airborne ES on both sides out-hear ground ES. Blue HQ nets hop "
             "across 30-88 MHz. Public geography only; forces, frequencies and values are notional. Use multi-select to "
             "compare, for example, both red GNSS jammers against the blue fires and UAV.",
    "centre": [54.15, 22.95], "zoom": 8, "params": {"df_fix_good_m": 5000}, "entities": SUW}, **EXAMPLES}


# ---- littoral A2/AD vignette: Vestfjord and Lofoten (notional forces; Cold Response-style area) ----
G = "grey"
NL, NA, NS = "SNGPU----------", "SNAP-----------", "SNSP-----------"   # neutral land / air / sea (drawn grey)
BVL, RVL, BU = 55.500, 47.600, 252.400
LIT = [
    # ---- blue: Littoral Response Group from seaward (south-west), raid force ashore
    em("Blue LPD (UHF net)", B, "comms", 67.750, 13.000, 25, BU, 25, 50, sens_dbm=-105, js_req_db=0, sidc=FS),
    rx("Blue frigate (UHF)", B, "Blue LPD (UHF net)", 67.850, 13.300, 25, BU, 25, 47, sidc=FS, track=[[68.000, 13.600]], speed_kmh=25),
    em("Blue frigate radar", B, "radar", 67.850, 13.300, 25, 3000, 10000, 95, sidc=FS, track=[[68.000, 13.600]], speed_kmh=25,
       notes="Air-defence radar: the EMCON test"),
    rx("Blue helicopter (UHF)", B, "Blue LPD (UHF net)", 67.800, 13.100, 300, BU, 25, 40, sidc=FA,
       track=[[68.050, 13.750], [67.800, 13.100]], speed_kmh=180),
    rx("Blue landing craft (UHF)", B, "Blue LPD (UHF net)", 67.780, 13.080, 3, BU, 25, 40, sidc=FS,
       track=[[68.080, 13.800]], speed_kmh=25),
    em("Blue raid force HQ (VHF)", B, "comms", 68.100, 13.850, 4, BVL, 25, 44, sens_dbm=-110, js_req_db=0, hop_bw_khz=58000,
       notes="Commando company group ashore, hopping 30-88 MHz"),
    rx("Blue raid team 1", B, "Blue raid force HQ (VHF)", 68.130, 13.950, 2, BVL, 25, 37),
    rx("Blue raid team 2", B, "Blue raid force HQ (VHF)", 68.090, 14.050, 2, BVL, 25, 37, track=[[68.150, 14.200]], speed_kmh=4),
    em("Blue raid SATCOM", B, "comms", 68.100, 13.855, 2, 7950, 5000, 60, pattern="sector", azimuth=175, beamwidth=5),
    em("Blue UAS GCS (ship)", B, "datalink", 67.750, 13.005, 20, 2350, 5000, 40, sens_dbm=-95, js_req_db=6, sidc=FS),
    rx("Blue UAV", B, "Blue UAS GCS (ship)", 67.950, 13.500, 600, 2350, 5000, 30, sidc=FA,
       track=[[68.150, 14.000], [68.050, 14.300], [67.950, 13.500]], speed_kmh=120),
    es("Blue LPD ES", B, 67.750, 13.000, 30, 20, 18000, -110, df=3, sidc=FS),
    es("Blue MPA ES", B, 67.500, 13.500, 8000, 20, 18000, -115, df=3, sidc=FA,
       track=[[67.600, 12.300], [67.500, 13.500]], speed_kmh=550),
    ea("Blue ship comms EA", B, "comms", 67.850, 13.300, 25, RVL, 25, 60, sidc=FS, track=[[68.000, 13.600]], speed_kmh=25,
       notes="Spot on the red coastal C2 net"),
    ea("Blue airborne EA", B, "comms", 67.700, 13.600, 8000, RVL, 5000, 65, sidc=FA, track=[[67.900, 14.100]], speed_kmh=600,
       notes="Stand-off; 5 MHz wide"),
    em("Blue Link 16 (AEW)", B, "datalink", 67.200, 12.300, 9000, 1087.5, 3000, 50, sens_dbm=-100, js_req_db=10, hop_bw_khz=255000, sidc=FA),
    rx("Blue fighter pair", B, "Blue Link 16 (AEW)", 67.700, 13.200, 8000, 1087.5, 3000, 43, sidc=FA,
       track=[[68.100, 14.100], [67.700, 13.200]], speed_kmh=700, notes="Strike route across Vestfjord"),
    em("GPS L1 (space)", B, "nav", 67.950, 13.700, 0, 1575.42, 2046, None, fixed_level_dbm=-128, js_req_db=35, sens_dbm=-140),
    rx("Blue landing craft (GNSS)", B, "GPS L1 (space)", 67.780, 13.080, 3, 1575.42, 2046, sidc=FS, track=[[68.080, 13.800]], speed_kmh=25),
    rx("Blue UAV (GNSS)", B, "GPS L1 (space)", 67.950, 13.500, 600, 1575.42, 2046, sidc=FA,
       track=[[68.150, 14.000], [68.050, 14.300], [67.950, 13.500]], speed_kmh=120),
    rx("Blue fighters (GNSS)", B, "GPS L1 (space)", 67.700, 13.200, 8000, 1575.42, 2046, sidc=FA,
       track=[[68.100, 14.100], [67.700, 13.200]], speed_kmh=700),
    # ---- red: A2/AD ashore on Lofoten
    em("Red coastal defence HQ", R, "comms", 68.230, 14.570, 15, RVL, 25, 50, sens_dbm=-110, js_req_db=0),
    rx("Red coastal battery (west)", R, "Red coastal defence HQ", 68.050, 13.950, 5, RVL, 25, 44),
    rx("Red coastal battery (east)", R, "Red coastal defence HQ", 68.300, 15.000, 5, RVL, 25, 44),
    em("Red coastal surveillance radar", R, "radar", 68.150, 13.600, 30, 9400, 20000, 85, pattern="sector", azimuth=225, beamwidth=180),
    em("Red missile targeting radar", R, "radar", 68.020, 13.900, 20, 9800, 20000, 90, pattern="sector", azimuth=200, beamwidth=120),
    em("Red SAM radar", R, "radar", 68.220, 14.200, 15, 3000, 10000, 95),
    es("Red ES/DF (Leknes)", R, 68.250, 13.700, 30, 20, 18000, -115, df=2),
    es("Red ES/DF (Svolvaer)", R, 68.350, 14.900, 30, 20, 18000, -115, df=2),
    es("Red patrol boat ES", R, 68.000, 14.400, 10, 20, 18000, -110, df=3, sidc=HS, track=[[67.900, 13.800]], speed_kmh=30),
    ea("Red UHF barrage", R, "comms", 68.200, 14.000, 20, 312.5, 175000, 70, notes="225-400 MHz against the ship nets"),
    ea("Red L-band barrage", R, "datalink", 68.150, 14.400, 20, 1087.5, 255000, 70, notes="Against Link 16"),
    ea("Red GNSS jammer (mountain)", R, "nav", 68.300, 14.300, 400, 1575.42, 2046, 55, notes="On high ground"),
    em("Red UAS GCS", R, "datalink", 68.200, 14.500, 10, 2200, 5000, 40, sens_dbm=-95, js_req_db=6),
    rx("Red maritime UAV", R, "Red UAS GCS", 68.000, 13.800, 800, 2200, 5000, 30, sidc=HA,
       track=[[67.800, 13.200], [68.000, 13.800]], speed_kmh=110),
    # ---- grey: civil and neutral
    em("Bodo ATC radar", G, "radar", 67.270, 14.370, 30, 2800, 2000, 90, sidc=NL, notes="Civil primary surveillance radar"),
    em("Coastal ferry (marine VHF)", G, "comms", 67.300, 14.350, 20, 156.8, 25, 44, sens_dbm=-110, js_req_db=0, sidc=NS,
       track=[[68.100, 13.900]], speed_kmh=30),
    rx("Fishing vessel 1", G, "Coastal ferry (marine VHF)", 67.900, 13.700, 5, 156.8, 25, 44, sidc=NS),
    rx("Fishing vessel 2", G, "Coastal ferry (marine VHF)", 68.050, 14.600, 5, 156.8, 25, 44, sidc=NS),
    em("FM broadcast (Svolvaer)", G, "comms", 68.235, 14.520, 60, 95.0, 200, 70, sidc=NL),
    em("Mobile mast (Leknes)", G, "comms", 68.150, 13.620, 30, 806.0, 10000, 60, sidc=NL),
    em("Airliner (ADS-B)", G, "other", 67.600, 13.900, 10000, 1090.0, 2000, 57, sidc=NA, track=[[68.400, 15.000]], speed_kmh=800),
    em("GPS L1 (civil users)", G, "nav", 68.000, 14.000, 0, 1575.42, 2046, None, fixed_level_dbm=-128, js_req_db=35, sens_dbm=-140, sidc=NL),
    rx("Civil GNSS (Svolvaer)", G, "GPS L1 (civil users)", 68.235, 14.570, 2, 1575.42, 2046, sidc=NL),
    rx("Civil GNSS (ferry)", G, "GPS L1 (civil users)", 67.300, 14.350, 20, 1575.42, 2046, sidc=NS, track=[[68.100, 13.900]], speed_kmh=30),
    rx("Civil GNSS (Leknes airport)", G, "GPS L1 (civil users)", 68.152, 13.609, 2, 1575.42, 2046, sidc=NL),
]
EXAMPLES = {"littoral-a2ad": {
    "title": "0c. Littoral A2/AD: Vestfjord and Lofoten (notional)",
    "about": "A Littoral Response Group approaches from seaward and puts a commando raid force ashore against a notional A2/AD "
             "position on Lofoten. The question: how does the commander convert electromagnetic understanding into a temporary "
             "advantage before red adapts? Find and fix the red targeting radars with blue ES; decide when the frigate radiates "
             "(EMCON); deny the red coastal C2 net with shipborne and airborne EA; judge whether the fighters' Link 16 survives the "
             "L-band barrage along the strike route; and count the civil GNSS collateral. Grey entities are civil. Notional forces "
             "and values on public geography.",
    "centre": [67.95, 13.80], "zoom": 8, "params": {"df_fix_good_m": 3000}, "entities": LIT}, **EXAMPLES}


# ---- realism pass (2026-09-25): grey (civil) entities in every scenario, and layout fixes ----
def _civil_gnss(lat, lon, users):
    """A civil GNSS 'net' (fixed space signal) and its users, so jamming shows as collateral."""
    net = em("GPS L1 (civil users)", G, "nav", lat, lon, 0, 1575.42, 2046, None, fixed_level_dbm=-128, js_req_db=35, sens_dbm=-140, sidc=NL)
    return [net] + [rx(n, G, "GPS L1 (civil users)", la, lo, h, 1575.42, 2046, sidc=sd) for n, la, lo, h, sd in users]


EXAMPLES["bg-vignette"]["entities"] += [
    em("Boscombe Down ATC radar", G, "radar", 51.152, -1.747, 25, 2800, 2000, 88, sidc=NL),
    em("FM broadcast (notional)", G, "comms", 51.070, -1.790, 60, 95.5, 200, 67, sidc=NL),
    em("Mobile mast (Larkhill)", G, "comms", 51.200, -1.805, 25, 806.0, 10000, 60, sidc=NL),
] + _civil_gnss(51.20, -1.90, [("Civil GNSS (A303 traffic)", 51.170, -1.830, 2, NL), ("Civil GNSS (farm)", 51.250, -1.950, 2, NL)])

EXAMPLES["mdo-operational"]["entities"] += [
    em("Inverness ATC radar", G, "radar", 57.540, -4.050, 25, 2800, 2000, 90, sidc=NL),
    em("FM/TV transmitter (notional)", G, "comms", 57.630, -4.120, 80, 94.0, 200, 70, sidc=NL),
    em("Ferry Ullapool-Stornoway (marine VHF)", G, "comms", 57.900, -5.170, 20, 156.8, 25, 44, sens_dbm=-110, js_req_db=0, sidc=NS,
       track=[[58.200, -6.350]], speed_kmh=30),
    rx("Fishing vessel (Minch)", G, "Ferry Ullapool-Stornoway (marine VHF)", 58.050, -5.700, 5, 156.8, 25, 44, sidc=NS),
] + _civil_gnss(57.9, -5.0, [("Civil GNSS (Ullapool)", 57.895, -5.160, 2, NL), ("Civil GNSS (ferry)", 57.900, -5.170, 20, NS)])

_s = EXAMPLES["suwalki-mdo"]["entities"]
_s.append(em("Red Bde HQ (south-east)", R, "comms", 53.680, 23.830, 12, RV2, 25, 47, sens_dbm=-110, js_req_db=0,
             notes="Own net: the western HQ is ~120 km away, beyond VHF"))
for _e in _s:
    if _e["name"] == "Red Bde (south-east)":
        _e["net"] = "Red Bde HQ (south-east)"
_s += [
    em("Kaunas ATC radar", G, "radar", 54.960, 24.080, 25, 2800, 2000, 90, sidc=NL),
    em("FM broadcast (Suwalki)", G, "comms", 54.100, 22.930, 60, 95.0, 200, 67, sidc=NL),
    em("Mobile mast (Augustow)", G, "comms", 53.845, 22.975, 30, 806.0, 10000, 60, sidc=NL),
] + _civil_gnss(54.2, 23.1, [("Civil GNSS (Via Baltica, Suwalki)", 54.100, 22.930, 2, NL),
                             ("Civil GNSS (Via Baltica, Marijampole)", 54.560, 23.350, 2, NL)])

EXAMPLES["solent-maritime"]["entities"] += [
    em("Coastguard VTS radar (Needles)", G, "radar", 50.662, -1.585, 60, 9410, 20000, 80, sidc=NL),
    em("Isle of Wight ferry (marine VHF)", G, "comms", 50.795, -1.105, 15, 156.8, 25, 44, sens_dbm=-110, js_req_db=0, sidc=NS,
       track=[[50.735, -1.165]], speed_kmh=25),
    rx("Yacht (Solent)", G, "Isle of Wight ferry (marine VHF)", 50.760, -1.300, 5, 156.8, 25, 37, sidc=NS),
] + _civil_gnss(50.75, -1.25, [("Civil GNSS (ferry)", 50.795, -1.105, 15, NS), ("Civil GNSS (Cowes)", 50.760, -1.300, 2, NL)])

EXAMPLES["a303-gnss"]["entities"] += [
    em("Boscombe Down ATC radar", G, "radar", 51.152, -1.747, 25, 2800, 2000, 88, sidc=NL),
] + _civil_gnss(51.15, -1.95, [("Civil GNSS (A303 west)", 51.120, -2.050, 2, NL), ("Civil GNSS (Amesbury)", 51.172, -1.780, 2, NL),
                               ("Civil GNSS (Stonehenge coach)", 51.179, -1.826, 2, NL)])

EXAMPLES["brecon-siting"]["entities"] += [
    ea("Red VHF jammer", R, "comms", 52.020, -3.650, 8, 62.3, 25, 57, notes="Spot on the blue net: test siting against EA too"),
    em("FM broadcast (notional)", G, "comms", 51.990, -3.400, 60, 97.0, 200, 67, sidc=NL),
    em("Mobile mast (Brecon)", G, "comms", 51.947, -3.395, 25, 806.0, 10000, 60, sidc=NL),
]

EXAMPLES["cuas-vs-datalink"]["entities"] += [
    em("Civil drone controller", G, "datalink", 51.200, -1.860, 2, 2440, 20000, 20, sens_dbm=-90, js_req_db=6, sidc=NL),
    rx("Civil hobby drone", G, "Civil drone controller", 51.205, -1.855, 60, 2440, 20000, 20, sidc=NA),
    em("Wi-Fi hotspot (farm)", G, "other", 51.215, -1.890, 5, 2437, 20000, 20, sidc=NL),
]


# ---- layout fixes from the realism scrub (2026-09-25) ----
def _set(ex, name, **kw):
    for _e in EXAMPLES[ex]["entities"]:
        if _e["name"] == name:
            _e.update(kw)
            return
    raise KeyError(f"{ex}: {name}")


# red UAS ground stations were sited below the Warminster escarpment (39 dB diffraction): move onto the plain, 10 m mast
_set("bg-vignette", "Red UAS GCS", lat=51.235, lon=-2.070, h_agl=10)
_set("cuas-vs-datalink", "Red UAS GCS", lat=51.235, lon=-2.070, h_agl=10)
# MDO: recce was ~45 km from its HQ through the Highlands; pull it into VHF range on higher ground
_set("mdo-operational", "Blue Recce", lat=57.880, lon=-4.880, h_agl=4)
# Brecon: give blue its own ES/DF so the red jammer can be located (two-way picture)
EXAMPLES["brecon-siting"]["entities"].append(es("Blue ES/DF (Sennybridge)", B, 51.990, -3.570, 12, 30, 400, -115, df=2))
EXAMPLES["brecon-siting"]["entities"].append(es("Blue ES/DF (Pen y Fan)", B, 51.884, -3.437, 10, 30, 400, -115, df=2))
# Solent: ES receivers cover 30-3000 MHz, so civil marine VHF and the ferry are heard too
for _n in ("Blue shore ES/DF (Portsdown)", "Blue shore ES/DF (Needles)", "Red ES vessel"):
    _set("solent-maritime", _n, freq_mhz=30, f_hi_mhz=3000)


# ---- radar EA (2026-09-25): noise jammers against radars, self-protection and stand-off ----
EXAMPLES["suwalki-mdo"]["entities"] += [
    ea("Blue stand-off radar jammer", B, "radar", 54.30, 22.60, 9000, 3000, 200000, 80, sidc=FA, track=[[54.10, 22.40], [54.30, 22.60]], speed_kmh=500,
       notes="Airborne noise jammer against the red SAM radar (S-band); stand-off, so it enters the radar sidelobes"),
    ea("Red radar jammer (ground)", R, "radar", 54.55, 23.55, 15, 3000, 200000, 75, notes="Against the blue AEW radar; sidelobe unless on a target bearing"),
]
EXAMPLES["littoral-a2ad"]["entities"] += [
    ea("Blue fighter EA pod", B, "radar", 67.700, 13.200, 8000, 9800, 500000, 60, sidc=FA, track=[[68.100, 14.100], [67.700, 13.200]], speed_kmh=700,
       notes="Self-protection pod on the fighter pair against the red targeting radar (X-band): mainlobe, self-screening"),
    ea("Blue stand-off radar jammer", B, "radar", 67.500, 13.000, 9000, 3000, 200000, 80, sidc=FA, track=[[67.600, 13.800], [67.500, 13.000]], speed_kmh=500,
       notes="Against the red SAM radar (S-band) from stand-off"),
]


# ---- GNSS spoofing (2026-09-25): a spoofer on the A303 alongside the jammer ----
_sp = ea("Red GNSS spoofer (van)", R, "nav", 51.160, -1.980, 2, 1575.42, 2046, 20, notes="Low power: aims to be accepted, not to deny")
_sp["ea_mode"] = "spoof"
EXAMPLES["a303-gnss"]["entities"].append(_sp)


# ---- 2026-09-26: two home-ground MDO scenarios built for AR (centres at ///shares.cared.shunts and ///gratitude.system.segmented)
CHI = [
    # blue: home defence of the Portsmouth approaches, Thorney Island and Chichester Harbour
    em("Blue Harbour HQ (Chichester)", B, "comms", 50.8537, -0.7696, 8, BVL, 25, 46, sens_dbm=-110, js_req_db=0, hop_bw_khz=58000,
       notes="Notional coordination HQ at the scenario centre; hopping 30-88 MHz"),
    rx("Blue OP (The Trundle)", B, "Blue Harbour HQ (Chichester)", 50.8890, -0.7580, 3, BVL, 25, 37),
    rx("Blue patrol (Itchenor)", B, "Blue Harbour HQ (Chichester)", 50.8000, -0.8630, 2, BVL, 25, 37, track=[[50.7900, -0.9100]], speed_kmh=6),
    rx("Blue Thorney Island det", B, "Blue Harbour HQ (Chichester)", 50.8180, -0.9170, 4, BVL, 25, 40),
    em("Blue UHF ship net", B, "comms", 50.7600, -0.9400, 20, BU, 25, 47, sens_dbm=-105, js_req_db=0, sidc=FS,
       track=[[50.7200, -1.0500]], speed_kmh=20, notes="Patrol vessel in the Solent approach"),
    rx("Blue RIB (harbour)", B, "Blue UHF ship net", 50.8050, -0.8900, 2, BU, 25, 40, sidc=FS, track=[[50.7800, -0.9300]], speed_kmh=25),
    rx("Blue helicopter (UHF)", B, "Blue UHF ship net", 50.8300, -0.9600, 250, BU, 25, 40, sidc=FA,
       track=[[50.7700, -0.8200], [50.8300, -0.9600]], speed_kmh=160),
    em("Blue harbour radar (Thorney)", B, "radar", 50.8180, -0.9160, 25, 9410, 20000, 82, pattern="sector", azimuth=180, beamwidth=180),
    em("Blue SATCOM (HQ)", B, "comms", 50.8540, -0.7690, 3, 7950, 5000, 58, pattern="sector", azimuth=170, beamwidth=5),
    em("Blue UAS GCS (Goodwood)", B, "datalink", 50.8590, -0.7590, 4, 2350, 5000, 38, sens_dbm=-95, js_req_db=6),
    rx("Blue UAV", B, "Blue UAS GCS (Goodwood)", 50.8400, -0.8300, 300, 2350, 5000, 30, sidc=FA,
       track=[[50.7900, -0.9000], [50.7800, -0.8000], [50.8400, -0.8300]], speed_kmh=90),
    es("Blue ES/DF (Trundle)", B, 50.8890, -0.7580, 6, 20, 3000, -115, df=2),
    es("Blue ES/DF (Thorney)", B, 50.8180, -0.9170, 12, 20, 3000, -115, df=2),
    es("Blue ES/DF (Selsey)", B, 50.7350, -0.7900, 8, 20, 3000, -115, df=2),
    ea("Blue VHF jammer (Bognor)", B, "comms", 50.7950, -0.6900, 6, RVL, 25, 58, notes="Against the red raid net"),
    ea("Blue C-UAS (harbour)", B, "datalink", 50.8050, -0.8900, 3, 2400, 20000, 45, notes="Against the red UAV datalink"),
    em("GPS L1 (space)", B, "nav", 50.82, -0.85, 0, 1575.42, 2046, None, fixed_level_dbm=-128, js_req_db=35, sens_dbm=-140),
    rx("Blue RIB (GNSS)", B, "GPS L1 (space)", 50.8050, -0.8900, 2, 1575.42, 2046, sidc=FS, track=[[50.7800, -0.9300]], speed_kmh=25),
    rx("Blue UAV (GNSS)", B, "GPS L1 (space)", 50.8400, -0.8300, 300, 1575.42, 2046, sidc=FA,
       track=[[50.7900, -0.9000], [50.7800, -0.8000], [50.8400, -0.8300]], speed_kmh=90),
    # red: raid group in the Channel, landed recce, UAV, GNSS interference
    em("Red raid net (mother ship)", R, "comms", 50.6800, -0.8500, 15, RVL, 25, 50, sens_dbm=-110, js_req_db=0, sidc=HS,
       track=[[50.7000, -0.9500]], speed_kmh=15),
    rx("Red landing party (Wittering)", R, "Red raid net (mother ship)", 50.7750, -0.8700, 2, RVL, 25, 40, track=[[50.7900, -0.8400]], speed_kmh=4),
    rx("Red recce (Selsey Bill)", R, "Red raid net (mother ship)", 50.7250, -0.7900, 2, RVL, 25, 40),
    em("Red ship radar", R, "radar", 50.6800, -0.8500, 18, 9400, 20000, 85, sidc=HS, track=[[50.7000, -0.9500]], speed_kmh=15),
    es("Red ship ES", R, 50.6800, -0.8500, 20, 20, 3000, -112, df=3, sidc=HS, track=[[50.7000, -0.9500]], speed_kmh=15),
    es("Red recce ES (Pagham)", R, 50.7700, -0.7500, 2, 20, 1000, -110, df=3),
    em("Red UAS GCS (ship)", R, "datalink", 50.6810, -0.8490, 12, 2440, 20000, 40, sens_dbm=-95, js_req_db=6, sidc=HS),
    rx("Red UAV", R, "Red UAS GCS (ship)", 50.7600, -0.8800, 200, 2440, 20000, 25, sidc=HA,
       track=[[50.8200, -0.9200], [50.8100, -0.7700], [50.7600, -0.8800]], speed_kmh=80),
    ea("Red GNSS jammer (van, A27)", R, "nav", 50.8480, -0.8300, 2, 1575.42, 2046, 30, notes="Low power, mobile"),
    ea("Red UHF jammer (ship)", R, "comms", 50.6800, -0.8500, 15, BU, 25, 62, sidc=HS, track=[[50.7000, -0.9500]], speed_kmh=15),
    # grey: civil
    em("Goodwood ATC (VHF)", G, "comms", 50.8590, -0.7590, 12, 122.45, 25, 44, sens_dbm=-110, js_req_db=0, sidc=NL),
    rx("Light aircraft (Goodwood)", G, "Goodwood ATC (VHF)", 50.8700, -0.7900, 500, 122.45, 25, 40, sidc=NA,
       track=[[50.8200, -0.9000], [50.8700, -0.7900]], speed_kmh=170),
    em("FM broadcast (Chichester)", G, "comms", 50.8600, -0.7200, 60, 96.7, 200, 60, sidc=NL),
    em("Mobile mast (Chichester)", G, "comms", 50.8380, -0.7800, 25, 806.0, 10000, 60, sidc=NL),
    em("Harbour ferry (marine VHF)", G, "comms", 50.8020, -0.8700, 5, 156.8, 25, 44, sens_dbm=-110, js_req_db=0, sidc=NS,
       track=[[50.7900, -0.9300]], speed_kmh=12),
    rx("Yacht (Chichester Harbour)", G, "Harbour ferry (marine VHF)", 50.7950, -0.9000, 4, 156.8, 25, 37, sidc=NS),
    em("Airliner (ADS-B, Solent)", G, "other", 50.8000, -1.0000, 6000, 1090.0, 2000, 57, sidc=NA, track=[[50.9000, -0.6000]], speed_kmh=600),
    em("GPS L1 (civil users)", G, "nav", 50.84, -0.80, 0, 1575.42, 2046, None, fixed_level_dbm=-128, js_req_db=35, sens_dbm=-140, sidc=NL),
    rx("Civil GNSS (A27 Fishbourne)", G, "GPS L1 (civil users)", 50.8380, -0.8200, 2, 1575.42, 2046, sidc=NL),
    rx("Civil GNSS (Chichester centre)", G, "GPS L1 (civil users)", 50.8370, -0.7800, 2, 1575.42, 2046, sidc=NL),
    rx("Civil GNSS (harbour ferry)", G, "GPS L1 (civil users)", 50.8020, -0.8700, 5, 1575.42, 2046, sidc=NS, track=[[50.7900, -0.9300]], speed_kmh=12),
]

COR = [
    # blue: a notional HQ site at the scenario centre with its backhaul and a mobile reserve on the Box Hill ridge
    em("Blue Site HQ (Neston)", B, "comms", 51.4214, -2.2154, 10, BVL, 25, 46, sens_dbm=-110, js_req_db=0, hop_bw_khz=58000,
       notes="Site command net; hopping 30-88 MHz"),
    rx("Blue guard force (Rudloe)", B, "Blue Site HQ (Neston)", 51.4170, -2.2470, 3, BVL, 25, 37),
    rx("Blue QRF (Box Hill)", B, "Blue Site HQ (Neston)", 51.4190, -2.2650, 4, BVL, 25, 40, track=[[51.4080, -2.2250]], speed_kmh=30),
    rx("Blue picket (Lacock)", B, "Blue Site HQ (Neston)", 51.4150, -2.1200, 2, BVL, 25, 37),
    em("Blue microwave backhaul (Neston)", B, "comms", 51.4216, -2.2150, 20, 7500, 28000, 55, pattern="sector", azimuth=290, beamwidth=6,
       sens_dbm=-90, js_req_db=10, notes="Point-to-point link to the Colerne relay"),
    rx("Blue relay (Colerne)", B, "Blue microwave backhaul (Neston)", 51.4400, -2.2900, 25, 7500, 28000, 55, pattern="sector", azimuth=110, beamwidth=6),
    em("Blue SATCOM (site)", B, "comms", 51.4210, -2.2160, 3, 7950, 5000, 58, pattern="sector", azimuth=175, beamwidth=5),
    em("Blue UHF ground-air", B, "comms", 51.4390, -2.2900, 15, BU, 25, 47, sens_dbm=-105, js_req_db=0),
    rx("Blue helicopter (Colerne)", B, "Blue UHF ground-air", 51.4400, -2.2900, 200, BU, 25, 40, sidc=FA,
       track=[[51.4200, -2.2100], [51.3900, -2.1500], [51.4400, -2.2900]], speed_kmh=150),
    em("Blue GBAD radar (Colerne)", B, "radar", 51.4400, -2.2900, 12, 3000, 10000, 92),
    es("Blue ES/DF (Box Hill)", B, 51.4190, -2.2650, 8, 20, 3000, -115, df=2),
    es("Blue ES/DF (Neston mast)", B, 51.4214, -2.2154, 20, 20, 3000, -115, df=2),
    es("Blue ES/DF (Lacock)", B, 51.4150, -2.1200, 6, 20, 3000, -115, df=2),
    ea("Blue C-UAS (site)", B, "datalink", 51.4220, -2.2170, 4, 2440, 20000, 45, notes="Against the red drone datalink"),
    ea("Blue VHF jammer (Box Hill)", B, "comms", 51.4180, -2.2700, 8, RVL, 25, 58, notes="Against the red team net"),
    em("GPS L1 (space)", B, "nav", 51.42, -2.22, 0, 1575.42, 2046, None, fixed_level_dbm=-128, js_req_db=35, sens_dbm=-140),
    rx("Blue QRF (GNSS)", B, "GPS L1 (space)", 51.4190, -2.2650, 4, 1575.42, 2046, track=[[51.4080, -2.2250]], speed_kmh=30),
    rx("Blue helicopter (GNSS)", B, "GPS L1 (space)", 51.4400, -2.2900, 200, 1575.42, 2046, sidc=FA,
       track=[[51.4200, -2.2100], [51.3900, -2.1500], [51.4400, -2.2900]], speed_kmh=150),
    # red: covert ES/DF team, a drone, a GNSS spoofer on the M4
    em("Red team net (Corsham park)", R, "comms", 51.4330, -2.1950, 2, RVL, 25, 40, sens_dbm=-110, js_req_db=0, notes="Low power, hand-held"),
    rx("Red observer (Box village)", R, "Red team net (Corsham park)", 51.4130, -2.2600, 2, RVL, 25, 37, track=[[51.4200, -2.2400]], speed_kmh=4),
    rx("Red observer (Neston edge)", R, "Red team net (Corsham park)", 51.4260, -2.2080, 2, RVL, 25, 37),
    es("Red ES/DF (van, A4)", R, 51.4290, -2.1700, 3, 20, 3000, -112, df=3, track=[[51.4360, -2.2300]], speed_kmh=40),
    es("Red ES/DF (Bowden Hill)", R, 51.4030, -2.1150, 4, 20, 3000, -112, df=3),
    em("Red drone controller", R, "datalink", 51.4330, -2.1960, 2, 2440, 20000, 25, sens_dbm=-90, js_req_db=6),
    rx("Red drone", R, "Red drone controller", 51.4260, -2.2100, 120, 2440, 20000, 20, sidc=HA,
       track=[[51.4200, -2.2200], [51.4160, -2.2050], [51.4260, -2.2100]], speed_kmh=50),
    ea("Red GNSS spoofer (M4 car)", R, "nav", 51.4650, -2.2100, 2, 1575.42, 2046, 20, track=[[51.4600, -2.1200]], speed_kmh=90,
       notes="Aims to be accepted, not to deny"),
    ea("Red VHF jammer (car)", R, "comms", 51.4380, -2.1650, 2, BVL, 25, 50, track=[[51.4300, -2.2500]], speed_kmh=40, notes="Against the site net"),
    # grey: civil
    em("FM broadcast (Bath)", G, "comms", 51.3820, -2.3080, 80, 103.0, 200, 70, sidc=NL),
    em("Mobile mast (Corsham)", G, "comms", 51.4330, -2.1880, 30, 806.0, 10000, 60, sidc=NL),
    em("Bristol ATC radar", G, "radar", 51.3830, -2.7190, 30, 2800, 2000, 90, sidc=NL),
    em("Airliner (ADS-B, Bristol approach)", G, "other", 51.4500, -2.3500, 3000, 1090.0, 2000, 57, sidc=NA, track=[[51.4000, -2.6500]], speed_kmh=400),
    em("Wi-Fi (Neston)", G, "other", 51.4200, -2.2170, 5, 2437, 20000, 20, sidc=NL),
    em("GPS L1 (civil users)", G, "nav", 51.43, -2.20, 0, 1575.42, 2046, None, fixed_level_dbm=-128, js_req_db=35, sens_dbm=-140, sidc=NL),
    rx("Civil GNSS (M4 J17)", G, "GPS L1 (civil users)", 51.4720, -2.1250, 2, 1575.42, 2046, sidc=NL),
    rx("Civil GNSS (A4 Corsham)", G, "GPS L1 (civil users)", 51.4330, -2.1900, 2, 1575.42, 2046, sidc=NL),
    rx("Civil GNSS (Neston)", G, "GPS L1 (civil users)", 51.4210, -2.2150, 2, 1575.42, 2046, sidc=NL),
]
_sp2 = [e for e in COR if e["name"] == "Red GNSS spoofer (M4 car)"][0]; _sp2["ea_mode"] = "spoof"

EXAMPLES = {
    "sussex-coast": {"title": "0d. Sussex coast: Chichester and the Solent approaches (notional, AR)",
                     "about": "Home-defence MDO on real ground you can stand on. Blue holds the Portsmouth approaches, Thorney Island "
                              "and Chichester Harbour from a coordination HQ at ///shares.cared.shunts; red probes from the Channel with "
                              "a raid group, a landed recce party, a UAV and GNSS interference on the A27; grey is Goodwood, the harbour "
                              "and the town. Built for the AR view: stand at the centre and the emitters sit in their real directions.",
                     "centre": [50.82, -0.85], "zoom": 12, "params": {"df_fix_good_m": 800}, "entities": CHI},
    "corsham-hub": {"title": "0e. Corsham hub: site defence around Neston (notional, AR)",
                    "about": "Site-defence MDO centred on ///gratitude.system.segmented. Blue protects a notional HQ site, its microwave "
                             "backhaul to Colerne and its SATCOM, with a QRF on the Box Hill ridge; red is a covert ES/DF team, a drone "
                             "and a GNSS spoofer on the M4; grey is Bath and Bristol civil, Corsham's mast and M4 traffic. Built for the "
                             "AR view from the centre.",
                    "centre": [51.425, -2.22], "zoom": 13, "params": {"df_fix_good_m": 500}, "entities": COR},
    **EXAMPLES}
