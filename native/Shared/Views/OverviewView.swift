import SwiftUI

/// The status strip of the web app as tiles: space weather, HF, GNSS interference, item counts, brief, collectors.
struct OverviewView: View {
    @Environment(AppModel.self) private var model

    private let cols = [GridItem(.adaptive(minimum: 150), spacing: 10)]

    var body: some View {
        ScrollView {
            if let err = model.lastError { ErrorBanner(text: err).padding(.horizontal) }
            if let s = model.status {
                LazyVGrid(columns: cols, spacing: 10) {
                    Tile("Kp", s.spaceweather?.kp.map { String(format: "%.1f", $0) } ?? "–",
                         sub: s.spaceweather?.kp_max_24h.map { String(format: "max %.1f in 24 h", $0) },
                         colour: kpColour(s.spaceweather?.kp))
                    Tile("R / S / G", s.spaceweather?.scales?.summary ?? "–", sub: "NOAA scales now")
                    Tile("Flare 24 h", s.spaceweather?.max_flare_24h ?? "–", sub: "largest X-ray class")
                    Tile("Solar flux", s.hf?.solarflux ?? s.spaceweather?.f107.map { String(Int($0)) } ?? "–",
                         sub: s.hf?.geomagfield.map { "geomag \($0.lowercased())" })
                    Tile("GNSS interference", "\(s.gnss?.high ?? 0) / \(s.gnss?.medium ?? 0)",
                         sub: "high / medium cells \(s.gnss?.date ?? "")")
                    Tile("Items 24 h", "\(s.counts?.items_24h ?? 0)", sub: "\(s.counts?.high_24h ?? 0) high severity")
                    Tile("Cyber / EM", "\(s.counts?.cyber_24h ?? 0) / \(s.counts?.em_24h ?? 0)", sub: "items in 24 h")
                    Tile("Infra / OSINT", "\(s.counts?.infra_24h ?? 0) / \(s.counts?.osint_24h ?? 0)", sub: "items in 24 h")
                    Tile("CVEs 7 d", "\(s.counts?.cve_7d ?? 0)", sub: nil)
                    Tile("Brief", s.brief?.generating == true ? "writing…" : relative(s.brief?.latest_at),
                         sub: s.brief?.model)
                }
                .padding()
                CollectorList(runs: s.collectors ?? [])
            } else if model.loading {
                ProgressView("Connecting to \(model.serverText)").padding(40)
            } else {
                ContentUnavailableView("No data", systemImage: "antenna.radiowaves.left.and.right.slash",
                                       description: Text("Check the server in Settings and that this device is on the tailnet."))
            }
        }
        .navigationTitle("CyEM")
        .toolbar { RefreshButton() }
        .refreshable { await model.refresh() }
    }

    private func kpColour(_ kp: Double?) -> Color {
        guard let kp else { return .primary }
        return kp >= 7 ? .red : kp >= 5 ? .orange : kp >= 4 ? .yellow : .primary
    }
}

struct Tile: View {
    let title: String, value: String, sub: String?, colour: Color
    init(_ title: String, _ value: String, sub: String?, colour: Color = .primary) {
        self.title = title; self.value = value; self.sub = sub; self.colour = colour
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title.uppercased()).font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
            Text(value).font(.title2.monospacedDigit().weight(.semibold)).foregroundStyle(colour).lineLimit(1).minimumScaleFactor(0.6)
            if let sub { Text(sub).font(.caption).foregroundStyle(.secondary).lineLimit(2) }
        }
        .frame(maxWidth: .infinity, minHeight: 78, alignment: .topLeading)
        .padding(10)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
    }
}

struct CollectorList: View {
    let runs: [StatusResponse.CollectorRun]
    @State private var open = false
    var body: some View {
        let bad = runs.filter { $0.enabled != false && !$0.healthy && $0.ok != nil }
        DisclosureGroup(isExpanded: $open) {
            ForEach(runs) { r in
                HStack(alignment: .firstTextBaseline) {
                    Image(systemName: r.enabled == false ? "pause.circle" : r.healthy ? "checkmark.circle.fill" : r.ok == nil ? "circle.dashed" : "exclamationmark.triangle.fill")
                        .foregroundStyle(r.enabled == false ? Color.secondary : r.healthy ? Color.green : r.ok == nil ? Color.secondary : Color.orange)
                    VStack(alignment: .leading) {
                        Text(r.name).font(.callout.monospaced())
                        if let m = r.message { Text(m).font(.caption).foregroundStyle(.secondary).lineLimit(2) }
                    }
                    Spacer()
                    Text(relative(r.last_finished)).font(.caption).foregroundStyle(.secondary)
                }
                .padding(.vertical, 2)
            }
        } label: {
            Text("Sources: \(runs.count) · \(bad.isEmpty ? "all healthy" : "\(bad.count) failing")")
                .font(.headline).foregroundStyle(bad.isEmpty ? Color.primary : Color.orange)
        }
        .padding(.horizontal)
        .padding(.bottom)
    }
}

struct ErrorBanner: View {
    let text: String
    var body: some View {
        Label(text, systemImage: "exclamationmark.triangle").font(.callout).foregroundStyle(.orange)
            .frame(maxWidth: .infinity, alignment: .leading).padding(10)
            .background(.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
    }
}

struct RefreshButton: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        Button { Task { await model.refresh() } } label: {
            if model.loading { ProgressView().controlSize(.small) } else { Label("Refresh", systemImage: "arrow.clockwise") }
        }
        .keyboardShortcut("r", modifiers: .command)
    }
}

func relative(_ iso: String?) -> String {
    guard let iso, let d = ISODate.parse(iso) else { return "–" }
    return d.formatted(.relative(presentation: .numeric, unitsStyle: .abbreviated))
}
