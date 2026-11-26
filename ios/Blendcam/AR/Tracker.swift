import ARKit
import Foundation
import simd

/// Runs ARKit world tracking and sends one pose packet per AR frame (~60 Hz) through the Link.
final class Tracker: NSObject, ObservableObject, ARSessionDelegate {
    let session = ARSession()

    @Published private(set) var tracking = "notAvailable"
    @Published private(set) var reason = ""
    @Published private(set) var angles = SIMD3<Float>(repeating: 0)
    @Published private(set) var position = SIMD3<Float>(repeating: 0)
    @Published private(set) var running = false

    weak var link: Link?
    var joy = CGVector.zero
    var lift: CGFloat = 0
    var focal: Float = 35
    private(set) var lastTimestamp: TimeInterval = 0
    private var seq = 0
    private var lastUI: TimeInterval = 0

    override init() {
        super.init()
        session.delegate = self
    }

    func start() {
        guard ARWorldTrackingConfiguration.isSupported else {
            reason = "Цей телефон не підтримує ARKit"
            return
        }
        let cfg = ARWorldTrackingConfiguration()
        cfg.worldAlignment = .gravity
        cfg.isAutoFocusEnabled = true
        if let fmt = ARWorldTrackingConfiguration.supportedVideoFormats.first(where: { $0.framesPerSecond == 60 }) {
            cfg.videoFormat = fmt
        }
        seq = 0
        session.run(cfg, options: [.resetTracking, .removeExistingAnchors])
        running = true
    }

    func stop() {
        session.pause()
        running = false
        tracking = "notAvailable"
    }

    // MARK: - ARSessionDelegate (called on the main queue)

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        let cam = frame.camera
        let t = cam.transform
        var trk = "normal"
        var why = ""
        switch cam.trackingState {
        case .normal:
            trk = "normal"
        case .notAvailable:
            trk = "notAvailable"
            why = "Немає відстеження"
        case .limited(let r):
            trk = "limited"
            switch r {
            case .initializing:
                why = "Запуск відстеження…"
            case .excessiveMotion:
                why = "Занадто швидко — повільніше"
            case .insufficientFeatures:
                why = "Мало деталей — поводь телефоном"
            case .relocalizing:
                why = "Відновлення відстеження…"
            @unknown default:
                why = "Відстеження обмежене"
            }
        }
        lastTimestamp = frame.timestamp

        if let link, !link.token.isEmpty {
            let packet = PosePacket(seq: seq, t: frame.timestamp, token: link.token,
                                    m: PosePacket.matrix(t), trk: trk,
                                    joy: [Float(joy.dx), Float(joy.dy)], lift: Float(lift), focal: focal)
            seq += 1
            link.sendPose(packet)
        }

        if frame.timestamp - lastUI > 0.1 {
            lastUI = frame.timestamp
            if tracking != trk { tracking = trk }
            if reason != why { reason = why }
            let c0 = SIMD3<Float>(t.columns.0.x, t.columns.0.y, t.columns.0.z)
            let c1 = SIMD3<Float>(t.columns.1.x, t.columns.1.y, t.columns.1.z)
            let c2 = SIMD3<Float>(t.columns.2.x, t.columns.2.y, t.columns.2.z)
            angles = PoseMath.angles(column0: c0, column1: c1, column2: c2)
            position = SIMD3<Float>(t.columns.3.x, t.columns.3.y, t.columns.3.z)
        }
    }

    func sessionShouldAttemptRelocalization(_ session: ARSession) -> Bool {
        false
    }

    func session(_ session: ARSession, didFailWithError error: Error) {
        reason = "Помилка ARKit: \(error.localizedDescription)"
        running = false
    }

    func sessionWasInterrupted(_ session: ARSession) {
        reason = "Відстеження перервано"
    }

    func sessionInterruptionEnded(_ session: ARSession) {
        start()
    }
}
