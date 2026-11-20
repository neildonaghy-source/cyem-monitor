import Foundation

/// What to notify after one check of the server: pure, no I/O, so it is unit-tested (native/Tests). The first check
/// against a server only records what is there (no flood of old items when the app is installed or the server changes).
struct NotifyPlan: Equatable, Sendable {
    struct Note: Equatable, Sendable {
        var id: String                     // notification identifier (item id or "brief-<id>")
        var title: String
        var body: String
        var link: String?                  // opened on tap: an item's source page; nil means the CyEM home page
        var thread: String                 // "items" or "briefs" (grouped in Notification Centre)
    }

    /// What the app remembers between checks (UserDefaults).
    struct Memory: Codable, Equatable, Sendable {
        var server: String = ""
        var seen: [String] = []            // high-severity item ids already seen, newest last, capped
        var lastBrief: Int?                // highest brief id seen
    }

    static let seenCap = 600
    static let maxSingle = 3               // more new items than this in one check: one summary notification

    var notes: [Note]
    var memory: Memory

    static func plan(server: String, items: [Item]?, latestBrief: BriefRow?, memory old: Memory,
                     itemsOn: Bool, briefsOn: Bool) -> NotifyPlan {
        var m = old
        let fresh = m.server != server
        if fresh { m = Memory(server: server) }
        var notes: [Note] = []

        if let items {
            let high = items.filter { $0.severity >= 4 }
            let known = Set(m.seen)
            let new = high.filter { !known.contains($0.id) }
            if !fresh && itemsOn && !new.isEmpty {
                if new.count > maxSingle {
                    let top = new.max { $0.severity < $1.severity }!
                    notes.append(Note(id: "items-\(top.id)", title: "\(new.count) new high-severity items",
                                      body: "Highest: \(top.title)", link: nil, thread: "items"))
                } else {
                    for it in new {
                        let place = it.country_name.map { " · \($0) (placement only)" } ?? ""
                        notes.append(Note(id: it.id, title: "Severity \(it.severity): \(it.title)",
                                          body: "\(it.source)\(place)" + (it.summary.map { "\n" + clip($0, 180) } ?? ""),
                                          link: it.url, thread: "items"))
                    }
                }
            }
            m.seen = Array((m.seen + new.map(\.id)).suffix(seenCap))
        }

        if let b = latestBrief {
            if let last = m.lastBrief, b.id > last, !fresh, briefsOn {
                let kind = b.kind.map { $0 + " brief" } ?? "Brief"
                notes.append(Note(id: "brief-\(b.id)", title: "\(kind.prefix(1).uppercased() + kind.dropFirst()) ready",
                                  body: clip(plain(b.preview ?? ""), 180), link: nil, thread: "briefs"))
            }
            m.lastBrief = max(m.lastBrief ?? b.id, b.id)
        }
        return NotifyPlan(notes: notes, memory: m)
    }

    static func clip(_ s: String, _ n: Int) -> String {
        let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.count <= n ? t : String(t.prefix(n - 1)) + "…"
    }

    /// Markdown preview to plain text (headings, emphasis, list marks, line breaks).
    static func plain(_ md: String) -> String {
        md.replacingOccurrences(of: #"[#*_`>]+"#, with: "", options: .regularExpression)
          .replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
          .trimmingCharacters(in: .whitespaces)
    }
}
