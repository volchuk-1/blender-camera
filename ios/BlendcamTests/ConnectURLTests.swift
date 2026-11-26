import XCTest

final class ConnectURLTests: XCTestCase {
    func testParse() throws {
        let u = try XCTUnwrap(ConnectURL(string: "blendcam://192.168.1.5:52700?token=abc"))
        XCTAssertEqual(u.host, "192.168.1.5")
        XCTAssertEqual(u.port, 52700)
        XCTAssertEqual(u.token, "abc")
        XCTAssertEqual(ConnectURL(string: u.string), u)
        XCTAssertNotNil(ConnectURL(string: "  blendcam://10.0.0.2:1234?token=x-_Y  "))
    }

    func testInvalid() {
        XCTAssertNil(ConnectURL(string: "http://192.168.1.5:52700?token=abc"))
        XCTAssertNil(ConnectURL(string: "blendcam://192.168.1.5?token=abc"))
        XCTAssertNil(ConnectURL(string: "blendcam://192.168.1.5:52700"))
        XCTAssertNil(ConnectURL(string: "blendcam://192.168.1.5:52700?token="))
        XCTAssertNil(ConnectURL(string: "blendcam://:52700?token=abc"))
        XCTAssertNil(ConnectURL(string: "garbage"))
        XCTAssertNil(ConnectURL(string: ""))
    }

    func testManual() {
        XCTAssertEqual(ConnectURL.manual(address: "192.168.1.5", token: "t"),
                       ConnectURL(host: "192.168.1.5", port: 52700, token: "t"))
        XCTAssertEqual(ConnectURL.manual(address: "192.168.1.5:1234", token: " t "),
                       ConnectURL(host: "192.168.1.5", port: 1234, token: "t"))
        XCTAssertNil(ConnectURL.manual(address: "192.168.1.5:abc", token: "t"))
        XCTAssertNil(ConnectURL.manual(address: "", token: "t"))
        XCTAssertNil(ConnectURL.manual(address: "1.2.3.4", token: ""))
    }
}
