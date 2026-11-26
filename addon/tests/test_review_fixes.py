"""Regression tests for the final review findings."""
import json
import math
import os
import shutil
import tempfile
import time
import unittest

import bpy
from mathutils import Euler, Matrix, Vector

from blendcam import export, mapping, protocol, runtime, takes
from blendcam.takes import Sample

from helpers import ar_m, fresh_scene, pose


def mk(seq, t):
    return protocol.Pose(seq=seq, t=t, m=[0.0] * 16, trk="normal", joy=(0.0, 0.0), lift=0.0,
                         focal=0.0, focus=None)


class ArRestartTest(unittest.TestCase):
    """Critical 1: AR session restart (seq back to 0, phone time keeps rising) without a new hello."""

    def test_filter_accepts_restart_rejects_reordered(self):
        f = protocol.PoseFilter()
        self.assertTrue(f.accept(mk(500, 100.0)))
        self.assertFalse(f.accept(mk(499, 99.98)))   # reordered old packet
        self.assertTrue(f.accept(mk(0, 105.0)))      # restart: lower seq, newer time
        self.assertTrue(f.restarted)
        self.assertTrue(f.accept(mk(1, 105.02)))
        self.assertFalse(f.restarted)

    def tearDown(self):
        s = runtime.get_session()
        if s is not None:
            s.stop()

    def test_runtime_reanchors_on_restart(self):
        scene = fresh_scene()
        cam = scene.camera
        s = runtime.Session().start(bpy.context, port=0, token="tt", register_timer=False)
        s.server._filter.accept(mk(0, 0.0))
        s._inject_pose(pose(500, ar_m(0, 1.4, 0), t=10.0))
        s.tick()
        s._inject_pose(pose(501, ar_m(0, 1.4, -1.0), t=10.02))
        s.tick()
        here = cam.matrix_world.translation.copy()
        # AR restarted: new world origin, the phone is now at (3, 1.4, 3) in the new world
        p = pose(0, ar_m(3, 1.4, 3), t=12.0)
        self.assertTrue(s.server._filter.accept(p))
        s._inject_pose(p)
        self.assertTrue(s.server._filter.restarted)
        s.server._controls.append({"type": "_restart"})
        s.tick()
        self.assertLess((cam.matrix_world.translation - here).length, 1e-4)


class FocalAndAnimationTest(unittest.TestCase):
    def tearDown(self):
        s = runtime.get_session()
        if s is not None:
            s.stop()

    def test_focal_zero_keeps_lens(self):
        scene = fresh_scene()
        cam = scene.camera
        cam.data.lens = 50.0
        s = runtime.Session().start(bpy.context, port=0, token="tt", register_timer=False)
        s._inject_pose(pose(1, ar_m(0, 1.4, 0), focal=0.0))
        s.tick()
        self.assertEqual(cam.data.lens, 50.0)

    def test_user_action_kept_with_fake_user(self):
        scene = fresh_scene()
        cam = scene.camera
        cam.keyframe_insert("location", frame=1)
        user_act = cam.animation_data.action
        s = runtime.Session().start(bpy.context, port=0, token="tt", register_timer=False)
        s._inject_pose(pose(1, ar_m(0, 1.4, 0)))
        s.tick()
        self.assertIsNone(cam.animation_data.action)
        self.assertTrue(user_act.use_fake_user)

    def test_take_stays_on_camera_after_recording(self):
        scene = fresh_scene()
        cam = scene.camera
        s = runtime.Session().start(bpy.context, port=0, token="tt", register_timer=False)
        s._inject_pose(pose(1, ar_m(0, 1.4, 0)))
        s.tick()
        s.start_recording(1 / 60)
        for i in range(2, 40):
            s._inject_pose(pose(i, ar_m(0.01 * i, 1.4, 0)))
            s.server._last_packet = time.monotonic()
            s.tick()
        self.assertTrue(s.recording)
        s._handle_control({"type": "record_stop"}, cam, scene)
        self.assertFalse(scene.blendcam.live)
        s._inject_pose(pose(41, ar_m(0.5, 1.4, 0)))
        s.tick()
        self.assertEqual(cam.animation_data.action.name, "Take_01")
        # anchor turns live control back on
        self.assertTrue(s.do_anchor())
        self.assertTrue(scene.blendcam.live)

    def test_tick_survives_exception(self):
        fresh_scene()
        s = runtime.Session().start(bpy.context, port=0, token="tt", register_timer=False)

        def boom():
            raise RuntimeError("boom")

        s._tick = boom
        self.assertEqual(s.tick(), runtime.TICK)
        self.assertTrue(s.running)


class YawTest(unittest.TestCase):
    def test_yaw_exact_with_pitch_and_roll(self):
        for pitch, roll in ((-30, 10), (-45, 20), (20, -15)):
            # heading 45, then pitch about the camera's right axis, then roll about its view axis
            m = (Matrix.Rotation(math.radians(45), 4, "Z") @ Matrix.Rotation(math.radians(90 + pitch), 4, "X")
                 @ Matrix.Rotation(math.radians(roll), 4, "Z"))
            self.assertAlmostEqual(math.degrees(mapping.yaw_of(m)), 45.0, places=3, msg=(pitch, roll))


def circle(seconds=3.0, hz=60, R=2.0, yaw0=170.0):
    out = []
    for i in range(int(seconds * hz) + 1):
        t = i / hz
        yaw = yaw0 + 20 * t / seconds  # crosses +-180
        m = Euler((math.radians(90), 0, math.radians(yaw)), "XYZ").to_matrix().to_4x4()
        m.translation = Vector((R * math.cos(t), R * math.sin(t), 1.5))
        out.append(Sample(t=t, world=m, focal=35.0, ok=True, phone=m.translation / 10))
    return out


class ExportContinuityTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="blendcam_rf_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_json_no_euler_or_quaternion_jumps(self):
        scene = fresh_scene()
        cam = scene.camera
        s = circle()
        frames, gaps = takes.process(s, 0.0, 24.0, 1, 0.0)
        takes.bake(cam, frames, "Take_01", s, t0=0.0, fps=24.0, frame_start=1, strength=0.0, gaps=gaps)
        files = export.export_take(bpy.context, "Take_01", self.dir, video=False)
        with open(files["json"], encoding="utf-8") as f:
            fr = json.load(f)["frames"]
        for a, b in zip(fr, fr[1:]):
            self.assertLess(max(abs(x - y) for x, y in zip(a["euler"], b["euler"])), 0.2)
            self.assertGreater(sum(x * y for x, y in zip(a["quaternion"], b["quaternion"])), 0)

    def test_take_on_another_camera(self):
        scene = fresh_scene()
        cam = scene.camera
        s = circle()
        frames, gaps = takes.process(s, 0.0, 24.0, 1, 0.0)
        takes.bake(cam, frames, "Take_01", s, t0=0.0, fps=24.0, frame_start=1, strength=0.0, gaps=gaps)
        data = bpy.data.cameras.new("Cam2")
        cam2 = bpy.data.objects.new("Cam2", data)
        scene.collection.objects.link(cam2)
        takes.activate(cam2, "Take_01")
        scene.frame_set(25)
        self.assertAlmostEqual(cam2.matrix_world.translation.x, frames[24].loc.x, places=3)
