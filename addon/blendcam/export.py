"""Export a take for video generation: trajectory JSON, camera FBX, viewport-render MP4."""
import glob
import json
import os

import bpy

from . import takes


def _camera_for(scene, info):
    cam = bpy.data.objects.get(info.get("camera", "")) if info.get("camera") else None
    if cam is None or cam.type != "CAMERA":
        cam = scene.camera
    if cam is None or cam.type != "CAMERA":
        raise ValueError("no camera for this take")
    return cam


def _view3d_override(context):
    wm = context.window_manager
    if wm is None:
        return {}
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                return {"window": win, "screen": win.screen, "area": area, "region": region}
    return {}


def write_json(scene, cam, take_name, info, path):
    fps = scene.render.fps / scene.render.fps_base
    start, end = int(info["frame_start"]), int(info["frame_end"])
    frames = []
    for f in range(start, end + 1):
        scene.frame_set(f)
        m = cam.matrix_world
        q = m.to_quaternion()
        e = m.to_euler("XYZ")
        frames.append({
            "frame": f,
            "location": [round(v, 6) for v in m.translation],
            "quaternion": [round(v, 7) for v in q],
            "euler": [round(v, 7) for v in e],
            "lens": round(cam.data.lens, 4),
        })
    data = {
        "take": take_name,
        "fps": round(fps, 6),
        "frame_start": start,
        "frame_end": end,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "sensor_width": cam.data.sensor_width,
        "sensor_fit": cam.data.sensor_fit,
        "units": "metres, Blender world (Z up); camera looks along its local -Z, local +Y is up",
        "quaternion_order": "wxyz",
        "euler_order": "XYZ, radians",
        "frames": frames,
        "gaps": info.get("gaps", []),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return path


def write_fbx(context, cam, path):
    view_layer = context.view_layer
    selected = [o for o in view_layer.objects if o.select_get()]
    active = view_layer.objects.active
    try:
        for o in selected:
            o.select_set(False)
        cam.select_set(True)
        view_layer.objects.active = cam
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True, object_types={"CAMERA"},
                                 bake_anim=True, bake_anim_use_all_actions=False,
                                 bake_anim_use_nla_strips=False, bake_anim_simplify_factor=0.0,
                                 add_leaf_bones=False)
    finally:
        cam.select_set(False)
        for o in selected:
            if o.name in view_layer.objects:
                o.select_set(True)
        view_layer.objects.active = active
    return path


def write_mp4(context, scene, cam, take_name, out_dir):
    r = scene.render
    saved = {
        "filepath": r.filepath,
        "file_format": r.image_settings.file_format,
        "camera": scene.camera,
    }
    ff = r.ffmpeg
    saved_ff = {k: getattr(ff, k) for k in ("format", "codec", "constant_rate_factor", "ffmpeg_preset",
                                             "audio_codec")}
    prefix = os.path.join(out_dir, take_name + "_")
    for old in glob.glob(glob.escape(prefix) + "*.mp4"):
        os.remove(old)
    try:
        scene.camera = cam
        r.image_settings.file_format = "FFMPEG"
        ff.format = "MPEG4"
        ff.codec = "H264"
        ff.constant_rate_factor = "HIGH"
        ff.ffmpeg_preset = "GOOD"
        ff.audio_codec = "NONE"
        r.filepath = prefix
        with context.temp_override(**_view3d_override(context)):
            bpy.ops.render.opengl(animation=True, view_context=False)
    finally:
        r.filepath = saved["filepath"]
        r.image_settings.file_format = saved["file_format"]
        for k, v in saved_ff.items():
            try:
                setattr(ff, k, v)
            except (TypeError, AttributeError):
                pass
        scene.camera = saved["camera"]
    produced = sorted(glob.glob(glob.escape(prefix) + "*.mp4"), key=os.path.getmtime)
    if not produced:
        raise RuntimeError("viewport render produced no video")
    final = os.path.join(out_dir, take_name + ".mp4")
    if os.path.exists(final):
        os.remove(final)
    os.replace(produced[-1], final)
    return final


def export_take(context, take_name: str, out_dir: str, video: bool = True) -> dict:
    scene = context.scene
    info = takes.take_info(bpy.data, take_name)
    if info is None or bpy.data.actions.get(take_name) is None:
        raise ValueError("no take %s" % take_name)
    cam = _camera_for(scene, info)
    os.makedirs(out_dir, exist_ok=True)
    takes.activate(cam, take_name)
    saved_range = (scene.frame_start, scene.frame_end, scene.frame_current)
    out = {}
    try:
        scene.frame_start = int(info["frame_start"])
        scene.frame_end = int(info["frame_end"])
        out["json"] = write_json(scene, cam, take_name, info,
                                 os.path.join(out_dir, take_name + "_camera.json"))
        out["fbx"] = write_fbx(context, cam, os.path.join(out_dir, take_name + "_camera.fbx"))
        if video:
            out["mp4"] = write_mp4(context, scene, cam, take_name, out_dir)
    finally:
        scene.frame_start, scene.frame_end = saved_range[0], saved_range[1]
        scene.frame_set(saved_range[2])
    return out
