"""GUI check (needs a window): panel, QR overlay, connected status. Saves screenshots and quits.

    blender --factory-startup --python addon/tests/gui_panel.py
Prints `GUI_PANEL OK <dir>` on success.
"""
import os
import subprocess
import sys
import tempfile
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "addon"))
sys.path.insert(0, HERE)

import blendcam  # noqa: E402
from blendcam import runtime  # noqa: E402

OUT = os.path.join(tempfile.gettempdir(), "blendcam_gui")
os.makedirs(OUT, exist_ok=True)
state = {"step": 0, "proc": None, "t": time.monotonic(), "ok": True, "log": None}


def view3d():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == "VIEW_3D":
            return win, area
    return win, None


def shot(name):
    win, area = view3d()
    path = os.path.join(OUT, name)
    with bpy.context.temp_override(window=win, area=area):
        bpy.ops.screen.screenshot(filepath=path)
    print("SCREENSHOT", path, flush=True)
    return path


def step():
    s = runtime.get_session()
    st = state
    elapsed = time.monotonic() - st["t"]
    if st["step"] == 0:
        bpy.ops.wm.read_factory_settings()  # also closes the splash screen
        st["step"] = 0.5
        return 0.5
    if st["step"] == 0.5:
        if bpy.context.preferences.addons.get("blendcam") is None:
            bpy.context.preferences.addons.new().module = "blendcam"
        blendcam.register()
        win, area = view3d()
        area.spaces.active.show_region_ui = True
        for r in area.regions:
            if r.type == "UI":
                try:
                    r.active_panel_category = "Blendcam"
                except (AttributeError, TypeError) as e:
                    print("active_panel_category:", e, flush=True)
                print("category now:", getattr(r, "active_panel_category", None), flush=True)
        with bpy.context.temp_override(window=win, area=area):
            bpy.ops.blendcam.start()
        st.update(step=1, t=time.monotonic())
        return 0.2
    if st["step"] == 1 and elapsed > 2.0:
        shot("panel_qr.png")
        # the sidebar tab cannot be switched from Python: show the panel in the "Item" tab for the screenshots
        from blendcam import ui
        bpy.utils.unregister_class(ui.VIEW3D_PT_blendcam)
        ui.VIEW3D_PT_blendcam.bl_category = "Item"
        bpy.utils.register_class(ui.VIEW3D_PT_blendcam)
        bpy.context.active_object.select_set(False)
        bpy.context.view_layer.objects.active = None
        s = runtime.get_session()
        st["log"] = open(os.path.join(OUT, "fake_phone.log"), "wb")
        st["proc"] = subprocess.Popen([sys.executable, os.path.join(ROOT, "tools", "fake_phone.py"),
                                       "--port", str(s.server.port), "--token", s.server.token,
                                       "--path", "circle", "--seconds", "5", "--record", "--wait", "1.0"],
                                      stdout=st["log"], stderr=subprocess.STDOUT)
        st.update(step=2, t=time.monotonic())
        return 0.2
    if st["step"] == 2 and elapsed > 2.5:
        shot("panel_connected.png")
        if not (s and s.server.client_name):
            print("GUI_PANEL FAIL: phone not connected", flush=True)
            st["ok"] = False
        st.update(step=3, t=time.monotonic())
        return 0.2
    if st["step"] == 3 and (st["proc"].poll() is not None or elapsed > 20):
        st.update(step=4, t=time.monotonic())
        return 0.5
    if st["step"] == 4 and elapsed > 1.0:
        shot("panel_after_take.png")
        names = [a.name for a in bpy.data.actions]
        if "Take_01" not in names:
            print("GUI_PANEL FAIL: no Take_01, actions:", names, flush=True)
            st["ok"] = False
        print("GUI_PANEL %s %s" % ("OK" if st["ok"] else "FAIL", OUT), flush=True)
        if s:
            s.stop()
        st["log"].close()
        bpy.ops.wm.quit_blender()
        return None
    return 0.1


bpy.app.timers.register(step, first_interval=1.0, persistent=True)
