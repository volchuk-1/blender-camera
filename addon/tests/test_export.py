import json
import math
import os
import shutil
import tempfile
import unittest

import bpy
from mathutils import Euler, Vector

from blendcam import export, takes
from blendcam.takes import Sample

from helpers import fresh_scene


def circle_samples(seconds=3.0, hz=60, R=2.0):
    out = []
    for i in range(int(seconds * hz) + 1):
        t = i / hz
        a = 2 * math.pi * t / seconds
        m = Euler((math.radians(90), 0, a + math.pi / 2), "XYZ").to_matrix().to_4x4()
        m.translation = Vector((R * math.cos(a), R * math.sin(a), 1.5))
        out.append(Sample(t=t, world=m, focal=30.0 + 10 * t, ok=True, phone=m.translation / 10))
    return out


def make_take(scene, frame_start=10):
    cam = scene.camera
    s = circle_samples()
    scene.frame_start = frame_start
    fps = scene.render.fps / scene.render.fps_base
    frames, gaps = takes.process(s, 0.0, fps, frame_start, 0.0)
    takes.bake(cam, frames, "Take_01", s, t0=0.0, fps=fps, frame_start=frame_start, strength=0.0, gaps=gaps)
    return cam, frames


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="blendcam_export_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_json_and_fbx(self):
        scene = fresh_scene()
        cam, frames = make_take(scene)
        files = export.export_take(bpy.context, "Take_01", self.dir, video=False)
        self.assertEqual(set(files), {"json", "fbx"})
        with open(files["json"], encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["take"], "Take_01")
        self.assertEqual(data["frame_start"], 10)
        self.assertEqual(data["frame_end"], frames[-1].frame)
        self.assertEqual(len(data["frames"]), frames[-1].frame - 10 + 1)
        self.assertEqual(data["resolution"], [scene.render.resolution_x, scene.render.resolution_y])
        self.assertAlmostEqual(data["fps"], 24.0)
        self.assertEqual(data["sensor_width"], cam.data.sensor_width)
        f0 = data["frames"][0]
        self.assertEqual(f0["frame"], 10)
        for k in ("location", "quaternion", "euler", "lens"):
            self.assertIn(k, f0)
        scene.frame_set(10)
        for a, b in zip(f0["location"], cam.matrix_world.translation):
            self.assertAlmostEqual(a, b, places=4)
        self.assertAlmostEqual(f0["lens"], cam.data.lens, places=3)
        self.assertAlmostEqual(data["frames"][24]["lens"], 40.0, delta=0.1)
        self.assertTrue(os.path.basename(files["fbx"]).endswith("Take_01_camera.fbx"))
        self.assertGreater(os.path.getsize(files["fbx"]), 1024)
        # export restores the scene
        self.assertEqual(scene.frame_start, 10)
        self.assertEqual(scene.frame_end, 250)

    def test_unknown_take(self):
        fresh_scene()
        with self.assertRaises(ValueError):
            export.export_take(bpy.context, "Take_99", self.dir, video=False)
