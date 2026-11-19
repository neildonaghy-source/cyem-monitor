import Foundation
import Observation

/// The server the app shows. The interface itself is the CyEM web app (as the September apps were), so everything the
/// web client has (APP-6 symbols, map layers, EMO dock, spectrum, links, briefs, Ask) is here unchanged.
@MainActor @Observable
final class AppModel {
    static let defaultServer = "https://nucbox-evo-x2.tail013324.ts.net/"

    var serverText: String { didSet { UserDefaults.standard.set(serverText, forKey: "server") } }
    /// Bumped to make the web view load the server again (Home, a new server).
    var homeTick = 0

    init() {
        serverText = UserDefaults.standard.string(forKey: "server") ?? AppModel.defaultServer
    }

    var serverURL: URL { URL(string: serverText) ?? URL(string: AppModel.defaultServer)! }

    /// Accepts the text in Settings if it is an http(s) URL; returns an error to show otherwise.
    func applyServer(_ text: String) -> String? {
        var s = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if !s.hasSuffix("/") { s += "/" }
        guard let u = URL(string: s), u.scheme == "https" || u.scheme == "http", u.host != nil else { return "Not a valid server address." }
        serverText = s
        homeTick += 1
        return nil
    }
}
