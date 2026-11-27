"""Stabilization: presets, a live One-Euro filter for the camera pose, and horizon (roll) removal.

One-Euro filter: Casiez, Roussel, Vogel, "1 Euro Filter" (CHI 2012). It smooths strongly while the
camera moves slowly and lets fast moves through with little lag.
"""
import math
from dataclasses import dataclass
from typing import Optional

from mathutils import Matrix, Quaternion, Vector


@dataclass(frozen=True)
class Preset:
    name: str
    min_cutoff: float   # Hz, live filter cutoff at rest (lower = smoother)
    beta: float         # how fast the cutoff rises with speed (higher = less lag on fast moves)
    bake_sigma: float   # Gaussian sigma in frames used when a take is baked
    roll_lock: bool     # force a level horizon
    tripod: bool        # position fixed, only rotation follows the phone


PRESETS = {
    "handheld": Preset("handheld", 3.0, 1.0, 0.6, False, False),
    "steadicam": Preset("steadicam", 0.8, 0.15, 3.0, False, False),
    "crane": Preset("crane", 0.25, 0.05, 8.0, True, False),
    "tripod": Preset("tripod", 0.6, 0.1, 3.0, False, True),
}
D_CUTOFF = 1.0


def preset_for(name: str, custom_smooth: float = 0.3) -> Preset:
    if name == "custom":
        s = max(0.0, min(1.0, float(custom_smooth)))
        if s <= 0.0:
            return Preset("custom", 1e9, 0.0, 0.0, False, False)  # 0 = raw handheld motion, no filter
        return Preset("custom", 3.0 / (1.0 + 10.0 * s), 0.3, 4.0 * s, False, False)
    return PRESETS.get(name, PRESETS["steadicam"])


def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-6))
    return 1.0 / (1.0 + tau / dt)


class LiveSmoother:
    def __init__(self, preset: Preset):
        self.preset = preset
        self.reset(None)

    def reset(self, world: Optional[Matrix]):
        self._t = None
        self._pos = None
        self._quat = None
        self._dpos = 0.0
        self._drot = 0.0
        if world is not None:
            self._pos = world.translation.copy()
            self._quat = world.to_quaternion()
            self._quat.normalize()

    def _result(self):
        m = self._quat.to_matrix().to_4x4()
        m.translation = self._pos
        return m

    def apply(self, world: Matrix, t: float) -> Matrix:
        pos = world.translation.copy()
        quat = world.to_quaternion()
        quat.normalize()
        if self._pos is None:
            self._pos, self._quat, self._t = pos, quat, t
            return self._result()
        if self._t is None:
            self._t = t - 1.0 / 60.0
        dt = t - self._t
        if dt <= 0:
            return self._result()
        self._t = t
        p = self.preset

        # position
        speed = (pos - self._pos).length / dt
        self._dpos += _alpha(D_CUTOFF, dt) * (speed - self._dpos)
        a = _alpha(p.min_cutoff + p.beta * self._dpos, dt)
        self._pos = self._pos.lerp(pos, a)

        # rotation (same hemisphere first, so +-180 never flips)
        if self._quat.dot(quat) < 0:
            quat.negate()
        ang_speed = quat_angle(self._quat, quat) / dt
        self._drot += _alpha(D_CUTOFF, dt) * (ang_speed - self._drot)
        a = _alpha(p.min_cutoff + p.beta * self._drot, dt)
        self._quat = self._quat.slerp(quat, a)
        self._quat.normalize()
        return self._result()


def quat_angle(a: Quaternion, b: Quaternion) -> float:
    """Smallest rotation angle between two orientations (radians, 0..pi)."""
    return 2.0 * math.acos(min(1.0, abs(a.dot(b))))


def remove_roll(m: Matrix) -> Matrix:
    """Same position and view direction, horizon level (camera right axis horizontal)."""
    r3 = m.to_3x3()
    fwd = (r3 @ Vector((0.0, 0.0, -1.0))).normalized()
    if abs(fwd.z) > 0.999:
        return m.copy()
    right = fwd.cross(Vector((0.0, 0.0, 1.0))).normalized()
    up = right.cross(fwd).normalized()
    rot = Matrix((right, up, -fwd)).transposed()
    out = rot.to_4x4()
    out.translation = m.translation
    return out
