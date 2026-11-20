import XCTest

final class WidgetSnapshotTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_795_000_000)

    private func status(_ json: String) throws -> StatusResponse {
        try JSONDecoder().decode(StatusResponse.self, from: Data(json.utf8))
    }

    func testMakeFromStatus() throws {
        let s = try status("""
        {"spaceweather": {"kp": 5.33, "kp_max_24h": 6.0, "scales": {"R": {"level": 0}, "S": {"level": "1"}, "G": {"level": 2}}},
         "gnss": {"date": "2026-11-19", "high": 7, "medium": 12, "by_region": {}},
         "counts": {"items_24h": 340, "high_24h": 5, "cyber_24h": 200, "em_24h": 40},
         "brief": {"latest_at": "2026-11-20T06:00:00+00:00", "latest_id": 9, "generating": false}}
        """)
        let w = WidgetSnapshot.make(status: s, server: "https://cyem.example/", now: now)
        XCTAssertEqual(w.kp, 5.33)
        XCTAssertEqual(w.scales, "R0 S1 G2")
        XCTAssertEqual(w.gnssHigh, 7)
        XCTAssertEqual(w.items24h, 340)
        XCTAssertEqual(w.high24h, 5)
        XCTAssertNotNil(w.briefAt)
        XCTAssertEqual(w.gnssText, "high 7, medium 12")
    }

    func testMissingFieldsDegrade() throws {
        let w = WidgetSnapshot.make(status: try status("{}"), server: "s", now: now)
        XCTAssertNil(w.kp)
        XCTAssertEqual(WidgetSnapshot.kpText(w.kp), "–")
        XCTAssertEqual(WidgetSnapshot.kpBand(w.kp), "no data")
        XCTAssertEqual(w.gnssText, "no data")
        XCTAssertEqual(WidgetSnapshot.count(w.items24h), "–")
        XCTAssertEqual(w.briefText(now: now), "none")
    }

    func testKpBands() {
        XCTAssertEqual(WidgetSnapshot.kpBand(1.7), "quiet")
        XCTAssertEqual(WidgetSnapshot.kpBand(3.0), "unsettled")
        XCTAssertEqual(WidgetSnapshot.kpBand(4.67), "active")
        XCTAssertEqual(WidgetSnapshot.kpBand(5.0), "storm G1")
        XCTAssertEqual(WidgetSnapshot.kpBand(7.33), "storm G3")
        XCTAssertEqual(WidgetSnapshot.kpBand(9.0), "storm G5")
        XCTAssertEqual(WidgetSnapshot.kpLevel(3.9), 0)
        XCTAssertEqual(WidgetSnapshot.kpLevel(4.0), 1)
        XCTAssertEqual(WidgetSnapshot.kpLevel(5.0), 2)
    }

    func testAgeAndStale() {
        var w = WidgetSnapshot.placeholder
        w.fetchedAt = now.addingTimeInterval(-20 * 60)
        XCTAssertFalse(w.isStale(now: now))
        XCTAssertEqual(WidgetSnapshot.age(w.fetchedAt, now: now), "20 min ago")
        w.fetchedAt = now.addingTimeInterval(-31 * 60)
        XCTAssertTrue(w.isStale(now: now))
        XCTAssertEqual(WidgetSnapshot.age(now.addingTimeInterval(-30), now: now), "just now")
        XCTAssertEqual(WidgetSnapshot.age(now.addingTimeInterval(-5 * 3600), now: now), "5 h ago")
        XCTAssertEqual(WidgetSnapshot.age(now.addingTimeInterval(-3 * 86400), now: now), "3 d ago")
        w.briefGenerating = true
        XCTAssertEqual(w.briefText(now: now), "writing")
    }

    func testRoundTripEncoding() throws {
        let enc = JSONEncoder(); enc.dateEncodingStrategy = .secondsSince1970
        let dec = JSONDecoder(); dec.dateDecodingStrategy = .secondsSince1970
        var w = WidgetSnapshot.placeholder
        w.fetchedAt = now
        XCTAssertEqual(try dec.decode(WidgetSnapshot.self, from: enc.encode(w)), w)
    }
}
