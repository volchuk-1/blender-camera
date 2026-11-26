import Foundation
import simd

/// One UDP pose packet, protocol v1 (see protocol/README.md).
struct PosePacket: Encodable {
    var v: Int = 1
    var seq: Int
    var t: Double
    var token: String
    var m: [Float]
    var trk: String
    var joy: [Float]
    var lift: Float
    var focal: Float
    var focus: Float?

    /// Column-major 16 floats from an ARKit camera transform.
    static func matrix(_ t: simd_float4x4) -> [Float] {
        let c = [t.columns.0, t.columns.1, t.columns.2, t.columns.3]
        var out: [Float] = []
        out.reserveCapacity(16)
        for col in c {
            out.append(col.x)
            out.append(col.y)
            out.append(col.z)
            out.append(col.w)
        }
        return out
    }

    func encoded() -> Data {
        (try? JSONEncoder().encode(self)) ?? Data()
    }
}

/// Settings the phone can change in Blender (every field optional).
struct BlendSettings: Codable, Equatable {
    var scale: Double?
    var smooth: Double?
    var joySpeed: Double?
    var rollDeg: Int?
    var mirrorX: Bool?
    var stream: Bool?

    enum CodingKeys: String, CodingKey {
        case scale, smooth, stream
        case joySpeed = "joy_speed"
        case rollDeg = "roll_deg"
        case mirrorX = "mirror_x"
    }
}

/// `state` message from Blender.
struct BlenderState: Codable, Equatable {
    var connected: Bool
    var recording: Bool
    var frame: Int
    var frameStart: Int
    var frameEnd: Int
    var fps: Double
    var focal: Double
    var camera: String
    var take: String
    var lastTake: String?
    var scale: Double?
    var smooth: Double?
    var joySpeed: Double?
    var rollDeg: Int?
    var mirrorX: Bool?
    var stream: Bool?
    var live: Bool?

    enum CodingKeys: String, CodingKey {
        case connected, recording, frame, fps, focal, camera, take, scale, smooth, stream, live
        case frameStart = "frame_start"
        case frameEnd = "frame_end"
        case lastTake = "last_take"
        case joySpeed = "joy_speed"
        case rollDeg = "roll_deg"
        case mirrorX = "mirror_x"
    }
}

/// Control messages over TCP (one JSON object per line).
enum Control: Equatable {
    case hello(token: String, device: String)
    case anchor
    case recordStart(t: Double)
    case recordStop
    case play
    case pause
    case frame(n: Int)
    case settings(BlendSettings)
    case state(BlenderState)
    case toast(text: String)
    case frameHeader(len: Int, ts: Double?)
}

extension Control: Codable {
    private enum K: String, CodingKey {
        case type, token, device, t, n, text, len, ts
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: K.self)
        let type = try c.decode(String.self, forKey: .type)
        switch type {
        case "hello":
            self = .hello(token: try c.decode(String.self, forKey: .token),
                          device: try c.decodeIfPresent(String.self, forKey: .device) ?? "")
        case "anchor":
            self = .anchor
        case "record_start":
            self = .recordStart(t: try c.decode(Double.self, forKey: .t))
        case "record_stop":
            self = .recordStop
        case "play":
            self = .play
        case "pause":
            self = .pause
        case "frame":
            if c.contains(.len) {
                self = .frameHeader(len: try c.decode(Int.self, forKey: .len),
                                    ts: try c.decodeIfPresent(Double.self, forKey: .ts))
            } else {
                self = .frame(n: try c.decode(Int.self, forKey: .n))
            }
        case "settings":
            self = .settings(try BlendSettings(from: decoder))
        case "state":
            self = .state(try BlenderState(from: decoder))
        case "toast":
            self = .toast(text: try c.decode(String.self, forKey: .text))
        default:
            throw DecodingError.dataCorruptedError(forKey: .type, in: c,
                                                   debugDescription: "unknown type \(type)")
        }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: K.self)
        switch self {
        case .hello(let token, let device):
            try c.encode("hello", forKey: .type)
            try c.encode(token, forKey: .token)
            try c.encode(device, forKey: .device)
        case .anchor:
            try c.encode("anchor", forKey: .type)
        case .recordStart(let t):
            try c.encode("record_start", forKey: .type)
            try c.encode(t, forKey: .t)
        case .recordStop:
            try c.encode("record_stop", forKey: .type)
        case .play:
            try c.encode("play", forKey: .type)
        case .pause:
            try c.encode("pause", forKey: .type)
        case .frame(let n):
            try c.encode("frame", forKey: .type)
            try c.encode(n, forKey: .n)
        case .settings(let s):
            try c.encode("settings", forKey: .type)
            try s.encode(to: encoder)
        case .state(let s):
            try c.encode("state", forKey: .type)
            try s.encode(to: encoder)
        case .toast(let text):
            try c.encode("toast", forKey: .type)
            try c.encode(text, forKey: .text)
        case .frameHeader(let len, let ts):
            try c.encode("frame", forKey: .type)
            try c.encode(len, forKey: .len)
            try c.encodeIfPresent(ts, forKey: .ts)
        }
    }
}

/// JSON line (UTF-8, no ASCII escaping) terminated by "\n".
func encodeControl(_ msg: Control) -> Data {
    let enc = JSONEncoder()
    enc.outputFormatting = [.withoutEscapingSlashes]
    var data = (try? enc.encode(msg)) ?? Data()
    data.append(0x0A)
    return data
}

func decodeControl(_ line: Data) -> Control? {
    try? JSONDecoder().decode(Control.self, from: line)
}
