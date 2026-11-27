"""ARKit -> Blender coordinates, calibration and the anchor (binding phone pose to camera pose)."""
import math

from mathutils import Matrix, Vector

# ARKit world (Y up) -> Blender world (Z up): +90 deg about X, (x, y, z) -> (x, -z, y)
C = Matrix.Rotation(math.radians(90), 4, "X")
_MIRROR = Matrix.Diagonal((-1.0, 1.0, 1.0, 1.0))


def ar_to_blender(m16) -> Matrix:
    """Column-major ARKit camera transform (16 floats) -> Blender world matrix of the camera."""
    m = Matrix([[m16[c * 4 + r] for c in range(4)] for r in range(4)])
    return C @ m


def apply_calibration(m: Matrix, roll_deg: int, mirror_x: bool) -> Matrix:
    """Roll the image about the camera's view axis (0/90/180/270) and optionally mirror left/right."""
    out = m.copy()
    roll = int(roll_deg) % 360
    if roll:
        out = out @ Matrix.Rotation(math.radians(roll), 4, "Z")
    if mirror_x:
        out = _MIRROR @ out @ _MIRROR
    return out


def yaw_of(m: Matrix) -> float:
    """Heading about world Z, radians; 0 = looking along +Y, positive = counter-clockwise."""
    r3 = m.to_3x3()
    fwd = r3 @ Vector((0, 0, -1))
    if math.hypot(fwd.x, fwd.y) > 0.2:
        return math.atan2(-fwd.x, fwd.y)  # exact for any roll: roll turns about this very axis
    # looking (almost) straight down or up: the top of the frame points along the heading (down)
    # or against it (up)
    up = r3 @ Vector((0, 1, 0))
    if fwd.z > 0:
        up = -up
    return math.atan2(-up.x, up.y)


def yaw_matrix(yaw: float) -> Matrix:
    return Matrix.Rotation(yaw, 3, "Z")


class Anchor:
    """Binds the phone pose at one moment to the camera pose at that moment.

    Only heading and position are aligned; pitch and roll always come from the phone (gravity),
    so the horizon stays level.
    """

    def __init__(self, yaw_delta: float, cam_pos: Vector, phone_pos: Vector):
        self.yaw_delta = yaw_delta
        self.cam_pos = cam_pos.copy()
        self.phone_pos = phone_pos.copy()
        self.rz = yaw_matrix(yaw_delta)

    @staticmethod
    def make(cam_world: Matrix, phone_world: Matrix) -> "Anchor":
        return Anchor(yaw_of(cam_world) - yaw_of(phone_world),
                      cam_world.translation, phone_world.translation)

    def heading(self, phone_world: Matrix) -> float:
        return yaw_of(phone_world) + self.yaw_delta

    def apply(self, phone_world: Matrix, scale: float, offset: Vector) -> Matrix:
        rot = self.rz @ phone_world.to_3x3()
        pos = self.cam_pos + self.rz @ ((phone_world.translation - self.phone_pos) * scale) + offset
        out = rot.to_4x4()
        out.translation = pos
        return out
