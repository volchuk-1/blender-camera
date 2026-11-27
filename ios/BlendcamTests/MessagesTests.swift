import XCTest
import simd

final class MessagesTests: XCTestCase {
    private func fixture(_ name: String) throws -> Data {
        let bundle = Bundle(for: MessagesTests.self)
        let dir = try XCTUnwrap(bundle.url(forResource: "fixtures", withExtension: nil), "fixtures folder missing")
        return try Data(contentsOf: dir.appendingPathComponent(name))
    }

    private func dict(_ data: Data) throws -> NSDictionary {
        try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? NSDictionary)
    }

    func testControlFixturesRoundTrip() throws {
        for name in ["hello", "record_start", "settings", "settings_v3", "state", "toast", "frame_header"] {
            let raw = try fixture(name + ".json")
            let msg = try XCTUnwrap(decodeControl(raw), name)
            let back = encodeControl(msg)
            XCTAssertEqual(back.last, 0x0A, name)
            XCTAssertEqual(try dict(raw), try dict(back.dropLast()), name)
        }
    }

    func testDecodedValues() throws {
        XCTAssertEqual(decodeControl(try fixture("hello.json")), .hello(token: "testtoken", device: "iPhone"))
        XCTAssertEqual(decodeControl(try fixture("record_start.json")), .recordStart(t: 12.5))
        guard case .settings(let s)? = decodeControl(try fixture("settings.json")) else {
            return XCTFail("settings")
        }
        XCTAssertEqual(s.scale, 10.0)
        XCTAssertEqual(s.joySpeed, 1.5)
        XCTAssertEqual(s.rollDeg, 0)
        XCTAssertEqual(s.mirrorX, false)
        guard case .state(let st)? = decodeControl(try fixture("state.json")) else { return XCTFail("state") }
        XCTAssertEqual(st.frameEnd, 250)
        XCTAssertEqual(st.take, "Take_01")
        XCTAssertEqual(decodeControl(try fixture("toast.json")), .toast(text: "Дубль збережено"))
        XCTAssertEqual(decodeControl(try fixture("frame_header.json")), .frameHeader(len: 1234, ts: 12.5))
        XCTAssertNil(decodeControl(Data("{\"type\":\"nope\"}".utf8)))
        XCTAssertNil(decodeControl(Data("garbage".utf8)))
    }

    func testV3Fields() throws {
        guard case .settings(let s)? = decodeControl(try fixture("settings_v3.json")) else {
            return XCTFail("settings_v3")
        }
        XCTAssertEqual(s.preset, "crane")
        XCTAssertEqual(s.rollLock, true)
        XCTAssertEqual(s.orbit, "turntable")
        XCTAssertEqual(s.orbitHold, 0.5)
        XCTAssertEqual(s.streamQuality, "normal")
        let line = Data(#"{"type":"state","connected":true,"recording":false,"frame":3,"frame_start":1,"frame_end":9,"fps":24,"focal":35,"camera":"Camera","take":"Take_02","orbit":"target","target":"Cube","preset":"tripod"}"#.utf8)
        guard case .state(let st)? = decodeControl(line) else { return XCTFail("state v3") }
        XCTAssertEqual(st.target, "Cube")
        XCTAssertEqual(st.orbit, "target")
        XCTAssertEqual(st.preset, "tripod")
        let out = try XCTUnwrap(String(data: encodeControl(.settings(BlendSettings(orbit: "off"))), encoding: .utf8))
        XCTAssertTrue(out.contains("\"orbit\":\"off\""))
        XCTAssertFalse(out.contains("preset"))
    }

    func testCyrillicNotEscaped() throws {
        let data = encodeControl(.toast(text: "Привіт"))
        let s = try XCTUnwrap(String(data: data, encoding: .utf8))
        XCTAssertTrue(s.contains("Привіт"))
        XCTAssertFalse(s.contains("\\u"))
    }

    func testPosePacketIdentity() throws {
        let m = PosePacket.matrix(matrix_identity_float4x4)
        XCTAssertEqual(m, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
        let p = PosePacket(seq: 3, t: 1.5, token: "abc", m: m, trk: "normal", joy: [0, 0], lift: 0, focal: 35)
        let d = try dict(p.encoded())
        XCTAssertEqual(d["v"] as? Int, 1)
        XCTAssertEqual((d["m"] as? [Double])?.count, 16)
        XCTAssertEqual(d["token"] as? String, "abc")
        XCTAssertNil(d["focus"])
    }

    func testPosePacketColumnMajorTranslation() throws {
        var t = matrix_identity_float4x4
        t.columns.3 = SIMD4<Float>(0.1, 1.5, -0.2, 1)
        let m = PosePacket.matrix(t)
        XCTAssertEqual(Array(m[12...14]), [0.1, 1.5, -0.2])
    }

    func testPoseFieldsMatchFixture() throws {
        // every key the fixture (and the Blender side) uses is produced by the phone
        let fixtureKeys = Set(try dict(try fixture("pose_basic.json")).allKeys.compactMap { $0 as? String })
        let p = PosePacket(seq: 1, t: 1, token: "t", m: Array(repeating: 0, count: 16), trk: "normal",
                           joy: [0, 0], lift: 0, focal: 35, focus: 2.5)
        let keys = Set(try dict(p.encoded()).allKeys.compactMap { $0 as? String })
        XCTAssertEqual(keys, fixtureKeys)
    }
}
