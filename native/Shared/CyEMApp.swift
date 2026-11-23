import SwiftUI

@main
struct CyEMApp: App {
    @State private var model = AppModel()
    @State private var web = WebController()
    @State private var tailnet = Tailnet()
    @State private var notifier = Notifier()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .environment(web)
                .environment(tailnet)
                .environment(notifier)
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
            #if os(macOS)
            CommandGroup(after: .saveItem) {
                Button("Share Page…") { web.sharePage() }.keyboardShortcut("s", modifiers: [.command, .shift])
            }
            #endif
        }
        #if os(macOS)
        Settings {
            SettingsView().environment(model).environment(tailnet).environment(notifier).frame(width: 460).padding()
        }
        #endif
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(WebController.self) private var web
    @Environment(Tailnet.self) private var tailnet
    @Environment(Notifier.self) private var notifier
    @State private var showSettings = false
    @State private var arWorkspace: ARLaunch?                     // iOS: the AR view, opened from the menu

    struct ARLaunch: Identifiable { let workspace: String; var id: String { workspace } }

    var body: some View {
        ZStack {
            Color(red: 0.04, green: 0.055, blue: 0.075).ignoresSafeArea()           // the web app's background, no white flash
            if tailnet.ready {
                CyEMWebView(url: model.serverURL, homeTick: model.homeTick, controller: web, proxy: tailnet.proxy)
                    .id(tailnet.generation)                                          // a new proxy needs a new web view
                    #if os(macOS)
                    .ignoresSafeArea()
                    #else
                    .ignoresSafeArea(.container, edges: .bottom)
                    #endif
            } else {
                TailnetGate(settings: { showSettings = true })
            }
            if tailnet.ready, let err = web.loadError {
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
                Button { Task { arWorkspace = ARLaunch(workspace: await web.workspace()) } } label: { Label("AR view", systemImage: "camera.viewfinder") }
                if let u = web.currentURL { ShareLink(item: u) { Label("Share page", systemImage: "square.and.arrow.up") } }
                Button { showSettings = true } label: { Label("Server", systemImage: "gearshape") }
            } label: {
                Image(systemName: "ellipsis.circle.fill").font(.title2).symbolRenderingMode(.hierarchical)
                    .foregroundStyle(.white.opacity(0.55)).padding(10)
            }
            .padding(.bottom, 64)
        }
        .sheet(isPresented: $showSettings) { NavigationStack { SettingsView().environment(model).environment(tailnet).environment(notifier) } }
        .sheet(item: Binding(get: { web.shareFile }, set: { web.shareFile = $0 })) { f in ShareSheet(url: f.url) }
        .fullScreenCover(item: $arWorkspace) { a in ARScreen(server: model.serverURL, workspace: a.workspace, proxy: tailnet.proxy) }
        #else
        .sheet(isPresented: $showSettings) { SettingsView().environment(model).environment(tailnet).environment(notifier).frame(width: 460).padding() }
        #endif
        // Handoff: the page shown here can be picked up in CyEM on the other device (same Apple ID).
        .userActivity(RootView.handoffType, isActive: web.currentURL != nil) { a in
            a.title = web.title ?? "CyEM"
            a.webpageURL = web.currentURL
            a.isEligibleForHandoff = true
        }
        .onContinueUserActivity(RootView.handoffType) { a in
            if let u = a.webpageURL, u.host == model.serverURL.host { web.open(u) }
        }
        .onAppear {
            tailnet.start()
            #if os(macOS)                                            // the iPhone app has no notifications (Neil, 23 Nov)
            notifier.openInApp = { [weak web] u in web?.open(u) }
            syncNotifier()
            notifier.start()
            #endif
        }
        .onChange(of: tailnet.generation) { syncNotifier() }
        .onChange(of: tailnet.mode) { syncNotifier() }
        .onChange(of: model.serverText) { syncNotifier() }
    }

    static let handoffType = "com.neildonaghy.cyem.page"

    private func syncNotifier() {
        notifier.server = model.serverURL
        notifier.proxy = tailnet.proxy
        notifier.ready = tailnet.ready
    }
}

/// Shown while the built-in Tailscale node starts or waits for its first sign-in.
struct TailnetGate: View {
    @Environment(Tailnet.self) private var tailnet
    @Environment(\.openURL) private var openURL
    let settings: () -> Void
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "network.badge.shield.half.filled").font(.system(size: 44)).foregroundStyle(.secondary)
            Text("Joining the tailnet").font(.title2.bold())
            if tailnet.hasKey {
                ProgressView()
                Text("Connecting through the app's own Tailscale connection (\(tailnet.state.lowercased()))…").foregroundStyle(.secondary)
            } else if let u = tailnet.authURL {
                Text("This app has its own Tailscale connection (\(Tailnet.hostName)). Sign in once with your Tailscale account; after that it connects by itself.")
                    .multilineTextAlignment(.center).foregroundStyle(.secondary).frame(maxWidth: 440)
                Button("Sign in to Tailscale") { openURL(u) }.buttonStyle(.borderedProminent)
            } else {
                ProgressView()
                Text("Tailscale: \(tailnet.state.lowercased())").foregroundStyle(.secondary)
            }
            if let e = tailnet.error { Text(e).font(.caption).foregroundStyle(.orange).multilineTextAlignment(.center) }
            Button("Use this device's Tailscale app instead") { tailnet.mode = .system }.font(.caption)
            Button("Settings…", action: settings).font(.caption)
        }
        .padding(30)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(red: 0.04, green: 0.055, blue: 0.075))
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
    @Environment(Tailnet.self) private var tailnet
    @Environment(Notifier.self) private var notifier
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
            Section {
                Picker("Connection", selection: Binding(get: { tailnet.mode }, set: { tailnet.mode = $0 })) {
                    Text("Built-in Tailscale").tag(Tailnet.Mode.builtIn)
                    Text("This device's network").tag(Tailnet.Mode.system)
                }
                if tailnet.mode == .builtIn {
                    LabeledContent("State", value: tailnet.state)
                    if let ip = tailnet.ip { LabeledContent("Address", value: ip) }
                    if let t = tailnet.tailnetName { LabeledContent("Tailnet", value: t) }
                    if let e = tailnet.error { Text(e).foregroundStyle(.orange) }
                    if tailnet.state == "Running" { Button("Sign this app out of Tailscale", role: .destructive) { Task { await tailnet.signOut() } } }
                }
            } header: { Text("Tailscale") } footer: {
                Text(tailnet.mode == .builtIn
                     ? (tailnet.hasKey ? "The app joins the tailnet by itself (\(Tailnet.nodeName)), limited to the CyEM server; no Tailscale account or app needed." : "This build has no tailnet key, so built-in Tailscale needs a Tailscale sign-in.")
                     : "The app uses this device's network: the Tailscale app on the tailnet, or from the internet the CyEM username and password.")
            }
            #if os(macOS)
            Section {
                Toggle("High-severity items (4 and 5)", isOn: Binding(get: { notifier.itemsOn }, set: { notifier.itemsOn = $0 }))
                Toggle("Finished briefs", isOn: Binding(get: { notifier.briefsOn }, set: { notifier.briefsOn = $0 }))
                if notifier.permitted == false { Text("Notifications are turned off for CyEM in System Settings.").foregroundStyle(.orange) }
                if let t = notifier.lastCheck { LabeledContent("Last check", value: t.formatted(date: .omitted, time: .shortened)) }
                LabeledContent("Widgets updated", value: notifier.lastWidget?.formatted(date: .omitted, time: .shortened) ?? "not yet")
                if let e = notifier.lastError { Text(e).font(.caption).foregroundStyle(.orange) }
                Button("Check now") { Task { await notifier.check() } }
            } header: { Text("Notifications and widgets") } footer: {
                #if os(macOS)
                Text("The app asks the server every 5 minutes while it runs, also with its window closed, and updates the widgets. Severity is a keyword heuristic.")
                #else
                Text("The app asks the server every 5 minutes while it is open, and updates the widgets; in the background only when iOS allows (often hours apart). Severity is a keyword heuristic.")
                #endif
            }
            #endif
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
