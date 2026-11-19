import Foundation
import MapKit
import SwiftUI

// Map layers from GET /api/layers/<name> (snapshots kept by the collectors). Each decoder is lenient: a missing field
// drops one point, never the layer.

enum MapLayer: String, CaseIterable, Identifiable, Sendable {
    case items, gpsjam, air, milair, ais, sats, radars, hfmap, cables, c2
    var id: String { rawValue }
    var label: String {
        switch self {
        case .items: "News and alerts (placed)"
        case .gpsjam: "GNSS interference"
        case .air: "All aircraft (ADS-B, UK)"
        case .milair: "Military aircraft"
        case .ais: "Ships (AIS, UK waters)"
        case .sats: "Satellites (now)"
        case .radars: "Radar sites (OSM)"
        case .hfmap: "HF MUF contours"
        case .cables: "Submarine cables"
        case .c2: "Botnet C2 by country"
        }
    }
    var symbol: String {
        switch self {
        case .items: "newspaper"
        case .gpsjam: "location.slash"
        case .air: "airplane"
        case .milair: "airplane.circle"
        case .ais: "ferry"
        case .sats: "satellite"
        case .radars: "dot.radiowaves.left.and.right"
        case .hfmap: "waveform.path"
        case .cables: "cable.connector"
        case .c2: "ladybug"
        }
    }
    var colour: Color {
        switch self {
        case .items: Palette.accent
        case .gpsjam: .red
        case .air: Color(white: 0.75)
        case .milair: .orange
        case .ais: .cyan
        case .sats: .purple
        case .radars: .mint
        case .hfmap: .yellow
        case .cables: Color(red: 0.4, green: 0.6, blue: 0.9)
        case .c2: Color(red: 0.86, green: 0.24, blue: 0.86)
        }
    }
    var api: String? { self == .items ? nil : rawValue }
}

struct LayerEnvelope<T: Decodable & Sendable>: Decodable, Sendable {
    var updated: String?
    var data: T?
}

/// A point on the map from any layer, with what the detail card shows.
struct MapPoint: Identifiable, Hashable, Sendable {
    var id: String
    var layer: MapLayer
    var lat: Double
    var lon: Double
    var title: String
    var detail: String
    var heading: Double?
    var tint: String?                      // gpsjam level, aircraft role, ship category
    var coordinate: CLLocationCoordinate2D { .init(latitude: lat, longitude: lon) }
    static func == (a: MapPoint, b: MapPoint) -> Bool { a.id == b.id }
    func hash(into h: inout Hasher) { h.combine(id) }
}

struct MapLine: Identifiable, Sendable {
    var id: String
    var layer: MapLayer
    var coords: [CLLocationCoordinate2D]
    var label: String
    var colour: String?
}

struct JamPolygon: Identifiable, Sendable {
    var id: String
    var coords: [CLLocationCoordinate2D]
    var level: String
    var label: String
}

// ---- wire shapes --------------------------------------------------------------------------------------------------
struct GpsJam: Decodable, Sendable {
    var date: String?
    var hexes: [Hex]
    struct Hex: Decodable, Sendable { var h3: String; var lat: Double; var lon: Double; var level: String; var pct: Double?; var aircraft: Int?; var region: String?; var boundary: [[Double]]? }
}
struct Aircraft: Decodable, Sendable {
    var aircraft: [A]
    struct A: Decodable, Sendable { var hex: String; var flight: String?; var reg: String?; var type: String?; var desc: String?; var role: String?; var lat: Double?; var lon: Double?; var alt: Int?; var gs: Double?; var track: Double? }
}
struct Ships: Decodable, Sendable {
    var vessels: [V]
    struct V: Decodable, Sendable { var mmsi: Int; var lat: Double?; var lon: Double?; var sog: Double?; var cog: Double?; var name: String?; var cat: String? }
}
struct Sats: Decodable, Sendable {
    var sats: [S]
    struct S: Decodable, Sendable { var name: String; var norad: Int; var group: String?; var lat: Double; var lon: Double; var alt_km: Int?; var period_min: Int? }
}
struct Radars: Decodable, Sendable {
    var sites: [R]
    struct R: Decodable, Sendable { var id: String; var lat: Double; var lon: Double; var cls: String?; var name: String?; var operator_: String?; var kind: String?
        enum CodingKeys: String, CodingKey { case id, lat, lon, cls, name, kind; case operator_ = "operator" } }
}
struct HFMap: Decodable, Sendable {
    var contours: [C]
    var stations: [St]?
    struct C: Decodable, Sendable { var mhz: Double; var colour: String?; var coords: [[[Double]]]?
        enum CodingKeys: String, CodingKey { case mhz, colour, coords }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            mhz = try c.decode(Double.self, forKey: .mhz); colour = try? c.decodeIfPresent(String.self, forKey: .colour)
            // one line ([[lat,lon]]) or several ([[[lat,lon]]])
            if let many = try? c.decodeIfPresent([[[Double]]].self, forKey: .coords) { coords = many }
            else if let one = try? c.decodeIfPresent([[Double]].self, forKey: .coords) { coords = [one] }
        }
    }
    struct St: Decodable, Sendable { var code: String; var name: String?; var lat: Double; var lon: Double; var mufd: Double?; var fof2: Double?; var time: String? }
}
struct C2: Decodable, Sendable {
    var countries: [Ct]
    struct Ct: Decodable, Sendable { var country: String; var name: String?; var lat: Double; var lon: Double; var count: Int; var online: Int?; var malware: [String]? }
}
struct Cables: Decodable, Sendable {
    var features: [F]
    struct F: Decodable, Sendable { var geometry: G?; var properties: P? }
    struct G: Decodable, Sendable {
        var type: String; var lines: [[[Double]]] = []
        enum CodingKeys: String, CodingKey { case type, coordinates }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            type = try c.decode(String.self, forKey: .type)
            if type == "MultiLineString" { lines = (try? c.decode([[[Double]]].self, forKey: .coordinates)) ?? [] }
            else if type == "LineString" { lines = [(try? c.decode([[Double]].self, forKey: .coordinates)) ?? []] }
        }
    }
    struct P: Decodable, Sendable { var name: String?; var color: String? }
}

/// Builds map content from the enabled layers.
@MainActor @Observable
final class LayerStore {
    var enabled: Set<MapLayer> { didSet { save() } }
    var points: [MapLayer: [MapPoint]] = [:]
    var lines: [MapLayer: [MapLine]] = [:]
    var polygons: [JamPolygon] = []
    var updated: [MapLayer: String] = [:]
    var errors: [MapLayer: String] = [:]
    private var cablesLoaded = false

    init() {
        let saved = UserDefaults.standard.stringArray(forKey: "layers") ?? ["items", "gpsjam", "milair"]
        enabled = Set(saved.compactMap(MapLayer.init(rawValue:)))
    }
    private func save() { UserDefaults.standard.set(enabled.map(\.rawValue), forKey: "layers") }

    func refresh(api: APIClient, items: [Item]) async {
        points[.items] = items.compactMap { i in
            guard let la = i.lat, let lo = i.lon else { return nil }
            return MapPoint(id: "i:\(i.id)", layer: .items, lat: la, lon: lo, title: i.title,
                            detail: "\(i.source) · \(i.domain.uppercased()) · severity \(i.severity)\(i.country_name.map { " · \($0) (placement, not attribution)" } ?? "")",
                            tint: i.domain)
        }
        for layer in enabled where layer.api != nil {
            if layer == .cables && cablesLoaded { continue }
            do { try await load(layer, api: api); errors[layer] = nil }
            catch is CancellationError { return }
            catch { errors[layer] = error.localizedDescription }
        }
    }

    private func load(_ layer: MapLayer, api: APIClient) async throws {
        let path = "api/layers/\(layer.rawValue)"
        switch layer {
        case .gpsjam:
            let e: LayerEnvelope<GpsJam> = try await api.get(path)
            updated[layer] = e.updated
            polygons = (e.data?.hexes ?? []).filter { $0.level != "low" }.compactMap { h in
                guard let b = h.boundary, b.count >= 3 else { return nil }
                return JamPolygon(id: h.h3, coords: b.map { .init(latitude: $0[0], longitude: $0[1]) }, level: h.level,
                                  label: "\(h.region ?? "") \(h.level): \(Int(h.pct ?? 0))% of \(h.aircraft ?? 0) aircraft degraded")
            }
        case .air, .milair:
            let e: LayerEnvelope<Aircraft> = try await api.get(path)
            updated[layer] = e.updated
            points[layer] = (e.data?.aircraft ?? []).compactMap { a in
                guard let la = a.lat, let lo = a.lon else { return nil }
                let call = (a.flight ?? "").trimmingCharacters(in: .whitespaces)
                return MapPoint(id: "\(layer.rawValue):\(a.hex)", layer: layer, lat: la, lon: lo,
                                title: call.isEmpty ? (a.reg ?? a.hex) : call,
                                detail: [a.desc ?? a.type, a.role.map { "role \($0)" }, a.alt.map { "\($0) ft" }, a.gs.map { "\(Int($0)) kt" }, a.reg].compactMap { $0 }.joined(separator: " · "),
                                heading: a.track, tint: a.role)
            }
        case .ais:
            let e: LayerEnvelope<Ships> = try await api.get(path)
            updated[layer] = e.updated
            points[layer] = (e.data?.vessels ?? []).compactMap { v in
                guard let la = v.lat, let lo = v.lon else { return nil }
                return MapPoint(id: "ais:\(v.mmsi)", layer: .ais, lat: la, lon: lo, title: v.name?.trimmingCharacters(in: .whitespaces).nilIfEmpty ?? "MMSI \(v.mmsi)",
                                detail: [v.cat, v.sog.map { String(format: "%.1f kn", $0) }, "MMSI \(v.mmsi)"].compactMap { $0 }.joined(separator: " · "),
                                heading: v.cog, tint: v.cat)
            }
        case .sats:
            let e: LayerEnvelope<Sats> = try await api.get(path)
            updated[layer] = e.updated
            points[layer] = (e.data?.sats ?? []).map { s in
                MapPoint(id: "sat:\(s.norad)", layer: .sats, lat: s.lat, lon: s.lon, title: s.name,
                         detail: [s.group, s.alt_km.map { "\($0) km" }, s.period_min.map { "\($0) min period" }, "NORAD \(s.norad)"].compactMap { $0 }.joined(separator: " · "),
                         tint: s.group)
            }
        case .radars:
            let e: LayerEnvelope<Radars> = try await api.get(path)
            updated[layer] = e.updated
            points[layer] = (e.data?.sites ?? []).map { r in
                MapPoint(id: "rdr:\(r.id)", layer: .radars, lat: r.lat, lon: r.lon, title: r.name?.nilIfEmpty ?? (r.kind ?? "radar"),
                         detail: [r.cls, r.kind, r.operator_].compactMap { $0?.nilIfEmpty }.joined(separator: " · "), tint: r.cls)
            }
        case .hfmap:
            let e: LayerEnvelope<HFMap> = try await api.get(path)
            updated[layer] = e.updated
            var out: [MapLine] = []
            for (i, c) in (e.data?.contours ?? []).enumerated() {
                for (j, line) in (c.coords ?? []).enumerated() where line.count > 1 {
                    out.append(MapLine(id: "muf:\(i):\(j)", layer: .hfmap, coords: line.map { .init(latitude: $0[1], longitude: $0[0]) },   // [lon, lat]
                                       label: "MUF \(Int(c.mhz)) MHz", colour: c.colour))
                }
            }
            lines[layer] = out
            points[layer] = (e.data?.stations ?? []).compactMap { s in
                guard let m = s.mufd else { return nil }
                return MapPoint(id: "iono:\(s.code)", layer: .hfmap, lat: s.lat, lon: s.lon, title: "\(s.name ?? s.code) ionosonde",
                                detail: "MUF(3000) \(String(format: "%.1f", m)) MHz · foF2 \(s.fof2.map { String(format: "%.1f", $0) } ?? "–") MHz · \(s.time ?? "")")
            }
        case .cables:
            let e: LayerEnvelope<Cables> = try await api.get(path)
            updated[layer] = e.updated
            var out: [MapLine] = []
            for (i, f) in (e.data?.features ?? []).enumerated() {
                for (j, l) in (f.geometry?.lines ?? []).enumerated() where l.count > 1 {
                    out.append(MapLine(id: "cab:\(i):\(j)", layer: .cables, coords: l.map { .init(latitude: $0[1], longitude: $0[0]) },
                                       label: f.properties?.name ?? "cable", colour: f.properties?.color))
                }
            }
            lines[layer] = out; cablesLoaded = true
        case .c2:
            let e: LayerEnvelope<C2> = try await api.get(path)
            updated[layer] = e.updated
            points[layer] = (e.data?.countries ?? []).map { c in
                MapPoint(id: "c2:\(c.country)", layer: .c2, lat: c.lat, lon: c.lon, title: "\(c.count) C2 servers: \(c.name ?? c.country)",
                         detail: "\(c.online ?? 0) online · \((c.malware ?? []).prefix(5).joined(separator: ", ")) · by hosting country, not attribution")
            }
        case .items: break
        }
    }

    /// Points of the enabled layers inside the visible region, at most `cap` per layer (the map stays responsive).
    func visiblePoints(in region: MKCoordinateRegion?, cap: Int = 400) -> [MapPoint] {
        var out: [MapPoint] = []
        for layer in MapLayer.allCases where enabled.contains(layer) {
            var pts = points[layer] ?? []
            if let r = region {
                let la0 = r.center.latitude - r.span.latitudeDelta / 2, la1 = r.center.latitude + r.span.latitudeDelta / 2
                let lo0 = r.center.longitude - r.span.longitudeDelta / 2, lo1 = r.center.longitude + r.span.longitudeDelta / 2
                pts = pts.filter { $0.lat >= la0 && $0.lat <= la1 && ($0.lon >= lo0 && $0.lon <= lo1 || lo1 > 180 && $0.lon + 360 <= lo1 || lo0 < -180 && $0.lon - 360 >= lo0) }
            }
            if pts.count > cap { pts = Array(pts.prefix(cap)) }
            out += pts
        }
        return out
    }

    func count(_ layer: MapLayer) -> Int {
        layer == .gpsjam ? polygons.count : (points[layer]?.count ?? 0) + (layer == .cables ? lines[layer]?.count ?? 0 : 0)
    }
}

extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}

extension Color {
    /// "#rrggbb" or "rgb(r,g,b)" from the server; nil if unreadable.
    init?(css: String?) {
        guard var s = css?.trimmingCharacters(in: .whitespaces), !s.isEmpty else { return nil }
        if s.hasPrefix("#") {
            s.removeFirst()
            if s.count == 3 { s = s.map { "\($0)\($0)" }.joined() }
            guard s.count == 6, let v = UInt32(s, radix: 16) else { return nil }
            self.init(red: Double((v >> 16) & 255) / 255, green: Double((v >> 8) & 255) / 255, blue: Double(v & 255) / 255)
            return
        }
        let nums = s.split(whereSeparator: { !"0123456789.".contains($0) }).compactMap { Double($0) }
        guard nums.count >= 3 else { return nil }
        self.init(red: nums[0] / 255, green: nums[1] / 255, blue: nums[2] / 255)
    }
}
