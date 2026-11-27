import SwiftUI
import UIKit

/// Main landscape screen: picture, status, joystick, height, anchor, playback, focal length, record.
struct ControlView: View {
    @EnvironmentObject var link: Link
    @EnvironmentObject var tracker: Tracker
    @Environment(\.scenePhase) private var scenePhase
    @AppStorage("blendcam.debug") private var debug = false
    var onReconnect: () -> Void

    @State private var joy = CGVector.zero
    @State private var lift: CGFloat = 0
    @State private var focal: Double = 35
    @State private var focalTouched = false
    @State private var frameValue: Double = 1
    @State private var editingFrame = false
    @State private var playing = false
    @State private var recording = false
    @State private var recStart = Date()
    @State private var countdown: Int?
    @State private var countdownTask: Task<Void, Never>?
    @State private var showSettings = false
    @State private var toastText: String?
    @State private var toastTask: Task<Void, Never>?

    var body: some View {
        ZStack {
            background
            VStack(spacing: 0) {
                topBar
                if link.state?.live == false && !recording {
                    Text("Перегляд дубля · «Прив'язати» — знову керувати камерою")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.black)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 6)
                        .background(Color.yellow, in: Capsule())
                        .padding(.top, 6)
                }
                Spacer(minLength: 0)
                middleControls
                bottomBar
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            if let n = countdown {
                Text("\(n)")
                    .font(.system(size: 160, weight: .heavy, design: .rounded))
                    .foregroundStyle(.white)
                    .shadow(radius: 12)
                    .transition(.scale)
                    .allowsHitTesting(false)
            }
            if let t = toastText {
                VStack {
                    Text(t)
                        .font(.headline)
                        .foregroundStyle(.white)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 10)
                        .background(Color.black.opacity(0.75), in: Capsule())
                        .padding(.top, 64)
                    Spacer()
                }
                .allowsHitTesting(false)
            }
            if debug {
                VStack {
                    Spacer()
                    HStack {
                        Spacer()
                        DebugOverlay()
                    }
                }
                .padding(.bottom, 120)
                .padding(.trailing, 100)
            }
        }
        .background(Color.black)
        .ignoresSafeArea()
        .sheet(isPresented: $showSettings) {
            SettingsView(onReconnect: onReconnect)
                .environmentObject(link)
        }
        .onAppear(perform: appear)
        .onDisappear(perform: disappear)
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                // only restart AR when it was really stopped: a restart means a new ARKit world
                if !tracker.running { tracker.start() }
                link.resume()
            } else if phase == .background {
                tracker.stop()
            }
        }
        .onChange(of: joy) { _, v in tracker.joy = v }
        .onChange(of: lift) { _, v in tracker.lift = v }
        .onChange(of: focal) { _, v in
            if focalTouched { tracker.focal = Float(v) }
        }
        .onChange(of: link.state) { _, s in stateChanged(s) }
        .onChange(of: link.toastID) { _, _ in
            if let t = link.toast { showToast(t) }
        }
        .onChange(of: link.connected) { old, new in
            if old && !new {
                Haptics.warning()
                showToast("Зв'язок з Blender втрачено")
            }
        }
        .onChange(of: tracker.tracking) { _, new in
            if recording && new != "normal" {
                Haptics.warning()
            }
        }
    }

    // MARK: - pieces

    private var streamFresh: Bool {
        guard link.latestFrame != nil, let at = link.lastFrameAt else { return false }
        return Date().timeIntervalSince(at) < 1.0 && (link.state?.stream ?? true)
    }

    @ViewBuilder private var background: some View {
        ZStack {
            ARCameraView(session: tracker.session)
                .overlay(Color.black.opacity(streamFresh ? 1.0 : 0.45))
            if streamFresh, let img = link.latestFrame {
                Image(uiImage: img)
                    .resizable()
                    .interpolation(.medium)
                    .scaledToFit()
            }
            Crosshair()
        }
        .ignoresSafeArea()
    }

    private var trackingText: String {
        switch tracker.tracking {
        case "normal":
            return "Відстеження: добре"
        case "limited":
            return tracker.reason.isEmpty ? "Мало деталей — поводь телефоном" : tracker.reason
        default:
            return tracker.reason.isEmpty ? "Немає відстеження" : tracker.reason
        }
    }

    private var takeText: String {
        guard let take = link.state?.take, !take.isEmpty else { return "" }
        let num = take.replacingOccurrences(of: "Take_", with: "")
        return "Дубль \(num)"
    }

    private var orbitMode: String { link.state?.orbit ?? "off" }

    private var orbitLabel: String {
        switch orbitMode {
        case "target":
            let t = link.state?.target ?? ""
            return t.isEmpty ? "Обліт: ціль" : "Обліт: \(t)"
        case "turntable":
            return "Обліт: стіл"
        default:
            return "Обліт: вимк"
        }
    }

    /// Off -> target -> turntable -> off.
    private var orbitButton: some View {
        Button {
            let next: String
            switch orbitMode {
            case "off": next = "target"
            case "target": next = "turntable"
            default: next = "off"
            }
            link.send(.settings(BlendSettings(orbit: next)))
            Haptics.heavy()
        } label: {
            Label(orbitLabel, systemImage: "rotate.3d")
                .font(.subheadline.weight(.semibold))
                .lineLimit(1)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(orbitMode == "off" ? Color.white.opacity(0.15) : Color.orange.opacity(0.85),
                            in: Capsule())
        }
        .disabled(!link.connected)
    }

    private var topBar: some View {
        HStack(spacing: 12) {
            Circle()
                .fill(link.connected ? Color.green : Color.red)
                .frame(width: 12, height: 12)
            Text(link.connected ? "Blender" : "Немає зв'язку")
                .font(.subheadline.weight(.semibold))
            Text(trackingText)
                .font(.subheadline)
                .foregroundStyle(tracker.tracking == "normal" ? Color.white : Color.yellow)
            Spacer()
            if recording {
                TimelineView(.periodic(from: .now, by: 0.1)) { ctx in
                    Text(elapsed(ctx.date))
                        .font(.system(.headline, design: .monospaced))
                        .foregroundStyle(.red)
                }
            }
            Text(takeText)
                .font(.subheadline.weight(.semibold))
            orbitButton
            Button {
                showSettings = true
            } label: {
                Image(systemName: "gearshape.fill")
                    .font(.title2)
            }
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(Color.black.opacity(0.45), in: Capsule())
    }

    private var middleControls: some View {
        HStack(alignment: .bottom) {
            JoystickView(value: $joy)
            Spacer()
            LiftSlider(value: $lift)
        }
        .padding(.bottom, 8)
    }

    private var frameRange: ClosedRange<Double> {
        let s = Double(link.state?.frameStart ?? 1)
        let e = Double(link.state?.frameEnd ?? 250)
        return e > s ? s...e : s...(s + 1)
    }

    private var bottomBar: some View {
        HStack(spacing: 14) {
            Button {
                link.send(.anchor)
                Haptics.heavy()
            } label: {
                Label("Прив'язати", systemImage: "scope")
                    .font(.headline)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(Color.white.opacity(0.2), in: Capsule())
            }
            Button {
                playing.toggle()
                link.send(playing ? .play : .pause)
            } label: {
                Image(systemName: playing ? "pause.fill" : "play.fill")
                    .font(.title2)
                    .frame(width: 44, height: 44)
                    .background(Color.white.opacity(0.2), in: Circle())
            }
            .disabled(recording)
            VStack(spacing: 2) {
                Text("Кадр \(Int(frameValue))")
                    .font(.caption)
                Slider(value: $frameValue, in: frameRange, step: 1, onEditingChanged: { editing in
                    editingFrame = editing
                    if !editing { link.send(.frame(n: Int(frameValue))) }
                })
                .disabled(recording)
            }
            VStack(spacing: 2) {
                Text("\(Int(focal)) мм")
                    .font(.caption)
                Slider(value: $focal, in: 12...200, step: 1, onEditingChanged: { editing in
                    if editing {
                        focalTouched = true
                        tracker.focal = Float(focal)
                    }
                })
            }
            recordButton
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Color.black.opacity(0.45), in: RoundedRectangle(cornerRadius: 22))
    }

    private var recordButton: some View {
        Button(action: recordTapped) {
            ZStack {
                Circle()
                    .stroke(Color.white, lineWidth: 4)
                    .frame(width: 72, height: 72)
                if recording {
                    RoundedRectangle(cornerRadius: 6)
                        .fill(Color.red)
                        .frame(width: 30, height: 30)
                } else {
                    Circle()
                        .fill(countdown == nil ? Color.red : Color.orange)
                        .frame(width: 58, height: 58)
                }
            }
        }
        .disabled(!link.connected && !recording)
        .opacity(link.connected || recording ? 1 : 0.4)
    }

    // MARK: - actions

    private func appear() {
        tracker.link = link
        tracker.focal = focalTouched ? Float(focal) : 0
        if !tracker.running { tracker.start() }
        link.resume()
        UIApplication.shared.isIdleTimerDisabled = true
    }

    private func disappear() {
        countdownTask?.cancel()
        tracker.stop()
        UIApplication.shared.isIdleTimerDisabled = false
    }

    private func recordTapped() {
        if recording {
            link.send(.recordStop)
            recording = false
            Haptics.strong()
            return
        }
        if countdown != nil {
            countdownTask?.cancel()
            countdownTask = nil
            countdown = nil
            return
        }
        countdownTask = Task { @MainActor in
            for n in [3, 2, 1] {
                withAnimation { countdown = n }
                Haptics.heavy()
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                if Task.isCancelled {
                    countdown = nil
                    return
                }
            }
            countdown = nil
            link.send(.recordStart(t: tracker.lastTimestamp))
            recording = true
            recStart = Date()
            playing = false
            Haptics.strong()
        }
    }

    private func stateChanged(_ s: BlenderState?) {
        guard let s else { return }
        if !focalTouched {
            focal = min(200, max(12, s.focal))  // follow Blender's lens until the user takes over
        }
        if !editingFrame {
            frameValue = Double(s.frame)
        }
        // Blender stopped the take by itself (lost connection / silence): follow it.
        if recording && !s.recording && Date().timeIntervalSince(recStart) > 1.5 {
            recording = false
            Haptics.strong()
        }
    }

    private func showToast(_ text: String) {
        toastTask?.cancel()
        withAnimation { toastText = text }
        toastTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            if !Task.isCancelled {
                withAnimation { toastText = nil }
            }
        }
    }

    private func elapsed(_ now: Date) -> String {
        let t = max(0, now.timeIntervalSince(recStart))
        let m = Int(t) / 60
        let s = Int(t) % 60
        let d = Int((t - floor(t)) * 10)
        return String(format: "● %d:%02d.%d", m, s, d)
    }
}
