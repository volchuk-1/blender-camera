"""Regression tests for the stage-3 review findings (switching while MOVING, raw take samples)."""
import math
import time
import unittest

import bpy
from mathutils import Vector

from test_runtime_v3 import V3Base, angle_to, ar_rot


class ReviewV3Test(V3Base):
    def walk(self, i, speed=1.0):
        return ar_rot(pos=(0.0, 1.4, -speed * i / 60.0))  # forward at `speed` m/s

    def test_preset_switch_keeps_target(self):
        cube = bpy.data.objects["Cube"].matrix_world.translation.copy()
        self.st.orbit_target = bpy.data.objects["Cube"]
        self.feed(ar_rot(), 10)
        self.st.orbit = "target"
        self.feed(ar_rot(pitch=-10), 180)
        for key, value in (("preset", "crane"), ("roll_lock", True), ("preset", "handheld"), ("roll_lock", False)):
            setattr(self.st, key, value)
            worst = 0.0
            for _ in range(90):
                worst = max(worst, angle_to(self.feed(ar_rot(pitch=-10)), cube))
            self.assertLess(worst, 1.5, (key, value))

    def test_switch_during_recording_no_step(self):
        self.st.preset = "crane"
        i = 0
        for _ in range(30):
            self.feed(self.walk(i))
            i += 1
        self.s.start_recording(self.seq / 60.0)
        bpy.context.view_layer.objects.active = bpy.data.objects["Cube"]
        switches = {30: ("preset", "steadicam"), 60: ("orbit", "target"), 90: ("preset", "tripod"),
                    120: ("preset", "handheld"), 150: ("orbit", "off")}
        for k in range(180):
            if k in switches:
                setattr(self.st, *switches[k])
            self.feed(self.walk(i))
            i += 1
        locs = [s.world.translation for s in self.s.samples]
        steps = [(b - a).length for a, b in zip(locs, locs[1:])]
        self.assertLess(max(steps), 0.05, "max raw step %.3f m" % max(steps))
        quats = [s.world.to_quaternion() for s in self.s.samples]
        rsteps = [math.degrees(2 * math.acos(min(1, abs(a.dot(b))))) for a, b in zip(quats, quats[1:])]
        self.assertLess(max(rsteps), 6.0, "max raw rotation step %.2f deg" % max(rsteps))

    def test_reconnect_target_aims(self):
        cube = bpy.data.objects["Cube"].matrix_world.translation.copy()
        self.st.orbit_target = bpy.data.objects["Cube"]
        self.seq = 6_000_000  # old phone: uptime ~100 000 s
        self.feed(ar_rot(), 10)
        self.st.orbit = "target"
        self.feed(ar_rot(), 120)
        # another phone / reboot: hello, then much lower phone uptime
        self.s._handle_control({"type": "hello", "device": "x"}, self.cam, self.scene)
        self.s.server._filter.reset()
        for n in range(240):
            self.s._inject_pose(__import__("helpers").pose(n, ar_rot(pos=(0.5, 1.4, 0.0)), t=1.0 + n / 60.0,
                                                           focal=0.0))
            self.s.server._last_packet = time.monotonic()
            self.s.tick()
        self.assertLess(angle_to(self.cam.matrix_world, cube), 1.0)

    def test_no_duplicate_samples(self):
        self.feed(ar_rot(), 5)
        self.s.start_recording(self.seq / 60.0)
        self.feed(ar_rot(), 10)
        n = len(self.s.samples)
        for _ in range(20):  # ticks without new packets (Wi-Fi stall shorter than LIVE_AGE)
            self.s.server._last_packet = time.monotonic()
            self.s.tick()
        self.assertEqual(len(self.s.samples), n)
        ts = [s.t for s in self.s.samples]
        self.assertEqual(ts, sorted(set(ts)))

    def test_roll_lock_not_in_raw(self):
        self.st.roll_lock = True
        self.feed(ar_rot(roll=15), 10)
        self.s.start_recording(self.seq / 60.0)
        self.feed(ar_rot(roll=15), 60)
        right = self.s.samples[-1].world.to_3x3() @ Vector((1, 0, 0))
        self.assertGreater(abs(right.z), 0.1)  # raw keeps the hand-held roll
        self.s._handle_control({"type": "record_stop"}, self.cam, self.scene)
        self.scene.frame_set(20)
        right = self.cam.matrix_world.to_3x3() @ Vector((1, 0, 0))
        self.assertAlmostEqual(right.z, 0.0, places=3)  # baked take is level
