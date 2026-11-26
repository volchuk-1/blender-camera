import Foundation
import Network
import UIKit

/// Network link to Blender: UDP for poses, TCP for control messages and live frames.
/// All socket work happens on a private serial queue; published values change on the main thread.
final class Link: ObservableObject {
    @Published private(set) var connected = false
    @Published private(set) var state: BlenderState?
    @Published private(set) var toast: String?
    @Published private(set) var toastID = 0
    @Published private(set) var latestFrame: UIImage?
    @Published private(set) var lastFrameAt: Date?
    @Published private(set) var framesPerSecond = 0
    @Published private(set) var packetsPerSecond = 0
    @Published private(set) var target: ConnectURL?

    private let queue = DispatchQueue(label: "blendcam.link")
    private var tcp: NWConnection?
    private var udp: NWConnection?
    private var buffer = Data()
    private var pendingFrameLen: Int?
    private var generation = 0
    private var wanted = false
    private var sentThisSecond = 0
    private var framesThisSecond = 0
    private var counterTimer: Timer?
    private var decoding = false
    private var qTarget: ConnectURL?  // copy of `target` owned by `queue`

    private static let savedKey = "blendcam.target"

    init() {
        if let data = UserDefaults.standard.data(forKey: Link.savedKey),
           let saved = try? JSONDecoder().decode(ConnectURL.self, from: data) {
            target = saved
            qTarget = saved
        }
        counterTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self else { return }
            self.queue.async {
                let sent = self.sentThisSecond
                let frames = self.framesThisSecond
                self.sentThisSecond = 0
                self.framesThisSecond = 0
                DispatchQueue.main.async {
                    self.packetsPerSecond = sent
                    self.framesPerSecond = frames
                }
            }
        }
    }

    var token: String { target?.token ?? "" }

    // MARK: - connection

    func connect(_ url: ConnectURL) {
        if let data = try? JSONEncoder().encode(url) {
            UserDefaults.standard.set(data, forKey: Link.savedKey)
        }
        target = url
        queue.async {
            self.qTarget = url
            self.wanted = true
            self.open(url)
        }
    }

    /// Reconnect to the saved address (app start / back from background).
    func resume() {
        guard let url = target else { return }
        queue.async {
            self.wanted = true
            if self.tcp == nil { self.open(url) }
        }
    }

    func disconnect(forget: Bool = false) {
        if forget {
            UserDefaults.standard.removeObject(forKey: Link.savedKey)
            target = nil
        }
        queue.async {
            if forget { self.qTarget = nil }
            self.wanted = false
            self.close()
        }
    }

    private func open(_ url: ConnectURL) {
        close()
        generation += 1
        let gen = generation
        guard let port = NWEndpoint.Port(rawValue: url.port) else { return }
        let host = NWEndpoint.Host(url.host)

        let tcpOptions = NWProtocolTCP.Options()
        tcpOptions.noDelay = true
        tcpOptions.connectionTimeout = 4
        let params = NWParameters(tls: nil, tcp: tcpOptions)
        let t = NWConnection(host: host, port: port, using: params)
        t.stateUpdateHandler = { [weak self] st in
            guard let self, gen == self.generation else { return }
            switch st {
            case .ready:
                self.onReady(gen)
            case .failed, .waiting:
                self.lost(gen)
            case .cancelled:
                break
            default:
                break
            }
        }
        tcp = t
        t.start(queue: queue)

        let u = NWConnection(host: host, port: port, using: .udp)
        udp = u
        u.start(queue: queue)
    }

    private func close() {
        tcp?.stateUpdateHandler = nil
        tcp?.cancel()
        udp?.cancel()
        tcp = nil
        udp = nil
        buffer = Data()
        pendingFrameLen = nil
        DispatchQueue.main.async {
            if self.connected { self.connected = false }
        }
    }

    private func onReady(_ gen: Int) {
        guard let target = currentTarget() else { return }
        let device = UIDevice.current.name
        sendOnQueue(.hello(token: target.token, device: device.isEmpty ? "iPhone" : device))
        DispatchQueue.main.async { self.connected = true }
        receive(gen)
    }

    private func currentTarget() -> ConnectURL? {
        qTarget
    }

    private func lost(_ gen: Int) {
        guard gen == generation else { return }
        close()
        generation += 1
        let next = generation
        guard wanted else { return }
        queue.asyncAfter(deadline: .now() + 2.0) { [weak self] in
            guard let self, self.wanted, next == self.generation, self.tcp == nil,
                  let url = self.currentTarget() else { return }
            self.open(url)
        }
    }

    // MARK: - receiving

    private func receive(_ gen: Int) {
        tcp?.receive(minimumIncompleteLength: 1, maximumLength: 1 << 16) { [weak self] data, _, isComplete, error in
            guard let self, gen == self.generation else { return }
            if let data, !data.isEmpty {
                self.buffer.append(data)
                self.process()
            }
            if isComplete || error != nil {
                self.lost(gen)
                return
            }
            self.receive(gen)
        }
    }

    private func process() {
        while true {
            if let need = pendingFrameLen {
                guard buffer.count >= need else { return }
                let start = buffer.startIndex
                let jpeg = buffer.subdata(in: start..<(start + need))
                buffer = buffer.subdata(in: (start + need)..<buffer.endIndex)
                pendingFrameLen = nil
                framesThisSecond += 1
                showFrame(jpeg)
                continue
            }
            guard let nl = buffer.firstIndex(of: 0x0A) else {
                if buffer.count > 1 << 20 { buffer = Data() }
                return
            }
            let line = buffer.subdata(in: buffer.startIndex..<nl)
            buffer = buffer.subdata(in: (nl + 1)..<buffer.endIndex)
            guard let msg = decodeControl(line) else { continue }
            switch msg {
            case .frameHeader(let len, _):
                if len > 0 && len < 8 << 20 { pendingFrameLen = len }
            case .state(let s):
                DispatchQueue.main.async { self.state = s }
            case .toast(let text):
                DispatchQueue.main.async {
                    self.toast = text
                    self.toastID += 1
                }
            default:
                break
            }
        }
    }

    private func showFrame(_ jpeg: Data) {
        if decoding { return }  // still decoding the previous one: skip, never pile up
        decoding = true
        DispatchQueue.global(qos: .userInteractive).async {
            let img = UIImage(data: jpeg)?.preparingForDisplay()
            DispatchQueue.main.async {
                if let img {
                    self.latestFrame = img
                    self.lastFrameAt = Date()
                }
                self.queue.async { self.decoding = false }
            }
        }
    }

    // MARK: - sending

    func send(_ msg: Control) {
        queue.async { self.sendOnQueue(msg) }
    }

    private func sendOnQueue(_ msg: Control) {
        guard let tcp else { return }
        tcp.send(content: encodeControl(msg), completion: .contentProcessed { _ in })
    }

    /// Called ~60 times a second from the AR session.
    func sendPose(_ packet: PosePacket) {
        let data = packet.encoded()
        queue.async {
            guard let udp = self.udp else { return }
            udp.send(content: data, completion: .idempotent)
            self.sentThisSecond += 1
        }
    }
}
