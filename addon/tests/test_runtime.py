import math
import time
import unittest

import bpy
from mathutils import Vector

import blendcam
from blendcam import prefs, qr, runtime, takes

from helpers import ar_m, fresh_scene, pose


class RuntimeTest(unittest.TestCase):
    def tearDown(self):
        s = runtime.get_session()
        if s is not None:
            s.stop()

    def start(self, scene=None):
        return runtime.Session().start(bpy.context, port=0, token="tt", register_timer=False)

    def test_creates_camera_when_missing(self):
        scene = fresh_scene(empty=True)
        self.assertIsNone(scene.camera)
        s = self.start()
        self.assertIsNotNone(scene.camera)
        self.assertEqual(scene.camera.name, "Blendcam_Camera")
        self.assertEqual(scene.camera.type, "CAMERA")
        self.assertEqual(s.cam_name, "Blendcam_Camera")

    def test_non_camera_active_object_replaced(self):
        scene = fresh_scene()
        scene.camera = bpy.data.objects["Cube"]
        self.start()
        self.assertEqual(scene.camera.type, "CAMERA")

    def test_pose_moves_camera_and_anchor_keeps_place(self):
        scene = fresh_scene()
        cam = scene.camera
        start = cam.matrix_world.translation.copy()
        s = self.start()
        s._inject_pose(pose(1, ar_m(0, 1.4, 0)))
        s.tick()
        # first pose auto-anchors: camera stays where it was
        self.assertLess((cam.matrix_world.translation - start).length, 1e-4)
        s._inject_pose(pose(2, ar_m(0, 1.4, -1.0)))  # 1 m forward
        s.tick()
        moved = cam.matrix_world.translation - start
        self.assertAlmostEqual(moved.length, 1.0, places=3)
        # horizon level: right vector horizontal
        right = cam.matrix_world.to_3x3() @ Vector((1, 0, 0))
        self.assertAlmostEqual(right.z, 0.0, places=4)
        # anchor: camera stays where it is now
        here = cam.matrix_world.translation.copy()
        self.assertTrue(s.do_anchor())
        s._inject_pose(pose(3, ar_m(0, 1.4, -1.0)))
        s.tick()
        self.assertLess((cam.matrix_world.translation - here).length, 1e-4)

    def test_scale_setting_from_phone(self):
        scene = fresh_scene()
        cam = scene.camera
        s = self.start()
        s.apply_settings({"type": "settings", "scale": 10.0, "smooth": 0.5, "roll_deg": 90,
                          "mirror_x": True}, scene.blendcam)
        self.assertEqual(scene.blendcam.scale, 10.0)
        self.assertEqual(scene.blendcam.roll_deg, "90")
        self.assertTrue(scene.blendcam.mirror_x)
        s.apply_settings({"type": "settings", "mirror_x": False, "roll_deg": 0}, scene.blendcam)
        s._inject_pose(pose(1, ar_m(0, 1.4, 0)))
        s.tick()
        a = cam.matrix_world.translation.copy()
        s._inject_pose(pose(2, ar_m(0, 1.4, -0.5)))
        s.tick()
        self.assertAlmostEqual((cam.matrix_world.translation - a).length, 5.0, places=3)

    def test_joystick_moves_forward(self):
        scene = fresh_scene()
        cam = scene.camera
        s = self.start()
        s._inject_pose(pose(1, ar_m(0, 1.4, 0)))
        s.tick()
        a = cam.matrix_world.translation.copy()
        heading = cam.matrix_world.to_3x3() @ Vector((0, 0, -1))
        heading.z = 0
        heading.normalize()
        for i in range(2, 32):
            s._inject_pose(pose(i, ar_m(0, 1.4, 0), joy=(0.0, 1.0)))
            time.sleep(1 / 60)
            s.tick()
        d = cam.matrix_world.translation - a
        self.assertGreater(d.length, 0.3)
        self.assertGreater(d.normalized().dot(heading), 0.99)

    def test_recording_stops_on_silence(self):
        scene = fresh_scene()
        s = self.start()
        s._inject_pose(pose(1, ar_m(0, 1.4, 0)))
        s.tick()
        s.start_recording(1 / 60)
        for i in range(2, 62):
            s._inject_pose(pose(i, ar_m(0.01 * i, 1.4, 0)))
            s.server._last_packet = time.monotonic()
            s.tick()
        self.assertTrue(s.recording)
        s.server._last_packet = time.monotonic() - 1.2  # phone went silent
        s.tick()
        self.assertFalse(s.recording)
        self.assertEqual(takes.list_takes(bpy.data), ["Take_01"])
        self.assertTrue(any("Зв'язок втрачено" in t for _, t in s.toasts))
        act = bpy.data.actions["Take_01"]
        self.assertGreater(len(act.fcurves.find("location", index=0).keyframe_points), 20)

    def test_token_survives_reregister(self):
        fresh_scene()
        p = prefs.get()
        self.assertIsNotNone(p)
        t = prefs.get_token()
        self.assertTrue(t)
        blendcam.unregister()
        blendcam.register()
        self.assertEqual(prefs.get_token(), t)
        new = prefs.set_new_token()
        self.assertNotEqual(new, t)
        self.assertEqual(prefs.get_token(), new)

    def test_state_message(self):
        scene = fresh_scene()
        s = self.start()
        st = s.state_message()
        for k in ("connected", "recording", "frame", "frame_start", "frame_end", "fps", "focal",
                  "camera", "take"):
            self.assertIn(k, st)
        self.assertEqual(st["take"], "Take_01")
        self.assertEqual(st["camera"], scene.camera.name)

    def test_network_report(self):
        fresh_scene()
        s = self.start()
        lines = s.network_report()
        self.assertTrue(any("слухається" in l for l in lines))


class QrTest(unittest.TestCase):
    def test_structure(self):
        m = qr.encode("blendcam://192.168.1.5:52700?token=abcDEF12_-x")
        n = len(m)
        self.assertEqual(n, 33)  # version 4
        self.assertTrue(all(len(r) == n for r in m))
        for (cx, cy) in ((0, 0), (n - 7, 0), (0, n - 7)):  # finder patterns
            self.assertTrue(all(m[cy][cx + i] for i in range(7)))
            self.assertTrue(all(m[cy + 6][cx + i] for i in range(7)))
            self.assertFalse(m[cy + 1][cx + 1])
            self.assertTrue(m[cy + 3][cx + 3])
        self.assertEqual(qr.encode("A"), qr.encode("A"))
        self.assertEqual(sum(l for _, _, l in qr.runs(m)), sum(sum(r) for r in m))
