#!/usr/bin/env python3
"""A stand-in iPhone for testing Blendcam without a phone. Standard library only.

    python tools/fake_phone.py --host 127.0.0.1 --port 52700 --token XXXX --path circle --seconds 5 --record

Sends `hello` over TCP, then ARKit-style pose packets over UDP. Prints every message it receives
from Blender as `RECV <json>`. With --recv-frames it also reads live JPEG frames and prints a summary
line `FRAMES {...}` at the end.
"""
import argparse
import json
import math
import random
import socket
import sys
import threading
import time


def arkit_matrix(yaw, pos):
    """Column-major 4x4: rotation about ARKit +Y by `yaw`, then translation `pos`."""
    c, s = math.cos(yaw), math.sin(yaw)
    return [c, 0.0, -s, 0.0,
            0.0, 1.0, 0.0, 0.0,
            s, 0.0, c, 0.0,
            pos[0], pos[1], pos[2], 1.0]


def pose_at(path, t, seconds, radius=0.5, height=1.4):
    if path == "circle":
        a = 2 * math.pi * t / max(seconds, 1e-6)
        pos = (radius * math.cos(a), height, radius * math.sin(a))
        yaw = math.pi / 2 - a  # look at the centre of the circle
        return arkit_matrix(yaw, pos)
    if path == "line":
        return arkit_matrix(0.0, (0.0, height, -t * 0.5))  # walk forward 0.5 m/s
    return arkit_matrix(0.0, (0.0, height, 0.0))


def jpeg_size(data):
    """(width, height) from a JPEG SOF marker, or None."""
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h = (data[i + 5] << 8) | data[i + 6]
            w = (data[i + 7] << 8) | data[i + 8]
            return w, h
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = (data[i + 2] << 8) | data[i + 3]
        i += 2 + seg
    return None


class Reader(threading.Thread):
    def __init__(self, sock, recv_frames):
        super().__init__(daemon=True)
        self.sock = sock
        self.recv_frames = recv_frames
        self.frames = 0
        self.bad = 0
        self.sizes = set()
        self.latencies = []
        self.first = None
        self.last = None
        self.closed = False

    def run(self):
        buf = b""
        try:
            while True:
                chunk = self.sock.recv(1 << 16)
                if not chunk:
                    break
                buf += chunk
                while True:
                    nl = buf.find(b"\n")
                    if nl < 0:
                        break
                    try:
                        msg = json.loads(buf[:nl].decode("utf-8"))
                    except ValueError:
                        buf = buf[nl + 1:]
                        continue
                    if msg.get("type") == "frame":
                        n = int(msg.get("len", 0))
                        if len(buf) < nl + 1 + n:
                            break  # wait for the rest of the image
                        img = buf[nl + 1:nl + 1 + n]
                        buf = buf[nl + 1 + n:]
                        now = time.time()
                        self.frames += 1
                        self.first = self.first or now
                        self.last = now
                        size = jpeg_size(img)
                        if size is None or img[-2:] != b"\xff\xd9":
                            self.bad += 1
                        else:
                            self.sizes.add(size)
                        if "ts" in msg:
                            self.latencies.append((now - float(msg["ts"])) * 1000.0)
                        continue
                    buf = buf[nl + 1:]
                    print("RECV " + json.dumps(msg, ensure_ascii=False), flush=True)
        except OSError:
            pass
        self.closed = True

    def summary(self):
        span = (self.last - self.first) if (self.first and self.last and self.last > self.first) else 0.0
        lat = sorted(self.latencies)
        return {
            "frames": self.frames,
            "bad": self.bad,
            "fps": round((self.frames - 1) / span, 2) if span > 0 else 0.0,
            "sizes": sorted(self.sizes),
            "latency_ms_avg": round(sum(lat) / len(lat), 1) if lat else None,
            "latency_ms_p95": round(lat[int(len(lat) * 0.95) - 1], 1) if lat else None,
        }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=52700)
    ap.add_argument("--token", required=True)
    ap.add_argument("--path", choices=("circle", "line", "still"), default="circle")
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--hz", type=float, default=60.0)
    ap.add_argument("--drop", type=float, default=0.0, help="probability of dropping a packet")
    ap.add_argument("--shuffle", type=float, default=0.0, help="probability of sending a packet late")
    ap.add_argument("--recv-frames", action="store_true")
    ap.add_argument("--anchor", action="store_true", help="send `anchor` before moving")
    ap.add_argument("--device", default="FakePhone")
    ap.add_argument("--wait", type=float, default=0.8, help="seconds to keep listening at the end")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    rnd = random.Random(args.seed)

    tcp = socket.create_connection((args.host, args.port), timeout=5)
    tcp.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    tcp.settimeout(None)
    reader = Reader(tcp, args.recv_frames)
    reader.start()

    def send_ctl(msg):
        tcp.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))

    send_ctl({"type": "hello", "token": args.token, "device": args.device})
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    time.sleep(0.2)

    base = 1000.0  # phone clock starts somewhere arbitrary
    t_start = time.monotonic()
    seq = 0
    late = None
    n = int(round(args.seconds * args.hz))
    if args.anchor:
        send_ctl({"type": "anchor"})
    for i in range(n + 1):
        target = t_start + i / args.hz
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        tl = i / args.hz
        if i == 0 and args.record:
            send_ctl({"type": "record_start", "t": base + tl})
        pkt = {
            "v": 1, "seq": seq, "t": base + tl, "token": args.token,
            "m": pose_at(args.path, tl, args.seconds), "trk": "normal",
            "joy": [0.0, 0.0], "lift": 0.0, "focal": 35.0,
        }
        seq += 1
        data = json.dumps(pkt).encode("utf-8")
        if rnd.random() < args.drop:
            continue
        if late is not None:
            udp.sendto(data, (args.host, args.port))
            udp.sendto(late, (args.host, args.port))
            late = None
            continue
        if rnd.random() < args.shuffle:
            late = data
            continue
        udp.sendto(data, (args.host, args.port))
    if args.record:
        send_ctl({"type": "record_stop"})
    time.sleep(args.wait)
    if args.recv_frames:
        print("FRAMES " + json.dumps(reader.summary()), flush=True)
    try:
        tcp.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    tcp.close()
    print("DONE sent=%d" % seq, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
