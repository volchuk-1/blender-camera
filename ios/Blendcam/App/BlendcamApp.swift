import SwiftUI

@main
struct BlendcamApp: App {
    @StateObject private var link = Link()

    var body: some Scene {
        WindowGroup {
            Text("Blendcam")
                .environmentObject(link)
        }
    }
}
