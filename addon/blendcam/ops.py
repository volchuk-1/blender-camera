"""Operators of the Blendcam panel."""
import os

import bpy
from bpy.props import StringProperty

from . import prefs, runtime, takes


def _session():
    return runtime.get_session()


class BLENDCAM_OT_start(bpy.types.Operator):
    bl_idname = "blendcam.start"
    bl_label = "Старт"
    bl_description = "Запустити сервер: телефон зможе підключитися по Wi‑Fi"

    def execute(self, context):
        s = _session()
        if s is not None and s.running:
            return {"FINISHED"}
        try:
            runtime.Session().start(context)
        except OSError as e:
            self.report({"ERROR"}, "Не вдалося відкрити порт: %s (Blender уже запущено двічі?)" % e)
            return {"CANCELLED"}
        return {"FINISHED"}


class BLENDCAM_OT_stop(bpy.types.Operator):
    bl_idname = "blendcam.stop"
    bl_label = "Стоп"
    bl_description = "Зупинити сервер"

    def execute(self, context):
        s = _session()
        if s is not None:
            s.stop()
        return {"FINISHED"}


class BLENDCAM_OT_new_token(bpy.types.Operator):
    bl_idname = "blendcam.new_token"
    bl_label = "Новий токен"
    bl_description = "Змінити секрет у QR-коді (телефон треба буде підключити заново)"

    def execute(self, context):
        token = prefs.set_new_token()
        s = _session()
        if s is not None and s.running:
            s.server.token = token
        return {"FINISHED"}


class BLENDCAM_OT_anchor(bpy.types.Operator):
    bl_idname = "blendcam.anchor"
    bl_label = "Прив'язати"
    bl_description = "Поточне положення телефона = поточне положення камери (горизонт рівний)"

    def execute(self, context):
        s = _session()
        if s is None or not s.do_anchor():
            self.report({"WARNING"}, "Немає даних з телефона")
            return {"CANCELLED"}
        return {"FINISHED"}


def _camera_for_take(context, name):
    info = takes.take_info(bpy.data, name) or {}
    cam = bpy.data.objects.get(info.get("camera", "")) if info.get("camera") else None
    if cam is None or cam.type != "CAMERA":
        cam = runtime.ensure_camera(context.scene)
    return cam


class BLENDCAM_OT_rebake(bpy.types.Operator):
    bl_idname = "blendcam.rebake"
    bl_label = "Перепекти"
    bl_description = "Перерахувати ключові кадри дубля з поточним згладжуванням (сирі дані не змінюються)"

    take: StringProperty()

    def execute(self, context):
        try:
            cam = _camera_for_take(context, self.take)
            takes.rebake(cam, self.take, context.scene.blendcam.smooth)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        context.scene.blendcam.live = False
        self.report({"INFO"}, "%s перепечено, згладжування %.2f" % (self.take, context.scene.blendcam.smooth))
        return {"FINISHED"}


class BLENDCAM_OT_set_active_take(bpy.types.Operator):
    bl_idname = "blendcam.set_active_take"
    bl_label = "Зробити активним"
    bl_description = "Поставити цей дубль на камеру (керування з телефона вимикається, щоб дубль було видно)"

    take: StringProperty()

    def execute(self, context):
        try:
            cam = _camera_for_take(context, self.take)
            takes.activate(cam, self.take)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        context.scene.blendcam.live = False
        info = takes.take_info(bpy.data, self.take)
        if info:
            context.scene.frame_set(int(info["frame_start"]))
        return {"FINISHED"}


class BLENDCAM_OT_export_take(bpy.types.Operator):
    bl_idname = "blendcam.export_take"
    bl_label = "Експорт"
    bl_description = "Зберегти дубль у //blendcam_exports/: відео проходу (mp4), траєкторія (JSON), камера (FBX)"

    take: StringProperty()

    def execute(self, context):
        from . import export

        if not bpy.data.filepath:
            self.report({"ERROR"}, "Спершу збережіть .blend — експорт іде в теку поруч із ним")
            return {"CANCELLED"}
        out_dir = bpy.path.abspath("//blendcam_exports/")
        os.makedirs(out_dir, exist_ok=True)
        try:
            files = export.export_take(context, self.take, out_dir, video=not bpy.app.background)
        except Exception as e:  # noqa: BLE001 - show any export failure to the user
            self.report({"ERROR"}, "Експорт не вдався: %s" % e)
            return {"CANCELLED"}
        context.scene.blendcam.live = False
        self.report({"INFO"}, "Експортовано: " + ", ".join(os.path.basename(v) for v in files.values()))
        return {"FINISHED"}


class BLENDCAM_OT_check_network(bpy.types.Operator):
    bl_idname = "blendcam.check_network"
    bl_label = "Перевірити мережу"
    bl_description = "Чи слухається порт, чи приходять пакети, з якої адреси"

    def execute(self, context):
        s = _session()
        if s is None:
            runtime_report = ["Сервер не запущено — натисніть «Старт»"]
            BLENDCAM_OT_check_network.last = runtime_report
        else:
            BLENDCAM_OT_check_network.last = s.network_report()
        return {"FINISHED"}


BLENDCAM_OT_check_network.last = []

classes = (
    BLENDCAM_OT_start,
    BLENDCAM_OT_stop,
    BLENDCAM_OT_new_token,
    BLENDCAM_OT_anchor,
    BLENDCAM_OT_rebake,
    BLENDCAM_OT_set_active_take,
    BLENDCAM_OT_export_take,
    BLENDCAM_OT_check_network,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
