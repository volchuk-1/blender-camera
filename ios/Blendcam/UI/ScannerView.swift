import AVFoundation
import SwiftUI
import UIKit

/// QR scanner (back camera). Calls `onCode` once with the first valid blendcam:// link.
struct ScannerView: UIViewControllerRepresentable {
    var onCode: (String) -> Void

    func makeUIViewController(context: Context) -> ScannerController {
        let c = ScannerController()
        c.onCode = onCode
        return c
    }

    func updateUIViewController(_ vc: ScannerController, context: Context) {
        vc.onCode = onCode
    }
}

final class ScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    var onCode: ((String) -> Void)?
    private let capture = AVCaptureSession()
    private var preview: AVCaptureVideoPreviewLayer?
    private var done = false
    private var configured = false

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        AVCaptureDevice.requestAccess(for: .video) { ok in
            DispatchQueue.main.async {
                if ok { self.setup() }
            }
        }
    }

    private func setup() {
        guard !configured,
              let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device),
              capture.canAddInput(input) else { return }
        configured = true
        capture.addInput(input)
        let output = AVCaptureMetadataOutput()
        guard capture.canAddOutput(output) else { return }
        capture.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr]
        let layer = AVCaptureVideoPreviewLayer(session: capture)
        layer.videoGravity = .resizeAspectFill
        layer.frame = view.bounds
        view.layer.addSublayer(layer)
        preview = layer
        rotate()
        let s = capture
        DispatchQueue.global(qos: .userInitiated).async { s.startRunning() }
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        preview?.frame = view.bounds
        rotate()
    }

    private func rotate() {
        // The app runs only in landscape right (home side on the right) = rotation angle 0.
        guard let conn = preview?.connection else { return }
        if conn.isVideoRotationAngleSupported(0) {
            conn.videoRotationAngle = 0
        }
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        let s = capture
        DispatchQueue.global(qos: .userInitiated).async { s.stopRunning() }
    }

    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput metadataObjects: [AVMetadataObject],
                        from connection: AVCaptureConnection) {
        guard !done else { return }
        for obj in metadataObjects {
            guard let code = (obj as? AVMetadataMachineReadableCodeObject)?.stringValue,
                  ConnectURL(string: code) != nil else { continue }
            done = true
            let s = capture
            DispatchQueue.global(qos: .userInitiated).async { s.stopRunning() }
            onCode?(code)
            return
        }
    }
}
