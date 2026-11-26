"""Blendcam protocol v1 (see protocol/README.md). Pure Python, no bpy."""
import json
import math
from dataclasses import dataclass
from typing import Optional, Tuple

VERSION = 1
DEFAULT_PORT = 52700
TRACKING_STATES = ("normal", "limited", "notAvailable")

CONTROL_TYPES = {
    # phone -> Blender
    "hello", "anchor", "record_start", "record_stop", "play", "pause", "frame", "settings",
    # Blender -> phone
    "state", "toast",
}


@dataclass
class Pose:
    seq: int
    t: float
    m: list  # 16 floats, column-major ARKit camera transform
    trk: str
    joy: Tuple[float, float]
    lift: float
    focal: float
    focus: Optional[float]


def _num(x, default=None):
    if isinstance(x, bool):
        return default
    if isinstance(x, (int, float)) and math.isfinite(x):
        return float(x)
    return default


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def parse_pose(data: bytes, token: str) -> Optional[Pose]:
    """Decode one UDP pose packet. Returns None for anything invalid or foreign."""
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("v") != VERSION or obj.get("token") != token:
        return None
    m = obj.get("m")
    if not isinstance(m, list) or len(m) != 16:
        return None
    mf = [_num(x) for x in m]
    if any(x is None for x in mf):
        return None
    seq = obj.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool):
        return None
    t = _num(obj.get("t"))
    if t is None:
        return None
    trk = obj.get("trk")
    if trk not in TRACKING_STATES:
        trk = "notAvailable"
    joy = obj.get("joy") or [0.0, 0.0]
    if not isinstance(joy, list) or len(joy) != 2:
        joy = [0.0, 0.0]
    jx = _clamp(_num(joy[0], 0.0), -1.0, 1.0)
    jy = _clamp(_num(joy[1], 0.0), -1.0, 1.0)
    lift = _clamp(_num(obj.get("lift"), 0.0), -1.0, 1.0)
    focal = _num(obj.get("focal"), 0.0)
    if focal <= 0:
        focal = 0.0  # 0 = "phone did not send a focal length"
    focus = _num(obj.get("focus"))
    return Pose(seq=seq, t=t, m=mf, trk=trk, joy=(jx, jy), lift=lift, focal=focal, focus=focus)


class PoseFilter:
    """Drops stale/out-of-order packets. A phone restart (seq < 10 after >= 1000) resets the counter."""

    RESTART_LOW = 10
    RESTART_HIGH = 1000

    def __init__(self):
        self.last_seq = None

    def reset(self):
        self.last_seq = None

    def accept(self, p: Pose) -> bool:
        if self.last_seq is None or p.seq > self.last_seq:
            self.last_seq = p.seq
            return True
        if p.seq < self.RESTART_LOW and self.last_seq >= self.RESTART_HIGH:
            self.last_seq = p.seq
            return True
        return False


def parse_control(line: bytes) -> Optional[dict]:
    """Decode one control line (JSON object with a known `type`)."""
    try:
        obj = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, AttributeError):
        return None
    if not isinstance(obj, dict) or obj.get("type") not in CONTROL_TYPES:
        return None
    return obj


def encode_control(msg: dict) -> bytes:
    return (json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def encode_frame_header(n: int, ts: Optional[float] = None) -> bytes:
    msg = {"type": "frame", "len": int(n)}
    if ts is not None:
        msg["ts"] = float(ts)
    return encode_control(msg)


def make_url(host: str, port: int, token: str) -> str:
    return "blendcam://%s:%d?token=%s" % (host, port, token)
