"""Stage 2: live camera view on the phone.

Every 1/fps s (from the session tick, main thread) the scene is drawn from the camera into an offscreen
buffer, the pixels go to a persistent ffmpeg process (raw RGBA -> MJPEG), a reader thread splits the
JPEGs and hands them to the server. A frame is never queued behind another: if ffmpeg or the network
is still busy, the frame is skipped.
"""
import collections
import shutil
import subprocess
import sys
import threading
import time

import bpy

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"


LONG_SIDE = {"normal": 640, "high": 1280}


def stream_size(quality: str, res_x: int, res_y: int):
    """Picture size for the phone: long side by quality, same aspect as the render, even numbers."""
    long_side = LONG_SIDE.get(quality, LONG_SIDE["high"])
    res_x, res_y = max(1, int(res_x)), max(1, int(res_y))
    if res_x >= res_y:
        w, h = long_side, long_side * res_y / res_x
    else:
        w, h = long_side * res_x / res_y, long_side
    even = lambda v: max(2, int(round(v / 2.0)) * 2)  # noqa: E731
    return even(w), even(h)


def find_ffmpeg():
    return shutil.which("ffmpeg")


class Streamer:
    def __init__(self, server, width=640, height=360, fps=20, jpeg_q=5):
        self.server = server
        self.width = int(width)
        self.height = int(height)
        self.fps = float(fps)
        self.jpeg_q = int(jpeg_q)
        self.enabled = False
        self.error = None
        self.frames_in = 0
        self.frames_out = 0
        self._offscreen = None
        self._proc = None
        self._reader = None
        self._stamps = collections.deque()
        self._next = 0.0
        self._lock = threading.Lock()
        self._inflight = 0

    # ------------------------------------------------------------------ ffmpeg
    def _ensure_proc(self):
        if self._proc is not None and self._proc.poll() is None:
            return True
        exe = find_ffmpeg()
        if exe is None:
            self.error = "ffmpeg не знайдено в PATH — картинку на телефон не передати"
            return False
        cmd = [exe, "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "%dx%d" % (self.width, self.height),
               "-r", str(int(self.fps)), "-i", "-", "-threads", "1",
               "-vf", "vflip", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", str(self.jpeg_q),
               "-flush_packets", "1", "-"]
        flags = 0
        if sys.platform.startswith("win"):
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, bufsize=0, creationflags=flags)
        with self._lock:
            self._stamps.clear()
            self._inflight = 0
        self._reader = threading.Thread(target=self._read_loop, args=(self._proc,), daemon=True,
                                        name="blendcam-jpeg")
        self._reader.start()
        return True

    def _read_loop(self, proc):
        buf = b""
        out = proc.stdout
        while True:
            try:
                chunk = out.read1(1 << 16) if hasattr(out, "read1") else out.read(4096)
            except (OSError, ValueError):
                return
            if not chunk:
                return
            buf += chunk
            while True:
                start = buf.find(SOI)
                if start < 0:
                    buf = b""
                    break
                end = buf.find(EOI, start + 2)
                if end < 0:
                    if start:
                        buf = buf[start:]
                    break
                jpeg = buf[start:end + 2]
                buf = buf[end + 2:]
                with self._lock:
                    ts = self._stamps.popleft() if self._stamps else time.time()
                    self._inflight = max(0, self._inflight - 1)
                self.frames_out += 1
                self.server.send_frame(jpeg, ts=ts)

    # ------------------------------------------------------------------ capture
    def _view3d(self):
        wm = bpy.context.window_manager
        if wm is None:
            return None
        for win in wm.windows:
            for area in win.screen.areas:
                if area.type == "VIEW_3D":
                    region = next((r for r in area.regions if r.type == "WINDOW"), None)
                    if region is not None:
                        return area.spaces.active, region
        return None

    def tick(self, scene, cam):
        """Called from the main thread at ~60 Hz; captures at most `fps` frames per second."""
        if not self.enabled or cam is None or bpy.app.background:
            return
        now = time.monotonic()
        if now < self._next:
            return
        if self.server.frame_busy():
            return  # the phone has not taken the previous frame yet: skip
        with self._lock:
            if self._inflight >= 4:
                return  # ffmpeg is behind (it holds ~1 frame anyway): skip
        view = self._view3d()
        if view is None:
            return
        if not self._ensure_proc():
            return
        # fixed schedule: timer ticks are ~16 ms apart on Windows, so "now - last >= 50 ms" would give 15 fps
        period = 1.0 / self.fps
        self._next = max(self._next + period, now - period)
        try:
            self._capture(scene, cam, *view)
        except Exception as e:  # noqa: BLE001 - never break the session because of the picture
            self.error = "Трансляція: %s" % e
            self.enabled = False

    def _capture(self, scene, cam, space, region):
        import gpu
        import numpy as np

        w, h = self.width, self.height
        if self._offscreen is None:
            self._offscreen = gpu.types.GPUOffScreen(w, h)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        proj = cam.calc_matrix_camera(depsgraph, x=w, y=h,
                                      scale_x=scene.render.pixel_aspect_x, scale_y=scene.render.pixel_aspect_y)
        view_matrix = cam.matrix_world.inverted()
        self._offscreen.draw_view3d(scene, bpy.context.view_layer, space, region, view_matrix, proj,
                                    do_color_management=True)
        with self._offscreen.bind():
            fb = gpu.state.active_framebuffer_get()
            buf = fb.read_color(0, 0, w, h, 4, 0, "UBYTE")
        buf.dimensions = w * h * 4
        data = np.array(buf, dtype=np.uint8).tobytes()
        with self._lock:
            self._stamps.append(time.time())
            self._inflight += 1
        try:
            self._proc.stdin.write(data)
            self.frames_in += 1
        except (OSError, ValueError):
            with self._lock:
                if self._stamps:
                    self._stamps.pop()
                self._inflight = max(0, self._inflight - 1)
            self._kill()

    def _kill(self):
        p = self._proc
        self._proc = None
        if p is None:
            return
        try:
            p.stdin.close()
        except OSError:
            pass
        try:
            p.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            p.kill()

    def stop(self):
        self.enabled = False
        self._kill()
        if self._offscreen is not None:
            try:
                self._offscreen.free()
            except Exception:  # noqa: BLE001
                pass
            self._offscreen = None
