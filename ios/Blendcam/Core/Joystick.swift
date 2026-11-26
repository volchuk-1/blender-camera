import CoreGraphics
import Foundation

enum Joystick {
    static let deadZone: CGFloat = 0.1

    /// Touch -> joystick value. Clamped to the circle, dead zone 0.1, output -1...1, y up = forward.
    static func value(touch: CGPoint, center: CGPoint, radius: CGFloat) -> CGVector {
        guard radius > 0 else { return .zero }
        let dx = (touch.x - center.x) / radius
        let dy = -(touch.y - center.y) / radius
        let len = (dx * dx + dy * dy).squareRoot()
        if len < deadZone { return .zero }
        let mag = (min(len, 1) - deadZone) / (1 - deadZone)
        return CGVector(dx: dx / len * mag, dy: dy / len * mag)
    }

    /// Knob position inside the base for drawing (clamped to the circle).
    static func knobOffset(touch: CGPoint, center: CGPoint, radius: CGFloat) -> CGSize {
        let dx = touch.x - center.x
        let dy = touch.y - center.y
        let len = (dx * dx + dy * dy).squareRoot()
        if len <= radius || len == 0 { return CGSize(width: dx, height: dy) }
        return CGSize(width: dx / len * radius, height: dy / len * radius)
    }
}

/// Small math helpers shared by the UI (debug overlay) and the tests.
enum PoseMath {
    /// Yaw / pitch / roll in degrees of an ARKit camera transform (gravity-aligned world, Y up).
    /// yaw: heading about +Y, pitch: up/down, roll: about the view axis.
    static func angles(column0 c0: SIMD3<Float>, column1 c1: SIMD3<Float>, column2 c2: SIMD3<Float>) -> SIMD3<Float> {
        let fwd = -c2  // camera looks along -Z
        let yaw = atan2(-fwd.x, -fwd.z)
        let pitch = asin(max(-1, min(1, fwd.y)))
        let roll = atan2(c0.y, c1.y)
        let deg: Float = 180 / .pi
        return SIMD3<Float>(yaw * deg, pitch * deg, roll * deg)
    }

    /// Log slider 0...1 <-> value lo...hi.
    static func logValue(_ s: Double, lo: Double, hi: Double) -> Double {
        exp(log(lo) + (log(hi) - log(lo)) * max(0, min(1, s)))
    }

    static func logSlider(_ v: Double, lo: Double, hi: Double) -> Double {
        guard v > 0 else { return 0 }
        return max(0, min(1, (log(v) - log(lo)) / (log(hi) - log(lo))))
    }
}
