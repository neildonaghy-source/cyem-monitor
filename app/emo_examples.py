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
    em("Blue Bde HQ", B, "comms", 57.600, -4.600, 10, BV, 25, 47, sens_dbm=-110, js_req_db=0),
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
    em("Blue Link 16 (AEW)", B, "datalink", 57.600, -3.800, 9000, L16, 255000, 50, sens_dbm=-100, js_req_db=10, sidc=FA),
    rx("Blue fighter pair", B, "Blue Link 16 (AEW)", 57.950, -5.000, 8000, L16, 255000, 43, sidc=FA,
       track=[[58.150, -5.250], [57.950, -5.450], [57.950, -5.000]], speed_kmh=700),
    es("Blue airborne ES", B, 57.700, -6.100, 10000, 20, 18000, -115, df=3, sidc=FA,
       track=[[58.050, -6.200], [57.600, -6.200], [58.050, -6.200]], speed_kmh=600),
    # ---- blue maritime
    em("Blue frigate radar", B, "radar", 57.750, -5.950, 25, 3000, 10000, 92, sidc=FS, track=[[58.000, -5.900]], speed_kmh=30),
    rx("Blue frigate (Link 16)", B, "Blue Link 16 (AEW)", 57.750, -5.950, 25, L16, 255000, 43, sidc=FS,
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
             "are the loudest emitters and are fixed first; the L-band barrage hits Link 16 (modelled as one "
             "wideband channel: hopping and processing gain are not modelled, so blue J/S is pessimistic); the red VHF barrage "
             "loses about 29 dB spreading over 20 MHz; GNSS jamming from high ground reaches aircraft, the frigate and precision fires; blue EA denies the red "
             "VHF net. Tap any symbol to focus on it. First run takes a couple of minutes (new terrain tiles).",
    "centre": [57.95, -5.10], "zoom": 8, "entities": MDO}, **EXAMPLES}
