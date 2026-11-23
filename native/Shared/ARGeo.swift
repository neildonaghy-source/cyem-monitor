import Foundation

/// AR view (iPhone, 0.6.0): what GET /api/emo/ar returns, and the pure geometry that puts it in an ARKit world aligned
/// with gravity and true north (ARWorldTrackingConfiguration.worldAlignment = .gravityAndHeading: +x east, +y up,
/// -z north, origin where the session started). Foundation only, so it is unit-tested on the Mac (CyEMTests).
struct ARScene: Decodable, Sendable {
    let t: Double
    let ran: Bool
    let entities: [AREntity]
    let corridor: ARCorridor?
}

struct AREntity: Decodable, Sendable, Identifiable {
    let id: String
    let name: String
    let side: String
    let kind: String
    let category: String?
    let lat: Double
    let lon: Double
    let h_agl: Double
    let freq_mhz: Double?
    let on_air: Bool
    let detected_by: [String]
    let status: String?
    let denies: [String]
    let target_quality: Bool
}

struct ARCorridor: Decodable, Sendable {
    struct Leg: Decodable, Sendable { let emcon: String?; let hold: Bool; let t_from: Double?; let path: [[Double]] }
    let unit: String?
    let side: String?
    let legs: [Leg]
}

enum ARGeo {
    static let earthRadius = 6_371_008.8
    static let eyeHeight = 1.5                       // the phone's height above the ground (m)

    /// East, north, up (m) from an observer to a point, on a sphere: the local tangent plane plus the drop of the
    /// earth's curve, so a distant mast sits lower in the view as it does to the eye. Heights are above local ground
    /// at each end (no terrain model on the phone).
    static func enu(fromLat lat0: Double, lon lon0: Double, toLat lat: Double, lon: Double, height h: Double,
                    observerHeight h0: Double = eyeHeight) -> (e: Double, n: Double, u: Double) {
        let r = Double.pi / 180
        let n = (lat - lat0) * r * earthRadius
        let e = (lon - lon0) * r * earthRadius * cos((lat + lat0) / 2 * r)
        let d2 = e * e + n * n
        return (e, n, h - h0 - d2 / (2 * earthRadius))
    }

    static func distance(_ v: (e: Double, n: Double, u: Double)) -> Double { (v.e * v.e + v.n * v.n).squareRoot() }

    /// Bearing from true north (0-360) and elevation (degrees) of an ENU offset.
    static func bearing(_ v: (e: Double, n: Double, u: Double)) -> Double {
        let b = atan2(v.e, v.n) * 180 / .pi
        return b < 0 ? b + 360 : b
    }
    static func elevation(_ v: (e: Double, n: Double, u: Double)) -> Double { atan2(v.u, max(distance(v), 0.01)) * 180 / .pi }

    /// The point in ARKit's gravity-and-heading world (x east, y up, z south). Far points keep their direction but are
    /// pulled in to `render` metres, which is all a screen projection needs and keeps the numbers small.
    static func world(_ v: (e: Double, n: Double, u: Double), render: Double = 200) -> (x: Double, y: Double, z: Double) {
        let len = (v.e * v.e + v.n * v.n + v.u * v.u).squareRoot()
        let k = len > render ? render / len : 1
        return (v.e * k, v.u * k, -v.n * k)
    }

    static func distanceText(_ m: Double) -> String {
        m < 1000 ? "\(Int(m.rounded())) m" : (m < 10_000 ? String(format: "%.1f km", m / 1000) : "\(Int((m / 1000).rounded())) km")
    }

    static func compass(_ b: Double) -> String {
        let pts = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        return pts[Int(((b.truncatingRemainder(dividingBy: 360) + 360).truncatingRemainder(dividingBy: 360) / 22.5).rounded()) % 16]
    }

    /// The second line under a marker: what the last run found.
    static func findings(_ e: AREntity) -> String {
        var s: [String] = []
        if !e.on_air { s.append("off air") }
        if e.target_quality { s.append("target-quality fix") }
        if let st = e.status { s.append(st) }
        if !e.denies.isEmpty { s.append("denies \(e.denies.count)") }
        if !e.detected_by.isEmpty { s.append("heard by \(e.detected_by.count)") }
        return s.joined(separator: " · ")
    }

    /// Which entities to draw: the chosen sides, within range, not the satellite signals (fixed level, no place).
    static func visible(_ ents: [AREntity], sides: Set<String>, fromLat lat: Double, lon: Double, rangeKm: Double) -> [AREntity] {
        ents.filter { e in
            sides.contains(e.side) && !(e.category == "nav" && e.kind == "emitter" && e.h_agl == 0)
                && distance(enu(fromLat: lat, lon: lon, toLat: e.lat, lon: e.lon, height: e.h_agl)) <= rangeKm * 1000
        }
    }
}
