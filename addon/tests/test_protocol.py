import json
import os
import unittest

from blendcam import protocol

FIX = os.path.join(os.path.dirname(__file__), "..", "..", "protocol", "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name), "rb") as f:
        return f.read()


class ProtocolTest(unittest.TestCase):
    def test_pose_fixtures_parse(self):
        p = protocol.parse_pose(fixture("pose_basic.json"), "testtoken")
        self.assertIsNotNone(p)
        self.assertEqual(p.seq, 42)
        self.assertAlmostEqual(p.t, 12.5)
        self.assertEqual(len(p.m), 16)
        self.assertEqual(p.trk, "normal")
        self.assertEqual(p.joy, (0.25, -0.5))
        self.assertAlmostEqual(p.focal, 35.0)
        self.assertAlmostEqual(p.focus, 2.5)
        q = protocol.parse_pose(fixture("pose_limited.json"), "testtoken")
        self.assertEqual(q.trk, "limited")
        self.assertIsNone(q.focus)
        self.assertAlmostEqual(q.lift, 0.5)

    def test_pose_rejects(self):
        raw = json.loads(fixture("pose_basic.json"))
        self.assertIsNone(protocol.parse_pose(fixture("pose_basic.json"), "other"))
        bad = dict(raw, v=2)
        self.assertIsNone(protocol.parse_pose(json.dumps(bad).encode(), "testtoken"))
        bad = dict(raw, m=raw["m"][:15])
        self.assertIsNone(protocol.parse_pose(json.dumps(bad).encode(), "testtoken"))
        bad = dict(raw, m=raw["m"][:15] + ["x"])
        self.assertIsNone(protocol.parse_pose(json.dumps(bad).encode(), "testtoken"))
        self.assertIsNone(protocol.parse_pose(b"{not json", "testtoken"))
        self.assertIsNone(protocol.parse_pose(b"\xff\xfe", "testtoken"))
        self.assertIsNone(protocol.parse_pose(b"[1,2]", "testtoken"))

    def test_pose_filter(self):
        f = protocol.PoseFilter()
        mk = lambda s: protocol.Pose(seq=s, t=0.0, m=[0.0] * 16, trk="normal",
                                     joy=(0.0, 0.0), lift=0.0, focal=35.0, focus=None)
        self.assertEqual([f.accept(mk(s)) for s in (5, 7, 6)], [True, True, False])
        f = protocol.PoseFilter()
        self.assertTrue(f.accept(mk(1000)))
        self.assertTrue(f.accept(mk(3)))
        self.assertTrue(f.accept(mk(4)))
        self.assertFalse(f.accept(mk(2)))

    def test_control_fixtures(self):
        for name in ("hello", "record_start", "settings", "state", "toast"):
            msg = protocol.parse_control(fixture(name + ".json").strip())
            self.assertIsNotNone(msg, name)
            self.assertEqual(msg, json.loads(fixture(name + ".json")))
        self.assertIsNone(protocol.parse_control(b"garbage"))
        self.assertIsNone(protocol.parse_control(b'{"no":"type"}'))

    def test_state_roundtrip(self):
        st = json.loads(fixture("state.json"))
        enc = protocol.encode_control(st)
        self.assertTrue(enc.endswith(b"\n"))
        self.assertEqual(protocol.parse_control(enc), st)

    def test_toast_cyrillic_unescaped(self):
        enc = protocol.encode_control({"type": "toast", "text": "Дубль збережено"})
        self.assertIn("Дубль".encode("utf-8"), enc)
        self.assertNotIn(b"\u", enc)

    def test_frame_header(self):
        self.assertEqual(protocol.encode_frame_header(1234), b'{"type":"frame","len":1234}\n')
        h = protocol.encode_frame_header(1234, ts=12.5)
        self.assertEqual(json.loads(h), json.loads(fixture("frame_header.json")))
