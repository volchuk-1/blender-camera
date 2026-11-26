import CoreGraphics
import XCTest

final class JoystickTests: XCTestCase {
    let c = CGPoint(x: 100, y: 100)

    func testCenterIsZero() {
        XCTAssertEqual(Joystick.value(touch: c, center: c, radius: 50), .zero)
    }

    func testClampedToCircle() {
        let v = Joystick.value(touch: CGPoint(x: 200, y: 100), center: c, radius: 50)
        XCTAssertEqual(v.dx, 1, accuracy: 1e-6)
        XCTAssertEqual(v.dy, 0, accuracy: 1e-6)
    }

    func testDeadZone() {
        XCTAssertEqual(Joystick.value(touch: CGPoint(x: 104, y: 100), center: c, radius: 50), .zero)
    }

    func testUpIsForward() {
        let v = Joystick.value(touch: CGPoint(x: 100, y: 50), center: c, radius: 50)
        XCTAssertEqual(v.dx, 0, accuracy: 1e-6)
        XCTAssertEqual(v.dy, 1, accuracy: 1e-6)
    }

    func testHalfway() {
        let v = Joystick.value(touch: CGPoint(x: 100, y: 125), center: c, radius: 50)
        XCTAssertEqual(v.dy, -(0.5 - 0.1) / 0.9, accuracy: 1e-6)
    }

    func testLogSlider() {
        XCTAssertEqual(PoseMath.logValue(0, lo: 0.1, hi: 100), 0.1, accuracy: 1e-9)
        XCTAssertEqual(PoseMath.logValue(1, lo: 0.1, hi: 100), 100, accuracy: 1e-9)
        XCTAssertEqual(PoseMath.logSlider(PoseMath.logValue(0.37, lo: 0.1, hi: 100), lo: 0.1, hi: 100), 0.37,
                       accuracy: 1e-9)
    }

    func testAnglesLevel() {
        let a = PoseMath.angles(column0: SIMD3<Float>(1, 0, 0), column1: SIMD3<Float>(0, 1, 0),
                                column2: SIMD3<Float>(0, 0, 1))
        XCTAssertEqual(a.x, 0, accuracy: 1e-4)
        XCTAssertEqual(a.y, 0, accuracy: 1e-4)
        XCTAssertEqual(a.z, 0, accuracy: 1e-4)
    }
}
