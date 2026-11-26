"""Session state: applies phone poses to the camera, handles control messages, records takes.

All bpy access happens here on the main thread (tick() is a bpy.app.timers callback).
"""
import math
import time

import bpy
from mathutils import Matrix, Vector

from . import mapping, protocol, takes
from .server import Server, local_ipv4s

TICK = 1.0 / 60.0
STATE_EVERY = 0.2
SILENCE_STOP = 1.0      # no packets for this long while recording -> stop and save
LIVE_AGE = 0.5          # poses older than this don't drive the camera
CAMERA_NAME = "Blendcam_Camera"

_session = None


def get_session():
    return _session


def settings(scene):
    return scene.blendcam


def ensure_camera(scene):
    """Camera to drive: the one picked in the panel, else the scene camera, else a new Blendcam_Camera."""
    st = getattr(scene, "blendcam", None)
    cam = st.camera if st is not None else None
    if cam is not None and cam.type == "CAMERA" and cam.name in scene.objects:
        if scene.camera is not cam:
            scene.camera = cam
        return cam
    cam = scene.camera
    if cam is not None and cam.type == "CAMERA":
        return cam
    data = bpy.data.cameras.new(CAMERA_NAME)
    cam = bpy.data.objects.new(CAMERA_NAME, data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, -6.0, 1.6)
    cam.rotation_euler = (math.radians(90), 0.0, 0.0)
    scene.camera = cam
    return cam


def scene_fps(scene):
    return scene.render.fps / scene.render.fps_base


def _window_override():
    wm = bpy.context.window_manager
    if wm is None:
        return None
    for win in wm.windows:
        scr = win.screen
        for area in scr.areas:
            if area.type in ("VIEW_3D", "TIMELINE", "DOPESHEET_EDITOR"):
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                return {"window": win, "screen": scr, "area": area, "region": region}
    return None


def _is_playing():
    scr = bpy.context.screen
    if scr is not None:
        return scr.is_animation_playing
    wm = bpy.context.window_manager
    if wm:
        for win in wm.windows:
            if win.screen.is_animation_playing:
                return True
    return False


def _play(play: bool):
    if bpy.app.background:
        return
    ov = _window_override()
    if ov is None:
        return
    playing = _is_playing()
    try:
        with bpy.context.temp_override(**ov):
            if play and not playing:
                bpy.ops.screen.animation_play()
            elif not play and playing:
                bpy.ops.screen.animation_cancel(restore_frame=False)
    except RuntimeError:
        pass


def _tag_redraw():
    wm = bpy.context.window_manager
    if wm is None:
        return
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


class Session:
    def __init__(self):
        self.server = None
        self.scene_name = None
        self.cam_name = None
        self.anchor = None
        self.offset = Vector((0.0, 0.0, 0.0))
        self.recording = False
        self.rec_take = None
        self.t0 = 0.0
        self.rec_frame_start = 1
        self.rec_fps = 24.0
        self.samples = []
        self.last_phone_world = None
        self.last_pose = None
        self.last_tick = None
        self.last_state = 0.0
        self.toasts = []           # (time, text) shown in the panel
        self.report = []           # lines from "Перевірити мережу"
        self.last_take = None
        self.tracking = "notAvailable"
        self.client_was = None
        self.streamer = None
        self.ips = []
        self._injected = []
        self._last_redraw = 0.0

    # ------------------------------------------------------------------ lifecycle
    def start(self, context, port=None, token=None, register_timer=True):
        from . import prefs

        global _session
        scene = context.scene
        self.scene_name = scene.name
        cam = ensure_camera(scene)
        self.cam_name = cam.name
        p = prefs.get()
        port = p.port if (port is None and p is not None) else (port or protocol.DEFAULT_PORT)
        token = token or prefs.get_token()
        self.server = Server(port, token)
        self.server.start()
        self.ips = local_ipv4s()
        self.last_tick = time.monotonic()
        _session = self
        if register_timer and not bpy.app.timers.is_registered(_timer):
            bpy.app.timers.register(_timer, first_interval=TICK, persistent=True)
        self._start_streamer()
        return self

    def stop(self):
        global _session
        if self.recording:
            self._finish_recording("Запис зупинено — дубль збережено")
        self._stop_streamer()
        if self.server:
            self.server.stop()
        self.server = None
        if bpy.app.timers.is_registered(_timer):
            bpy.app.timers.unregister(_timer)
        if _session is self:
            _session = None

    @property
    def running(self):
        return self.server is not None and self.server.running

    def _start_streamer(self):
        if bpy.app.background:
            return
        try:
            from .stream import Streamer
        except ImportError:
            return
        self.streamer = Streamer(self.server)

    def _stop_streamer(self):
        if self.streamer is not None:
            self.streamer.stop()
        self.streamer = None

    # ------------------------------------------------------------------ helpers
    @property
    def scene(self):
        return bpy.data.scenes.get(self.scene_name) or bpy.context.scene

    def camera(self):
        cam = ensure_camera(self.scene)
        if cam.name != self.cam_name:
            self.cam_name = cam.name
            self.anchor = None
        return cam

    def toast(self, text, send=True):
        self.toasts.append((time.monotonic(), text))
        self.toasts = self.toasts[-5:]
        if send and self.server:
            self.server.send({"type": "toast", "text": text})

    def take_names(self):
        return takes.list_takes(bpy.data)

    def _inject_pose(self, p):
        """Test hook: feed a Pose as if it came from the network."""
        self._injected.append(p)

    def _phone_world(self, p):
        st = settings(self.scene)
        m = mapping.ar_to_blender(p.m)
        return mapping.apply_calibration(m, int(st.roll_deg), st.mirror_x)

    def _detach_animation(self, cam):
        if cam.animation_data and cam.animation_data.action is not None:
            cam.animation_data.action = None
        if cam.type == "CAMERA" and cam.data.animation_data and cam.data.animation_data.action is not None:
            cam.data.animation_data.action = None

    # ------------------------------------------------------------------ main loop
    def tick(self):
        if not self.running:
            return None
        try:
            self._tick()
        except ReferenceError:
            pass  # objects removed under us (file reload); next tick re-resolves
        return TICK

    def _tick(self):
        now = time.monotonic()
        dt = min(0.1, max(0.0, now - (self.last_tick or now)))
        self.last_tick = now
        scene = self.scene
        st = settings(scene)
        cam = self.camera()

        for msg in self.server.poll_controls():
            self._handle_control(msg, cam, scene)

        poses = self.server.drain_poses() + self._injected
        self._injected = []
        if poses:
            p = poses[-1]
            self.last_pose = p
            self.tracking = p.trk
        p = self.last_pose
        fresh = bool(poses) or (p is not None and self.server.last_packet_age() < LIVE_AGE)
        if p is not None and fresh and st.live:
            phone_world = self._phone_world(p)
            self.last_phone_world = phone_world
            if self.anchor is None:
                self.anchor = mapping.Anchor.make(cam.matrix_world, phone_world)
                self.offset = Vector((0.0, 0.0, 0.0))
            jx, jy = p.joy
            if jx or jy or p.lift:
                yaw = mapping.yaw_matrix(self.anchor.heading(phone_world))
                speed = st.joy_speed * dt
                self.offset += yaw @ Vector((jx, jy, 0.0)) * speed
                self.offset.z += p.lift * speed
            self._detach_animation(cam)
            world = self.anchor.apply(phone_world, st.scale, self.offset)
            cam.matrix_world = world
            if p.focal > 0 and cam.type == "CAMERA":
                cam.data.lens = p.focal
            if self.recording:
                for q in poses:
                    if q.t < self.t0 - 1e-6:
                        continue
                    pw = self._phone_world(q) if q is not p else phone_world
                    w = self.anchor.apply(pw, st.scale, self.offset)
                    self.samples.append(takes.Sample(t=q.t, world=w, focal=q.focal or cam.data.lens,
                                                     ok=(q.trk == "normal"), phone=pw.translation.copy()))
                frame = self.rec_frame_start + int(round((p.t - self.t0) * self.rec_fps))
                if frame != scene.frame_current:
                    scene.frame_set(frame)

        if self.recording and self.server.last_packet_age() > SILENCE_STOP:
            self._finish_recording("Зв'язок втрачено — дубль збережено")

        if self.server.client_name != self.client_was:
            self.client_was = self.server.client_name
            self.last_state = 0.0
        if self.server.has_client() and now - self.last_state >= STATE_EVERY:
            self.last_state = now
            self.server.send(self.state_message())
        if self.streamer is not None:
            want = bool(st.stream) and self.server.has_client()
            if want and not self.streamer.enabled and self.streamer.error is None:
                self.streamer.enabled = True
            elif not want:
                self.streamer.enabled = False
                self.streamer.error = None  # switching it off and on again retries
            self.streamer.tick(scene, cam)
        if now - self._last_redraw > 0.25:
            self._last_redraw = now
            _tag_redraw()

    def state_message(self):
        scene = self.scene
        st = settings(scene)
        cam = bpy.data.objects.get(self.cam_name) if self.cam_name else None
        focal = cam.data.lens if (cam is not None and cam.type == "CAMERA") else 50.0
        take = self.rec_take if self.recording else takes.next_take_name(bpy.data)
        return {
            "type": "state",
            "connected": True,
            "recording": self.recording,
            "frame": scene.frame_current,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
            "fps": round(scene_fps(scene), 4),
            "focal": round(focal, 2),
            "camera": cam.name if cam else "",
            "take": take,
            "last_take": self.last_take or "",
            "scale": st.scale,
            "smooth": st.smooth,
            "joy_speed": st.joy_speed,
            "roll_deg": int(st.roll_deg),
            "mirror_x": st.mirror_x,
            "stream": st.stream,
            "live": st.live,
        }

    # ------------------------------------------------------------------ controls
    def _handle_control(self, msg, cam, scene):
        st = settings(scene)
        t = msg.get("type")
        if t == "hello":
            self.anchor = None
            self.last_pose = None
            self.toast("Підключено: %s" % msg.get("device", "iPhone"), send=False)
            self.server.send({"type": "toast", "text": "Підключено до Blender"})
        elif t == "_bye":
            self.toast("Телефон відключився", send=False)
        elif t == "anchor":
            self.do_anchor()
        elif t == "record_start":
            tt = msg.get("t")
            if isinstance(tt, (int, float)) and not isinstance(tt, bool):
                self.start_recording(float(tt))
        elif t == "record_stop":
            if self.recording:
                self._finish_recording(None)
        elif t == "play":
            _play(True)
        elif t == "pause":
            _play(False)
        elif t == "frame":
            n = msg.get("n")
            if isinstance(n, (int, float)) and not isinstance(n, bool) and not self.recording:
                scene.frame_set(int(n))
        elif t == "settings":
            self.apply_settings(msg, st)

    def apply_settings(self, msg, st):
        def num(key, lo, hi):
            v = msg.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                setattr(st, key, max(lo, min(hi, float(v))))

        num("scale", 0.01, 1000.0)
        num("smooth", 0.0, 1.0)
        num("joy_speed", 0.05, 50.0)
        r = msg.get("roll_deg")
        if isinstance(r, (int, float)) and not isinstance(r, bool) and int(r) % 90 == 0:
            st.roll_deg = str(int(r) % 360)
        if isinstance(msg.get("mirror_x"), bool):
            st.mirror_x = msg["mirror_x"]
        if isinstance(msg.get("stream"), bool):
            st.stream = msg["stream"]
        self.last_state = 0.0

    def do_anchor(self):
        scene = self.scene
        st = settings(scene)
        cam = self.camera()
        if self.last_pose is None:
            self.toast("Немає даних з телефона — прив'язати нема до чого")
            return False
        st.live = True
        phone_world = self._phone_world(self.last_pose)
        self.anchor = mapping.Anchor.make(cam.matrix_world, phone_world)
        self.offset = Vector((0.0, 0.0, 0.0))
        self.toast("Прив'язано")
        return True

    def start_recording(self, t0):
        if self.recording:
            return
        scene = self.scene
        st = settings(scene)
        st.live = True
        cam = self.camera()
        self._detach_animation(cam)
        _play(False)
        self.recording = True
        self.rec_take = takes.next_take_name(bpy.data)
        self.t0 = t0
        self.rec_frame_start = scene.frame_start
        self.rec_fps = scene_fps(scene)
        self.samples = []
        scene.frame_set(self.rec_frame_start)
        self.last_state = 0.0
        self.toast("Запис %s" % self.rec_take)

    def _finish_recording(self, message):
        scene = self.scene
        st = settings(scene)
        self.recording = False
        name = self.rec_take or takes.next_take_name(bpy.data)
        samples, self.samples = self.samples, []
        self.last_state = 0.0
        if len(samples) < 2:
            self.toast("Дубль порожній — нічого не збережено")
            return None
        cam = self.camera()
        frames, gaps = takes.process(samples, self.t0, self.rec_fps, self.rec_frame_start, st.smooth)
        if not frames:
            self.toast("Дубль порожній — нічого не збережено")
            return None
        takes.bake(cam, frames, name, samples, t0=self.t0, fps=self.rec_fps,
                   frame_start=self.rec_frame_start, strength=st.smooth, gaps=gaps)
        self.last_take = name
        text = message or ("Дубль %s збережено (%d кадрів)" % (name, len(frames)))
        if gaps:
            text += " ⚠ втрата відстеження: " + ", ".join("%d–%d" % (a, b) for a, b in gaps[:3])
        self.toast(text)
        scene.frame_set(self.rec_frame_start)
        return name

    # ------------------------------------------------------------------ diagnostics
    def network_report(self):
        s = self.server
        lines = []
        if s is None or not s.running:
            return ["Сервер не запущено — натисніть «Старт»"]
        st = s.stats()
        lines.append("Порт %d слухається (UDP і TCP)" % st["port"])
        lines.append("Адреси ПК: " + ", ".join(self.ips))
        lines.append("Телефон: %s" % (("%s (%s)" % (st["client"], st["client_addr"])) if st["client"]
                                      else "не підключено"))
        lines.append("Пакетів руху за секунду: %d" % st["pps"])
        lines.append("Остання адреса пакетів: %s" % (st["addr"] or "—"))
        lines.append("Прийнято: %d, відкинуто (чужий токен/битий): %d" % (st["accepted"], st["rejected"]))
        if not st["client"] and st["pps"] == 0:
            lines.append("Нічого не приходить. Перевірте:")
            lines.append("• брандмауер Windows: дозволити Blender у «Приватних» мережах")
            lines.append("• Wi‑Fi на ПК: профіль мережі «Приватна»")
            lines.append("• телефон і ПК в одній Wi‑Fi (не гостьова, без ізоляції клієнтів)")
            lines.append("• на iPhone: Налаштування → Blendcam → Локальна мережа — увімкнено")
        elif st["client"] and st["pps"] == 0:
            lines.append("Керування є, а руху немає: UDP блокується брандмауером — дозвольте Blender")
        elif st["rejected"] > st["accepted"]:
            lines.append("Багато чужих пакетів: відскануйте QR ще раз (токен змінився?)")
        self.report = lines
        return lines


def _timer():
    s = _session
    if s is None:
        return None
    return s.tick()
