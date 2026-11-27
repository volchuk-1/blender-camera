"""Orbit modes: keep a target in frame ("Ціль") and the turntable ("Стіл")."""
import math

from mathutils import Matrix, Vector

from . import mapping

MIN_DISTANCE = 0.2
MAX_ELEVATION = math.radians(80.0)
SPIN_SPEED = math.radians(60.0)  # rad/s at full joystick deflection


def look_rotation(cam_pos: Vector, target: Vector) -> Matrix:
    """3x3 rotation of a camera at cam_pos looking at target, top of the frame up (no roll)."""
    d = Vector(target) - Vector(cam_pos)
    if d.length < 1e-9:
        return Matrix.Rotation(math.radians(90.0), 3, "X")
    f = d.normalized()
    if abs(f.z) > 0.999:
        return Matrix.Identity(3) if f.z < 0 else Matrix.Rotation(math.radians(180.0), 3, "X")
    right = f.cross(Vector((0.0, 0.0, 1.0))).normalized()
    up = right.cross(f).normalized()
    return Matrix((right, up, -f)).transposed()


def aim(world: Matrix, target: Vector, hold: float) -> Matrix:
    """Turn the camera towards the target by `hold` (0 = as is, 1 = target exactly in the centre)."""
    hold = max(0.0, min(1.0, float(hold)))
    q = world.to_quaternion()
    if hold <= 0.0:
        out = q.to_matrix().to_4x4()
    else:
        look = look_rotation(world.translation, target).to_quaternion()
        if q.dot(look) < 0:
            look.negate()
        out = q.slerp(look, hold).to_matrix().to_4x4()
    out.translation = world.translation
    return out


def _wrap(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def _pitch(m: Matrix) -> float:
    f = (m.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
    return math.asin(max(-1.0, min(1.0, f.z)))


class Turntable:
    """Stand still and turn: the phone's heading flies the camera around the target, its tilt raises/lowers it.

    The camera heading follows the phone heading exactly (turn right -> the view turns right);
    tilting the phone down lifts the camera to look down on the target.
    """

    def __init__(self):
        self.target = Vector((0.0, 0.0, 0.0))
        self.azimuth = 0.0     # direction target -> camera, radians about +Z
        self.elevation = 0.0
        self.distance = 1.0
        self._yaw = 0.0        # last phone heading (unwrapped accumulation)
        self._pitch0 = 0.0
        self._el0 = 0.0

    def start(self, cam_world: Matrix, target: Vector, phone_world: Matrix):
        self.target = Vector(target)
        d = cam_world.translation - self.target
        if d.length < 1e-6:
            self.distance = MIN_DISTANCE
            self.azimuth = mapping.yaw_of(cam_world) - math.pi / 2.0
            self.elevation = 0.0
        else:
            self.distance = max(MIN_DISTANCE, d.length)
            self.azimuth = math.atan2(d.y, d.x)
            self.elevation = max(-MAX_ELEVATION, min(MAX_ELEVATION, math.asin(d.z / d.length)))
        self._el0 = self.elevation
        self._yaw = mapping.yaw_of(phone_world)
        self._pitch0 = _pitch(phone_world)

    def apply(self, phone_world: Matrix, joy, dt: float, joy_speed: float) -> Matrix:
        yaw = mapping.yaw_of(phone_world)
        self.azimuth += _wrap(yaw - self._yaw)
        self._yaw = yaw
        jx, jy = joy
        self.azimuth += jx * SPIN_SPEED * dt
        self.distance = max(MIN_DISTANCE, self.distance - jy * joy_speed * dt)
        el = self._el0 - (_pitch(phone_world) - self._pitch0)
        self.elevation = max(-MAX_ELEVATION, min(MAX_ELEVATION, el))
        ce = math.cos(self.elevation)
        offset = Vector((ce * math.cos(self.azimuth), ce * math.sin(self.azimuth), math.sin(self.elevation)))
        pos = self.target + offset * self.distance
        out = look_rotation(pos, self.target).to_4x4()
        out.translation = pos
        return out
