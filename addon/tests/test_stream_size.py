import unittest

from blendcam.stream import stream_size


class StreamSizeTest(unittest.TestCase):
    def test_stream_size(self):
        self.assertEqual(stream_size("high", 1920, 1080), (1280, 720))
        self.assertEqual(stream_size("normal", 1920, 1080), (640, 360))
        self.assertEqual(stream_size("high", 1080, 1920), (720, 1280))  # vertical: long side 1280
        self.assertEqual(stream_size("normal", 1080, 1920), (360, 640))
        w, h = stream_size("high", 2048, 858)  # scope 2.39:1, odd height rounds to even
        self.assertEqual(w, 1280)
        self.assertEqual(h % 2, 0)
        self.assertAlmostEqual(w / h, 2048 / 858, delta=0.02)
        self.assertEqual(stream_size("bogus", 1920, 1080), (1280, 720))
