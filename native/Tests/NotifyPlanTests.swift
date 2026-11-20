import XCTest

final class NotifyPlanTests: XCTestCase {
    private let srv = "https://cyem.example/"

    private func item(_ id: String, sev: Int, title: String = "t", url: String? = "https://src.example/a") -> Item {
        Item(id: id, source: "src", domain: "cyber", kind: "news", title: title, url: url, summary: "s", published_at: nil,
             country: "GB", country_name: "United Kingdom", lat: nil, lon: nil, severity: sev, tags: nil)
    }
    private func brief(_ id: Int) -> BriefRow { BriefRow(id: id, created_at: nil, kind: "scheduled", preview: "## Key points\n**A** b") }

    func testFirstCheckOnlyRemembers() {
        let p = NotifyPlan.plan(server: srv, items: [item("a", sev: 5)], latestBrief: brief(3), memory: .init(), itemsOn: true, briefsOn: true)
        XCTAssertTrue(p.notes.isEmpty)
        XCTAssertEqual(p.memory.seen, ["a"])
        XCTAssertEqual(p.memory.lastBrief, 3)
        XCTAssertEqual(p.memory.server, srv)
    }

    func testNewHighItemsAndBrief() {
        let m = NotifyPlan.Memory(server: srv, seen: ["a"], lastBrief: 3)
        let p = NotifyPlan.plan(server: srv, items: [item("a", sev: 5), item("b", sev: 4, title: "Exploited"), item("c", sev: 3)],
                                latestBrief: brief(4), memory: m, itemsOn: true, briefsOn: true)
        XCTAssertEqual(p.notes.map(\.id), ["b", "brief-4"])
        XCTAssertEqual(p.notes[0].title, "Severity 4: Exploited")
        XCTAssertTrue(p.notes[0].body.contains("placement only"))
        XCTAssertEqual(p.notes[0].link, "https://src.example/a")
        XCTAssertEqual(p.notes[1].title, "Scheduled brief ready")
        XCTAssertEqual(p.notes[1].body, "Key points A b")
        XCTAssertNil(p.notes[1].link)
        XCTAssertEqual(p.memory.seen, ["a", "b"])                     // severity 3 is never remembered or notified
        XCTAssertEqual(p.memory.lastBrief, 4)
    }

    func testManyNewItemsGiveOneSummary() {
        let m = NotifyPlan.Memory(server: srv, seen: [], lastBrief: nil)
        let items = (1...5).map { item("i\($0)", sev: $0 == 3 ? 5 : 4, title: "T\($0)") }
        let p = NotifyPlan.plan(server: srv, items: items, latestBrief: nil, memory: m, itemsOn: true, briefsOn: true)
        XCTAssertEqual(p.notes.count, 1)
        XCTAssertEqual(p.notes[0].title, "5 new high-severity items")
        XCTAssertEqual(p.notes[0].body, "Highest: T3")
    }

    func testSwitchedOffStillRemembers() {
        let m = NotifyPlan.Memory(server: srv, seen: [], lastBrief: 1)
        let p = NotifyPlan.plan(server: srv, items: [item("x", sev: 5)], latestBrief: brief(2), memory: m, itemsOn: false, briefsOn: false)
        XCTAssertTrue(p.notes.isEmpty)
        XCTAssertEqual(p.memory.seen, ["x"])
        XCTAssertEqual(p.memory.lastBrief, 2)                         // turning them back on does not replay old ones
    }

    func testNewServerStartsAfresh() {
        let m = NotifyPlan.Memory(server: "https://other/", seen: ["a"], lastBrief: 9)
        let p = NotifyPlan.plan(server: srv, items: [item("b", sev: 5)], latestBrief: brief(2), memory: m, itemsOn: true, briefsOn: true)
        XCTAssertTrue(p.notes.isEmpty)
        XCTAssertEqual(p.memory, NotifyPlan.Memory(server: srv, seen: ["b"], lastBrief: 2))
    }

    func testFailedFetchKeepsMemory() {
        let m = NotifyPlan.Memory(server: srv, seen: ["a"], lastBrief: 3)
        let p = NotifyPlan.plan(server: srv, items: nil, latestBrief: nil, memory: m, itemsOn: true, briefsOn: true)
        XCTAssertTrue(p.notes.isEmpty)
        XCTAssertEqual(p.memory, m)
    }

    func testSeenIsCapped() {
        let m = NotifyPlan.Memory(server: srv, seen: (0..<NotifyPlan.seenCap).map { "o\($0)" }, lastBrief: nil)
        let p = NotifyPlan.plan(server: srv, items: [item("n", sev: 4)], latestBrief: nil, memory: m, itemsOn: true, briefsOn: true)
        XCTAssertEqual(p.memory.seen.count, NotifyPlan.seenCap)
        XCTAssertEqual(p.memory.seen.last, "n")
        XCTAssertEqual(p.memory.seen.first, "o1")
    }
}
