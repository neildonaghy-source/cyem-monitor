import XCTest

final class ARGeoTests: XCTestCase {
    func testENUDirectionsAndDistance() {
        // 0.01 degree north of a point at 51 N is about 1112 m; 0.01 degree east about 700 m
        let n = ARGeo.enu(fromLat: 51, lon: -1.8, toLat: 51.01, lon: -1.8, height: 1.5)
        XCTAssertEqual(n.n, 1111.9, accuracy: 1); XCTAssertEqual(n.e, 0, accuracy: 1e-6)
        XCTAssertEqual(ARGeo.bearing(n), 0, accuracy: 1e-6)
        let e = ARGeo.enu(fromLat: 51, lon: -1.8, toLat: 51, lon: -1.79, height: 1.5)
        XCTAssertEqual(e.e, 699.8, accuracy: 1); XCTAssertEqual(ARGeo.bearing(e), 90, accuracy: 1e-6)
        let sw = ARGeo.enu(fromLat: 51, lon: -1.8, toLat: 50.99, lon: -1.81, height: 1.5)
        XCTAssertEqual(ARGeo.bearing(sw), 212, accuracy: 1)             // south-west, more south than west at 51 N
        XCTAssertEqual(ARGeo.compass(ARGeo.bearing(sw)), "SSW")
    }

    func testEarthCurveDropsFarPoints() {
        // a 30 m mast 20 km away: 30 - 1.5 - 20000^2 / (2 R) = 28.5 - 31.4 = about -2.9 m, just below eye level
        let v = ARGeo.enu(fromLat: 51, lon: 0, toLat: 51 + 20_000 / 111_195, lon: 0, height: 30)
        XCTAssertEqual(v.u, -2.9, accuracy: 0.2)
        XCTAssertLessThan(ARGeo.elevation(v), 0)
        let near = ARGeo.enu(fromLat: 51, lon: 0, toLat: 51.001, lon: 0, height: 30)
        XCTAssertEqual(ARGeo.elevation(near), atan2(28.5, 111.2) * 180 / .pi, accuracy: 0.1)
    }

    func testWorldIsGravityAndHeading() {
        // ARKit gravity-and-heading: +x east, +y up, -z north
        let w = ARGeo.world((e: 0, n: 100, u: 10))
        XCTAssertEqual(w.x, 0); XCTAssertEqual(w.y, 10); XCTAssertEqual(w.z, -100)
        let far = ARGeo.world((e: 30_000, n: 40_000, u: 0), render: 200)   // 50 km pulled in to 200 m, same direction
        XCTAssertEqual(far.x, 120, accuracy: 1e-9); XCTAssertEqual(far.z, -160, accuracy: 1e-9)
    }

    func testTextAndFindings() throws {
        XCTAssertEqual(ARGeo.distanceText(640), "640 m")
        XCTAssertEqual(ARGeo.distanceText(4_260), "4.3 km")
        XCTAssertEqual(ARGeo.distanceText(23_600), "24 km")
        let json = """
        {"t": 10, "ran": true, "corridor": {"unit": "Blue UAV", "side": "blue", "legs": [{"emcon": "silent", "hold": false, "t_from": 0, "path": [[51.2, -1.8], [51.21, -1.81]]}]},
         "entities": [
          {"id": "a", "name": "Red ES/DF 1", "side": "red", "kind": "sensor", "category": "df", "lat": 51.27, "lon": -2.07, "h_agl": 12, "freq_mhz": 2000,
           "on_air": true, "detected_by": [], "status": null, "denies": [], "target_quality": false},
          {"id": "b", "name": "Blue UAS GCS", "side": "blue", "kind": "emitter", "category": "datalink", "lat": 51.2, "lon": -1.8, "h_agl": 5, "freq_mhz": 2350,
           "on_air": true, "detected_by": ["Red ES/DF 1", "Red ES/DF 2"], "status": "degraded", "denies": [], "target_quality": true},
          {"id": "c", "name": "GPS L1 (space)", "side": "blue", "kind": "emitter", "category": "nav", "lat": 51.2, "lon": -1.9, "h_agl": 0, "freq_mhz": 1575.42,
           "on_air": true, "detected_by": [], "status": null, "denies": [], "target_quality": false}]}
        """
        let s = try JSONDecoder().decode(ARScene.self, from: Data(json.utf8))
        XCTAssertEqual(s.corridor?.legs.first?.path.count, 2)
        XCTAssertEqual(ARGeo.findings(s.entities[1]), "target-quality fix · degraded · heard by 2")
        let v = ARGeo.visible(s.entities, sides: ["blue", "red"], fromLat: 51.2, lon: -1.8, rangeKm: 10)
        XCTAssertEqual(v.map(\.id), ["b"])                                // ES/DF is 20 km off; the GPS signal is not a place
        XCTAssertEqual(ARGeo.visible(s.entities, sides: ["red"], fromLat: 51.2, lon: -1.8, rangeKm: 50).map(\.id), ["a"])
    }
}
