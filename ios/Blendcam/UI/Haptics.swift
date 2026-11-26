import UIKit

/// Strong haptics (light taps are too faint while walking with the phone).
enum Haptics {
    static func heavy() {
        let g = UIImpactFeedbackGenerator(style: .heavy)
        g.prepare()
        g.impactOccurred(intensity: 1.0)
    }

    /// Double heavy hit: start / stop of a recording.
    static func strong() {
        heavy()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) { heavy() }
    }

    static func success() {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }

    static func warning() {
        UINotificationFeedbackGenerator().notificationOccurred(.warning)
    }
}
