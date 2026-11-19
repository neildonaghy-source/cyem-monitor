import SwiftUI

@main
struct CyEMApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .preferredColorScheme(.dark)
                .tint(Palette.accent)
        }
        #if os(macOS)
        .defaultSize(width: 1280, height: 820)
        Settings {
            SettingsView().environment(model).frame(width: 460).padding()
        }
        #endif
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        TabView {
            Tab("Overview", systemImage: "gauge.with.dots.needle.33percent") { NavigationStack { OverviewView() } }
            Tab("Feed", systemImage: "list.bullet.rectangle") { NavigationStack { FeedView() } }
            Tab("Map", systemImage: "map") { NavigationStack { MapScreen() } }
            #if os(iOS)
            Tab("Settings", systemImage: "gearshape") { NavigationStack { SettingsView() } }
            #endif
        }
        .tabViewStyle(.sidebarAdaptable)
        .task { await model.loop() }
        .sheet(isPresented: Binding(get: { model.needsSignIn }, set: { model.needsSignIn = $0 })) {
            SignInView().environment(model)
        }
    }
}

enum Palette {
    static let accent = Color(red: 0.24, green: 0.55, blue: 1.0)            // #3c8cff, as the web app
    static func severity(_ s: Int) -> Color {
        switch s {
        case 5...: Color(red: 1.0, green: 0.27, blue: 0.27)
        case 4: Color(red: 1.0, green: 0.55, blue: 0.2)
        case 3: Color(red: 0.95, green: 0.70, blue: 0.24)
        default: Color.secondary
        }
    }
    static func domain(_ d: String) -> Color {
        switch d {
        case "cyber": Color(red: 0.86, green: 0.24, blue: 0.86)
        case "em": Color(red: 0.27, green: 0.83, blue: 0.54)
        case "infra": Color(red: 0.24, green: 0.55, blue: 1.0)
        case "osint": Color(red: 0.95, green: 0.70, blue: 0.24)
        default: Color.secondary
        }
    }
}
