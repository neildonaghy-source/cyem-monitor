import SwiftUI
import WidgetKit

// CyEM widgets (W5): Kp, GNSS interference, item counts, latest brief time. The extension never asks the server: it
// shows the snapshot the app wrote at its last check (WidgetSnapshot.Store) and says how old it is. Tapping opens CyEM.

struct StatusEntry: TimelineEntry {
    let date: Date
    let snap: WidgetSnapshot?
}

struct StatusProvider: TimelineProvider {
    func placeholder(in context: Context) -> StatusEntry { StatusEntry(date: Date(), snap: .placeholder) }
    func getSnapshot(in context: Context, completion: @escaping (StatusEntry) -> Void) {
        completion(StatusEntry(date: Date(), snap: context.isPreview ? (WidgetSnapshot.Store.load() ?? .placeholder) : WidgetSnapshot.Store.load()))
    }
    /// One entry now and another in 15 minutes, so "as of" and the stale warning keep up even if the app stops.
    /// The app also asks WidgetKit to reload after each check.
    func getTimeline(in context: Context, completion: @escaping (Timeline<StatusEntry>) -> Void) {
        let now = Date(), snap = WidgetSnapshot.Store.load()
        let later = now.addingTimeInterval(15 * 60)
        completion(Timeline(entries: [StatusEntry(date: now, snap: snap), StatusEntry(date: later, snap: snap)],
                            policy: .after(later.addingTimeInterval(15 * 60))))
    }
}

private enum Palette {
    static let bg = Color(red: 0.04, green: 0.055, blue: 0.075)       // the web app's background
    static let dim = Color(white: 0.62)
    static let amber = Color(red: 1.0, green: 0.72, blue: 0.25)
    static let red = Color(red: 1.0, green: 0.38, blue: 0.33)
    static let green = Color(red: 0.42, green: 0.85, blue: 0.5)
    static func kp(_ kp: Double?) -> Color { [green, amber, red][WidgetSnapshot.kpLevel(kp)] }
}

struct StatusWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: StatusEntry

    var body: some View {
        Group {
            if let s = entry.snap {
                switch family {
                case .systemMedium: medium(s)
                #if os(iOS)
                case .accessoryRectangular: rectangular(s)
                case .accessoryInline: Text("Kp \(WidgetSnapshot.kpText(s.kp)) · high \(WidgetSnapshot.count(s.high24h))")
                #endif
                default: small(s)
                }
            } else {
                VStack(alignment: .leading, spacing: 4) {
                    Text("CyEM").font(.headline)
                    Text("Open CyEM once; the widget shows its last check.").font(.caption).foregroundStyle(Palette.dim)
                }
            }
        }
        .containerBackground(for: .widget) { Palette.bg }
    }

    private func small(_ s: WidgetSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline) {
                Text("Kp").font(.caption).foregroundStyle(Palette.dim)
                Text(WidgetSnapshot.kpText(s.kp)).font(.title2.weight(.semibold)).foregroundStyle(Palette.kp(s.kp))
                Spacer(minLength: 0)
            }
            Text(WidgetSnapshot.kpBand(s.kp)).font(.caption2).foregroundStyle(Palette.dim)
            row("GNSS", s.gnssHigh.map { "\($0) high" } ?? "–", warn: (s.gnssHigh ?? 0) > 0)
            row("Items 24 h", WidgetSnapshot.count(s.items24h))
            row("High", WidgetSnapshot.count(s.high24h), warn: (s.high24h ?? 0) > 0)
            Spacer(minLength: 0)
            footer(s)
        }
    }

    private func medium(_ s: WidgetSnapshot) -> some View {
        HStack(alignment: .top, spacing: 14) {
            VStack(alignment: .leading, spacing: 3) {
                Text("Space weather").font(.caption).foregroundStyle(Palette.dim)
                HStack(alignment: .firstTextBaseline, spacing: 4) {
                    Text("Kp").font(.caption).foregroundStyle(Palette.dim)
                    Text(WidgetSnapshot.kpText(s.kp)).font(.title.weight(.semibold)).foregroundStyle(Palette.kp(s.kp))
                }
                Text(WidgetSnapshot.kpBand(s.kp)).font(.caption2).foregroundStyle(Palette.dim)
                row("24 h max", WidgetSnapshot.kpText(s.kpMax24h))
                row("NOAA", s.scales ?? "–")
                Spacer(minLength: 0)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text("GNSS interference").font(.caption).foregroundStyle(Palette.dim)
                Text(s.gnssText).font(.caption.weight(.medium)).foregroundStyle((s.gnssHigh ?? 0) > 0 ? Palette.amber : .primary)
                Text("Items, last 24 h").font(.caption).foregroundStyle(Palette.dim).padding(.top, 2)
                row("All", WidgetSnapshot.count(s.items24h))
                row("Cyber / EM", "\(WidgetSnapshot.count(s.cyber24h)) / \(WidgetSnapshot.count(s.em24h))")
                row("High", WidgetSnapshot.count(s.high24h), warn: (s.high24h ?? 0) > 0)
                row("Brief", s.briefText(now: entry.date))
                Spacer(minLength: 0)
                footer(s)
            }
        }
    }

    #if os(iOS)
    private func rectangular(_ s: WidgetSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text("Kp \(WidgetSnapshot.kpText(s.kp)) \(WidgetSnapshot.kpBand(s.kp))").font(.headline)
            Text("GNSS \(s.gnssText)").font(.caption)
            Text("High \(WidgetSnapshot.count(s.high24h)) · \(WidgetSnapshot.age(s.fetchedAt, now: entry.date))").font(.caption)
        }
    }
    #endif

    private func row(_ label: String, _ value: String, warn: Bool = false) -> some View {
        HStack(spacing: 4) {
            Text(label).font(.caption2).foregroundStyle(Palette.dim)
            Spacer(minLength: 2)
            Text(value).font(.caption2.weight(.medium)).foregroundStyle(warn ? Palette.amber : .primary).lineLimit(1)
        }
    }

    private func footer(_ s: WidgetSnapshot) -> some View {
        let stale = s.isStale(now: entry.date)
        return Text(stale ? "Stale: \(WidgetSnapshot.age(s.fetchedAt, now: entry.date))" : "As of \(WidgetSnapshot.age(s.fetchedAt, now: entry.date))")
            .font(.caption2).foregroundStyle(stale ? Palette.amber : Palette.dim)
    }
}

struct CyEMStatusWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: WidgetSnapshot.Store.kind, provider: StatusProvider()) { StatusWidgetView(entry: $0) }
            .configurationDisplayName("CyEM status")
            .description("Kp, GNSS interference, item counts and the latest brief, as of the app's last check.")
            #if os(iOS)
            .supportedFamilies([.systemSmall, .systemMedium, .accessoryRectangular, .accessoryInline])
            #else
            .supportedFamilies([.systemSmall, .systemMedium])
            #endif
    }
}

@main
struct CyEMWidgets: WidgetBundle {
    var body: some Widget { CyEMStatusWidget() }
}
