"""End to end without a phone: fake_phone.py <-> the real Session over 127.0.0.1."""
import math
import os
import subprocess
import sys
import tempfile
import time
import unittest

import bpy

from blendcam import runtime, takes

from helpers import fresh_scene

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FAKE = os.path.join(ROOT, "tools", "fake_phone.py")


class EndToEndRecordTest(unittest.TestCase):
    def tearDown(self):
        s = runtime.get_session()
        if s is not None:
            s.stop()

    def test_record_circle(self):
        scene = fresh_scene()
        scene.blendcam.scale = 4.0
        scene.blendcam.smooth = 0.0
        s = runtime.Session().start(bpy.context, port=0, token="e2e", register_timer=False)
        log = tempfile.TemporaryFile()
        proc = subprocess.Popen([sys.executable, FAKE, "--host", "127.0.0.1", "--port", str(s.server.port),
                                 "--token", "e2e", "--path", "circle", "--seconds", "5", "--record",
                                 "--wait", "0.5"],
                                stdout=log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 30
        while proc.poll() is None and time.monotonic() < deadline:
            s.tick()
            time.sleep(1 / 60)
        for _ in range(10):
            s.tick()
            time.sleep(1 / 60)
        proc.wait(timeout=10)
        log.seek(0)
        out = log.read().decode("utf-8", "replace")
        log.close()
        self.assertEqual(proc.returncode, 0, out)
        self.assertFalse(s.recording)
        self.assertEqual(takes.list_takes(bpy.data), ["Take_01"])
        act = bpy.data.actions["Take_01"]
        xs = act.fcurves.find("location", index=0).keyframe_points
        ys = act.fcurves.find("location", index=1).keyframe_points
        self.assertGreaterEqual(len(xs), 100)
        pts = [(a.co[1], b.co[1]) for a, b in zip(xs, ys)]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        radii = [math.hypot(x - cx, y - cy) for x, y in pts]
        avg = sum(radii) / len(radii)
        self.assertAlmostEqual(avg, 0.5 * 4.0, delta=0.1)
        self.assertLess(max(radii) - min(radii), 0.2)
        self.assertIn("збережено", out)  # the phone got the toast
        info = takes.take_info(bpy.data, "Take_01")
        self.assertEqual(info["frame_start"], scene.frame_start)
        self.assertEqual(info["gaps"], [])
