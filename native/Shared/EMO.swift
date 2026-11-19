import Foundation
import MapKit
import SwiftUI

// EMO (red / blue in the spectrum) over /api/emo. Notional scenarios only. The server keeps the scenario per workspace
// (X-CyEM-WS): "default" is shared by every device; a private id keeps experiments off it.

struct EMOEntity: Decodable, Sendable, Identifiable, Hashable {
    var id: String
    var name: String
    var side: String
    var kind: String
    var category: String?
    var lat: Double
    var lon: Double
    var h_agl: Double?
    var freq_mhz: Double?
    var f_hi_mhz: Double?
    var bw_khz: Double?
    var eirp_dbm: Double?
    var sens_dbm: Double?
    var net: String?
    var active: Bool?
    var sidc: String?
    var track: [[Double]]?
    var notes: String?
    static func == (a: EMOEntity, b: EMOEntity) -> Bool { a.id == b.id }
    func hash(into h: inout Hasher) { h.combine(id) }
}

struct EMOEntities: Decodable, Sendable { var entities: [EMOEntity] }
struct EMOExample: Decodable, Sendable, Identifiable { var id: String; var title: String; var about: String?; var centre: [Double]?; var zoom: Double?; var entities: Int? }
struct EMOExamples: Decodable, Sendable { var examples: [EMOExample] }
struct EMOLoaded: Decodable, Sendable { var entities: [EMOEntity]?; var about: String?; var centre: [Double]?; var zoom: Double? }

struct EMODetection: Decodable, Sendable, Identifiable {
    var sensor: String; var sensor_id: String?; var sensor_side: String?
    var target: String; var target_id: String?
    var level_dbm: Double?; var margin_db: Double?; var detected: Bool?; var df: Bool?; var p: Int?
    var id: String { "\(sensor_id ?? sensor)>\(target_id ?? target)" }
}
struct EMOFix: Decodable, Sendable, Identifiable {
    var target: String; var target_side: String?; var by_side: String?
    var lobs: Int?; var sensors: [String]?
    var bearings: [Bearing]?
    var fix: FixPoint?
    var targetable: Bool?; var located: Bool?; var pos: [Double]?; var p: Int?
    var id: String { "\(by_side ?? "")>\(target)" }
    struct Bearing: Decodable, Sendable { var site: [Double]; var bearing: Double }
    struct FixPoint: Decodable, Sendable { var cut_deg: Double?; var error_m: Int?; var fix: [Double]?; var method: String? }
}
struct EMOJam: Decodable, Sendable, Identifiable {
    var effector: String; var effector_id: String?; var victim: String; var victim_id: String?; var net: String?
    var effector_side: String?; var collateral: Bool?; var js_db: Double?; var js_req_db: Double?; var status: String
    var a: [Double]?; var b: [Double]?; var p: Int?
    var id: String { "\(effector_id ?? effector)>\(victim_id ?? victim)" }
}
struct EMONet: Decodable, Sendable, Identifiable {
    var net: String; var side: String; var space: Bool?; var coverage_km2: Double?; var denied_km2: Double?; var denied_pct: Double?; var js_req_db: Double?
    var id: String { net }
}
struct EMORadar: Decodable, Sendable, Identifiable {
    var radar: String; var radar_side: String?; var target: String; var target_side: String?
    var range_km: Double?; var margin_db: Double?; var detected: Bool?; var p: Int?; var screened: Bool?; var tracked: Bool?
    var id: String { "\(radar)>\(target)" }
}
struct EMOScoreSide: Decodable, Sendable {
    var net_availability_pct: Double?; var emitters_exposed: String?; var mean_exposure_db: Double?
    var fixed: Int?; var targetable: Int?; var denial_achieved: Int?; var deceived: Int?; var collateral: Int?
    var net_area_denied_pct: Double?; var radar_tracks: Int?; var radar_screened: Int?
}
struct EMOScore: Decodable, Sendable { var blue: EMOScoreSide?; var red: EMOScoreSide? }
struct EMORun: Decodable, Sendable {
    var t_min: Double
    var horizon_min: Double?
    var bounds: [[Double]]?
    var layers: [String: String]?
    var positions: [String: [Double]]?
    var on_air: [String: Bool]?
    var detections: [EMODetection]?
    var fixes: [EMOFix]?
    var jamming: [EMOJam]?
    var nets: [EMONet]?
    var radar: [EMORadar]?
    var score: EMOScore?
    var compute_s: Double?
    var notes: String?
}
struct EMOFocus: Decodable, Sendable {
    var id: String; var name: String; var side: String; var kind: String; var category: String?; var active: Bool?
    var overlay: Overlay?
    var heard_by: [EMODetection]?; var hears: [EMODetection]?
    var jams: [EMOJam]?; var jammed: [EMOJam]?
    var fix: EMOFix?
    struct Overlay: Decodable, Sendable { var png: String; var bounds: [[Double]] }
}

enum Side {
    static func colour(_ s: String) -> Color {
        switch s {
        case "blue": Color(red: 0.24, green: 0.55, blue: 1.0)
        case "red": Color(red: 1.0, green: 0.27, blue: 0.27)
        default: Color(white: 0.7)
        }
    }
    static func symbol(_ kind: String) -> String {
        switch kind {
        case "emitter": "antenna.radiowaves.left.and.right"
        case "receiver": "radio"
        case "sensor": "ear"
        case "effector": "bolt.fill"
        default: "circle"
        }
    }
    static let kindText = ["emitter": "Emitter / net control", "receiver": "Net user", "sensor": "ES / DF sensor", "effector": "EA effector"]
}

/// EMO overlays from a run: the same PNG washes as the web map.
enum EMOLayer: String, CaseIterable, Identifiable {
    case blue_cov, red_cov, blue_seen, red_seen, blue_denied, red_denied
    var id: String { rawValue }
    var label: String {
        switch self {
        case .blue_cov: "Blue net coverage"
        case .red_cov: "Red net coverage"
        case .blue_seen: "Where red hears blue"
        case .red_seen: "Where blue hears red"
        case .blue_denied: "Blue nets denied"
        case .red_denied: "Red nets denied"
        }
    }
}

@MainActor @Observable
final class EMOModel {
    var entities: [EMOEntity] = []
    var run: EMORun?
    var t: Double = 0
    var running = false
    var started: Date?
    var error: String?
    var examples: [EMOExample] = []
    var about: String?
    var on: Set<EMOLayer> = [.blue_denied, .red_denied]
    var focus: EMOFocus?
    var stale = false
    private var images: [String: PlatformImage] = [:]

    func load(_ api: APIClient) async {
        do { entities = try await api.get("api/emo", as: EMOEntities.self).entities; error = nil }
        catch { self.error = error.localizedDescription }
        if examples.isEmpty, let ex = try? await api.get("api/emo/examples", as: EMOExamples.self) { examples = ex.examples }
    }

    func runNow(_ api: APIClient) async {
        guard !running, !entities.isEmpty else { return }
        running = true; started = .now; defer { running = false }
        do {
            let r: EMORun = try await api.send("POST", "api/emo/run", query: ["t_min": String(Int(t))], timeout: 600)
            run = r; images = [:]; stale = false; error = nil
            if let f = focus { await openFocus(api, id: f.id) }
        } catch { self.error = error.localizedDescription }
    }

    func loadExample(_ api: APIClient, _ ex: EMOExample) async -> CLLocationCoordinate2D? {
        do {
            let r: EMOLoaded = try await api.send("POST", "api/emo/examples/\(ex.id)")
            about = r.about ?? ex.about; t = 0; run = nil; focus = nil
            await load(api)
            await runNow(api)
            if let c = r.centre ?? ex.centre, c.count == 2 { return .init(latitude: c[0], longitude: c[1]) }
        } catch { self.error = error.localizedDescription }
        return nil
    }

    func openFocus(_ api: APIClient, id: String) async {
        do { focus = try await api.get("api/emo/focus/\(id)", query: ["t_min": String(Int(t))], as: EMOFocus.self) }
        catch APIClient.APIError.badStatus(409, _) { await runNow(api) }
        catch { self.error = error.localizedDescription }
    }

    func setActive(_ api: APIClient, _ e: EMOEntity, _ on: Bool) async {
        struct R: Decodable, Sendable { var id: String? }
        do {
            let _: R = try await api.send("POST", "api/emo/\(e.id)/active", query: ["on": on ? "true" : "false"])
            await load(api); await runNow(api)
        } catch { self.error = error.localizedDescription }
    }

    func position(_ e: EMOEntity) -> CLLocationCoordinate2D {
        if let p = run?.positions?[e.id], p.count == 2 { return .init(latitude: p[0], longitude: p[1]) }
        return .init(latitude: e.lat, longitude: e.lon)
    }
    func onAir(_ e: EMOEntity) -> Bool { run?.on_air?[e.id] ?? e.active ?? true }

    func image(_ key: String, _ dataURL: String) -> PlatformImage? {
        if let i = images[key] { return i }
        guard let comma = dataURL.firstIndex(of: ","), let d = Data(base64Encoded: String(dataURL[dataURL.index(after: comma)...])),
              let img = PlatformImage(data: d) else { return nil }
        images[key] = img
        return img
    }
}

#if os(macOS)
import AppKit
typealias PlatformImage = NSImage
extension Image { init(platform: PlatformImage) { self.init(nsImage: platform) } }
#else
import UIKit
typealias PlatformImage = UIImage
extension Image { init(platform: PlatformImage) { self.init(uiImage: platform) } }
#endif
