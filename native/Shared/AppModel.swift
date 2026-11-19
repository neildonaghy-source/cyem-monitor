import Foundation
import Observation

/// App-wide state: the server, who is signed in, the status strip and the feed. Refreshes every minute while visible.
@MainActor @Observable
final class AppModel {
    static let defaultServer = "https://nucbox-evo-x2.tail013324.ts.net/"

    var serverText: String { didSet { UserDefaults.standard.set(serverText, forKey: "server") } }
    private(set) var api: APIClient
    var me: MeResponse?
    var needsSignIn = false
    var status: StatusResponse?
    var items: [Item] = []
    var mapItems: [Item] = []
    let layers = LayerStore()
    let emo = EMOModel()
    enum WSMode: String { case shared, device }
    /// EMO workspace: the shared scenario, or one private to this device (as the web app's "This device only").
    var wsMode: WSMode { didSet { UserDefaults.standard.set(wsMode.rawValue, forKey: "wsMode"); rebuild() } }
    var wsKey: String { "\(serverText)|\(workspace)" }
    var workspace: String {
        if wsMode == .shared { return "default" }
        if let v = UserDefaults.standard.string(forKey: "wsDevice") { return v }
        let v = "n" + String(UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(9)).lowercased()
        UserDefaults.standard.set(v, forKey: "wsDevice")
        return v
    }
    var domain: Domain = .all
    var search = ""
    var hours = 48
    var lastError: String?
    var lastRefresh: Date?
    var loading = false

    init() {
        let s = UserDefaults.standard.string(forKey: "server") ?? AppModel.defaultServer
        serverText = s
        let mode = WSMode(rawValue: UserDefaults.standard.string(forKey: "wsMode") ?? "") ?? .shared
        wsMode = mode
        api = APIClient(base: URL(string: s) ?? URL(string: AppModel.defaultServer)!, workspace: "default")
        api = APIClient(base: api.base, workspace: workspace)
    }

    private func rebuild() {
        api = APIClient(base: api.base, workspace: workspace)
        emo.run = nil; emo.focus = nil; emo.entities = []
    }

    func applyServer() {
        var s = serverText.trimmingCharacters(in: .whitespacesAndNewlines)
        if !s.hasSuffix("/") { s += "/" }
        guard let u = URL(string: s), u.scheme == "https" || u.scheme == "http" else { lastError = APIClient.APIError.badURL.localizedDescription; return }
        serverText = s
        api = APIClient(base: u, workspace: workspace)
        Task { await refresh() }
    }

    func refresh() async {
        loading = true; defer { loading = false }
        do {
            me = try await api.get("api/me", as: MeResponse.self)
            async let st: StatusResponse = api.get("api/status")
            async let it: ItemsResponse = api.get("api/items", query: [
                "domain": domain == .all ? nil : domain.rawValue,
                "q": search.isEmpty ? nil : search,
                "hours": String(hours), "limit": "300"])
            let (s1, i1) = try await (st, it)
            status = s1; items = i1.items
            await refreshLayers()
            needsSignIn = false; lastError = nil; lastRefresh = .now
        } catch APIClient.APIError.signInRequired {
            needsSignIn = true
        } catch is CancellationError {
        } catch let e as URLError where e.code == .cancelled {
        } catch {
            lastError = error.localizedDescription
        }
    }

    /// Map content: placed news items (7 days, as the web map) and the enabled layers.
    func refreshLayers() async {
        struct Placed: Decodable, Sendable { var points: [Item] }
        if let p = try? await api.get("api/layers/items", query: ["hours": "168"], as: Placed.self) { mapItems = p.points }
        await layers.refresh(api: api, items: mapItems)
    }

    func signIn(_ user: String, _ pw: String) async -> String? {
        do { try await api.signIn(username: user, password: pw); needsSignIn = false; await refresh(); return nil }
        catch { return error.localizedDescription }
    }

    func signOut() async { await api.signOut(); me = nil; await refresh() }

    func loop() async {
        while !Task.isCancelled {
            await refresh()
            try? await Task.sleep(for: .seconds(60))
        }
    }
}
