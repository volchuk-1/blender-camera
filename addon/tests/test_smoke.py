import unittest

import blendcam


class SmokeTest(unittest.TestCase):
    def test_bl_info(self):
        self.assertEqual(blendcam.bl_info["blender"], (4, 5, 0))
