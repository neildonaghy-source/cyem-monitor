import SwiftUI
import WebKit
#if os(macOS)
import AppKit
#else
import UIKit
#endif

/// State and commands for the one web view: loading, progress, errors, downloads.
@MainActor @Observable
final class WebController {
    weak var view: WKWebView?
    var loading = false
    var progress: Double = 0
    var loadError: String?
    var shareFile: SharedFile?                  // iOS: a finished download waiting for the share sheet

    struct SharedFile: Identifiable { let url: URL; var id: String { url.path } }

    func reload() { loadError = nil; view?.reload() }
    func back() { view?.goBack() }
    func forward() { view?.goForward() }
}

#if os(macOS)
typealias Representable = NSViewRepresentable
#else
typealias Representable = UIViewRepresentable
#endif

struct CyEMWebView: Representable {
    let url: URL
    let homeTick: Int
    let controller: WebController

    func makeCoordinator() -> Coordinator { Coordinator(controller: controller) }

    private func make(_ ctx: Context) -> WKWebView {
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .default()                         // cookies (internet log-in) and localStorage persist
        cfg.preferences.javaScriptCanOpenWindowsAutomatically = true
        cfg.applicationNameForUserAgent = "CyEMApp/\(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0")"
        #if os(iOS)
        cfg.allowsInlineMediaPlayback = true
        cfg.dataDetectorTypes = []
        #endif
        let wv = WKWebView(frame: .zero, configuration: cfg)
        wv.navigationDelegate = ctx.coordinator
        wv.uiDelegate = ctx.coordinator
        wv.allowsBackForwardNavigationGestures = true
        wv.isInspectable = true                                   // Safari > Develop for debugging
        #if os(macOS)
        wv.setValue(false, forKey: "drawsBackground")             // dark background before the page paints
        #else
        wv.isOpaque = false
        wv.backgroundColor = .clear
        wv.scrollView.backgroundColor = .clear
        wv.scrollView.contentInsetAdjustmentBehavior = .never
        wv.scrollView.bounces = false
        #endif
        ctx.coordinator.observe(wv)
        controller.view = wv
        wv.load(URLRequest(url: url))
        ctx.coordinator.loaded = (url, homeTick)
        return wv
    }

    private func update(_ wv: WKWebView, _ ctx: Context) {
        if ctx.coordinator.loaded.0 != url || ctx.coordinator.loaded.1 != homeTick {
            ctx.coordinator.loaded = (url, homeTick)
            controller.loadError = nil
            wv.load(URLRequest(url: url))
        }
    }

    #if os(macOS)
    func makeNSView(context: Context) -> WKWebView { make(context) }
    func updateNSView(_ nsView: WKWebView, context: Context) { update(nsView, context) }
    #else
    func makeUIView(context: Context) -> WKWebView { make(context) }
    func updateUIView(_ uiView: WKWebView, context: Context) { update(uiView, context) }
    #endif

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
        let controller: WebController
        var loaded: (URL?, Int) = (nil, -1)
        private var observers: [NSKeyValueObservation] = []
        private var destinations: [ObjectIdentifier: URL] = [:]

        init(controller: WebController) { self.controller = controller }

        func observe(_ wv: WKWebView) {
            observers = [
                wv.observe(\.estimatedProgress, options: [.new]) { [weak self] v, _ in Task { @MainActor in self?.controller.progress = v.estimatedProgress } },
                wv.observe(\.isLoading, options: [.new]) { [weak self] v, _ in Task { @MainActor in self?.controller.loading = v.isLoading } },
            ]
        }

        // ---- navigation: same-site pages stay in the app; other sites open in the browser; files download
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction) async -> WKNavigationActionPolicy {
            guard let u = action.request.url else { return .cancel }
            if action.shouldPerformDownload { return .download }
            if u.scheme == "data" || u.scheme == "blob" || u.scheme == "about" { return .allow }
            let home = loaded.0?.host
            if action.navigationType == .linkActivated || action.targetFrame == nil, u.host != home, u.scheme == "http" || u.scheme == "https" {
                openExternally(u); return .cancel
            }
            if u.scheme == "mailto" || u.scheme == "tel" { openExternally(u); return .cancel }
            return .allow
        }

        func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse) async -> WKNavigationResponsePolicy {
            if let http = response.response as? HTTPURLResponse,
               (http.value(forHTTPHeaderField: "Content-Disposition") ?? "").lowercased().contains("attachment") { return .download }
            return response.canShowMIMEType ? .allow : .download
        }

        func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
        func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }

        func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String) async -> URL? {
            let name = suggestedFilename.isEmpty ? "cyem-download" : suggestedFilename
            #if os(macOS)
            let dir = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first ?? FileManager.default.temporaryDirectory
            #else
            let dir = FileManager.default.temporaryDirectory
            #endif
            var dest = dir.appending(path: name)
            var n = 1
            while FileManager.default.fileExists(atPath: dest.path) {
                let base = (name as NSString).deletingPathExtension, ext = (name as NSString).pathExtension
                dest = dir.appending(path: "\(base) \(n)\(ext.isEmpty ? "" : "." + ext)"); n += 1
            }
            destinations[ObjectIdentifier(download)] = dest
            return dest
        }

        func downloadDidFinish(_ download: WKDownload) {
            guard let dest = destinations.removeValue(forKey: ObjectIdentifier(download)) else { return }
            #if os(macOS)
            NSWorkspace.shared.activateFileViewerSelecting([dest])
            #else
            controller.shareFile = .init(url: dest)
            #endif
        }

        func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
            destinations.removeValue(forKey: ObjectIdentifier(download))
            controller.loadError = nil
        }

        // ---- load errors: a native page instead of a blank one
        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { failed(error) }
        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { failed(error) }
        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { controller.loadError = nil }

        private func failed(_ error: Error) {
            let e = error as NSError
            if e.domain == NSURLErrorDomain && e.code == NSURLErrorCancelled { return }
            if e.domain == "WebKitErrorDomain" && e.code == 102 { return }          // frame load interrupted (a download)
            controller.loadError = e.localizedDescription
        }

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { webView.reload() }

        // ---- window.open: same site in place, others in the browser
        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction,
                     windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let u = action.request.url {
                if u.host == loaded.0?.host { webView.load(action.request) } else { openExternally(u) }
            }
            return nil
        }

        // ---- JavaScript dialogs
        func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo) async {
            _ = await ask(message, buttons: ["OK"])
        }
        func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo) async -> Bool {
            await ask(message, buttons: ["OK", "Cancel"]) == 0
        }

        #if os(macOS)
        func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo) async -> [URL]? {
            let p = NSOpenPanel()
            p.allowsMultipleSelection = parameters.allowsMultipleSelection
            p.canChooseDirectories = parameters.allowsDirectories
            p.canChooseFiles = true
            return await p.begin() == .OK ? p.urls : nil
        }
        #endif

        private func ask(_ message: String, buttons: [String]) async -> Int {
            #if os(macOS)
            let a = NSAlert(); a.messageText = "CyEM"; a.informativeText = message
            buttons.forEach { a.addButton(withTitle: $0) }
            return a.runModal().rawValue - NSApplication.ModalResponse.alertFirstButtonReturn.rawValue
            #else
            return await withCheckedContinuation { cont in
                let a = UIAlertController(title: "CyEM", message: message, preferredStyle: .alert)
                for (i, b) in buttons.enumerated() { a.addAction(UIAlertAction(title: b, style: i == 0 ? .default : .cancel) { _ in cont.resume(returning: i) }) }
                guard let root = UIApplication.shared.connectedScenes.compactMap({ ($0 as? UIWindowScene)?.keyWindow }).first?.rootViewController else { cont.resume(returning: 0); return }
                var top = root; while let p = top.presentedViewController { top = p }
                top.present(a, animated: true)
            }
            #endif
        }

        private func openExternally(_ u: URL) {
            #if os(macOS)
            NSWorkspace.shared.open(u)
            #else
            UIApplication.shared.open(u)
            #endif
        }
    }
}

#if os(iOS)
struct ShareSheet: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> UIActivityViewController { UIActivityViewController(activityItems: [url], applicationActivities: nil) }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
#endif
