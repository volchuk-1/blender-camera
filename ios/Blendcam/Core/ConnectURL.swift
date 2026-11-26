import Foundation

/// `blendcam://<host>:<port>?token=<token>` from the QR code in Blender.
struct ConnectURL: Equatable, Codable {
    static let defaultPort: UInt16 = 52700

    let host: String
    let port: UInt16
    let token: String

    init(host: String, port: UInt16, token: String) {
        self.host = host
        self.port = port
        self.token = token
    }

    init?(string: String) {
        let s = string.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let comps = URLComponents(string: s),
              comps.scheme?.lowercased() == "blendcam",
              let host = comps.host, !host.isEmpty,
              let port = comps.port, port > 0, port < 65536,
              let token = comps.queryItems?.first(where: { $0.name == "token" })?.value,
              !token.isEmpty
        else { return nil }
        self.host = host
        self.port = UInt16(port)
        self.token = token
    }

    /// Manual entry: "192.0.2.5" or "192.0.2.5:52700" plus the token shown in Blender.
    static func manual(address: String, token: String) -> ConnectURL? {
        let a = address.trimmingCharacters(in: .whitespacesAndNewlines)
        let tok = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !a.isEmpty, !tok.isEmpty, !a.contains("/"), !a.contains("?") else { return nil }
        let parts = a.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count <= 2, let first = parts.first, !first.isEmpty else { return nil }
        var port = ConnectURL.defaultPort
        if parts.count == 2 {
            guard let p = UInt16(parts[1]), p > 0 else { return nil }
            port = p
        }
        return ConnectURL(host: String(first), port: port, token: tok)
    }

    var string: String { "blendcam://\(host):\(port)?token=\(token)" }
}
