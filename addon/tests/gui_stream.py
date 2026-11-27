"""GUI check (needs a window): live picture to the phone.

fake_phone --recv-frames for 5 s: >= 75 frames (>= 15 fps), every frame a valid 1280x720 JPEG (quality high),
average latency from capture to arrival < 200 ms.

    blender --factory-startup --python addon/tests/gui_stream.py
Prints `GUI_STREAM OK {...}` on success.
"""
import json
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

LOG = os.path.join(tempfile.gettempdir(), "blendcam_gui_stream.log")
state = {"step": 0, "t": 0.0, "proc": None, "log": None}


def finish(ok, summary):
    print("GUI_STREAM %s %s" % ("OK" if ok else "FAIL", json.dumps(summary)), flush=True)
    s = runtime.get_session()
    if s is not None:
        if s.streamer is not None:
            print("STREAMER in=%d out=%d sent=%d skipped=%d error=%s" % (
                s.streamer.frames_in, s.streamer.frames_out, s.server.frames_sent, s.server.frames_skipped,
                s.streamer.error), flush=True)
        s.stop()
    bpy.ops.wm.quit_blender()


def step():
    st = state
    if st["step"] == 0:
        bpy.ops.wm.read_factory_settings()
        st["step"] = 1
        return 0.5
    if st["step"] == 1:
        if bpy.context.preferences.addons.get("blendcam") is None:
            bpy.context.preferences.addons.new().module = "blendcam"
        blendcam.register()
        bpy.context.scene.blendcam.show_qr = False
        win = bpy.context.window_manager.windows[0]
        area = next(a for a in win.screen.areas if a.type == "VIEW_3D")
        with bpy.context.temp_override(window=win, area=area):
            bpy.ops.blendcam.start()
        s = runtime.get_session()
        if s.streamer is None:
            finish(False, {"error": "no streamer"})
            return None
        st["log"] = open(LOG, "wb")
        st["proc"] = subprocess.Popen([sys.executable, os.path.join(ROOT, "tools", "fake_phone.py"),
                                       "--port", str(s.server.port), "--token", s.server.token,
                                       "--path", "circle", "--seconds", "5", "--recv-frames", "--wait", "0.3"],
                                      stdout=st["log"], stderr=subprocess.STDOUT)
        st.update(step=2, t=time.monotonic())
        return 0.2
    if st["step"] == 2:
        if st["proc"].poll() is None and time.monotonic() - st["t"] < 30:
            return 0.2
        st["log"].close()
        with open(LOG, encoding="utf-8", errors="replace") as f:
            out = f.read()
        line = next((l for l in out.splitlines() if l.startswith("FRAMES ")), None)
        if line is None:
            finish(False, {"error": "no FRAMES line", "out": out[-500:]})
            return None
        summ = json.loads(line[7:])
        ok = (summ["frames"] >= 75 and summ["bad"] == 0 and summ["sizes"] == [[1280, 720]]
              and summ["latency_ms_avg"] is not None and summ["latency_ms_avg"] < 200)
        finish(ok, summ)
        return None
    return 0.2


bpy.app.timers.register(step, first_interval=1.0, persistent=True)
