import math
import unittest

from mathutils import Euler, Matrix, Vector

from blendcam import mapping


def ar_matrix(rot: Matrix = None, pos=(0.0, 0.0, 0.0)):
    """Build a column-major ARKit 4x4 (list of 16) from a 3x3 rotation and a position (ARKit space)."""
    m = (rot or Matrix.Identity(3)).to_4x4()
    m.translation = Vector(pos)
    return [m[r][c] for c in range(4) for r in range(4)]


def blender_cam(euler_deg, pos=(0, 0, 0)):
    m = Euler([math.radians(a) for a in euler_deg], "XYZ").to_matrix().to_4x4()
    m.translation = Vector(pos)
    return m


def forward(m):
    return (m.to_3x3() @ Vector((0, 0, -1))).normalized()


def pitch_deg(m):
    f = forward(m)
    return math.degrees(math.asin(max(-1, min(1, f.z))))


def roll_deg(m):
    # angle of the camera's right vector above the horizon
    r = (m.to_3x3() @ Vector((1, 0, 0))).normalized()
    return math.degrees(math.asin(max(-1, min(1, r.z))))


class MappingTest(unittest.TestCase):
    def assertVec(self, a, b, places=4):
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y, places=places)

    def test_level_phone_looks_plus_y(self):
        m = mapping.ar_to_blender(ar_matrix())
        self.assertVec(m.to_euler(), (math.pi / 2, 0, 0))
        self.assertVec(forward(m), (0, 1, 0))

    def test_translation(self):
        m = mapping.ar_to_blender(ar_matrix(pos=(0, 0, -1)))
        self.assertVec(m.translation, (0, 1, 0))
        m = mapping.ar_to_blender(ar_matrix(pos=(0, 2, 0)))
        self.assertVec(m.translation, (0, 0, 2))

    def test_column_major(self):
        # ARKit rotation of +90 deg yaw (about ARKit +Y): camera now looks along ARKit -X
        rot = Matrix.Rotation(math.radians(90), 3, "Y")
        m = mapping.ar_to_blender(ar_matrix(rot))
        self.assertVec(forward(m), (-1, 0, 0))
        self.assertAlmostEqual(math.degrees(mapping.yaw_of(m)), 90, places=3)

    def test_anchor_keeps_horizon_and_heading(self):
        cam = blender_cam((60, 0, 45), pos=(3, -2, 1.6))  # 30 deg down, heading 45
        phone = mapping.ar_to_blender(ar_matrix(pos=(0.3, 1.4, 0.2)))
        a = mapping.Anchor.make(cam, phone)
        out = a.apply(phone, 1.0, Vector((0, 0, 0)))
        self.assertAlmostEqual(math.degrees(mapping.yaw_of(out)), 45, places=3)
        self.assertAlmostEqual(pitch_deg(out), 0, places=3)
        self.assertAlmostEqual(roll_deg(out), 0, places=3)
        self.assertVec(out.translation, (3, -2, 1.6))

    def test_anchor_scale_and_offset(self):
        cam = blender_cam((60, 0, 45), pos=(3, -2, 1.6))
        phone0 = mapping.ar_to_blender(ar_matrix())
        a = mapping.Anchor.make(cam, phone0)
        phone1 = mapping.ar_to_blender(ar_matrix(pos=(0, 0, -1)))  # 1 m forward
        out = a.apply(phone1, 10.0, Vector((0, 0, 0)))
        d = out.translation - Vector((3, -2, 1.6))
        self.assertAlmostEqual(d.length, 10, places=4)
        self.assertVec(d.normalized(), (-math.sqrt(0.5), math.sqrt(0.5), 0))
        out2 = a.apply(phone1, 10.0, Vector((0, 0, 2)))
        self.assertVec(out2.translation - out.translation, (0, 0, 2))

    def test_anchor_keeps_phone_tilt(self):
        cam = blender_cam((90, 0, 0))
        phone0 = mapping.ar_to_blender(ar_matrix())
        a = mapping.Anchor.make(cam, phone0)
        tilt = Matrix.Rotation(math.radians(-20), 3, "X")  # phone pitched 20 deg down
        out = a.apply(mapping.ar_to_blender(ar_matrix(tilt)), 1.0, Vector())
        self.assertAlmostEqual(pitch_deg(out), -20, places=3)

    def test_calibration(self):
        m = blender_cam((70, 10, 30), pos=(1, 2, 3))
        twice = mapping.apply_calibration(mapping.apply_calibration(m, 180, False), 180, False)
        for r in range(4):
            self.assertVec(twice[r], m[r])
        r90 = mapping.apply_calibration(m, 90, False)
        new_x = r90.to_3x3() @ Vector((1, 0, 0))
        old_y = m.to_3x3() @ Vector((0, 1, 0))
        self.assertVec(new_x, old_y)
        self.assertVec(r90.translation, m.translation)
        ident = mapping.apply_calibration(m, 0, False)
        for r in range(4):
            self.assertVec(ident[r], m[r])

    def test_mirror(self):
        m = blender_cam((90, 0, 30), pos=(1, 2, 3))
        mm = mapping.apply_calibration(m, 0, True)
        self.assertAlmostEqual(math.degrees(mapping.yaw_of(mm)), -30, places=3)
        self.assertVec(mm.translation, (-1, 2, 3))
        self.assertAlmostEqual(mm.to_3x3().determinant(), 1.0, places=5)

    def test_yaw_robust_when_looking_down(self):
        m = blender_cam((0, 0, 30))  # looking straight down, top of frame towards heading 30
        self.assertAlmostEqual(math.degrees(mapping.yaw_of(m)), 30, places=3)
