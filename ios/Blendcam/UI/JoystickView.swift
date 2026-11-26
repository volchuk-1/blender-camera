import SwiftUI

/// Virtual joystick: moves the camera through the scene without walking. Springs back to the centre.
struct JoystickView: View {
    @Binding var value: CGVector
    var size: CGFloat = 170

    @State private var knob = CGSize.zero

    var body: some View {
        ZStack {
            Circle()
                .fill(Color.black.opacity(0.35))
                .overlay(Circle().stroke(Color.white.opacity(0.55), lineWidth: 2))
            Circle()
                .fill(Color.white.opacity(0.85))
                .frame(width: 64, height: 64)
                .offset(knob)
        }
        .frame(width: size, height: size)
        .contentShape(Circle())
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { g in
                    let c = CGPoint(x: size / 2, y: size / 2)
                    knob = Joystick.knobOffset(touch: g.location, center: c, radius: size / 2)
                    value = Joystick.value(touch: g.location, center: c, radius: size / 2)
                }
                .onEnded { _ in
                    withAnimation(.spring(duration: 0.2)) { knob = .zero }
                    value = .zero
                }
        )
    }
}

/// Vertical slider for height (lift): -1...1, springs back to 0 when released.
struct LiftSlider: View {
    @Binding var value: CGFloat
    var height: CGFloat = 200
    var width: CGFloat = 64

    var body: some View {
        ZStack {
            Capsule()
                .fill(Color.black.opacity(0.35))
                .overlay(Capsule().stroke(Color.white.opacity(0.55), lineWidth: 2))
            VStack {
                Image(systemName: "chevron.up")
                Spacer()
                Image(systemName: "chevron.down")
            }
            .font(.headline)
            .foregroundStyle(Color.white.opacity(0.7))
            .padding(.vertical, 12)
            Circle()
                .fill(Color.white.opacity(0.85))
                .frame(width: width - 12, height: width - 12)
                .offset(y: -value * (height / 2 - width / 2))
        }
        .frame(width: width, height: height)
        .contentShape(Capsule())
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { g in
                    let half = height / 2 - width / 2
                    let v = -(g.location.y - height / 2) / max(half, 1)
                    value = max(-1, min(1, v))
                }
                .onEnded { _ in
                    withAnimation(.spring(duration: 0.2)) { value = 0 }
                }
        )
    }
}
