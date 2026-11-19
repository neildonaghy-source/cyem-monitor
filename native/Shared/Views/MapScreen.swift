import MapKit
import SwiftUI

/// Items with a position, coloured by domain. Positions are keyword heuristics (placement, not attribution).
struct MapScreen: View {
    @Environment(AppModel.self) private var model
    @State private var position: MapCameraPosition = .region(MKCoordinateRegion(
        center: .init(latitude: 50, longitude: 10), span: .init(latitudeDelta: 60, longitudeDelta: 80)))
    @State private var picked: Item?

    var body: some View {
        let placed = model.items.filter { $0.lat != nil && $0.lon != nil }
        Map(position: $position, selection: $picked) {
            ForEach(placed) { item in
                Annotation(item.title, coordinate: .init(latitude: item.lat!, longitude: item.lon!), anchor: .center) {
                    Circle().fill(Palette.domain(item.domain).opacity(0.85))
                        .frame(width: CGFloat(8 + 2 * item.severity), height: CGFloat(8 + 2 * item.severity))
                        .overlay(Circle().stroke(.black.opacity(0.6), lineWidth: 1))
                }
                .annotationTitles(.hidden)
                .tag(item)
            }
        }
        .mapStyle(.standard(elevation: .flat, emphasis: .muted, pointsOfInterest: .excludingAll))
        .mapControls { MapCompass(); MapScaleView() }
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: 6) {
                if let p = picked {
                    NavigationLink(value: p) { ItemRow(item: p).foregroundStyle(.primary) }
                        .padding(10).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
                }
                Text("\(placed.count) of \(model.items.count) items have a position (from keywords: placement, not attribution).")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .padding(.horizontal).padding(.bottom, 6)
        }
        .navigationDestination(for: Item.self) { ItemDetail(item: $0) }
        .toolbar { RefreshButton() }
        .navigationTitle("Map")
    }
}
