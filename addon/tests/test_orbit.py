import math
import unittest

from mathutils import Matrix, Vector

from blendcam import mapping, orbit
from blendcam.orbit import Turntable, aim, look_rotation


def cam(pos, yaw_deg=0.0, pitch_deg=0.0, roll_deg=0.0):
    m = (Matrix.Rotation(math.radians(yaw_deg), 4, "Z") @ Matrix.Rotation(math.radians(90 + pitch_deg), 4, "X")
         @ Matrix.Rotation(math.radians(roll_deg), 4, "Z"))
    m.translation = Vector(pos)
    return m


def fwd(m):
    return (m.to_3x3() @ Vector((0, 0, -1))).normalized()


def angle_to(m, target):
    d = (Vector(target) - m.translation).normalized()
    return math.degrees(fwd(m).angle(d))


class OrbitTest(unittest.TestCase):
    T = Vector((0.0, 3.0, 1.0))

    def test_hold_one_centers_target(self):
        m = aim(cam((2, -1, 1.6), 30, 10), self.T, 1.0)
        self.assertLess(angle_to(m, self.T), 1e-3)
        self.assertLess((m.translation - Vector((2, -1, 1.6))).length, 1e-9)

    def test_hold_zero_unchanged(self):
        c = cam((2, -1, 1.6), 30, 10)
        m = aim(c, self.T, 0.0)
        self.assertLess((fwd(m) - fwd(c)).length, 1e-6)

    def test_hold_half_between(self):
        c = cam((0, 0, 1.0), 40, 0)
        full = angle_to(c, self.T)
        m = aim(c, self.T, 0.5)
        self.assertAlmostEqual(angle_to(m, self.T), full / 2, delta=0.5)

    def test_look_rotation_no_roll(self):
        r = look_rotation(Vector((4, -2, 2.5)), self.T)
        right = r @ Vector((1, 0, 0))
        up = r @ Vector((0, 1, 0))
        self.assertAlmostEqual(right.z, 0.0, places=6)
        self.assertGreater(up.z, 0)
        down = look_rotation(Vector((0, 0, 5)), Vector((0, 0, 0)))
        self.assertLess(((down @ Vector((0, 0, -1))) - Vector((0, 0, -1))).length, 1e-6)

    def phone(self, yaw_deg=0.0, pitch_deg=0.0):
        return cam((0, 0, 1.4), yaw_deg, pitch_deg)

    def test_turntable_quarter_turn(self):
        start = cam((0, -2, 1.0), 0, 0)  # 5 m in front of the target, looking at it
        tt = Turntable()
        tt.start(start, self.T, self.phone())
        m0 = tt.apply(self.phone(), (0.0, 0.0), 1 / 60, 1.0)
        self.assertLess((m0.translation - start.translation).length, 1e-6)
        m = tt.apply(self.phone(-90), (0.0, 0.0), 1 / 60, 1.0)  # phone turned 90 deg to the right
        self.assertAlmostEqual((m.translation - self.T).length, 5.0, places=5)
        self.assertAlmostEqual(m.translation.z, 1.0, places=5)
        self.assertLess(angle_to(m, self.T), 1e-3)
        yaw0 = math.degrees(mapping.yaw_of(m0))
        yaw1 = math.degrees(mapping.yaw_of(m))
        self.assertAlmostEqual((yaw1 - yaw0 + 540) % 360 - 180, -90, places=3)  # view turned right

    def test_turntable_full_circle_continuous(self):
        tt = Turntable()
        tt.start(cam((0, -2, 1.0)), self.T, self.phone())
        prev = None
        for i in range(0, 361, 5):
            yaw = -i
            yaw = (yaw + 180) % 360 - 180
            m = tt.apply(self.phone(yaw), (0.0, 0.0), 1 / 60, 1.0)
            if prev is not None:
                self.assertLess((m.translation - prev).length, 0.5)
            prev = m.translation.copy()
        self.assertLess((prev - Vector((0, -2, 1.0))).length, 1e-3)

    def test_turntable_pitch_clamp(self):
        tt = Turntable()
        tt.start(cam((0, -2, 1.0)), self.T, self.phone(0, 40))
        m = tt.apply(self.phone(0, -85), (0.0, 0.0), 1 / 60, 1.0)  # tilted down by 125 deg
        d = m.translation - self.T
        self.assertAlmostEqual(math.degrees(math.asin(d.z / d.length)), 80.0, places=3)

    def test_turntable_joystick_distance(self):
        tt = Turntable()
        tt.start(cam((0, -2, 1.0)), self.T, self.phone())
        for _ in range(60):
            m = tt.apply(self.phone(), (0.0, 1.0), 1 / 60, 1.0)
        self.assertAlmostEqual((m.translation - self.T).length, 4.0, places=4)
        for _ in range(600):
            m = tt.apply(self.phone(), (0.0, 1.0), 1 / 60, 1.0)
        self.assertAlmostEqual((m.translation - self.T).length, 0.2, places=6)

    def test_turntable_zero_distance(self):
        tt = Turntable()
        tt.start(cam(tuple(self.T)), self.T, self.phone())
        m = tt.apply(self.phone(), (0.0, 0.0), 1 / 60, 1.0)
        self.assertAlmostEqual((m.translation - self.T).length, 0.2, places=6)

    def test_target_update(self):
        tt = Turntable()
        tt.start(cam((0, -2, 1.0)), self.T, self.phone())
        tt.target = self.T + Vector((1, 0, 0))
        m = tt.apply(self.phone(), (0.0, 0.0), 1 / 60, 1.0)
        self.assertLess(angle_to(m, tt.target), 1e-3)
