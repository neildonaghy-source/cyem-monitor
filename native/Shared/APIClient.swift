import Foundation

/// Talks to one CyEM server. On the tailnet no log-in is needed; through Tailscale Funnel (the internet) the server
/// answers 401 until the app has signed in with POST /login, after which a session cookie (30 days) rides along.
final class APIClient: Sendable {
    let base: URL
    private let session: URLSession

    enum APIError: LocalizedError {
        case signInRequired, badStatus(Int, String), badURL, wrongCredentials, tooManyAttempts
        var errorDescription: String? {
            switch self {
            case .signInRequired: "Sign in required (internet access)."
            case .badStatus(let c, let m): "Server answered \(c)\(m.isEmpty ? "" : ": \(m)")"
            case .badURL: "The server address is not a valid URL."
            case .wrongCredentials: "Wrong username or password, or the account is locked for 15 minutes."
            case .tooManyAttempts: "Too many attempts from this address; try again in 15 minutes."
            }
        }
    }

    init(base: URL) {
        self.base = base
        let cfg = URLSessionConfiguration.default
        cfg.httpCookieStorage = .shared
        cfg.httpShouldSetCookies = true
        cfg.timeoutIntervalForRequest = 30
        cfg.waitsForConnectivity = false
        session = URLSession(configuration: cfg)
    }

    func get<T: Decodable & Sendable>(_ path: String, query: [String: String?] = [:], as type: T.Type = T.self) async throws -> T {
        guard var comps = URLComponents(url: base.appending(path: path), resolvingAgainstBaseURL: false) else { throw APIError.badURL }
        let q = query.compactMap { k, v in v.map { URLQueryItem(name: k, value: $0) } }
        if !q.isEmpty { comps.queryItems = q }
        guard let url = comps.url else { throw APIError.badURL }
        var req = URLRequest(url: url)
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, resp) = try await session.data(for: req)
        try check(resp, data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    func signIn(username: String, password: String) async throws {
        var req = URLRequest(url: base.appending(path: "login"))
        req.httpMethod = "POST"
        req.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        let enc = { (v: String) in v.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? "" }
        req.httpBody = "username=\(enc(username))&password=\(enc(password))&next=\(enc("/api/me"))".data(using: .utf8)
        let (data, resp) = try await session.data(for: req)            // follows the 302 to /api/me
        guard let http = resp as? HTTPURLResponse else { return }
        if http.statusCode == 401 { throw APIError.wrongCredentials }
        if http.statusCode == 429 { throw APIError.tooManyAttempts }
        try check(resp, data)
    }

    func signOut() async {
        var req = URLRequest(url: base.appending(path: "logout"))
        req.httpMethod = "POST"
        _ = try? await session.data(for: req)
        for c in HTTPCookieStorage.shared.cookies(for: base) ?? [] { HTTPCookieStorage.shared.deleteCookie(c) }
    }

    private func check(_ resp: URLResponse, _ data: Data) throws {
        guard let http = resp as? HTTPURLResponse else { return }
        if http.statusCode == 401 || http.url?.path == "/login" { throw APIError.signInRequired }
        guard (200..<300).contains(http.statusCode) else {
            let msg = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]).flatMap { ($0["detail"] ?? $0["error"]) as? String } ?? ""
            throw APIError.badStatus(http.statusCode, msg)
        }
    }
}
