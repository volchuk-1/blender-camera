"""Sidebar panel (N > Blendcam) and the QR overlay drawn in the 3D viewport."""
import time

import bpy

from . import protocol, qr, runtime, takes

_qr_cache = {"text": None, "runs": None, "size": 0}
_draw_handle = None


def _connect_url(s):
    ip = s.ips[0] if s.ips else "127.0.0.1"
    return protocol.make_url(ip, s.server.port, s.server.token)


def _gap_text(info):
    gaps = info.get("gaps") or []
    if not gaps:
        return ""
    return "⚠ втрата відстеження " + ", ".join("%d–%d" % (a, b) for a, b in gaps[:3])


class VIEW3D_PT_blendcam(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Blendcam"
    bl_label = "Blendcam"

    def draw(self, context):
        layout = self.layout
        st = context.scene.blendcam
        s = runtime.get_session()
        running = s is not None and s.running

        row = layout.row(align=True)
        row.scale_y = 1.4
        if running:
            row.operator("blendcam.stop", icon="PAUSE")
        else:
            row.operator("blendcam.start", icon="PLAY")

        if running:
            box = layout.box()
            col = box.column(align=True)
            stats = s.server.stats()
            if stats["client"]:
                trk = {"normal": "добре", "limited": "мало деталей", "notAvailable": "немає"}.get(s.tracking, s.tracking)
                col.label(text="Підключено: %s" % stats["client"], icon="CHECKMARK")
                col.label(text="Відстеження: %s · %d пак/с" % (trk, stats["pps"]))
            else:
                col.label(text="Чекаю телефон… Відскануйте QR у вікні 3D", icon="TIME")
            if s.recording:
                col.label(text="ЗАПИС %s" % s.rec_take, icon="REC")
            col.separator()
            col.label(text="Адреса для ручного введення:")
            for ip in s.ips[:4]:
                col.label(text="%s:%d" % (ip, s.server.port))
            col.label(text="Токен: %s" % s.server.token)
            box.prop(st, "show_qr")
            if s.streamer is not None and s.streamer.error:
                box.label(text=s.streamer.error, icon="ERROR")
            now = time.monotonic()
            for t, text in s.toasts[-2:]:
                if now - t < 8:
                    box.label(text=text, icon="INFO")

        col = layout.column()
        col.prop(st, "camera")
        col.prop(st, "live")
        col.prop(st, "scale")
        col.prop(st, "smooth")
        col.prop(st, "joy_speed")
        col.prop(st, "stream")
        row = col.row(align=True)
        row.prop(st, "roll_deg", expand=True)
        col.prop(st, "mirror_x")
        r = col.row()
        r.scale_y = 1.2
        r.enabled = running
        r.operator("blendcam.anchor", icon="PIVOT_CURSOR")

        names = takes.list_takes(bpy.data)
        box = layout.box()
        box.label(text="Дублі (%d)" % len(names), icon="SEQUENCE")
        active = None
        cam = context.scene.camera
        if cam is not None and cam.animation_data and cam.animation_data.action:
            active = cam.animation_data.action.name
        for name in reversed(names):
            info = takes.take_info(bpy.data, name) or {}
            row = box.row(align=True)
            label = name
            if info:
                label += "  %d–%d" % (info.get("frame_start", 0), info.get("frame_end", 0))
            row.label(text=label, icon="RADIOBUT_ON" if name == active else "RADIOBUT_OFF")
            row.operator("blendcam.set_active_take", text="", icon="PLAY").take = name
            row.operator("blendcam.rebake", text="", icon="FILE_REFRESH").take = name
            row.operator("blendcam.export_take", text="", icon="EXPORT").take = name
            g = _gap_text(info)
            if g:
                box.label(text="   " + g)

        box = layout.box()
        box.operator("blendcam.check_network", icon="WORLD")
        from .ops import BLENDCAM_OT_check_network
        for line in BLENDCAM_OT_check_network.last:
            box.label(text=line)


def _draw_qr_overlay():
    s = runtime.get_session()
    if s is None or not s.running or s.server.has_client():
        return
    ctx = bpy.context
    scene = ctx.scene
    if scene is None or not getattr(scene, "blendcam", None) or not scene.blendcam.show_qr:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader

    text = _connect_url(s)
    if _qr_cache["text"] != text:
        m = qr.encode(text)
        _qr_cache.update(text=text, runs=qr.runs(m), size=len(m))
    n = _qr_cache["size"]
    region = ctx.region
    side = min(region.width, region.height) * 0.45
    side = max(150.0, min(side, 420.0))
    cell = side / (n + 8)
    # centred: the sidebar overlaps the right edge of the viewport, the toolbar the left one
    x0 = (region.width - side) / 2
    y0 = (region.height - side) / 2
    verts, idx = [], []

    def quad(x, y, w, h):
        k = len(verts)
        verts.extend([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])
        idx.extend([(k, k + 1, k + 2), (k, k + 2, k + 3)])

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    bg = batch_for_shader(shader, "TRIS", {"pos": [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side),
                                                   (x0, y0 + side)]}, indices=[(0, 1, 2), (0, 2, 3)])
    shader.uniform_float("color", (1, 1, 1, 1))
    bg.draw(shader)
    for (x, y, length) in _qr_cache["runs"]:
        quad(x0 + (x + 4) * cell, y0 + side - (y + 5) * cell, length * cell, cell)
    batch = batch_for_shader(shader, "TRIS", {"pos": verts}, indices=idx)
    shader.uniform_float("color", (0, 0, 0, 1))
    batch.draw(shader)
    gpu.state.blend_set("NONE")
    try:
        import blf
        blf.size(0, 14)
        blf.color(0, 1, 1, 1, 1)
        blf.position(0, x0, y0 - 22, 0)
        blf.draw(0, "Blendcam: відскануйте телефоном")
    except Exception:  # noqa: BLE001 - text is optional
        pass


classes = (VIEW3D_PT_blendcam,)


def register():
    global _draw_handle
    for c in classes:
        bpy.utils.register_class(c)
    if _draw_handle is None and not bpy.app.background:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_qr_overlay, (), "WINDOW", "POST_PIXEL")


def unregister():
    global _draw_handle
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, "WINDOW")
        _draw_handle = None
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
