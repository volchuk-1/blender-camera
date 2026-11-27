"""Shared helpers for tests that need the add-on registered in a fresh scene."""
import bpy

import blendcam
from blendcam import protocol, runtime

_registered = False


def fresh_scene(empty=False):
    global _registered
    s = runtime.get_session()
    if s is not None:
        s.stop()
    if _registered:
        try:
            blendcam.unregister()
        except RuntimeError:
            pass
        _registered = False
    bpy.ops.wm.read_factory_settings(use_empty=empty)
    if bpy.context.preferences.addons.get("blendcam") is None:
        bpy.context.preferences.addons.new().module = "blendcam"
    blendcam.register()
    _registered = True
    return bpy.context.scene


def raw_motion(scene):
    """Live filter off (custom preset, smoothing 0): the camera follows the phone exactly."""
    scene.blendcam.preset = "custom"
    scene.blendcam.smooth = 0.0


def pose(seq, m, t=None, trk="normal", joy=(0.0, 0.0), lift=0.0, focal=35.0):
    return protocol.Pose(seq=seq, t=seq / 60.0 if t is None else t, m=list(m), trk=trk,
                         joy=joy, lift=lift, focal=focal, focus=None)


IDENTITY = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def ar_m(x=0.0, y=0.0, z=0.0):
    m = list(IDENTITY)
    m[12], m[13], m[14] = x, y, z
    return m
