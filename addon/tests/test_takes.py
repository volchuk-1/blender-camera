import json
import math
import random
import unittest

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from blendcam import takes
from blendcam.takes import Sample


def cam_matrix(pos, yaw_deg, pitch_deg=0.0):
    m = Euler((math.radians(90 + pitch_deg), 0, math.radians(yaw_deg)), "XYZ").to_matrix().to_4x4()
    m.translation = Vector(pos)
    return m


def circle(R=2.0, seconds=5.0, hz=60, t0=10.0):
    out = []
    n = int(round(seconds * hz))
    for i in range(n + 1):
        t = i / hz
        a = 2 * math.pi * t / seconds
        pos = (R * math.cos(a), R * math.sin(a), 1.5)
        out.append(Sample(t=t0 + t, world=cam_matrix(pos, math.degrees(a) + 90), focal=35.0, ok=True,
                          phone=Vector(pos) / 10.0))
    return out


def still(seconds=5.0, hz=60, noise=0.0, seed=1):
    rnd = random.Random(seed)
    out = []
    for i in range(int(seconds * hz) + 1):
        p = Vector((rnd.gauss(0, noise), rnd.gauss(0, noise), 1.5 + rnd.gauss(0, noise)))
        out.append(Sample(t=i / hz, world=cam_matrix(p, 0), focal=35.0, ok=True, phone=p.copy()))
    return out


class ResampleTest(unittest.TestCase):
    def test_circle_24fps(self):
        s = circle()
        frames = takes.resample(s, 10.0, 24.0, 1)
        self.assertIn(len(frames), (120, 121))
        self.assertEqual(frames[0].frame, 1)
        for f in frames:
            r = math.hypot(f.loc.x, f.loc.y)
            self.assertAlmostEqual(r, 2.0, delta=0.02)
            self.assertFalse(f.gap)

    def test_ntsc_and_frame_start(self):
        s = circle(t0=0.0)
        fps = 30000 / 1001
        frames = takes.resample(s, 0.0, fps, 101)
        self.assertEqual(frames[0].frame, 101)
        f = frames[30]
        self.assertEqual(f.frame, 131)
        t = 30 / fps
        self.assertAlmostEqual(t, 1.001, places=3)
        a = 2 * math.pi * t / 5.0
        self.assertAlmostEqual(f.loc.x, 2.0 * math.cos(a), delta=0.01)
        self.assertAlmostEqual(f.loc.y, 2.0 * math.sin(a), delta=0.01)

    def test_gaps_hold_last_good(self):
        s = circle(t0=0.0)
        for x in s:
            if 2.0 <= x.t <= 2.5:
                x.ok = False
        frames = takes.resample(s, 0.0, 24.0, 1)
        gaps = takes.mark_gaps(frames)
        self.assertEqual(len(gaps), 1)
        a, b = gaps[0]
        self.assertIn(a, (48, 49, 50))
        self.assertIn(b, (60, 61, 62))
        last_good = next(f for f in frames if f.frame == a - 1)
        for f in frames:
            if a <= f.frame <= b:
                self.assertTrue(f.gap)
                self.assertAlmostEqual((f.loc - last_good.loc).length, 0, places=6)
        after = next(f for f in frames if f.frame == b + 1)
        self.assertFalse(after.gap)

    def test_jump_marked(self):
        s = still()
        for x in s:
            if x.t >= 3.0:
                x.phone = x.phone + Vector((0.5, 0, 0))
                x.world = x.world.copy()
                x.world.translation += Vector((5, 0, 0))
        frames = takes.resample(s, 0.0, 24.0, 1)
        gaps = takes.mark_gaps(frames)
        self.assertEqual(len(gaps), 1)
        self.assertTrue(72 <= gaps[0][0] <= 74)

    def test_yaw_wrap_no_jumps(self):
        out = []
        for i in range(121):
            yaw = 170 + i * (20 / 120)  # 170 .. 190 == -170
            if yaw > 180:
                yaw -= 360
            out.append(Sample(t=i / 60, world=cam_matrix((0, 0, 1), yaw), focal=35, ok=True, phone=Vector()))
        frames = takes.make_continuous(takes.resample(out, 0.0, 24.0, 1))
        for a, b in zip(frames, frames[1:]):
            self.assertLess(math.degrees(a.quat.rotation_difference(b.quat).angle), 15)
            self.assertGreater(a.quat.dot(b.quat), 0)
            e1 = a.quat.to_euler("XYZ")
            e2 = b.quat.to_euler("XYZ", e1)
            self.assertLess(max(abs(x - y) for x, y in zip(e1, e2)), math.radians(15))

    def test_smooth(self):
        frames = takes.resample(still(noise=0.005), 0.0, 24.0, 1)
        same = takes.smooth(frames, 0.0)
        for a, b in zip(frames, same):
            self.assertEqual(tuple(a.loc), tuple(b.loc))
            self.assertEqual(tuple(a.quat), tuple(b.quat))

        def var(fr):
            return sum((f.loc - Vector((0, 0, 1.5))).length_squared for f in fr) / len(fr)

        sm = takes.smooth(frames, 1.0)
        self.assertEqual(len(sm), len(frames))
        self.assertGreaterEqual(var(frames) / var(sm), 3.0)
        for f in sm:
            self.assertAlmostEqual(f.quat.magnitude, 1.0, places=5)


class BakeTest(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=False)
        self.cam = bpy.data.objects["Camera"]

    def fcurve_keys(self, action, path, index=0):
        fc = action.fcurves.find(path, index=index)
        return [tuple(k.co) for k in fc.keyframe_points]

    def test_bake_and_rebake(self):
        s = circle(t0=0.0)
        self.assertEqual(takes.next_take_name(bpy.data), "Take_01")
        frames = takes.resample(s, 0.0, 24.0, 1)
        act = takes.bake(self.cam, frames, "Take_01", s, t0=0.0, fps=24.0, frame_start=1, strength=0.0)
        self.assertEqual(act.name, "Take_01")
        self.assertIs(self.cam.animation_data.action, act)
        self.assertEqual(self.cam.rotation_mode, "QUATERNION")
        self.assertGreaterEqual(len(self.fcurve_keys(act, "location")), 120)
        self.assertIsNotNone(act.fcurves.find("rotation_quaternion", index=3))
        lens_act = self.cam.data.animation_data.action
        self.assertEqual(lens_act.name, "Take_01_lens")
        txt = bpy.data.texts["Blendcam_Take_01.json"]
        raw = json.loads(txt.as_string())
        self.assertEqual(len(raw["samples"]), len(s))

        bpy.context.scene.frame_set(1 + 24)
        a = 2 * math.pi * 1.0 / 5.0
        self.assertAlmostEqual(self.cam.matrix_world.translation.x, 2 * math.cos(a), delta=0.01)

        before = self.fcurve_keys(act, "location")
        self.assertEqual(takes.next_take_name(bpy.data), "Take_02")
        s2 = still()
        act2 = takes.bake(self.cam, takes.resample(s2, 0.0, 24.0, 1), "Take_02", s2,
                          t0=0.0, fps=24.0, frame_start=1, strength=0.0)
        self.assertEqual(act2.name, "Take_02")
        self.assertEqual(self.fcurve_keys(bpy.data.actions["Take_01"], "location"), before)

        # rebake Take_01 with strong smoothing: keys change, raw data does not
        raw_before = json.loads(bpy.data.texts["Blendcam_Take_01.json"].as_string())["samples"]
        takes.rebake(self.cam, "Take_01", 1.0)
        after = self.fcurve_keys(bpy.data.actions["Take_01"], "location")
        self.assertEqual(len(after), len(before))
        self.assertNotEqual(after, before)
        meta = json.loads(bpy.data.texts["Blendcam_Take_01.json"].as_string())
        self.assertEqual(meta["samples"], raw_before)
        self.assertEqual(meta["smooth"], 1.0)
        self.assertIs(self.cam.animation_data.action, bpy.data.actions["Take_01"])

    def test_take_info(self):
        s = circle(t0=0.0)
        for x in s:
            if 2.0 <= x.t <= 2.5:
                x.ok = False
        frames = takes.resample(s, 0.0, 24.0, 1)
        takes.bake(self.cam, frames, "Take_01", s, t0=0.0, fps=24.0, frame_start=1, strength=0.0)
        info = takes.take_info(bpy.data, "Take_01")
        self.assertEqual(info["frame_start"], 1)
        self.assertEqual(info["frame_end"], frames[-1].frame)
        self.assertEqual(len(info["gaps"]), 1)
        self.assertEqual(takes.list_takes(bpy.data), ["Take_01"])
