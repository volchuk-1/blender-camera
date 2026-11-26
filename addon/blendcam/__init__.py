bl_info = {
    "name": "Blendcam",
    "author": "volchuk-1",
    "version": (0, 1, 0),
    "blender": (4, 5, 0),
    "location": "3D View > Sidebar (N) > Blendcam",
    "description": "Use an iPhone (ARKit) as a handheld camera: live control, take recording, export",
    "category": "Camera",
}

if "bpy" in locals():
    import importlib

    for _m in (protocol, mapping, takes, server, qr, prefs, runtime, ops, ui):  # noqa: F821
        importlib.reload(_m)

import bpy  # noqa: E402

from . import mapping, ops, prefs, protocol, qr, runtime, server, takes, ui  # noqa: E402,F401


def register():
    prefs.register()
    ops.register()
    ui.register()


def unregister():
    s = runtime.get_session()
    if s is not None:
        s.stop()
    ui.unregister()
    ops.unregister()
    prefs.unregister()
