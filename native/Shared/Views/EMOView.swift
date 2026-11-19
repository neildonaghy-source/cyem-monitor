import MapKit
import SwiftUI

/// EMO on the map: units by side, the run's washes (coverage, where each side is heard, denial), DF fixes and jamming,
/// time, the scoreboard and a card per unit. Notional scenarios only.
struct EMOView: View {
    @Environment(AppModel.self) private var model
    @State private var position: MapCameraPosition = .automatic
    @State private var picked: EMOEntity?
    @State private var showScore = false
    @State private var showLayers = false
    @State private var confirmExample: EMOExample?
    @State private var cameraTick = 0
    @State private var showFixes = true
    @State private var showJamming = true
    @State private var tool: EMOTool?
    @State private var moving = false
    @State private var note: String?

    var body: some View {
        let E = model.emo
        MapReader { proxy in
            Map(position: $position, selection: $picked) {
                fixLines(E)
                jamLines(E)
                corridorLines(model.corridor)
                ForEach(E.entities) { e in
                    Annotation(e.name, coordinate: E.position(e), anchor: .center) { UnitGlyph(e: e, onAir: E.onAir(e)) }
                        .tag(e)
                }
            }
            .mapStyle(.standard(elevation: .flat, emphasis: .muted, pointsOfInterest: .excludingAll))
            .onMapCameraChange(frequency: .continuous) { _ in cameraTick &+= 1 }
            .overlay { washes(E, proxy).allowsHitTesting(false) }
            .onTapGesture { pt in
                guard let c = proxy.convert(pt, from: .local) else { return }
                if model.corridor.picking { model.corridor.to = c; model.corridor.picking = false; tool = .corridor }
                else if moving, let p = picked { moving = false; Task { await move(p, to: c) } }
            }
        }
        .safeAreaInset(edge: .top) { topBar(E) }
        .safeAreaInset(edge: .bottom) { if let f = E.focus { UnitCard(focus: f, entity: E.entities.first { $0.id == f.id }, move: { moving = true }) { picked = nil; E.focus = nil } } }
        .onChange(of: picked) { _, p in if let p { Task { await E.openFocus(model.api, id: p.id) } } else { E.focus = nil } }
        .task(id: model.wsKey) {
            await E.load(model.api)
            fit(E)
            if E.run == nil { await E.runNow(model.api) }
        }
        .toolbar {
            ToolbarItem {
                Menu {
                    ForEach(E.examples) { ex in Button(ex.title) { confirmExample = ex } }
                } label: { Label("Examples", systemImage: "tray.and.arrow.down") }
            }
            ToolbarItem {
                Menu {
                    ForEach(EMOTool.allCases) { t in Button { tool = t } label: { Label(t.label, systemImage: t.symbol) } }
                } label: { Label("Tools", systemImage: "wrench.and.screwdriver") }
            }
            ToolbarItem { Button { Task { await undo() } } label: { Label("Undo", systemImage: "arrow.uturn.backward") } }
            ToolbarItem { Button { showLayers.toggle() } label: { Label("Overlays", systemImage: "square.3.layers.3d") } }
            ToolbarItem { Button { showScore.toggle() } label: { Label("Score", systemImage: "list.number") }.disabled(E.run == nil) }
        }
        .confirmationDialog(confirmExample.map { "Load \u{201C}\($0.title)\u{201D}?" } ?? "", isPresented: Binding(get: { confirmExample != nil }, set: { if !$0 { confirmExample = nil } }), titleVisibility: .visible) {
            Button(model.wsMode == .shared ? "Replace the shared scenario" : "Replace this device's scenario", role: .destructive) {
                guard let ex = confirmExample else { return }
                Task {
                    if let c = await E.loadExample(model.api, ex) {
                        position = .region(MKCoordinateRegion(center: c, span: .init(latitudeDelta: 0.5, longitudeDelta: 0.8)))
                    }
                }
            }
        } message: { Text(model.wsMode == .shared ? "Every device sees the shared scenario. Switch to This device in Settings to experiment privately." : "Only this device's private workspace changes.") }
        .sheet(isPresented: $showScore) { ScoreSheet().environment(model).presentationDetents([.medium, .large]) }
        .sheet(isPresented: $showLayers) { EMOLayerSheet(showFixes: $showFixes, showJamming: $showJamming).environment(model).presentationDetents([.medium]) }
        .inspector(isPresented: Binding(get: { tool != nil && !model.corridor.picking }, set: { if !$0 { tool = nil } })) {
            NavigationStack {
                Group {
                    switch tool {
                    case .corridor: CorridorPanel()
                    case .coas: COAPanel()
                    case .adversary: AdversaryPanel()
                    case .timeline: TimelinePanel()
                    case nil: EmptyView()
                    }
                }
                .navigationTitle(tool?.label ?? "")
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Close") { tool = nil } } }
            }
            .inspectorColumnWidth(min: 340, ideal: 440, max: 640)
        }
        .navigationTitle("EMO")
    }

    private func move(_ e: EMOEntity, to c: CLLocationCoordinate2D) async {
        struct B: Encodable, Sendable { var lat: Double; var lon: Double }
        struct R: Decodable, Sendable { var moved: String? }
        do {
            let _: R = try await model.api.send("POST", "api/emo/\(e.id)/move", body: B(lat: (c.latitude * 1e5).rounded() / 1e5, lon: (c.longitude * 1e5).rounded() / 1e5))
            note = "Moved \(e.name)"
            await model.emo.load(model.api); await model.emo.runNow(model.api)
        } catch { model.emo.error = error.localizedDescription }
    }

    private func undo() async {
        do {
            let r: Undone = try await model.api.send("POST", "api/emo/undo")
            note = "Undid: \(r.undone ?? "last change")"
            model.emo.focus = nil; picked = nil
            await model.emo.load(model.api); await model.emo.runNow(model.api)
        } catch { note = "Nothing to undo" }
    }

    @MapContentBuilder private func corridorLines(_ c: CorridorState) -> some MapContent {
        let legs: [CorridorLeg] = c.result?.legs ?? []
        ForEach(legs) { lg in
            let col: Color = lg.emcon == "transmit" ? Color(red: 0.95, green: 0.70, blue: 0.24) : Color(red: 0.27, green: 0.83, blue: 0.54)
            MapPolyline(coordinates: (lg.path ?? [lg.from, lg.to]).map { .init(latitude: $0[0], longitude: $0[1]) }).stroke(col, lineWidth: 5)
        }
        if let t = c.to {
            Annotation("Destination", coordinate: t) { Image(systemName: "flag.checkered.circle.fill").font(.title3).foregroundStyle(.white, Palette.accent) }
        }
    }

    private func fit(_ E: EMOModel) {
        let core = E.entities.filter { $0.side != "grey" }
        let pts = (core.isEmpty ? E.entities : core).map { E.position($0) }
        guard let la0 = pts.map(\.latitude).min(), let la1 = pts.map(\.latitude).max(),
              let lo0 = pts.map(\.longitude).min(), let lo1 = pts.map(\.longitude).max() else { return }
        position = .region(MKCoordinateRegion(center: .init(latitude: (la0 + la1) / 2, longitude: (lo0 + lo1) / 2),
                                              span: .init(latitudeDelta: max(0.05, (la1 - la0) * 1.3), longitudeDelta: max(0.05, (lo1 - lo0) * 1.3))))
    }

    @ViewBuilder private func topBar(_ E: EMOModel) -> some View {
        VStack(spacing: 4) {
            HStack(spacing: 10) {
                Text(model.wsMode == .shared ? "Shared" : "This device").font(.caption.weight(.semibold))
                    .padding(.horizontal, 6).padding(.vertical, 2).background(.quaternary, in: Capsule())
                Text("T+\(Int(E.t)) min").font(.callout.monospacedDigit())
                Slider(value: Binding(get: { E.t }, set: { E.t = $0.rounded(); E.stale = true }),
                       in: 0...max(10, ((E.run?.horizon_min ?? 0) / 5).rounded(.up) * 5), step: 5)   // the range must hold at least one step { editing in
                    if !editing { Task { await E.runNow(model.api) } }
                }
                .frame(maxWidth: 360)
                Button { Task { await E.runNow(model.api) } } label: {
                    if E.running { ProgressView().controlSize(.small) } else { Label("Run", systemImage: "play.fill") }
                }
                .disabled(E.running || E.entities.isEmpty)
            }
            if moving { Text("Tap the map to move \(picked?.name ?? "the unit") there (T+0 position).").font(.caption).foregroundStyle(.yellow) }
            if model.corridor.picking { Text("Tap the map for the corridor destination.").font(.caption).foregroundStyle(.yellow) }
            if let n = note { Text(n).font(.caption).foregroundStyle(.secondary) }
            if E.running, let s = E.started {
                TimelineView(.periodic(from: .now, by: 1)) { _ in
                    Text("Computing… \(Int(Date.now.timeIntervalSince(s))) s (a new scenario takes about half a minute)").font(.caption).foregroundStyle(.secondary)
                }
            } else if let r = E.run {
                Text(summary(r)).font(.caption).foregroundStyle(.secondary).lineLimit(2)
            } else if E.entities.isEmpty {
                Text("No units in this workspace: load an example from the toolbar.").font(.caption).foregroundStyle(.secondary)
            }
            if let err = E.error { Text(err).font(.caption).foregroundStyle(.orange) }
        }
        .padding(8)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
        .padding(.horizontal)
    }

    private func summary(_ r: EMORun) -> String {
        let tq = (r.fixes ?? []).filter { $0.targetable == true }.count
        let worst = (r.nets ?? []).max { ($0.denied_pct ?? 0) < ($1.denied_pct ?? 0) }
        return "T+\(Int(r.t_min)) · \(tq) target-quality fix\(tq == 1 ? "" : "es")\(worst.map { " · \($0.net) \(String(format: "%.0f", $0.denied_pct ?? 0))% denied" } ?? "") · \(String(format: "%.1f", r.compute_s ?? 0)) s\(E_stale ? " · stale" : "")"
    }
    private var E_stale: Bool { model.emo.stale }

    @MapContentBuilder private func fixLines(_ E: EMOModel) -> some MapContent {
        let fixes: [EMOFix] = showFixes ? (E.run?.fixes ?? []).filter { $0.fix != nil && $0.target_side != "grey" } : []
        ForEach(fixes) { f in
            let to: [Double] = f.fix?.fix ?? f.pos ?? [0, 0]
            let c: Color = f.targetable == true ? .red : .yellow
            ForEach(Array((f.bearings ?? []).enumerated()), id: \.offset) { _, b in
                MapPolyline(coordinates: [.init(latitude: b.site[0], longitude: b.site[1]), .init(latitude: to[0], longitude: to[1])])
                    .stroke(c.opacity(0.6), style: StrokeStyle(lineWidth: 1, dash: [4, 4]))
            }
        }
    }

    @MapContentBuilder private func jamLines(_ E: EMOModel) -> some MapContent {
        let jams: [EMOJam] = showJamming ? (E.run?.jamming ?? []).filter { $0.status == "denied" && $0.a != nil && $0.b != nil } : []
        ForEach(jams) { j in
            MapPolyline(coordinates: [.init(latitude: j.a![0], longitude: j.a![1]), .init(latitude: j.b![0], longitude: j.b![1])])
                .stroke(Color(red: 0.86, green: 0.24, blue: 0.86), lineWidth: 2)
        }
    }

    /// The run's PNG washes and the focused unit's footprint, placed by projecting their bounds through the map.
    @ViewBuilder private func washes(_ E: EMOModel, _ proxy: MapProxy) -> some View {
        let _ = cameraTick
        GeometryReader { _ in
            if let r = E.run, let b = r.bounds, b.count == 2 {
                ForEach(EMOLayer.allCases.filter { E.on.contains($0) }) { l in
                    if let s = r.layers?[l.rawValue], let img = E.image("\(Int(r.t_min)):\(l.rawValue)", s),
                       let rect = rectFor(b, proxy) {
                        Image(platform: img).resizable().frame(width: rect.width, height: rect.height).position(x: rect.midX, y: rect.midY).opacity(E.stale ? 0.3 : 0.85)
                    }
                }
            }
            if let r = model.corridor.result, let band = r.band, let b = r.bounds, let img = E.image("corr:\(band.count):\(r.legs.count):\(r.summary.km)", band), let rect = rectFor(b, proxy) {
                Image(platform: img).resizable().frame(width: rect.width, height: rect.height).position(x: rect.midX, y: rect.midY).opacity(0.8)
            }
            if let o = E.focus?.overlay, let img = E.image("focus:\(E.focus?.id ?? ""):\(Int(E.t))", o.png), let rect = rectFor(o.bounds, proxy) {
                Image(platform: img).resizable().frame(width: rect.width, height: rect.height).position(x: rect.midX, y: rect.midY).opacity(0.8)
            }
        }
    }

    private func rectFor(_ b: [[Double]], _ proxy: MapProxy) -> CGRect? {
        guard b.count == 2, let nw = proxy.convert(CLLocationCoordinate2D(latitude: b[1][0], longitude: b[0][1]), to: .local),
              let se = proxy.convert(CLLocationCoordinate2D(latitude: b[0][0], longitude: b[1][1]), to: .local) else { return nil }
        return CGRect(x: nw.x, y: nw.y, width: se.x - nw.x, height: se.y - nw.y)
    }
}

struct UnitGlyph: View {
    let e: EMOEntity
    let onAir: Bool
    var body: some View {
        VStack(spacing: 1) {
            Image(systemName: Side.symbol(e.kind))
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 22, height: 22)
                .background(Side.colour(e.side).opacity(onAir || e.kind == "sensor" || e.kind == "receiver" ? 0.95 : 0.35),
                            in: e.side == "red" ? AnyShape(Diamond()) : e.side == "blue" ? AnyShape(RoundedRectangle(cornerRadius: 3)) : AnyShape(Circle()))
                .overlay((e.side == "red" ? AnyShape(Diamond()) : e.side == "blue" ? AnyShape(RoundedRectangle(cornerRadius: 3)) : AnyShape(Circle())).stroke(.black.opacity(0.7), lineWidth: 1))
            Text(e.name).font(.system(size: 9, weight: .medium)).foregroundStyle(.white).shadow(color: .black, radius: 1.5).lineLimit(1)
        }
    }
}

/// APP-6 hostile frame (diamond); friendly is a rectangle, neutral a circle.
struct Diamond: Shape {
    func path(in r: CGRect) -> Path {
        Path { p in p.move(to: .init(x: r.midX, y: r.minY)); p.addLine(to: .init(x: r.maxX, y: r.midY)); p.addLine(to: .init(x: r.midX, y: r.maxY)); p.addLine(to: .init(x: r.minX, y: r.midY)); p.closeSubpath() }
    }
}

struct UnitCard: View {
    @Environment(AppModel.self) private var model
    let focus: EMOFocus
    let entity: EMOEntity?
    let move: () -> Void
    let close: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Image(systemName: Side.symbol(focus.kind)).foregroundStyle(Side.colour(focus.side))
                Text(focus.name).font(.headline)
                Text(Side.kindText[focus.kind] ?? focus.kind).font(.caption).foregroundStyle(.secondary)
                Spacer()
                if let e = entity, focus.kind == "emitter" || focus.kind == "effector" {
                    Toggle("On air", isOn: Binding(get: { focus.active ?? true }, set: { v in Task { await model.emo.setActive(model.api, e, v) } }))
                        .toggleStyle(.switch).controlSize(.small).fixedSize()
                }
                Button("Move", action: move).controlSize(.small)
                Button(action: close) { Image(systemName: "xmark.circle.fill") }.buttonStyle(.plain).foregroundStyle(.secondary)
            }
            if let e = entity {
                Text([e.freq_mhz.map { "\(fmt($0)) MHz" }, e.f_hi_mhz.map { "to \(fmt($0)) MHz" }, e.eirp_dbm.map { "EIRP \(fmt($0)) dBm" }, e.h_agl.map { "\(fmt($0)) m AGL" }, e.category].compactMap { $0 }.joined(separator: " · "))
                    .font(.caption).foregroundStyle(.secondary)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 4) {
                    if let f = focus.fix {
                        Text(f.fix != nil ? "\(f.targetable == true ? "TARGETABLE: " : "")fixed by \(f.by_side ?? "") ±\(f.fix?.error_m ?? 0) m (cut \(Int(f.fix?.cut_deg ?? 0))°, p \(f.p ?? 0)%)" : "\(f.lobs ?? 0) line of bearing only")
                            .foregroundStyle(f.targetable == true ? .red : .yellow).font(.callout.weight(.semibold))
                    }
                    section("Heard by", (focus.heard_by ?? []).filter { $0.detected == true }.map { "\($0.sensor): margin \(fmt($0.margin_db ?? 0)) dB, p \($0.p ?? 0)%\($0.df == true ? ", DF" : "")" })
                    section("Hears", (focus.hears ?? []).filter { $0.detected == true }.map { "\($0.target): margin \(fmt($0.margin_db ?? 0)) dB" })
                    section("Jams", (focus.jams ?? []).map { "\($0.victim) (\($0.net ?? "")): J/S \(fmt($0.js_db ?? 0)) dB, \($0.status)" })
                    section("Jammed by", (focus.jammed ?? []).map { "\($0.effector) at \($0.victim): J/S \(fmt($0.js_db ?? 0)) dB, \($0.status)" })
                    if focus.overlay != nil { Text("Map wash: this unit's footprint against the opposing sensors' sensitivity.").font(.caption2).foregroundStyle(.secondary) }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: 180)
        }
        .padding(10)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
        .padding(.horizontal).padding(.bottom, 6)
    }

    @ViewBuilder private func section(_ title: String, _ rows: [String]) -> some View {
        if !rows.isEmpty {
            Text(title.uppercased()).font(.caption2.weight(.bold)).foregroundStyle(.secondary).padding(.top, 2)
            ForEach(rows, id: \.self) { Text($0).font(.caption) }
        }
    }
}

struct ScoreSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    private let rows: [(String, (EMOScoreSide) -> String)] = [
        ("Net availability %", { s in s.net_availability_pct.map { fmt($0) } ?? "–" }),
        ("Emitters detected by the other side", { $0.emitters_exposed ?? "–" }),
        ("Mean exposure dB", { s in s.mean_exposure_db.map { fmt($0) } ?? "–" }),
        ("Located by the other side", { s in s.fixed.map(String.init) ?? "–" }),
        ("Target-quality fixes", { s in s.targetable.map(String.init) ?? "–" }),
        ("Outstations denied", { s in s.denial_achieved.map(String.init) ?? "–" }),
        ("Outstations deceived", { s in s.deceived.map(String.init) ?? "–" }),
        ("Collateral (civil)", { s in s.collateral.map(String.init) ?? "–" }),
        ("Own net coverage denied %", { s in s.net_area_denied_pct.map { fmt($0) } ?? "–" }),
        ("Radar tracks held", { s in s.radar_tracks.map(String.init) ?? "–" }),
        ("Own platforms screened from radar", { s in s.radar_screened.map(String.init) ?? "–" }),
    ]
    var body: some View {
        let r = model.emo.run
        NavigationStack {
            List {
                if let sc = r?.score {
                    Section("Scoreboard at T+\(Int(r?.t_min ?? 0))") {
                        HStack { Text(""); Spacer(); Text("Blue").foregroundStyle(Side.colour("blue")).frame(width: 70); Text("Red").foregroundStyle(Side.colour("red")).frame(width: 70) }.font(.caption.bold())
                        ForEach(rows, id: \.0) { (label, f) in
                            HStack {
                                Text(label).font(.callout)
                                Spacer()
                                Text(sc.blue.map(f) ?? "–").monospacedDigit().frame(width: 70)
                                Text(sc.red.map(f) ?? "–").monospacedDigit().frame(width: 70)
                            }
                        }
                    }
                }
                if let nets = r?.nets, !nets.isEmpty {
                    Section("EA: nets under attack") {
                        ForEach(nets) { n in
                            HStack {
                                Text(n.net).foregroundStyle(Side.colour(n.side))
                                Spacer()
                                Text(n.space == true ? "space signal" : "\(Int(n.coverage_km2 ?? 0)) km²").font(.caption).foregroundStyle(.secondary)
                                Text("\(fmt(n.denied_pct ?? 0))% denied").bold().monospacedDigit()
                            }
                        }
                    }
                }
                if let fx = r?.fixes?.filter({ $0.fix != nil || ($0.lobs ?? 0) > 0 }), !fx.isEmpty {
                    Section("ES: who can fix whom") {
                        ForEach(fx) { f in
                            VStack(alignment: .leading) {
                                Text(f.target).foregroundStyle(Side.colour(f.target_side ?? ""))
                                Text(f.fix.map { "\(f.targetable == true ? "TARGETABLE " : "")±\($0.error_m ?? 0) m, cut \(Int($0.cut_deg ?? 0))°" } ?? "\(f.lobs ?? 0) line of bearing only")
                                    .font(.caption).foregroundStyle(f.targetable == true ? .red : .secondary)
                                Text((f.sensors ?? []).joined(separator: ", ")).font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                if let rd = r?.radar?.filter({ $0.detected == true || $0.screened == true }), !rd.isEmpty {
                    Section("Radar") {
                        ForEach(rd) { x in
                            HStack {
                                Text("\(x.radar) → \(x.target)").font(.callout)
                                Spacer()
                                Text(x.tracked == true ? "tracked" : x.screened == true ? "screened" : "no track")
                                    .foregroundStyle(x.tracked == true ? .green : x.screened == true ? .purple : .secondary).font(.caption.bold())
                            }
                        }
                    }
                }
                if let n = r?.notes { Section { Text(n).font(.caption).foregroundStyle(.secondary) } }
            }
            .navigationTitle("EMO results")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        #if os(macOS)
        .frame(minWidth: 560, minHeight: 520)
        #endif
    }
}

struct EMOLayerSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Binding var showFixes: Bool
    @Binding var showJamming: Bool
    var body: some View {
        let E = model.emo
        NavigationStack {
            List {
                Section("Washes (ground receivers, 2 m)") {
                    ForEach(EMOLayer.allCases) { l in
                        Toggle(l.label, isOn: Binding(get: { E.on.contains(l) }, set: { if $0 { E.on.insert(l) } else { E.on.remove(l) } }))
                    }
                }
                Section("Lines") {
                    Toggle("DF bearings to fixes (red: target quality)", isOn: $showFixes)
                    Toggle("Jamming that denies (magenta)", isOn: $showJamming)
                }
            }
            .navigationTitle("EMO overlays")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        #if os(macOS)
        .frame(minWidth: 380, minHeight: 420)
        #endif
    }
}

func fmt(_ v: Double) -> String { v.rounded() == v ? String(Int(v)) : String(format: "%.1f", v) }
