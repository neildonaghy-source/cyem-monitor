import SwiftUI

@main
struct CyEMApp: App {
    @State private var model = AppModel()
    @State private var web = WebController()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .environment(web)
                .preferredColorScheme(.dark)
        }
        .defaultSize(width: 1440, height: 900)
        .commands {
            CommandGroup(after: .toolbar) {
                Button("Reload") { web.reload() }.keyboardShortcut("r", modifiers: .command)
                Button("Back") { web.back() }.keyboardShortcut("[", modifiers: .command)
                Button("Forward") { web.forward() }.keyboardShortcut("]", modifiers: .command)
                Button("Home") { model.homeTick += 1 }.keyboardShortcut("h", modifiers: [.command, .shift])
            }
        }
        #if os(macOS)
        Settings {
            SettingsView().environment(model).frame(width: 460).padding()
        }
        #endif
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(WebController.self) private var web
    @State private var showSettings = false

    var body: some View {
        ZStack {
            Color(red: 0.04, green: 0.055, blue: 0.075).ignoresSafeArea()           // the web app's background, no white flash
            CyEMWebView(url: model.serverURL, homeTick: model.homeTick, controller: web)
                #if os(macOS)
                .ignoresSafeArea()
                #else
                .ignoresSafeArea(.container, edges: .bottom)
                #endif
            if let err = web.loadError {
                ConnectionProblem(message: err, server: model.serverText, retry: { web.loadError = nil; model.homeTick += 1 }, settings: { showSettings = true })
            }
            if web.loading && web.progress < 1 {
                VStack { ProgressView(value: web.progress).progressViewStyle(.linear).tint(Color(red: 0.24, green: 0.55, blue: 1.0)); Spacer() }
            }
        }
        #if os(iOS)
        .overlay(alignment: .bottomTrailing) {
            Menu {
                Button { web.reload() } label: { Label("Reload", systemImage: "arrow.clockwise") }
                Button { model.homeTick += 1 } label: { Label("Home", systemImage: "house") }
                Button { showSettings = true } label: { Label("Server", systemImage: "gearshape") }
            } label: {
                Image(systemName: "ellipsis.circle.fill").font(.title2).symbolRenderingMode(.hierarchical)
                    .foregroundStyle(.white.opacity(0.55)).padding(10)
            }
            .padding(.bottom, 64)
        }
        .sheet(isPresented: $showSettings) { NavigationStack { SettingsView().environment(model) } }
        .sheet(item: Binding(get: { web.shareFile }, set: { web.shareFile = $0 })) { f in ShareSheet(url: f.url) }
        #else
        .sheet(isPresented: $showSettings) { SettingsView().environment(model).frame(width: 460).padding() }
        #endif
    }
}

struct ConnectionProblem: View {
    let message: String
    let server: String
    let retry: () -> Void
    let settings: () -> Void
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "antenna.radiowaves.left.and.right.slash").font(.system(size: 44)).foregroundStyle(.secondary)
            Text("Cannot reach CyEM").font(.title2.bold())
            Text(message).multilineTextAlignment(.center).foregroundStyle(.secondary)
            Text("Server: \(server)").font(.caption.monospaced()).foregroundStyle(.secondary)
            Text("On the tailnet, check that Tailscale is connected on this device. From the internet the same address asks for the CyEM username and password.")
                .font(.caption).multilineTextAlignment(.center).foregroundStyle(.secondary).frame(maxWidth: 420)
            HStack { Button("Try again", action: retry).buttonStyle(.borderedProminent); Button("Server…", action: settings) }
        }
        .padding(30)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(red: 0.04, green: 0.055, blue: 0.075))
    }
}

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var error: String?
    var body: some View {
        Form {
            Section {
                TextField("Server", text: $text)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never).keyboardType(.URL)
                    #endif
                    .onSubmit(apply)
                HStack {
                    Button("Use this server", action: apply)
                    Button("Default") { text = AppModel.defaultServer; apply() }
                }
                if let error { Text(error).foregroundStyle(.red) }
            } header: { Text("CyEM server") } footer: {
                Text("The app shows the CyEM web interface from this server. Tailnet: no log-in. Internet (Tailscale Funnel): the CyEM log-in page appears and the session lasts 30 days.")
            }
            Section("About") {
                LabeledContent("App", value: "\(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?") (\(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "?"))")
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Settings")
        .onAppear { text = model.serverText }
    }
    private func apply() {
        error = model.applyServer(text)
        if error == nil { dismiss() }
    }
}
