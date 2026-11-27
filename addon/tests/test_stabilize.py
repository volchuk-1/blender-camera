import math
import random
import unittest

from mathutils import Euler, Matrix, Vector

from blendcam import stabilize
from blendcam.stabilize import PRESETS, LiveSmoother, preset_for, remove_roll


def cam(pos, yaw_deg=0.0, pitch_deg=0.0, roll_deg=0.0):
    m = (Matrix.Rotation(math.radians(yaw_deg), 4, "Z") @ Matrix.Rotation(math.radians(90 + pitch_deg), 4, "X")
         @ Matrix.Rotation(math.radians(roll_deg), 4, "Z"))
    m.translation = Vector(pos)
    return m


def noisy_run(preset, noise=0.005, seconds=4.0, hz=60, seed=3):
    rnd = random.Random(seed)
    sm = LiveSmoother(PRESETS[preset])
    raw_var = out_var = 0.0
    n = 0
    for i in range(int(seconds * hz)):
        p = Vector((rnd.gauss(0, noise), rnd.gauss(0, noise), 1.5 + rnd.gauss(0, noise)))
        out = sm.apply(cam(p), i / hz)
        if i > hz:  # after warm-up
            raw_var += (p - Vector((0, 0, 1.5))).length_squared
            out_var += (out.translation - Vector((0, 0, 1.5))).length_squared
            n += 1
    return raw_var / n, out_var / n


class StabilizeTest(unittest.TestCase):
    def test_constant_input_passes(self):
        for name in PRESETS:
            sm = LiveSmoother(PRESETS[name])
            m = cam((1, 2, 1.6), 30, -10)
            for i in range(30):
                out = sm.apply(m, i / 60)
            for r in range(4):
                for c in range(4):
                    self.assertAlmostEqual(out[r][c], m[r][c], places=5)

    def test_noise_reduction(self):
        raw, out = noisy_run("steadicam")
        self.assertGreaterEqual(raw / out, 3.0)
        raw, out = noisy_run("crane")
        self.assertGreaterEqual(raw / out, 10.0)

    def test_handheld_low_lag(self):
        sm = LiveSmoother(PRESETS["handheld"])
        for i in range(61):
            t = i / 60
            out = sm.apply(cam((0, t * 1.0, 1.6)), t)
        self.assertLess(abs(out.translation.y - 1.0), 0.05)

    def test_quaternion_wrap(self):
        sm = LiveSmoother(PRESETS["steadicam"])
        prev = None
        for i in range(121):
            yaw = 170 + i * (20 / 120)
            out = sm.apply(cam((0, 0, 1.6), yaw if yaw <= 180 else yaw - 360), i / 60)
            q = out.to_quaternion()
            if prev is not None:
                self.assertLess(math.degrees(stabilize.quat_angle(prev, q)), 5.0)
            prev = q

    def test_remove_roll(self):
        m = cam((1, 2, 3), 40, -15, 20)
        r = remove_roll(m)
        right = r.to_3x3() @ Vector((1, 0, 0))
        self.assertAlmostEqual(right.z, 0.0, places=6)
        f0 = m.to_3x3() @ Vector((0, 0, -1))
        f1 = r.to_3x3() @ Vector((0, 0, -1))
        self.assertLess((f0 - f1).length, 1e-6)
        self.assertLess((r.translation - m.translation).length, 1e-9)
        up = r.to_3x3() @ Vector((0, 1, 0))
        self.assertGreater(up.z, 0)  # not upside down
        straight_down = cam((0, 0, 3), 0, -90, 10)
        self.assertEqual(remove_roll(straight_down), straight_down)

    def test_preset_for(self):
        self.assertEqual(preset_for("custom", 0.0).bake_sigma, 0.0)
        raw = LiveSmoother(preset_for("custom", 0.0))
        raw.apply(cam((0, 0, 1.6)), 0.0)
        self.assertAlmostEqual(raw.apply(cam((1, 0, 1.6)), 1 / 60).translation.x, 1.0, places=5)
        self.assertAlmostEqual(preset_for("custom", 0.5).bake_sigma, 2.0)
        self.assertEqual(preset_for("nope", 0.3).name, "steadicam")
        self.assertTrue(preset_for("crane", 0).roll_lock)
        self.assertTrue(preset_for("tripod", 0).tripod)
        self.assertEqual(set(PRESETS), {"handheld", "steadicam", "crane", "tripod"})

    def test_reset_jumps_to_new_pose(self):
        sm = LiveSmoother(PRESETS["crane"])
        sm.apply(cam((0, 0, 1.6)), 0.0)
        sm.reset(cam((5, 5, 1.6)))
        out = sm.apply(cam((5, 5, 1.6)), 0.016)
        self.assertLess((out.translation - Vector((5, 5, 1.6))).length, 1e-6)
