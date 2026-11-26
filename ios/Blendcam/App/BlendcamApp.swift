import SwiftUI

@main
struct BlendcamApp: App {
    @StateObject private var link = Link()
    @StateObject private var tracker = Tracker()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(link)
                .environmentObject(tracker)
                .preferredColorScheme(.dark)
        }
    }
}

struct RootView: View {
    @EnvironmentObject var link: Link
    @State private var showConnect = false

    var body: some View {
        Group {
            if showConnect || link.target == nil {
                ConnectView(onDone: { showConnect = false })
            } else {
                ControlView(onReconnect: { showConnect = true })
            }
        }
        .statusBarHidden(true)
        .persistentSystemOverlays(.hidden)
        .onOpenURL { url in
            // QR scanned with the system Camera app opens blendcam://…
            if let u = ConnectURL(string: url.absoluteString) {
                link.connect(u)
                showConnect = false
            }
        }
    }
}
