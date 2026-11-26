"""Add-on preferences (token, port) and per-scene settings."""
import os
import secrets

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from . import protocol

ADDON_ID = __package__
_fallback_token = None


def _token_file():
    try:
        d = bpy.utils.user_resource("CONFIG", path="blendcam", create=True)
    except Exception:  # noqa: BLE001 - any failure: just no file fallback
        return None
    return os.path.join(d, "token.txt")


def _read_token_file():
    path = _token_file()
    if path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                t = f.read().strip()
            return t or None
        except OSError:
            return None
    return None


def _write_token_file(token):
    path = _token_file()
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(token)
    except OSError:
        pass


def new_token():
    return secrets.token_urlsafe(8)


def get():
    addon = bpy.context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon is not None else None


def get_token():
    """The persistent token. Created on first use and kept in the preferences (+ a small config file)."""
    global _fallback_token
    p = get()
    if p is not None and p.token:
        return p.token
    token = _read_token_file() or _fallback_token or new_token()
    _fallback_token = token
    if p is not None:
        p.token = token
    _write_token_file(token)
    return token


def set_new_token():
    global _fallback_token
    token = new_token()
    _fallback_token = token
    p = get()
    if p is not None:
        p.token = token
    _write_token_file(token)
    return token


class BlendcamPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    token: StringProperty(name="Токен", description="Секрет із QR-коду; чужі пакети без нього відкидаються")
    port: IntProperty(name="Порт", default=protocol.DEFAULT_PORT, min=1024, max=65535)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "port")
        row = col.row()
        row.enabled = False
        row.prop(self, "token")
        col.operator("blendcam.new_token", icon="FILE_REFRESH")


def _poll_camera(self, obj):
    return obj.type == "CAMERA"


class BlendcamSceneSettings(bpy.types.PropertyGroup):
    camera: PointerProperty(name="Камера", type=bpy.types.Object, poll=_poll_camera,
                            description="Яку камеру вести (порожньо = активна камера сцени)")
    scale: FloatProperty(name="Масштаб руху", default=1.0, min=0.01, max=1000.0, soft_min=0.1, soft_max=100.0,
                         description="1 м у кімнаті = стільки метрів у сцені")
    smooth: FloatProperty(name="Згладжування", default=0.3, min=0.0, max=1.0,
                          description="0 = сирий ручний рух, 1 = сильно згладжено (для нових дублів і «Перепекти»)")
    joy_speed: FloatProperty(name="Швидкість джойстика", default=1.5, min=0.05, max=50.0, soft_max=10.0,
                             unit="VELOCITY", description="Метрів сцени за секунду")
    roll_deg: EnumProperty(name="Поворот кадру", items=[("0", "0°", ""), ("90", "90°", ""),
                                                        ("180", "180°", ""), ("270", "270°", "")], default="0")
    mirror_x: BoolProperty(name="Дзеркало", default=False)
    live: BoolProperty(name="Керувати камерою з телефона", default=True)
    stream: BoolProperty(name="Показувати картинку на телефоні", default=True)
    show_qr: BoolProperty(name="Показувати QR у вікні 3D", default=True)


classes = (BlendcamPreferences, BlendcamSceneSettings)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.blendcam = PointerProperty(type=BlendcamSceneSettings)


def unregister():
    del bpy.types.Scene.blendcam
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
