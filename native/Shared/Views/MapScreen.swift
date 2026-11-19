import MapKit
import SwiftUI

/// The operating picture: news and alerts, GNSS interference, aircraft, ships, satellites, radars, HF MUF, cables, C2.
struct MapScreen: View {
    @Environment(AppModel.self) private var model
    @State private var position: MapCameraPosition = .region(MKCoordinateRegion(
        center: .init(latitude: 52, longitude: 5), span: .init(latitudeDelta: 40, longitudeDelta: 60)))
    @State private var region: MKCoordinateRegion?
    @State private var picked: MapPoint?
    @State private var showLayers = false
    @State private var imagery = false

    var body: some View {
        let L = model.layers
        let pts = L.visiblePoints(in: region)
        Map(position: $position, selection: $picked) {
            cableLines(L)
            jamPolygons(L)
            mufLines(L)
            ForEach(pts) { p in
                Annotation(p.title, coordinate: p.coordinate, anchor: .center) { PointGlyph(p: p) }
                    .annotationTitles(.hidden)
                    .tag(p)
            }
        }
        .mapStyle(imagery ? .imagery(elevation: .flat) : .standard(elevation: .flat, emphasis: .muted, pointsOfInterest: .excludingAll))
        .mapControls {
            MapCompass(); MapScaleView()
            #if os(macOS)
            MapZoomStepper()
            #endif
        }
        .onMapCameraChange(frequency: .onEnd) { ctx in region = ctx.region }
        .safeAreaInset(edge: .bottom) { bottomBar(L, shown: pts.count) }
        .toolbar {
            ToolbarItem { Toggle(isOn: $imagery) { Label("Imagery", systemImage: "globe.europe.africa") } }
            ToolbarItem { Button { showLayers.toggle() } label: { Label("Layers", systemImage: "square.3.layers.3d") } }
            ToolbarItem { RefreshButton() }
        }
        .sheet(isPresented: $showLayers) { LayerPicker().environment(model).presentationDetents([.medium, .large]) }
        .navigationTitle("Map")
    }

    @MapContentBuilder private func cableLines(_ L: LayerStore) -> some MapContent {
        let lines: [MapLine] = L.enabled.contains(.cables) ? (L.lines[.cables] ?? []) : []
        ForEach(lines) { l in
            let c: Color = Color(css: l.colour) ?? .blue
            MapPolyline(coordinates: l.coords).stroke(c.opacity(0.55), lineWidth: 1)
        }
    }

    @MapContentBuilder private func jamPolygons(_ L: LayerStore) -> some MapContent {
        let polys: [JamPolygon] = L.enabled.contains(.gpsjam) ? L.polygons : []
        ForEach(polys) { p in
            let c: Color = p.level == "high" ? .red : .orange
            MapPolygon(coordinates: p.coords).foregroundStyle(c.opacity(0.35)).stroke(c.opacity(0.7), lineWidth: 0.5)
        }
    }

    @MapContentBuilder private func mufLines(_ L: LayerStore) -> some MapContent {
        let lines: [MapLine] = L.enabled.contains(.hfmap) ? (L.lines[.hfmap] ?? []) : []
        ForEach(lines) { l in
            let c: Color = Color(css: l.colour) ?? .yellow
            MapPolyline(coordinates: l.coords).stroke(c, lineWidth: 2)
        }
    }

    @ViewBuilder private func bottomBar(_ L: LayerStore, shown: Int) -> some View {
        VStack(spacing: 6) {
            if let p = picked {
                HStack(alignment: .top) {
                    Image(systemName: p.layer.symbol).foregroundStyle(p.layer.colour)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(p.title).font(.callout.weight(.semibold)).lineLimit(2)
                        Text(p.detail).font(.caption).foregroundStyle(.secondary).lineLimit(3)
                        Text(String(format: "%.4f, %.4f", p.lat, p.lon)).font(.caption2.monospaced()).foregroundStyle(.secondary).textSelection(.enabled)
                    }
                    Spacer()
                    Button { picked = nil } label: { Image(systemName: "xmark.circle.fill") }.buttonStyle(.plain).foregroundStyle(.secondary)
                }
                .padding(10).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
            }
            Text("\(shown) points in view · positions of news items are placement, not attribution")
                .font(.caption2).foregroundStyle(.secondary)
        }
        .padding(.horizontal).padding(.bottom, 6)
    }
}

struct PointGlyph: View {
    let p: MapPoint
    var body: some View {
        switch p.layer {
        case .air, .milair, .ais:
            Image(systemName: p.layer == .ais ? "location.north.fill" : "airplane")
                .font(.system(size: p.layer == .milair ? 13 : 10))
                .rotationEffect(.degrees((p.heading ?? 0) - (p.layer == .ais ? 0 : 90)))
                .foregroundStyle(p.layer == .milair ? roleColour(p.tint) : p.layer.colour)
                .shadow(color: .black, radius: 1)
        case .items:
            Circle().fill(Palette.domain(p.tint ?? "").opacity(0.9)).frame(width: 10, height: 10)
                .overlay(Circle().stroke(.black.opacity(0.6), lineWidth: 1))
        default:
            Circle().fill(p.layer.colour.opacity(0.9)).frame(width: 8, height: 8)
                .overlay(Circle().stroke(.black.opacity(0.6), lineWidth: 1))
        }
    }
    private func roleColour(_ r: String?) -> Color {
        switch r {
        case "isr", "ew": .red
        case "aew": .orange
        case "tanker": .yellow
        case "mpa": .cyan
        default: .orange
        }
    }
}

struct LayerPicker: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        let L = model.layers
        NavigationStack {
            List {
                ForEach(MapLayer.allCases) { layer in
                    Toggle(isOn: Binding(get: { L.enabled.contains(layer) },
                                         set: { on in if on { L.enabled.insert(layer) } else { L.enabled.remove(layer) }; Task { await model.refreshLayers() } })) {
                        HStack {
                            Image(systemName: layer.symbol).foregroundStyle(layer.colour).frame(width: 24)
                            VStack(alignment: .leading) {
                                Text(layer.label)
                                if let e = L.errors[layer] { Text(e).font(.caption).foregroundStyle(.orange) }
                                else if L.enabled.contains(layer) {
                                    Text("\(L.count(layer)) shown\(L.updated[layer].map { " · " + relative($0) } ?? "")").font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }
                Section {
                    Text("Aircraft and ships are around the UK (the collectors' boxes). Radars: up to 400 in view; zoom in for more.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Layers")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        #if os(macOS)
        .frame(minWidth: 380, minHeight: 480)
        #endif
    }
}
