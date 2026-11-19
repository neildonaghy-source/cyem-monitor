import SwiftUI

struct FeedView: View {
    @Environment(AppModel.self) private var model
    @State private var selection: Item?

    var body: some View {
        @Bindable var m = model
        List(selection: $selection) {
            ForEach(FeedGroup.build(model.items)) { g in
                if g.items.count == 1 {
                    NavigationLink(value: g.items[0]) { ItemRow(item: g.items[0]) }
                } else {
                    DisclosureGroup {
                        ForEach(g.items) { item in NavigationLink(value: item) { ItemRow(item: item) } }
                    } label: { GroupRow(group: g) }
                }
            }
        }
        .navigationDestination(for: Item.self) { ItemDetail(item: $0) }
        .overlay {
            if model.items.isEmpty && !model.loading {
                ContentUnavailableView("Nothing in the last \(model.hours) h", systemImage: "tray",
                                       description: Text(model.search.isEmpty ? "Try another domain or a longer window." : "No match for \u{201C}\(model.search)\u{201D}."))
            }
        }
        .searchable(text: $m.search, prompt: "Search titles and summaries")
        .onSubmit(of: .search) { Task { await model.refresh() } }
        .onChange(of: model.search) { _, new in if new.isEmpty { Task { await model.refresh() } } }
        .toolbar {
            ToolbarItem {
                Picker("Domain", selection: $m.domain) {
                    ForEach(Domain.allCases) { Text($0.label).tag($0) }
                }
                .pickerStyle(.menu)
                .onChange(of: model.domain) { Task { await model.refresh() } }
            }
            ToolbarItem {
                Picker("Window", selection: $m.hours) {
                    Text("24 h").tag(24); Text("48 h").tag(48); Text("7 days").tag(168); Text("30 days").tag(720)
                }
                .pickerStyle(.menu)
                .onChange(of: model.hours) { Task { await model.refresh() } }
            }
            ToolbarItem { RefreshButton() }
        }
        .refreshable { await model.refresh() }
        .navigationTitle("Feed")
    }
}

struct ItemRow: View {
    let item: Item
    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            RoundedRectangle(cornerRadius: 2).fill(Palette.severity(item.severity)).frame(width: 4)
            VStack(alignment: .leading, spacing: 3) {
                Text(item.title).font(.callout.weight(.medium)).lineLimit(3)
                HStack(spacing: 6) {
                    Text(item.domain.uppercased()).font(.caption2.weight(.bold)).foregroundStyle(Palette.domain(item.domain))
                    Text(item.source).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    if let c = item.country_name { Text("· \(c)").font(.caption).foregroundStyle(.secondary).lineLimit(1) }
                    Spacer(minLength: 0)
                    Text(item.published.map { $0.formatted(.relative(presentation: .numeric, unitsStyle: .abbreviated)) } ?? "")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 2)
    }
}

struct ItemDetail: View {
    let item: Item
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text(item.title).font(.title3.weight(.semibold)).textSelection(.enabled)
                HStack {
                    Text(item.domain.uppercased()).foregroundStyle(Palette.domain(item.domain)).bold()
                    Text(item.kind)
                    Text("severity \(item.severity)").foregroundStyle(Palette.severity(item.severity))
                }
                .font(.caption)
                LabeledContent("Source", value: item.source)
                if let p = item.published { LabeledContent("Published", value: p.formatted(date: .abbreviated, time: .shortened)) }
                if let c = item.country_name {
                    LabeledContent("Country", value: c)
                    Text("Country and map position come from keywords in the text: placement, not attribution.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let s = item.summary, !s.isEmpty { Text(s).textSelection(.enabled) }
                if let tags = item.tags, !tags.isEmpty {
                    Text(tags.joined(separator: " · ")).font(.caption.monospaced()).foregroundStyle(.secondary)
                }
                if let link = item.link {
                    HStack {
                        Link(destination: link) { Label("Open source", systemImage: "safari") }
                        ShareLink(item: link)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding()
        }
        .navigationTitle(item.kind)
    }
}

/// A burst of like items (same source and kind, close in time) shown as one row, as 50 BGP hijacks in one fetch.
struct FeedGroup: Identifiable {
    var items: [Item]
    var id: String { items[0].id }

    static func build(_ items: [Item], minSize: Int = 4, window: TimeInterval = 3 * 3600) -> [FeedGroup] {
        var out: [FeedGroup] = []
        var used = Set<String>()
        for (i, it) in items.enumerated() where !used.contains(it.id) {
            let t0 = it.published ?? .distantPast
            let like = items[i...].filter { !used.contains($0.id) && $0.source == it.source && $0.kind == it.kind
                && abs(($0.published ?? .distantPast).timeIntervalSince(t0)) <= window }
            if like.count >= minSize {
                like.forEach { used.insert($0.id) }
                out.append(FeedGroup(items: like))
            } else {
                used.insert(it.id)
                out.append(FeedGroup(items: [it]))
            }
        }
        return out
    }
}

struct GroupRow: View {
    let group: FeedGroup
    var body: some View {
        let first = group.items[0]
        let worst = group.items.map(\.severity).max() ?? first.severity
        HStack(alignment: .top, spacing: 8) {
            RoundedRectangle(cornerRadius: 2).fill(Palette.severity(worst)).frame(width: 4)
            VStack(alignment: .leading, spacing: 3) {
                Text("\(group.items.count) × \(first.kind.replacingOccurrences(of: "_", with: " ")) from \(first.source)")
                    .font(.callout.weight(.medium))
                Text(first.title).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                HStack(spacing: 6) {
                    Text(first.domain.uppercased()).font(.caption2.weight(.bold)).foregroundStyle(Palette.domain(first.domain))
                    Spacer(minLength: 0)
                    Text(first.published.map { $0.formatted(.relative(presentation: .numeric, unitsStyle: .abbreviated)) } ?? "")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 2)
    }
}
