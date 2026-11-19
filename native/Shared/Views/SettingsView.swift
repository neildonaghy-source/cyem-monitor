import SwiftUI

struct SettingsView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var m = model
        Form {
            Section {
                TextField("Server", text: $m.serverText)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never).keyboardType(.URL)
                    #endif
                    .onSubmit { model.applyServer() }
                HStack {
                    Button("Use server") { model.applyServer() }
                    Button("Default") { m.serverText = AppModel.defaultServer; model.applyServer() }
                }
            } header: { Text("Server") } footer: {
                Text("On the tailnet no log-in is needed. From the internet (Tailscale Funnel) the app asks for the CyEM username and password.")
            }
            Section {
                Picker("EMO scenario", selection: $m.wsMode) {
                    Text("Shared (all devices)").tag(AppModel.WSMode.shared)
                    Text("This device only").tag(AppModel.WSMode.device)
                }
            } header: { Text("EMO") } footer: {
                Text(model.wsMode == .shared ? "Changes here change what every device sees." : "Private workspace \(model.workspace): experiments stay off the shared scenario.")
            }
            Section("Connection") {
                LabeledContent("Route", value: model.me.map { $0.internet ? "Internet (signed in)" : "Tailnet" } ?? "–")
                if let u = model.me?.user { LabeledContent("Signed in as", value: u) }
                if let t = model.lastRefresh { LabeledContent("Last update", value: t.formatted(date: .omitted, time: .standard)) }
                if let e = model.lastError { Text(e).foregroundStyle(.orange) }
                if model.me?.user != nil { Button("Sign out", role: .destructive) { Task { await model.signOut() } } }
            }
            Section("About") {
                LabeledContent("App", value: "\(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?") (\(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "?"))")
                Text("Open and notional data only. Positions on news items are placement heuristics, not attribution.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Settings")
    }
}

struct SignInView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var user = ""
    @State private var pw = ""
    @State private var error: String?
    @State private var busy = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Username", text: $user).textContentType(.username).autocorrectionDisabled()
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        #endif
                    SecureField("Password", text: $pw).textContentType(.password).onSubmit(go)
                } footer: {
                    Text("This device is reaching \(model.serverText) over the internet, which needs the CyEM log-in. On the tailnet it is not asked for.")
                }
                if let error { Text(error).foregroundStyle(.red) }
            }
            .formStyle(.grouped)
            .navigationTitle("Sign in to CyEM")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(action: go) { busy ? AnyView(ProgressView()) : AnyView(Text("Sign in")) }.disabled(user.isEmpty || pw.isEmpty || busy)
                }
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            }
        }
        #if os(macOS)
        .frame(minWidth: 380, minHeight: 260)
        #endif
    }

    private func go() {
        busy = true
        Task {
            error = await model.signIn(user, pw)
            busy = false
            if error == nil { pw = ""; dismiss() }
        }
    }
}
