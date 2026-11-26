import ARKit
import SceneKit
import SwiftUI

/// The phone camera image of the running AR session (shown dimmed when there is no picture from Blender).
struct ARCameraView: UIViewRepresentable {
    let session: ARSession

    func makeUIView(context: Context) -> ARSCNView {
        let v = ARSCNView(frame: .zero)
        v.session = session
        v.scene = SCNScene()
        v.automaticallyUpdatesLighting = false
        v.rendersCameraGrain = false
        v.isUserInteractionEnabled = false
        return v
    }

    func updateUIView(_ uiView: ARSCNView, context: Context) {}
}

/// Thin crosshair in the middle of the frame.
struct Crosshair: View {
    var body: some View {
        ZStack {
            Rectangle().fill(Color.white.opacity(0.8)).frame(width: 36, height: 1.5)
            Rectangle().fill(Color.white.opacity(0.8)).frame(width: 1.5, height: 36)
        }
        .allowsHitTesting(false)
    }
}
