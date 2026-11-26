"""GUI check (needs a window): export a take with the viewport-render MP4 and check it with ffprobe.

    blender --factory-startup --python addon/tests/gui_export.py
Prints `GUI_EXPORT OK <dir>` on success.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "addon"))
sys.path.insert(0, HERE)

import blendcam  # noqa: E402
from blendcam import export, takes  # noqa: E402
from test_export import circle_samples  # noqa: E402

OUT = os.path.join(tempfile.gettempdir(), "blendcam_gui_export")
state = {"step": 0}


def step():
    if state["step"] == 0:
        bpy.ops.wm.read_factory_settings()
        state["step"] = 1
        return 0.5
    ok = True
    try:
        shutil.rmtree(OUT, ignore_errors=True)
        os.makedirs(OUT, exist_ok=True)
        if bpy.context.preferences.addons.get("blendcam") is None:
            bpy.context.preferences.addons.new().module = "blendcam"
        blendcam.register()
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "scene.blend"))
        scene = bpy.context.scene
        scene.render.resolution_percentage = 50
        cam = scene.camera
        s = circle_samples(seconds=3.0)
        fps = scene.render.fps / scene.render.fps_base
        frames, gaps = takes.process(s, 0.0, fps, 1, 0.3)
        takes.bake(cam, frames, "Take_01", s, t0=0.0, fps=fps, frame_start=1, strength=0.3, gaps=gaps)
        files = export.export_take(bpy.context, "Take_01", os.path.join(OUT, "blendcam_exports"), video=True)
        print("FILES", json.dumps(files), flush=True)
        mp4 = files["mp4"]
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                                "-show_entries", "stream=nb_read_frames,width,height,codec_name:format=duration",
                                "-of", "json", mp4], capture_output=True, text=True)
        info = json.loads(probe.stdout)
        st = info["streams"][0]
        n = int(st["nb_read_frames"])
        dur = float(info["format"]["duration"])
        expect_n = frames[-1].frame - frames[0].frame + 1
        print("PROBE frames=%d expect=%d duration=%.3f expect=%.3f codec=%s size=%sx%s" % (
            n, expect_n, dur, expect_n / fps, st["codec_name"], st["width"], st["height"]), flush=True)
        if abs(n - expect_n) > 1 or abs(dur - expect_n / fps) > 1.5 / fps or st["codec_name"] != "h264":
            ok = False
        if (st["width"], st["height"]) != (scene.render.resolution_x // 2, scene.render.resolution_y // 2):
            ok = False
        if scene.render.image_settings.file_format != "PNG":
            print("render settings not restored", flush=True)
            ok = False
    except Exception as e:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        print("GUI_EXPORT error", e, flush=True)
        ok = False
    print("GUI_EXPORT %s %s" % ("OK" if ok else "FAIL", OUT), flush=True)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(step, first_interval=1.0, persistent=True)
