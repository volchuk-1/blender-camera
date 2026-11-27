"""Stage 3 in the live session: presets, roll lock, orbit modes, baking with presets, protocol fields."""
import json
import math
import os
import time
import unittest

import bpy
from mathutils import Matrix, Vector

from blendcam import runtime, takes

from helpers import fresh_scene, pose

FIX = os.path.join(os.path.dirname(__file__), "..", "..", "protocol", "fixtures")


def ar_rot(yaw=0.0, pitch=0.0, roll=0.0, pos=(0.0, 1.4, 0.0)):
    """ARKit (Y up) camera matrix, column-major: heading about +Y, pitch about X, roll about Z."""
    r = (Matrix.Rotation(math.radians(yaw), 3, "Y") @ Matrix.Rotation(math.radians(pitch), 3, "X")
         @ Matrix.Rotation(math.radians(roll), 3, "Z")).to_4x4()
    r.translation = Vector(pos)
    return [r[row][col] for col in range(4) for row in range(4)]


def fwd(m):
    return (m.to_3x3() @ Vector((0, 0, -1))).normalized()


def angle_to(m, target):
    return math.degrees(fwd(m).angle((Vector(target) - m.translation).normalized()))


def rot_delta(a, b):
    qa, qb = a.to_quaternion(), b.to_quaternion()
    return math.degrees(2 * math.acos(min(1.0, abs(qa.dot(qb)))))


class V3Base(unittest.TestCase):
    def setUp(self):
        self.scene = fresh_scene()
        self.st = self.scene.blendcam
        self.cam = self.scene.camera
        self.s = runtime.Session().start(bpy.context, port=0, token="tt", register_timer=False)
        self.seq = 0

    def tearDown(self):
        s = runtime.get_session()
        if s is not None:
            s.stop()

    def feed(self, m16, n=1, joy=(0.0, 0.0), trk="normal"):
        for _ in range(n):
            self.seq += 1
            self.s._inject_pose(pose(self.seq, m16, joy=joy, trk=trk, focal=0.0))
            self.s.server._last_packet = time.monotonic()
            self.s.tick()
        return self.cam.matrix_world.copy()


class SwitchTest(V3Base):
    def test_switch_no_jump(self):
        cube = bpy.data.objects["Cube"].matrix_world.translation.copy()
        cases = [("preset", "crane"), ("preset", "tripod"), ("preset", "handheld"), ("preset", "custom"),
                 ("roll_lock", True), ("roll_lock", False), ("orbit", "turntable"), ("orbit", "target"),
                 ("orbit", "off")]
        self.feed(ar_rot(), 30)
        for key, value in cases:
            before = self.feed(ar_rot(), 10)
            setattr(self.st, key, value)
            after = self.feed(ar_rot(), 1)
            self.assertLess((after.translation - before.translation).length, 1e-3, (key, value))
            if key == "orbit":
                # entering/leaving an orbit re-aims the camera: it must glide (live filter), never snap
                self.assertLess(rot_delta(before, after), 5.0, (key, value))
            else:
                self.assertLess(rot_delta(before, after), 0.1, (key, value))

    def test_tripod_holds_position(self):
        self.st.preset = "tripod"
        start = self.feed(ar_rot(), 20)
        for i in range(60):
            m = self.feed(ar_rot(yaw=-i * 0.5, pos=(0.0, 1.4, -i / 60.0)))
        self.assertLess((m.translation - start.translation).length, 1e-3)
        self.assertGreater(rot_delta(start, m), 10)

    def test_roll_lock_live(self):
        self.st.roll_lock = True
        self.feed(ar_rot(), 10)
        m = self.feed(ar_rot(roll=15), 180)
        right = m.to_3x3() @ Vector((1, 0, 0))
        self.assertAlmostEqual(right.z, 0.0, places=4)


class OrbitTest(V3Base):
    def test_target_mode_centers(self):
        cube = bpy.data.objects["Cube"].matrix_world.translation.copy()
        self.feed(ar_rot(), 10)
        self.st.orbit_target = bpy.data.objects["Cube"]
        self.st.orbit = "target"
        self.st.orbit_hold = 1.0
        for i in range(120):
            m = self.feed(ar_rot(pos=(i / 120.0, 1.4, 0.0)))  # walk 1 m sideways
        m = self.feed(ar_rot(pos=(1.0, 1.4, 0.0)), 60)
        self.assertLess(angle_to(m, cube), 1.0)
        self.assertEqual(self.s.state_message()["target"], "Cube")

    def test_active_object_becomes_target(self):
        bpy.context.view_layer.objects.active = bpy.data.objects["Cube"]
        self.feed(ar_rot(), 5)
        self.st.orbit = "target"
        self.feed(ar_rot(), 1)
        self.assertEqual(self.st.orbit_target.name, "Cube")

    def test_turntable_mode(self):
        cube = bpy.data.objects["Cube"].matrix_world.translation.copy()
        self.st.orbit_target = bpy.data.objects["Cube"]
        self.feed(ar_rot(), 10)
        self.st.orbit = "turntable"
        start = self.feed(ar_rot(), 1)
        d0 = start.translation - cube
        for i in range(61):
            self.feed(ar_rot(yaw=-90 * i / 60))  # turn right 90 deg in 1 s
        m = self.feed(ar_rot(yaw=-90), 120)
        d1 = m.translation - cube
        self.assertAlmostEqual(d1.length, d0.length, delta=0.01 * d0.length)
        az0 = math.degrees(math.atan2(d0.y, d0.x))
        az1 = math.degrees(math.atan2(d1.y, d1.x))
        self.assertAlmostEqual((az1 - az0 + 540) % 360 - 180, -90, delta=3)
        self.assertLess(angle_to(m, cube), 1.0)

    def test_target_deleted(self):
        self.st.orbit_target = bpy.data.objects["Cube"]
        self.feed(ar_rot(), 5)
        self.st.orbit = "target"
        self.feed(ar_rot(), 5)
        bpy.data.objects.remove(bpy.data.objects["Cube"])
        self.feed(ar_rot(), 2)
        self.assertEqual(self.st.orbit, "off")
        self.assertTrue(any("Ціль зникла" in t for _, t in self.s.toasts))


class BakeV3Test(V3Base):
    def test_rebake_keeps_orbit(self):
        cube = bpy.data.objects["Cube"].matrix_world.translation.copy()
        self.st.orbit_target = bpy.data.objects["Cube"]
        self.st.preset = "handheld"
        self.feed(ar_rot(), 10)
        self.st.orbit = "target"
        self.feed(ar_rot(), 90)
        self.s.start_recording(self.seq / 60.0)
        for i in range(96):
            self.feed(ar_rot(pos=(i / 96.0, 1.4, 0.0)))
        self.s._handle_control({"type": "record_stop"}, self.cam, self.scene)
        act = bpy.data.actions["Take_01"]
        before = [tuple(k.co) for k in act.fcurves.find("location", index=0).keyframe_points]
        self.st.preset = "crane"
        bpy.ops.blendcam.rebake(take="Take_01")
        after = [tuple(k.co) for k in act.fcurves.find("location", index=0).keyframe_points]
        self.assertEqual(len(after), len(before))
        self.assertNotEqual(after, before)
        info = takes.take_info(bpy.data, "Take_01")
        self.assertEqual(info["preset"], "crane")
        mid = (info["frame_start"] + info["frame_end"]) // 2
        self.scene.frame_set(mid)
        self.assertLess(angle_to(self.cam.matrix_world, cube), 2.0)


class ProtocolV3Test(V3Base):
    def test_settings_fixture_v3(self):
        with open(os.path.join(FIX, "settings_v3.json"), encoding="utf-8") as f:
            msg = json.load(f)
        self.s.apply_settings(msg, self.st)
        self.assertEqual(self.st.preset, "crane")
        self.assertTrue(self.st.roll_lock)
        self.assertEqual(self.st.orbit, "turntable")
        self.assertAlmostEqual(self.st.orbit_hold, 0.5)
        self.assertEqual(self.st.stream_quality, "normal")
        self.s.apply_settings({"type": "settings", "preset": "nonsense", "orbit": 7}, self.st)
        self.assertEqual(self.st.preset, "crane")
        self.assertEqual(self.st.orbit, "turntable")

    def test_state_has_v3_fields(self):
        st = self.s.state_message()
        for k in ("preset", "roll_lock", "orbit", "orbit_hold", "stream_quality", "target"):
            self.assertIn(k, st)
        self.assertEqual(st["preset"], "steadicam")
        self.assertEqual(st["orbit"], "off")
        self.assertEqual(st["stream_quality"], "high")
