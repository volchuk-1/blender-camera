import SwiftUI

/// First screen: scan the QR code shown in Blender, or type the address and token.
struct ConnectView: View {
    @EnvironmentObject var link: Link
    var onDone: () -> Void

    @State private var address = ""
    @State private var token = ""
    @State private var error: String?

    var body: some View {
        HStack(spacing: 0) {
            ZStack {
                ScannerView { code in
                    handle(code)
                }
                RoundedRectangle(cornerRadius: 16)
                    .stroke(Color.white.opacity(0.8), lineWidth: 3)
                    .frame(width: 220, height: 220)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .clipped()

            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Blendcam")
                        .font(.largeTitle.bold())
                    Text("Відскануйте QR-код у Blender: бічна панель (N) → Blendcam → Старт.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    Divider()
                    Text("Або введіть вручну")
                        .font(.headline)
                    TextField("Адреса, напр. 192.0.2.5", text: $address)
                        .keyboardType(.numbersAndPunctuation)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .textFieldStyle(.roundedBorder)
                    TextField("Токен (у панелі Blender)", text: $token)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .textFieldStyle(.roundedBorder)
                    Button("Підключити") {
                        manual()
                    }
                    .buttonStyle(.borderedProminent)
                    if let error {
                        Text(error)
                            .foregroundStyle(.red)
                            .font(.callout)
                    }
                    if let saved = link.target {
                        Divider()
                        Button("Повернутись до \(saved.host)") {
                            link.connect(saved)
                            onDone()
                        }
                    }
                }
                .padding(20)
            }
            .frame(width: 340)
            .background(Color(.systemBackground))
        }
        .ignoresSafeArea(edges: .vertical)
    }

    private func handle(_ code: String) {
        guard let url = ConnectURL(string: code) else {
            error = "Це не QR-код Blendcam"
            return
        }
        Haptics.success()
        link.connect(url)
        onDone()
    }

    private func manual() {
        guard let url = ConnectURL.manual(address: address, token: token) else {
            error = "Перевірте адресу (напр. 192.0.2.5 або 192.0.2.5:52700) і токен"
            return
        }
        Haptics.success()
        link.connect(url)
        onDone()
    }
}
