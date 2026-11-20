import Foundation

// Wire models for the CyEM API (app/main.py). Every field is optional unless the server always sends it, so a
// server change degrades a field rather than failing the whole decode.

struct StatusResponse: Decodable, Sendable {
    var time: String?
    var spaceweather: SpaceWeather?
    var hf: HFSnapshot?
    var gnss: GNSS?
    var counts: Counts?
    var brief: BriefState?
    var collectors: [CollectorRun]?

    struct SpaceWeather: Decodable, Sendable {
        var kp: Double?
        var kp_max_24h: Double?
        var scales: Scales?
        var max_flare_24h: String?
        var f107: Double?
    }
    struct Scales: Decodable, Sendable {
        var R: Scale?
        var S: Scale?
        var G: Scale?
        var summary: String { "R\(R?.level ?? "0") S\(S?.level ?? "0") G\(G?.level ?? "0")" }
    }
    struct Scale: Decodable, Sendable {
        var level: String?
        var text: String?

        enum CodingKeys: String, CodingKey { case level, text }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            // the level comes as a string or a number
            if let s = try? c.decodeIfPresent(String.self, forKey: .level) { level = s }
            else if let n = try? c.decodeIfPresent(Int.self, forKey: .level) { level = String(n) }
            text = try? c.decodeIfPresent(String.self, forKey: .text)
        }
    }
    struct HFSnapshot: Decodable, Sendable {
        var solarflux: String?
        var geomagfield: String?
        var signalnoise: String?

        enum CodingKeys: String, CodingKey { case solarflux, geomagfield, signalnoise }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            func str(_ k: CodingKeys) -> String? {
                if let s = try? c.decodeIfPresent(String.self, forKey: k) { return s }
                if let d = try? c.decodeIfPresent(Double.self, forKey: k) { return String(Int(d)) }
                return nil
            }
            solarflux = str(.solarflux); geomagfield = str(.geomagfield); signalnoise = str(.signalnoise)
        }
    }
    struct GNSS: Decodable, Sendable {
        var date: String?
        var high: Int?
        var medium: Int?
    }
    struct Counts: Decodable, Sendable {
        var items_24h: Int?
        var cyber_24h: Int?
        var em_24h: Int?
        var infra_24h: Int?
        var osint_24h: Int?
        var high_24h: Int?
        var cve_7d: Int?
    }
    struct BriefState: Decodable, Sendable {
        var latest_at: String?
        var latest_id: Int?
        var generating: Bool?
        var model: String?
    }
    struct CollectorRun: Decodable, Sendable, Identifiable {
        var name: String
        var domain: String?
        var description: String?
        var enabled: Bool?
        var running: Bool?
        var ok: Int?
        var last_finished: String?
        var message: String?
        var id: String { name }
        var healthy: Bool { ok == 1 }
    }
}

struct ItemsResponse: Decodable, Sendable {
    var items: [Item]
    var count: Int?
}

struct Item: Decodable, Sendable, Identifiable, Hashable {
    var id: String
    var source: String
    var domain: String
    var kind: String
    var title: String
    var url: String?
    var summary: String?
    var published_at: String?
    var country: String?
    var country_name: String?
    var lat: Double?
    var lon: Double?
    var severity: Int
    var tags: [String]?

    var published: Date? { published_at.flatMap(ISODate.parse) }
    var link: URL? { url.flatMap(URL.init(string:)) }
}

struct BriefsResponse: Decodable, Sendable {
    var briefs: [BriefRow]
}

/// One row of GET /api/briefs (the first 160 characters of the brief as `preview`).
struct BriefRow: Decodable, Sendable, Equatable {
    var id: Int
    var created_at: String?
    var kind: String?
    var preview: String?
}

struct MeResponse: Decodable, Sendable {
    var internet: Bool
    var user: String?
}

enum Domain: String, CaseIterable, Identifiable, Sendable {
    case all, cyber, em, infra, osint
    var id: String { rawValue }
    var label: String {
        switch self {
        case .all: "All"
        case .cyber: "Cyber"
        case .em: "EM"
        case .infra: "Infra"
        case .osint: "OSINT"
        }
    }
}

enum ISODate {
    nonisolated(unsafe) private static let withFraction: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]; return f
    }()
    nonisolated(unsafe) private static let plain: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime]; return f
    }()
    static func parse(_ s: String) -> Date? { withFraction.date(from: s) ?? plain.date(from: s) }
}
