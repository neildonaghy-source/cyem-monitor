import Foundation
import Network
import Observation
import UserNotifications
import WebKit
import WidgetKit
#if os(iOS)
import BackgroundTasks
import UIKit
#else
import AppKit
#endif

/// Local notifications for high-severity items (severity 4 and 5) and finished briefs. No push service: the app asks the
/// server itself, every 5 minutes while it runs (on the Mac also with its windows closed) and, on the iPhone, when iOS
/// grants a background refresh (at iOS's discretion, often hours apart). It polls GET /api/items?min_severity=4 and
/// GET /api/briefs?limit=1, through the built-in Tailscale proxy when that is in use, with the web view's cookies so the
/// internet route (CyEM log-in) works too. What to say is decided in NotifyPlan (pure, tested).
@MainActor @Observable
final class Notifier {
    static let refreshTask = "com.neildonaghy.cyem.refresh"
    static let interval: TimeInterval = 300

    var itemsOn: Bool { didSet { UserDefaults.standard.set(itemsOn, forKey: "notifyItems"); if itemsOn { askPermission() } } }
    var briefsOn: Bool { didSet { UserDefaults.standard.set(briefsOn, forKey: "notifyBriefs"); if briefsOn { askPermission() } } }
    private(set) var permitted: Bool?
    private(set) var lastCheck: Date?
    private(set) var lastError: String?

    /// Set by the root view: where to ask and how.
    var server: URL?
    var proxy: ProxyConfiguration?
    var ready = false
    /// Set by the root view: show a page of the CyEM server in the web view (a tapped brief notification).
    var openInApp: ((URL) -> Void)?

    private var loop: Task<Void, Never>?
    private var checking = false
    private let delegate = Delegate()

    init() {
        let d = UserDefaults.standard
        itemsOn = d.object(forKey: "notifyItems") as? Bool ?? true
        briefsOn = d.object(forKey: "notifyBriefs") as? Bool ?? true
        delegate.owner = self
        UNUserNotificationCenter.current().delegate = delegate
    }

    func start() {
        guard loop == nil else { return }
        if itemsOn || briefsOn { askPermission() }
        loop = Task { [weak self] in
            try? await Task.sleep(for: .seconds(20))                 // let the tailnet node and the page come up first
            while !Task.isCancelled {
                await self?.check()
                try? await Task.sleep(for: .seconds(Notifier.interval))
            }
        }
        scheduleRefresh()
    }

    func askPermission() {
        Task {
            let c = UNUserNotificationCenter.current()
            let ok = (try? await c.requestAuthorization(options: [.alert, .sound, .badge])) ?? false
            permitted = ok
        }
    }

    /// One check. Safe to call often; overlapping calls are dropped. Also refreshes the widget snapshot
    /// (GET /api/status), whether or not notifications are on.
    func check() async {
        guard ready, let server, !checking else { return }
        checking = true; defer { checking = false }
        await copyWebCookies(for: server)
        let api = APIClient(base: server, proxy: proxy)
        var err: String?
        do {
            let st = try await api.get("api/status", as: StatusResponse.self)
            if WidgetSnapshot.Store.save(.make(status: st, server: server.absoluteString, now: Date())) {
                WidgetCenter.shared.reloadTimelines(ofKind: WidgetSnapshot.Store.kind)
            }
        } catch { err = error.localizedDescription }
        if itemsOn || briefsOn {
            var items: [Item]?, brief: BriefRow?
            do { items = try await api.get("api/items", query: ["min_severity": "4", "hours": "24", "limit": "200"], as: ItemsResponse.self).items }
            catch { err = err ?? error.localizedDescription }
            do { brief = try await api.get("api/briefs", query: ["limit": "1"], as: BriefsResponse.self).briefs.first }
            catch { err = err ?? error.localizedDescription }
            let mem = loadMemory()
            let plan = NotifyPlan.plan(server: server.absoluteString, items: items, latestBrief: brief, memory: mem,
                                       itemsOn: itemsOn, briefsOn: briefsOn)
            saveMemory(plan.memory)
            for n in plan.notes { await post(n) }
        }
        lastCheck = Date()
        lastError = err
    }

    private func post(_ n: NotifyPlan.Note) async {
        let c = UNMutableNotificationContent()
        c.title = n.title
        c.body = n.body
        c.sound = .default
        c.threadIdentifier = n.thread
        if let l = n.link { c.userInfo = ["link": l] }
        try? await UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: n.id, content: c, trigger: nil))
    }

    /// A tapped notification: an item opens its source page in the browser, a brief opens CyEM (the brief panel).
    fileprivate func tapped(link: String?) {
        if let l = link, let u = URL(string: l), u.host != server?.host {
            #if os(macOS)
            NSWorkspace.shared.open(u)
            #else
            UIApplication.shared.open(u)
            #endif
        } else if let s = server {
            openInApp?(link.flatMap(URL.init(string:)) ?? s)
        }
    }

    /// The internet route needs the CyEM session cookie, which lives in the web view's store.
    private func copyWebCookies(for server: URL) async {
        let all = await WKWebsiteDataStore.default().httpCookieStore.allCookies()
        for c in all where server.host?.hasSuffix(c.domain.trimmingCharacters(in: CharacterSet(charactersIn: "."))) == true {
            HTTPCookieStorage.shared.setCookie(c)
        }
    }

    private func loadMemory() -> NotifyPlan.Memory {
        guard let d = UserDefaults.standard.data(forKey: "notifyMemory"),
              let m = try? JSONDecoder().decode(NotifyPlan.Memory.self, from: d) else { return .init() }
        return m
    }
    private func saveMemory(_ m: NotifyPlan.Memory) {
        if let d = try? JSONEncoder().encode(m) { UserDefaults.standard.set(d, forKey: "notifyMemory") }
    }

    /// iPhone: ask iOS for the next background refresh (it decides when; nothing runs if the app is force-quit).
    func scheduleRefresh() {
        #if os(iOS)
        let r = BGAppRefreshTaskRequest(identifier: Notifier.refreshTask)
        r.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        try? BGTaskScheduler.shared.submit(r)
        #endif
    }

    /// iPhone background refresh: give the built-in Tailscale node a few seconds to reconnect, then check once.
    func backgroundCheck() async {
        scheduleRefresh()
        for _ in 0..<10 where !ready { try? await Task.sleep(for: .seconds(1)) }
        await check()
    }

    /// Banners also while the app is in front; taps come back to the owner on the main actor.
    final class Delegate: NSObject, UNUserNotificationCenterDelegate, @unchecked Sendable {
        weak var owner: Notifier?
        func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
            [.banner, .list, .sound]
        }
        func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
            let link = response.notification.request.content.userInfo["link"] as? String
            await MainActor.run { self.owner?.tapped(link: link) }
        }
    }
}
