import Foundation
import Network
import Observation
import TailscaleKit

/// Built-in Tailscale (as the September apps had): the app joins the tailnet as its own node ("cyem-mac" or
/// "cyem-iphone") through TailscaleKit, so it reaches the CyEM server without the Tailscale app. First use: the node asks
/// for a Tailscale sign-in in the browser (no auth key is stored in the app). The web view then goes through the node's
/// local SOCKS5 proxy. Node state lives in Application Support/tailscale.
@MainActor @Observable
final class Tailnet {
    enum Mode: String { case builtIn, system }

    var mode: Mode { didSet { UserDefaults.standard.set(mode.rawValue, forKey: "tailnetMode"); restart() } }
    private(set) var state = "Stopped"                        // Tailscale BackendState
    private(set) var authURL: URL?
    private(set) var ip: String?
    private(set) var tailnetName: String?
    private(set) var proxy: ProxyConfiguration?
    private(set) var generation = 0                           // bumps when the web view must be rebuilt (proxy changed)
    private(set) var error: String?

    var ready: Bool { mode == .system || proxy != nil }

    private var node: TailscaleNode?
    private var poll: Task<Void, Never>?

    #if os(macOS)
    static let hostName = "cyem-mac"
    #else
    static let hostName = "cyem-iphone"
    #endif

    init() {
        mode = Mode(rawValue: UserDefaults.standard.string(forKey: "tailnetMode") ?? "") ?? .builtIn
    }

    func start() {
        guard mode == .builtIn, node == nil else { return }
        error = nil
        do {
            let dir = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
                .appending(path: "tailscale", directoryHint: .isDirectory)
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            let cfg = Configuration(hostName: Tailnet.hostName, path: dir.path(percentEncoded: false), authKey: nil,
                                    controlURL: kDefaultControlURL, ephemeral: false)
            let n = try TailscaleNode(config: cfg, logger: QuietLog())
            node = n
            state = "Starting"
            Task.detached { do { try await n.up() } catch { await MainActor.run { self.error = "\(error)" } } }  // returns once signed in
            poll = Task { [weak self] in await self?.watch(n) }
        } catch {
            self.error = "Tailscale did not start: \(error)"
        }
    }

    /// Polls the node's status (in memory, no network) until it runs, then keeps an eye on it.
    private func watch(_ n: TailscaleNode) async {
        while !Task.isCancelled {
            if let data = try? await n.statusJSON(), let s = try? JSONDecoder().decode(Status.self, from: data) {
                state = s.BackendState
                authURL = s.AuthURL.flatMap { $0.isEmpty ? nil : URL(string: $0) }
                ip = s.SelfStatus?.TailscaleIPs?.first { !$0.contains(":") } ?? s.TailscaleIPs?.first
                tailnetName = s.CurrentTailnet?.Name
                if s.BackendState == "Running", proxy == nil { await makeProxy(n) }
                if s.BackendState != "Running", proxy != nil { proxy = nil; generation += 1 }
            }
            try? await Task.sleep(for: .seconds(proxy == nil ? 1 : 10))
        }
    }

    private func makeProxy(_ n: TailscaleNode) async {
        do {
            let lb = try await n.loopback()
            guard let ip = lb.ip, let port = lb.port, let p = NWEndpoint.Port(rawValue: UInt16(port)) else { throw TailscaleError.invalidProxyAddress }
            let pc = ProxyConfiguration(socksv5Proxy: .hostPort(host: NWEndpoint.Host(ip), port: p))
            pc.applyCredential(username: "tsnet", password: lb.proxyCredential)
            proxy = pc
            generation += 1
        } catch {
            self.error = "Tailscale proxy: \(error)"
        }
    }

    /// Re-reads the setting: stops the node for "system", starts it for "built in".
    func restart() {
        poll?.cancel(); poll = nil
        let old = node; node = nil
        proxy = nil; authURL = nil; ip = nil; state = "Stopped"
        generation += 1
        if let old { Task.detached { try? await old.close() } }
        start()
    }

    /// Signs this node out of the tailnet (it will ask for a sign-in again).
    func signOut() async {
        guard let n = node else { return }
        let api = LocalAPIClient(localNode: n, logger: QuietLog())
        try? await api.resetAuth()
        restart()
    }

    // The parts of ipnstate.Status the app shows.
    private struct Status: Decodable {
        var BackendState: String
        var AuthURL: String?
        var TailscaleIPs: [String]?
        var SelfStatus: Peer?
        var CurrentTailnet: TailnetInfo?
        enum CodingKeys: String, CodingKey { case BackendState, AuthURL, TailscaleIPs, CurrentTailnet; case SelfStatus = "Self" }
        struct Peer: Decodable { var TailscaleIPs: [String]? }
        struct TailnetInfo: Decodable { var Name: String? }
    }
}

/// Tailscale's own logs go nowhere (they are verbose); the app shows state and errors instead.
struct QuietLog: LogSink {
    var logFileHandle: Int32? = nil
    func log(_ message: String) {}
}
