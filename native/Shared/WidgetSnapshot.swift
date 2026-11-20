import Foundation

/// What the widgets show: Kp, GNSS interference, item counts and the time of the latest brief, as of the app's last
/// check. The widgets never ask the server themselves (an extension cannot use the app's built-in Tailscale node): the
/// app takes GET /api/status on every check (Notifier, every 5 minutes while it runs; on the iPhone also on a background
/// refresh), writes this snapshot to the shared app-group container and asks WidgetKit to redraw. Pure apart from
/// `Store`, so the wording and thresholds are tested (native/Tests/WidgetSnapshotTests.swift).
struct WidgetSnapshot: Codable, Sendable, Equatable {
    var fetchedAt: Date
    var server: String
    var kp: Double?
    var kpMax24h: Double?
    var scales: String?                 // "R0 S0 G1"
    var gnssHigh: Int?
    var gnssMedium: Int?
    var gnssDate: String?               // the day the GNSS interference map describes (YYYY-MM-DD)
    var items24h: Int?
    var high24h: Int?
    var cyber24h: Int?
    var em24h: Int?
    var briefAt: Date?
    var briefGenerating: Bool?

    /// Built from GET /api/status. Missing fields stay nil and show as a dash.
    static func make(status s: StatusResponse, server: String, now: Date) -> WidgetSnapshot {
        WidgetSnapshot(
            fetchedAt: now, server: server,
            kp: s.spaceweather?.kp, kpMax24h: s.spaceweather?.kp_max_24h, scales: s.spaceweather?.scales?.summary,
            gnssHigh: s.gnss?.high, gnssMedium: s.gnss?.medium, gnssDate: s.gnss?.date,
            items24h: s.counts?.items_24h, high24h: s.counts?.high_24h, cyber24h: s.counts?.cyber_24h, em24h: s.counts?.em_24h,
            briefAt: s.brief?.latest_at.flatMap(ISODate.parse), briefGenerating: s.brief?.generating)
    }

    /// Notional placeholder for the widget gallery (never real data).
    static let placeholder = WidgetSnapshot(
        fetchedAt: Date(timeIntervalSince1970: 0), server: "", kp: 2.3, kpMax24h: 3.0, scales: "R0 S0 G0",
        gnssHigh: 4, gnssMedium: 9, gnssDate: nil, items24h: 120, high24h: 3, cyber24h: 60, em24h: 25, briefAt: nil, briefGenerating: false)

    // MARK: wording

    /// NOAA G-scale reading of Kp: below 4 quiet or unsettled, 4 active, 5 to 9 storm G1 to G5.
    static func kpBand(_ kp: Double?) -> String {
        guard let kp else { return "no data" }
        switch kp {
        case ..<3: return "quiet"
        case ..<4: return "unsettled"
        case ..<5: return "active"
        default: return "storm G\(min(5, Int(kp.rounded(.down)) - 4))"
        }
    }
    /// 0 quiet, 1 unsettled or active, 2 storm: drives the colour.
    static func kpLevel(_ kp: Double?) -> Int {
        guard let kp else { return 0 }
        return kp >= 5 ? 2 : (kp >= 4 ? 1 : 0)
    }
    static func kpText(_ kp: Double?) -> String { kp.map { String(format: "%.1f", $0) } ?? "–" }
    static func count(_ n: Int?) -> String { n.map(String.init) ?? "–" }

    /// "high 4, medium 9" (cells of the daily GNSS interference map).
    var gnssText: String {
        guard gnssHigh != nil || gnssMedium != nil else { return "no data" }
        return "high \(WidgetSnapshot.count(gnssHigh)), medium \(WidgetSnapshot.count(gnssMedium))"
    }

    /// Older than 30 minutes: the app has not checked (not running, no connection); the widget says so.
    static let staleAfter: TimeInterval = 30 * 60
    func isStale(now: Date) -> Bool { now.timeIntervalSince(fetchedAt) > WidgetSnapshot.staleAfter }

    /// "just now", "12 min ago", "3 h ago", "2 d ago".
    static func age(_ from: Date?, now: Date) -> String {
        guard let from else { return "–" }
        let s = max(0, now.timeIntervalSince(from))
        if s < 90 { return "just now" }
        if s < 3600 { return "\(Int(s / 60)) min ago" }
        if s < 48 * 3600 { return "\(Int(s / 3600)) h ago" }
        return "\(Int(s / 86400)) d ago"
    }

    func briefText(now: Date) -> String {
        if briefGenerating == true { return "writing" }
        return briefAt == nil ? "none" : WidgetSnapshot.age(briefAt, now: now)
    }

    // MARK: shared container

    /// The app group both the app and its widget extension carry (project.yml). macOS uses the team-prefixed form,
    /// which needs no registration; iOS the `group.` form.
    #if os(macOS)
    static let appGroup = "747JXF57MZ.com.neildonaghy.cyem"
    #else
    static let appGroup = "group.com.neildonaghy.cyem"
    #endif

    enum Store {
        static let kind = "CyEMStatus"
        private static var url: URL? {
            FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: WidgetSnapshot.appGroup)?
                .appending(path: "widget-snapshot.json")
        }
        static func load() -> WidgetSnapshot? {
            guard let url, let d = try? Data(contentsOf: url) else { return nil }
            let dec = JSONDecoder(); dec.dateDecodingStrategy = .secondsSince1970
            return try? dec.decode(WidgetSnapshot.self, from: d)
        }
        @discardableResult
        static func save(_ s: WidgetSnapshot) -> Bool {
            guard let url else { return false }
            let enc = JSONEncoder(); enc.dateEncodingStrategy = .secondsSince1970
            guard let d = try? enc.encode(s) else { return false }
            return (try? d.write(to: url, options: .atomic)) != nil
        }
    }
}
