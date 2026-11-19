import MapKit
import SwiftUI

// EMO planning tools as in the web dock: corridor, courses of action, adversary COA, timeline, undo.

struct CorridorLeg: Decodable, Sendable, Identifiable {
    var from: [Double]; var to: [Double]; var km: Double; var minutes: Double; var emcon: String
    var p_detect: Int; var p_fix: Int; var p_radar: Int; var p_c2: Int
    var heard_by: [String]?; var path: [[Double]]?
    var verified: Verified?
    struct Verified: Decodable, Sendable { var p_detect: Int?; var p_c2: Int? }
    var id: String { "\(from)\(to)" }
}
struct CorridorResult: Decodable, Sendable {
    var unit: String; var side: String; var domain: String
    var bounds: [[Double]]?; var path: [[Double]]?; var band: String?
    var legs: [CorridorLeg]
    var summary: Summary
    var notes: String?
    struct Summary: Decodable, Sendable {
        var km: Double; var direct_km: Double; var minutes: Double; var speed_kmh: Double; var transmit_pct: Int
        var max_p_detect: Int; var max_p_fix: Int; var max_p_radar: Int; var min_p_c2: Int
        var cost: Double?; var direct_cost: Double?; var band_km2: Double?; var cell_m: Double?; var c2: String?; var sensors: [String]?
    }
}
struct CorridorIn: Encodable, Sendable {
    var mover: String; var to_lat: Double; var to_lon: Double; var domain: String; var emcon: String; var silent_cost: Double
    var alt_m: Double?; var speed_kmh: Double?
}
struct COAMove: Decodable, Sendable, Identifiable {
    var entity: String; var `where`: String?; var detail: String?; var from: [Double]?; var to: [Double]?
    var id: String { entity + (`where` ?? "") }
}
struct COAResult: Decodable, Sendable { var coa: String?; var target: String?; var moves: [COAMove]?; var reverted: Int? }
struct COAItem: Decodable, Sendable, Identifiable { var id: String; var name: String; var score: EMOScore? }
struct COAList: Decodable, Sendable { var coas: [COAItem]; var current: EMOScore? }
struct TimelineRow: Decodable, Sendable { var side: String; var heard: [Bool]; var denied: [Bool]; var targetable: [Bool]; var tracked: Bool?; var heard_by: [[String]]? }
struct TimelineResult: Decodable, Sendable {
    var steps: [Double]; var rows: [String: TimelineRow]; var horizon_min: Double?; var notes: String?
    var windows: Windows?
    struct Windows: Decodable, Sendable { var net: String; var summary: String?; var advantage: [Span] }
    struct Span: Decodable, Sendable { var from_min: Double; var to_min: Double }
}
struct Undone: Decodable, Sendable { var undone: String?; var depth: Int? }

enum EMOTool: String, Identifiable, CaseIterable {
    case corridor, coas, adversary, timeline
    var id: String { rawValue }
    var label: String { switch self { case .corridor: "Corridor"; case .coas: "COAs"; case .adversary: "Adversary COA"; case .timeline: "Timeline" } }
    var symbol: String { switch self { case .corridor: "point.topleft.down.to.point.bottomright.curvepath"; case .coas: "square.stack.3d.up"; case .adversary: "shield.lefthalf.filled"; case .timeline: "chart.bar.xaxis" } }
}

@MainActor @Observable
final class CorridorState {
    var mover = ""
    var domain = "ground"
    var emcon = "auto"
    var silent = 0.6
    var alt = 150.0
    var speed = ""
    var to: CLLocationCoordinate2D?
    var picking = false
    var result: CorridorResult?
    var busy = false
    var error: String?
}

struct CorridorPanel: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        let E = model.emo, c = model.corridor
        @Bindable var cb = c
        let units = E.entities.filter { $0.side == "blue" || $0.side == "red" }
        Form {
            Picker("Unit", selection: $cb.mover) { ForEach(units) { Text($0.name).foregroundStyle(Side.colour($0.side)).tag($0.name) } }
            Picker("Domain", selection: $cb.domain) { Text("Ground").tag("ground"); Text("Sea").tag("sea"); Text("Air (low level)").tag("air") }
            if c.domain == "air" { LabeledContent("Height m AGL") { TextField("150", value: $cb.alt, format: .number).frame(width: 80) } }
            LabeledContent("Speed km/h") { TextField("auto", text: $cb.speed).frame(width: 80) }
            Picker("EMCON", selection: $cb.emcon) { Text("Auto").tag("auto"); Text("Transmit").tag("emit"); Text("Silent").tag("silent") }
            LabeledContent("Silent price") { TextField("0.6", value: $cb.silent, format: .number).frame(width: 80) }
            HStack {
                Button(c.picking ? "Tap the map…" : "Pick destination") { c.picking = true }
                if let t = c.to { Text(String(format: "%.4f, %.4f", t.latitude, t.longitude)).font(.caption.monospaced()) }
            }
            HStack {
                Button { Task { await plan() } } label: { c.busy ? AnyView(ProgressView().controlSize(.small)) : AnyView(Text("Plan").bold()) }
                    .disabled(c.to == nil || c.mover.isEmpty || c.busy)
                Button("Clear") { c.result = nil; c.to = nil; c.error = nil }
            }
            if let e = c.error { Text(e).foregroundStyle(.orange).font(.caption) }
            if let r = c.result { CorridorTable(r: r) }
            Text("At T+\(Int(E.t)) with the last run's atmosphere. Notional data; screening grade.").font(.caption2).foregroundStyle(.secondary)
        }
        .formStyle(.grouped)
        .onAppear { if c.mover.isEmpty || !units.contains(where: { $0.name == c.mover }) { c.mover = units.first { $0.side == "blue" }?.name ?? units.first?.name ?? "" } }
    }

    private func plan() async {
        let c = model.corridor
        guard let to = c.to else { return }
        c.busy = true; c.error = nil; defer { c.busy = false }
        let body = CorridorIn(mover: c.mover, to_lat: to.latitude, to_lon: to.longitude, domain: c.domain, emcon: c.emcon, silent_cost: c.silent,
                              alt_m: c.domain == "air" ? c.alt : nil, speed_kmh: Double(c.speed).flatMap { $0 > 0 ? $0 : nil })
        do { c.result = try await model.api.send("POST", "api/emo/plan/corridor", query: ["t_min": String(Int(model.emo.t))], body: body, timeout: 600) }
        catch { c.error = error.localizedDescription }
    }
}

struct CorridorTable: View {
    let r: CorridorResult
    var body: some View {
        let s = r.summary
        VStack(alignment: .leading, spacing: 6) {
            Text("\(r.unit) (\(r.domain)) \(fmt(s.km)) km in about \(Int(s.minutes)) min at \(Int(s.speed_kmh)) km/h (direct \(fmt(s.direct_km)) km); transmitting on \(s.transmit_pct)% of the route.")
                .font(.callout)
            Text("Worst: detect \(s.max_p_detect)%, fix \(s.max_p_fix)%, radar \(s.max_p_radar)%, C2 at least \(s.min_p_c2)%\(s.c2.map { " (\($0))" } ?? "").")
                .font(.caption).foregroundStyle(.secondary)
            Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 3) {
                GridRow { ForEach(["Leg", "km", "min", "EMCON", "Det", "Fix", "Rdr", "C2", "Verified", "Heard by"], id: \.self) { Text($0).font(.caption2.bold()).foregroundStyle(.secondary) } }
                ForEach(Array(r.legs.enumerated()), id: \.offset) { i, lg in
                    GridRow {
                        Text("\(i + 1)"); Text(fmt(lg.km)); Text(fmt(lg.minutes))
                        Text(lg.emcon).foregroundStyle(lg.emcon == "transmit" ? Color.orange : Color.green)
                        Text("\(lg.p_detect)%"); Text("\(lg.p_fix)%"); Text("\(lg.p_radar)%"); Text("\(lg.p_c2)%")
                        Text("\(lg.verified?.p_detect ?? 0)%\(lg.verified?.p_c2.map { " / \($0)%" } ?? "")")
                        Text((lg.heard_by ?? []).joined(separator: ", ")).lineLimit(1)
                    }
                    .font(.caption.monospacedDigit())
                }
            }
            if let n = r.notes { Text(n).font(.caption2).foregroundStyle(.secondary) }
        }
    }
}

struct COAPanel: View {
    @Environment(AppModel.self) private var model
    @State private var list: COAList?
    @State private var name = ""
    @State private var error: String?
    var body: some View {
        Form {
            HStack {
                TextField("COA name", text: $name)
                Button("Save current") { Task { await save() } }
            }
            if let l = list {
                if l.coas.isEmpty { Text("No COAs saved.").foregroundStyle(.secondary) }
                ForEach(l.coas) { c in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(c.name)
                            Text("Blue avail \(c.score?.blue?.net_availability_pct.map { fmt($0) } ?? "–")% · TQF \(c.score?.blue?.targetable ?? 0) | Red avail \(c.score?.red?.net_availability_pct.map { fmt($0) } ?? "–")% · TQF \(c.score?.red?.targetable ?? 0)")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("Load") { Task { await load(c) } }
                        Button(role: .destructive) { Task { await del(c) } } label: { Image(systemName: "trash") }
                    }
                }
            }
            if let error { Text(error).foregroundStyle(.orange).font(.caption) }
            if let u = URL(string: "api/emo/coas/export.docx", relativeTo: model.api.base) { Link("Word annex of all COAs", destination: u) }
        }
        .formStyle(.grouped)
        .task { await refresh() }
    }
    private func refresh() async { do { list = try await model.api.get("api/emo/coas") } catch { self.error = error.localizedDescription } }
    private func save() async {
        struct B: Encodable, Sendable { var name: String }
        struct R: Decodable, Sendable { var id: String? }
        let n = name.trimmingCharacters(in: .whitespaces).isEmpty ? "COA \(Date.now.formatted(date: .omitted, time: .shortened))" : name
        do { let _: R = try await model.api.send("POST", "api/emo/coas", body: B(name: n)); name = ""; await refresh() } catch { self.error = error.localizedDescription }
    }
    private func load(_ c: COAItem) async {
        struct R: Decodable, Sendable { var t_min: Double? }
        do {
            let r: R = try await model.api.send("POST", "api/emo/coas/\(c.id)/load")
            if let t = r.t_min { model.emo.t = t }
            await model.emo.load(model.api); await model.emo.runNow(model.api)
        } catch { self.error = error.localizedDescription }
    }
    private func del(_ c: COAItem) async {
        struct R: Decodable, Sendable {}
        do { let _: R = try await model.api.send("DELETE", "api/emo/coas/\(c.id)"); await refresh() } catch { self.error = error.localizedDescription }
    }
}

struct AdversaryPanel: View {
    @Environment(AppModel.self) private var model
    @State private var side = "red"
    @State private var busy = false
    @State private var result: COAResult?
    @State private var error: String?
    var body: some View {
        Form {
            Picker("Side that moves", selection: $side) { Text("Red").tag("red"); Text("Blue").tag("blue") }.pickerStyle(.segmented)
            HStack {
                Button("MLCOA") { Task { await go("mlcoa") } }.help("Most likely: at most two modest moves")
                Button("MDCOA") { Task { await go("mdcoa") } }.help("Most dangerous: every jammer and DF site re-sited for effect")
                Button("Revert") { Task { await go("revert") } }
                if busy { ProgressView().controlSize(.small) }
            }
            if let r = result {
                if let n = r.reverted { Text("Reverted \(n) positions.") }
                else if let moves = r.moves, !moves.isEmpty {
                    Text("\(r.coa?.uppercased() ?? "") against \(r.target ?? "")").bold()
                    ForEach(moves) { m in VStack(alignment: .leading) { Text("\(m.entity) \(m.where ?? "")"); if let d = m.detail { Text(d).font(.caption).foregroundStyle(.secondary) } } }
                } else { Text("No move clearly improves \(side)'s laydown.").foregroundStyle(.secondary) }
            }
            if let error { Text(error).foregroundStyle(.orange).font(.caption) }
            Text("Applies the moves to the current workspace; Revert puts them back.").font(.caption2).foregroundStyle(.secondary)
        }
        .formStyle(.grouped)
    }
    private func go(_ kind: String) async {
        struct B: Encodable, Sendable { var side: String; var coa: String }
        busy = true; error = nil; defer { busy = false }
        let t = String(Int(model.emo.t))
        do {
            result = kind == "revert"
                ? try await model.api.send("POST", "api/emo/plan/coa/revert", query: ["side": side, "t_min": t], timeout: 600)
                : try await model.api.send("POST", "api/emo/plan/coa", query: ["t_min": t], body: B(side: side, coa: kind), timeout: 600)
            await model.emo.load(model.api); await model.emo.runNow(model.api)
        } catch { self.error = error.localizedDescription }
    }
}

struct TimelinePanel: View {
    @Environment(AppModel.self) private var model
    @State private var step = 10.0
    @State private var net = ""
    @State private var busy = false
    @State private var result: TimelineResult?
    @State private var error: String?
    var body: some View {
        let nets = model.emo.entities.filter { e in e.kind == "emitter" && model.emo.entities.contains { $0.net == e.id } }
        Form {
            LabeledContent("Step (min)") { TextField("10", value: $step, format: .number).frame(width: 60) }
            Picker("Windows for net", selection: $net) { Text("(none)").tag(""); ForEach(nets) { Text($0.name).tag($0.name) } }
            HStack { Button("Run timeline") { Task { await go() } }.disabled(busy); if busy { ProgressView().controlSize(.small) } }
            if let r = result { TimelineChart(r: r) }
            if let error { Text(error).foregroundStyle(.orange).font(.caption) }
        }
        .formStyle(.grouped)
    }
    private func go() async {
        struct B: Encodable, Sendable { var step_min: Double; var net: String? }
        busy = true; error = nil; defer { busy = false }
        do { result = try await model.api.send("POST", "api/emo/plan/timeline", body: B(step_min: max(1, step), net: net.isEmpty ? nil : net), timeout: 900) }
        catch { self.error = error.localizedDescription }
    }
}

struct TimelineChart: View {
    let r: TimelineResult
    var body: some View {
        let names = r.rows.keys.filter { n in let x = r.rows[n]!; return x.tracked == true || x.heard.contains(true) || x.denied.contains(true) }
            .sorted { (r.rows[$0]!.side + $0) < (r.rows[$1]!.side + $1) }
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 10) {
                legend(.green, "undetected"); legend(.orange, "detected"); legend(.red, "target-quality fix"); legend(Color(red: 0.86, green: 0.24, blue: 0.86), "denied")
            }.font(.caption2)
            ForEach(names, id: \.self) { n in
                let row = r.rows[n]!
                HStack(spacing: 1) {
                    Text(n).font(.caption2).foregroundStyle(Side.colour(row.side)).frame(width: 130, alignment: .leading).lineLimit(1)
                    ForEach(r.steps.indices, id: \.self) { i in
                        Rectangle().fill(row.denied[i] ? Color(red: 0.86, green: 0.24, blue: 0.86) : row.targetable[i] ? .red : row.heard[i] ? .orange : .green)
                            .frame(height: 11)
                    }
                }
            }
            HStack { Text("T+\(Int(r.steps.first ?? 0))"); Spacer(); Text("T+\(Int(r.steps.last ?? 0)) min") }.font(.caption2).foregroundStyle(.secondary).padding(.leading, 131)
            if let w = r.windows {
                Text("\(w.net): \(w.summary ?? "")").font(.caption)
                Text(w.advantage.isEmpty ? "No window: siting alone gives none; use EMCON or another bearer." : "Undetected and not denied: " + w.advantage.map { "T+\(Int($0.from_min))–\(Int($0.to_min))" }.joined(separator: ", "))
                    .font(.caption).foregroundStyle(w.advantage.isEmpty ? .red : .green)
            }
        }
    }
    private func legend(_ c: Color, _ t: String) -> some View { HStack(spacing: 3) { Rectangle().fill(c).frame(width: 9, height: 9); Text(t) } }
}
