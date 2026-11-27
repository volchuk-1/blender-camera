import SwiftUI

/// Settings sent to Blender (scale, smoothing, joystick speed, calibration, picture) + local debug switch.
struct SettingsView: View {
    @EnvironmentObject var link: Link
    @Environment(\.dismiss) private var dismiss
    @AppStorage("blendcam.debug") private var debug = false
    var onReconnect: () -> Void

    @State private var scaleSlider: Double = PoseMath.logSlider(1, lo: 0.1, hi: 100)
    @State private var smooth: Double = 0.3
    @State private var joySpeed: Double = 1.5
    @State private var roll: Int = 0
    @State private var mirror = false
    @State private var stream = true
    @State private var preset = "steadicam"
    @State private var rollLock = false
    @State private var orbit = "off"
    @State private var orbitHold: Double = 1.0
    @State private var quality = "high"
    @State private var loaded = false

    static let presetIDs = ["handheld", "steadicam", "crane", "tripod", "custom"]

    static func presetTitle(_ id: String) -> String {
        switch id {
        case "handheld": return "Ручна"
        case "steadicam": return "Стедікам"
        case "crane": return "Кран / дрон"
        case "tripod": return "Штатив"
        default: return "Власний"
        }
    }

    private var scale: Double { PoseMath.logValue(scaleSlider, lo: 0.1, hi: 100) }

    private var targetName: String {
        let t = link.state?.target ?? ""
        return t.isEmpty ? "ще не вибрано" : t
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Рух") {
                    VStack(alignment: .leading) {
                        Text("Масштаб: 1 м у кімнаті = \(formatScale(scale)) м у сцені")
                        Slider(value: $scaleSlider, in: 0...1, onEditingChanged: { editing in
                            if !editing { send(BlendSettings(scale: rounded(scale))) }
                        })
                    }
                    VStack(alignment: .leading) {
                        Text(String(format: "Швидкість джойстика: %.1f м/с", joySpeed))
                        Slider(value: $joySpeed, in: 0.2...10, onEditingChanged: { editing in
                            if !editing { send(BlendSettings(joySpeed: joySpeed)) }
                        })
                    }
                }
                Section("Стабілізація") {
                    Picker("Пресет", selection: $preset) {
                        ForEach(SettingsView.presetIDs, id: \.self) { id in
                            Text(SettingsView.presetTitle(id)).tag(id)
                        }
                    }
                    .onChange(of: preset) { _, new in
                        if loaded { send(BlendSettings(preset: new)) }
                    }
                    if preset == "custom" {
                        VStack(alignment: .leading) {
                            Text(String(format: "Згладжування: %.2f (0 = сирий рух)", smooth))
                            Slider(value: $smooth, in: 0...1, onEditingChanged: { editing in
                                if !editing { send(BlendSettings(smooth: smooth)) }
                            })
                        }
                    }
                    Toggle("Без крену (горизонт завжди рівний)", isOn: $rollLock)
                        .onChange(of: rollLock) { _, new in
                            if loaded { send(BlendSettings(rollLock: new)) }
                        }
                }
                Section("Обліт") {
                    Picker("Режим", selection: $orbit) {
                        Text("Вимк").tag("off")
                        Text("Ціль").tag("target")
                        Text("Стіл").tag("turntable")
                    }
                    .pickerStyle(.segmented)
                    .onChange(of: orbit) { _, new in
                        if loaded { send(BlendSettings(orbit: new)) }
                    }
                    if orbit == "target" {
                        VStack(alignment: .leading) {
                            Text("Тримати ціль: \(Int((orbitHold * 100).rounded())) %")
                            Slider(value: $orbitHold, in: 0...1, onEditingChanged: { editing in
                                if !editing { send(BlendSettings(orbitHold: orbitHold)) }
                            })
                        }
                    }
                    if orbit != "off" {
                        Text("Ціль: \(targetName)")
                            .foregroundStyle(.secondary)
                    }
                    Text("Ціль вибирається в Blender: поле «Ціль» у панелі Blendcam, або виділений об'єкт.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                Section("Калібрування (якщо картинка повернута чи дзеркальна)") {
                    Picker("Поворот кадру", selection: $roll) {
                        Text("0°").tag(0)
                        Text("90°").tag(90)
                        Text("180°").tag(180)
                        Text("270°").tag(270)
                    }
                    .pickerStyle(.segmented)
                    .onChange(of: roll) { _, new in
                        if loaded { send(BlendSettings(rollDeg: new)) }
                    }
                    Toggle("Дзеркало (ліво ↔ право)", isOn: $mirror)
                        .onChange(of: mirror) { _, new in
                            if loaded { send(BlendSettings(mirrorX: new)) }
                        }
                }
                Section("Екран") {
                    Toggle("Картинка з Blender на телефоні", isOn: $stream)
                        .onChange(of: stream) { _, new in
                            if loaded { send(BlendSettings(stream: new)) }
                        }
                    Picker("Якість картинки", selection: $quality) {
                        Text("Звичайна").tag("normal")
                        Text("Висока").tag("high")
                    }
                    .pickerStyle(.segmented)
                    .onChange(of: quality) { _, new in
                        if loaded { send(BlendSettings(streamQuality: new)) }
                    }
                    Toggle("Налагодження (кути, координати)", isOn: $debug)
                }
                Section("Підключення") {
                    if let t = link.target {
                        Text("\(t.host):\(t.port)")
                            .foregroundStyle(.secondary)
                    }
                    Button("Сканувати QR заново") {
                        dismiss()
                        onReconnect()
                    }
                    Button("Забути адресу", role: .destructive) {
                        link.disconnect(forget: true)
                        dismiss()
                        onReconnect()
                    }
                }
            }
            .navigationTitle("Налаштування")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Готово") { dismiss() }
                }
            }
        }
        .onAppear(perform: load)
    }

    private func load() {
        if let s = link.state {
            if let v = s.scale { scaleSlider = PoseMath.logSlider(v, lo: 0.1, hi: 100) }
            if let v = s.smooth { smooth = v }
            if let v = s.joySpeed { joySpeed = min(10, max(0.2, v)) }
            if let v = s.rollDeg { roll = v }
            if let v = s.mirrorX { mirror = v }
            if let v = s.stream { stream = v }
            if let v = s.preset { preset = v }
            if let v = s.rollLock { rollLock = v }
            if let v = s.orbit { orbit = v }
            if let v = s.orbitHold { orbitHold = v }
            if let v = s.streamQuality { quality = v }
        }
        DispatchQueue.main.async { loaded = true }
    }

    private func send(_ s: BlendSettings) {
        link.send(.settings(s))
    }

    private func rounded(_ v: Double) -> Double {
        v >= 10 ? v.rounded() : (v * 100).rounded() / 100
    }

    private func formatScale(_ v: Double) -> String {
        v >= 10 ? String(format: "%.0f", v) : String(format: "%.2f", v)
    }
}

/// Debug overlay: phone angles, position, packet rates.
struct DebugOverlay: View {
    @EnvironmentObject var link: Link
    @EnvironmentObject var tracker: Tracker

    var body: some View {
        let a = tracker.angles
        let p = tracker.position
        VStack(alignment: .leading, spacing: 2) {
            Text(String(format: "курс %.1f°  нахил %.1f°  крен %.1f°", a.x, a.y, a.z))
            Text(String(format: "x %.2f  y %.2f  z %.2f м (ARKit)", p.x, p.y, p.z))
            Text("відстеження: \(tracker.tracking)  пакетів/с: \(link.packetsPerSecond)  кадрів/с: \(link.framesPerSecond)")
        }
        .font(.system(size: 12, design: .monospaced))
        .foregroundStyle(.white)
        .padding(8)
        .background(Color.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 8))
        .allowsHitTesting(false)
    }
}
