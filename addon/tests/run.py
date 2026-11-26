"""Run the add-on unit tests inside Blender.

    blender -b --factory-startup --python addon/tests/run.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ROOT = os.path.dirname(HERE)
for p in (ADDON_ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

pattern = os.environ.get("BLENDCAM_TEST_PATTERN", "test_*.py")
suite = unittest.defaultTestLoader.discover(HERE, pattern=pattern, top_level_dir=HERE)
result = unittest.TextTestRunner(verbosity=1).run(suite)
sys.stdout.flush()
sys.exit(0 if result.wasSuccessful() else 1)
