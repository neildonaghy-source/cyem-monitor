#if os(iOS)
import ARKit
import CoreLocation
import Network
import SceneKit
import SwiftUI

/// AR view (iPhone, 0.6.0; the September apps had one, their source was lost): the camera with the EMO scenario's
/// units drawn where they are, by bearing and elevation from where you stand. ARKit tracks the phone with its world
/// aligned to gravity and true north at the start; the phone's GPS gives your position. Positions are the last run's
/// (GET /api/emo/ar, the web app's workspace), with what the run found under each name, and the last planned corridor
/// as a line. Accuracy is the compass's (a few degrees, worse near steel and vehicles) and the GPS's; notional data.
@MainActor @Observable
final class ARModel: NSObject, CLLocationManagerDelegate {
    var scene: ARScene?
    var error: String?
    var location: CLLocation?
    var sides: Set<String> = ["blue", "red", "grey"]
    var rangeKm: Double = 25
    var marks: [Mark] = []                      // projected each frame
    var legs: [[CGPoint]] = []                  // corridor polylines, projected
    var legColours: [Color] = []
    var tracking = "starting"
    var origin: CLLocation?                     // where the AR session started: the world's (0, 0, 0)

    struct Mark: Identifiable { let id: String; let at: CGPoint; let entity: AREntity; let dist: Double; let bearing: Double }

    private let lm = CLLocationManager()

    override init() {
        super.init()
        lm.delegate = self
        lm.desiredAccuracy = kCLLocationAccuracyBest
    }

    func start() {
        lm.requestWhenInUseAuthorization()
        lm.startUpdatingLocation()
    }
    func stop() { lm.stopUpdatingLocation() }

    func load(server: URL, workspace: String, proxy: ProxyConfiguration?) async {
        do {
            scene = try await APIClient(base: server, workspace: workspace, proxy: proxy).get("api/emo/ar", as: ARScene.self)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    // CLLocationManager calls back on the thread that created it: the main thread here.
    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locs: [CLLocation]) {
        guard let l = locs.last else { return }
        MainActor.assumeIsolated {
            self.location = l
            if self.origin == nil || (self.origin!.horizontalAccuracy > 30 && l.horizontalAccuracy < self.origin!.horizontalAccuracy) {
                self.origin = l                         // the first fix, or a much better one while still poor
            }
        }
    }
    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        let msg = "Location: \(error.localizedDescription)"
        MainActor.assumeIsolated { self.error = msg }
    }

    /// Project every visible entity and the corridor with the current camera.
    func project(frame: ARFrame, viewport: CGSize, orientation: UIInterfaceOrientation) {
        switch frame.camera.trackingState {
        case .normal: tracking = "tracking"
        case .notAvailable: tracking = "not available"
        case .limited(let r): tracking = r == .initializing ? "starting" : "limited"
        }
        guard let scene, let o = origin else { marks = []; legs = []; return }
        let here = location ?? o
        let cam = frame.camera
        let inv = simd_inverse(cam.transform)
        func screen(_ lat: Double, _ lon: Double, _ h: Double) -> CGPoint? {
            let v = ARGeo.enu(fromLat: o.coordinate.latitude, lon: o.coordinate.longitude, toLat: lat, lon: lon, height: h)
            let w = ARGeo.world(v)
            let p = simd_float3(Float(w.x), Float(w.y), Float(w.z))
            let c = inv * simd_float4(p, 1)
            guard c.z < 0 else { return nil }                       // behind the camera
            let s = cam.projectPoint(p, orientation: orientation, viewportSize: viewport)
            guard s.x > -40, s.y > -40, s.x < viewport.width + 40, s.y < viewport.height + 40 else { return nil }
            return s
        }
        let vis = ARGeo.visible(scene.entities, sides: sides, fromLat: here.coordinate.latitude, lon: here.coordinate.longitude, rangeKm: rangeKm)
        marks = vis.compactMap { e in
            guard let s = screen(e.lat, e.lon, e.h_agl) else { return nil }
            let v = ARGeo.enu(fromLat: here.coordinate.latitude, lon: here.coordinate.longitude, toLat: e.lat, lon: e.lon, height: e.h_agl)
            return Mark(id: e.id, at: s, entity: e, dist: ARGeo.distance(v), bearing: ARGeo.bearing(v))
        }.sorted { $0.dist > $1.dist }                                // near ones drawn last, on top
        if let c = scene.corridor {
            legs = c.legs.map { lg in lg.path.compactMap { p in p.count == 2 ? screen(p[0], p[1], 2) : nil } }
            legColours = c.legs.map { $0.emcon == "transmit" ? Color(red: 0.95, green: 0.70, blue: 0.24) : Color(red: 0.27, green: 0.83, blue: 0.54) }
        } else { legs = []; legColours = [] }
    }
}

/// The camera and ARKit session; hands each frame to the model to project.
struct ARCamera: UIViewRepresentable {
    let model: ARModel

    func makeUIView(context: Context) -> ARSCNView {
        let v = ARSCNView(frame: .zero)
        v.automaticallyUpdatesLighting = false
        v.session.delegate = context.coordinator
        context.coordinator.view = v
        let cfg = ARWorldTrackingConfiguration()
        cfg.worldAlignment = .gravityAndHeading
        v.session.run(cfg)
        return v
    }
    func updateUIView(_ v: ARSCNView, context: Context) {}
    static func dismantleUIView(_ v: ARSCNView, coordinator: Coordinator) { v.session.pause() }
    func makeCoordinator() -> Coordinator { Coordinator(model: model) }

    @MainActor final class Coordinator: NSObject, ARSessionDelegate {
        let model: ARModel
        weak var view: ARSCNView?
        private var last: TimeInterval = 0
        init(model: ARModel) { self.model = model }
        // The session's delegate queue is the main queue (none set), so this runs on the main thread.
        nonisolated func session(_ session: ARSession, didUpdate frame: ARFrame) {
            MainActor.assumeIsolated {
                guard frame.timestamp - last > 1.0 / 20, let v = view else { return }   // 20 a second is plenty for labels
                last = frame.timestamp
                let o = v.window?.windowScene?.interfaceOrientation ?? .portrait
                model.project(frame: frame, viewport: v.bounds.size, orientation: o)
            }
        }
    }
}

struct ARScreen: View {
    let server: URL
    let workspace: String
    let proxy: ProxyConfiguration?
    @Environment(\.dismiss) private var dismiss
    @State private var model = ARModel()

    private static let sideColour: [String: Color] = ["blue": Color(red: 0.24, green: 0.55, blue: 1.0),
                                                      "red": Color(red: 1.0, green: 0.36, blue: 0.36),
                                                      "grey": Color(red: 0.67, green: 0.71, blue: 0.75)]

    var body: some View {
        ZStack {
            ARCamera(model: model).ignoresSafeArea()
            Canvas { ctx, _ in
                for (i, pts) in model.legs.enumerated() where pts.count > 1 {
                    var p = Path(); p.addLines(pts)
                    ctx.stroke(p, with: .color(model.legColours[safe: i] ?? .white), style: StrokeStyle(lineWidth: 4, lineCap: .round, dash: [10, 6]))
                }
            }
            .ignoresSafeArea().allowsHitTesting(false)
            ForEach(model.marks) { m in
                marker(m).position(m.at)
            }
            .ignoresSafeArea()
            VStack(spacing: 8) {
                header
                Spacer()
                footer
            }
            .padding(12)
        }
        .background(Color.black)
        .task {
            model.start()
            await model.load(server: server, workspace: workspace, proxy: proxy)
        }
        .onDisappear { model.stop() }
    }

    private func marker(_ m: ARModel.Mark) -> some View {
        let e = m.entity
        let col = ARScreen.sideColour[e.side] ?? .white
        let near = m.dist < 2000
        return VStack(spacing: 2) {
            Circle().fill(col).frame(width: near ? 16 : 11, height: near ? 16 : 11)
                .overlay(Circle().stroke(.white, lineWidth: e.target_quality ? 3 : 1))
                .opacity(e.on_air ? 1 : 0.45)
            VStack(spacing: 0) {
                Text(e.name).font(.system(size: near ? 13 : 11, weight: .semibold))
                Text("\(ARGeo.distanceText(m.dist)) \(ARGeo.compass(m.bearing))").font(.system(size: 10).monospacedDigit())
                let f = ARGeo.findings(e)
                if !f.isEmpty { Text(f).font(.system(size: 10)).foregroundStyle(e.target_quality || e.status == "denied" ? .orange : .secondary) }
            }
            .padding(.horizontal, 5).padding(.vertical, 2)
            .background(.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 5))
            .overlay(RoundedRectangle(cornerRadius: 5).stroke(col.opacity(0.8), lineWidth: 1))
        }
        .foregroundStyle(.white)
        .fixedSize()
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 2) {
                Text("EMO in AR").font(.headline)
                if let s = model.scene {
                    Text("\(s.ran ? "T+\(Int(s.t)) min, last run" : "T+0, not run yet") · \(model.marks.count) of \(s.entities.count) in view · \(workspace == "default" ? "shared" : "this device's") scenario")
                        .font(.caption)
                } else if model.error == nil {
                    Text("Loading the scenario…").font(.caption)
                }
                if let l = model.location {
                    Text("GPS ±\(Int(l.horizontalAccuracy)) m · AR \(model.tracking) · compass alignment, a few degrees").font(.caption2).foregroundStyle(.secondary)
                } else {
                    Text("Waiting for your position…").font(.caption2).foregroundStyle(.secondary)
                }
                if let e = model.error { Text(e).font(.caption).foregroundStyle(.orange) }
            }
            Spacer()
            Button { dismiss() } label: { Image(systemName: "xmark.circle.fill").font(.title) }
                .accessibilityLabel("Close")
        }
        .foregroundStyle(.white)
        .padding(10)
        .background(.black.opacity(0.55), in: RoundedRectangle(cornerRadius: 10))
    }

    private var footer: some View {
        VStack(spacing: 8) {
            HStack {
                ForEach(["blue", "red", "grey"], id: \.self) { s in
                    Button {
                        if model.sides.contains(s) { model.sides.remove(s) } else { model.sides.insert(s) }
                    } label: {
                        Text(s == "grey" ? "Civil" : s.capitalized).font(.caption.bold())
                            .padding(.horizontal, 10).padding(.vertical, 6)
                            .background((ARScreen.sideColour[s] ?? .white).opacity(model.sides.contains(s) ? 0.85 : 0.2), in: Capsule())
                    }
                }
                Spacer()
                Button { Task { await model.load(server: server, workspace: workspace, proxy: proxy) } } label: {
                    Image(systemName: "arrow.clockwise").font(.body.bold())
                }
                .accessibilityLabel("Reload the scenario")
            }
            HStack {
                Text("Range \(Int(model.rangeKm)) km").font(.caption.monospacedDigit()).frame(width: 90, alignment: .leading)
                Slider(value: Binding(get: { model.rangeKm }, set: { model.rangeKm = $0 }), in: 1...100, step: 1)
            }
            Text("Notional scenario. Markers sit by bearing and elevation from you; the dashed line is the last planned corridor (amber transmit, green silent). Recalibrate by closing and reopening if the picture drifts.")
                .font(.caption2).foregroundStyle(.secondary).multilineTextAlignment(.leading)
        }
        .foregroundStyle(.white)
        .padding(10)
        .background(.black.opacity(0.55), in: RoundedRectangle(cornerRadius: 10))
    }
}

private extension Array {
    subscript(safe i: Int) -> Element? { indices.contains(i) ? self[i] : nil }
}
#endif
