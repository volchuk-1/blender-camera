"""Takes: resampling phone samples to scene frames, gaps, smoothing, baking into Actions."""
import bisect
import json
import math
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from mathutils import Matrix, Quaternion, Vector

JUMP_METRES = 0.3  # phone-space jump between neighbouring samples that we flag
TAKE_RE = re.compile(r"^Take_(\d+)$")
TEXT_PREFIX = "Blendcam_"


@dataclass
class Sample:
    t: float
    world: Matrix              # final camera world matrix (after anchor/scale/offset)
    focal: float
    ok: bool                   # False when tracking was not "normal"
    phone: Optional[Vector] = None  # raw phone position in metres (for jump detection)


@dataclass
class FrameSample:
    frame: int
    loc: Vector
    quat: Quaternion
    focal: float
    gap: bool = False


def _bad_flags(samples: List[Sample]) -> List[bool]:
    bad = []
    prev = None
    for s in samples:
        b = not s.ok
        if prev is not None:
            a = prev.phone if prev.phone is not None else prev.world.translation
            c = s.phone if s.phone is not None else s.world.translation
            if (c - a).length > JUMP_METRES:
                b = True
        bad.append(b)
        prev = s
    return bad


def resample(samples: List[Sample], t0: float, fps: float, frame_start: int) -> List[FrameSample]:
    """Phone-time samples -> one sample per scene frame. Frame frame_start + k <-> time t0 + k / fps."""
    if not samples:
        return []
    samples = sorted(samples, key=lambda s: s.t)
    times = [s.t for s in samples]
    bad = _bad_flags(samples)
    locs = [s.world.translation.copy() for s in samples]
    quats = [s.world.to_quaternion() for s in samples]
    t_last = times[-1]
    out = []
    k = 0
    while True:
        t = t0 + k / fps
        if t > t_last + 1e-9:
            break
        i = bisect.bisect_right(times, t) - 1
        if i < 0:
            fs = FrameSample(frame_start + k, locs[0].copy(), quats[0].copy(), samples[0].focal, bad[0])
        elif i >= len(samples) - 1:
            fs = FrameSample(frame_start + k, locs[-1].copy(), quats[-1].copy(), samples[-1].focal, bad[-1])
        else:
            j = i + 1
            dt = times[j] - times[i]
            w = (t - times[i]) / dt if dt > 0 else 0.0
            loc = locs[i].lerp(locs[j], w)
            quat = quats[i].slerp(quats[j], w)
            focal = samples[i].focal + (samples[j].focal - samples[i].focal) * w
            gap = bad[i] or (w > 1e-9 and bad[j])
            fs = FrameSample(frame_start + k, loc, quat, focal, gap)
        out.append(fs)
        k += 1
    return out


def gap_ranges(frames: List[FrameSample]) -> List[Tuple[int, int]]:
    ranges = []
    start = None
    prev = None
    for f in frames:
        if f.gap and start is None:
            start = f.frame
        elif not f.gap and start is not None:
            ranges.append((start, prev))
            start = None
        prev = f.frame
    if start is not None:
        ranges.append((start, frames[-1].frame))
    return ranges


def mark_gaps(frames: List[FrameSample]) -> List[Tuple[int, int]]:
    """Return gap frame ranges (inclusive) and hold the last good pose inside each gap (in place)."""
    ranges = gap_ranges(frames)
    good = [f for f in frames if not f.gap]
    if not good:
        return ranges
    last = None
    for f in frames:
        if not f.gap:
            last = f
            continue
        ref = last if last is not None else good[0]
        f.loc = ref.loc.copy()
        f.quat = ref.quat.copy()
        f.focal = ref.focal
    return ranges


def make_continuous(frames: List[FrameSample]) -> List[FrameSample]:
    """Flip quaternion signs so neighbours never jump to the other hemisphere."""
    for a, b in zip(frames, frames[1:]):
        if a.quat.dot(b.quat) < 0:
            b.quat.negate()
    return frames


def smooth(frames: List[FrameSample], strength: float) -> List[FrameSample]:
    """Gaussian smoothing, sigma = strength * 4 frames. 0 returns an identical copy."""
    copy = [FrameSample(f.frame, f.loc.copy(), f.quat.copy(), f.focal, f.gap) for f in frames]
    sigma = max(0.0, float(strength)) * 4.0
    if sigma < 1e-6 or len(frames) < 3:
        return copy
    radius = int(math.ceil(3 * sigma))
    weights = [math.exp(-0.5 * (d / sigma) ** 2) for d in range(-radius, radius + 1)]
    n = len(frames)
    out = []
    for i, f in enumerate(frames):
        loc = Vector((0.0, 0.0, 0.0))
        focal = 0.0
        q = [0.0, 0.0, 0.0, 0.0]
        wsum = 0.0
        center = f.quat
        for d in range(-radius, radius + 1):
            j = i + d
            if j < 0 or j >= n:
                continue
            w = weights[d + radius]
            g = frames[j]
            loc += g.loc * w
            focal += g.focal * w
            s = 1.0 if center.dot(g.quat) >= 0 else -1.0
            for c in range(4):
                q[c] += g.quat[c] * w * s
            wsum += w
        quat = Quaternion(q)
        quat.normalize()
        out.append(FrameSample(f.frame, loc / wsum, quat, focal / wsum, f.gap))
    return out


def process(samples, t0, fps, frame_start, strength):
    """Full pipeline: resample -> gaps (hold) -> smooth -> continuous. Returns (frames, gaps)."""
    frames = resample(samples, t0, fps, frame_start)
    gaps = mark_gaps(frames)
    frames = make_continuous(smooth(frames, strength))
    return frames, gaps


# ---------------------------------------------------------------- Blender side

def list_takes(data) -> List[str]:
    names = [a.name for a in data.actions if TAKE_RE.match(a.name)]
    return sorted(names, key=lambda n: int(TAKE_RE.match(n).group(1)))


def next_take_name(data) -> str:
    nums = [0]
    for a in data.actions:
        m = TAKE_RE.match(a.name)
        if m:
            nums.append(int(m.group(1)))
    for t in data.texts:
        m = re.match(r"^%sTake_(\d+)\.json$" % TEXT_PREFIX, t.name)
        if m:
            nums.append(int(m.group(1)))
    return "Take_%02d" % (max(nums) + 1)


def text_name(take_name: str) -> str:
    return "%s%s.json" % (TEXT_PREFIX, take_name)


def _fresh_action(data, id_block, name):
    act = data.actions.get(name)
    if act is None:
        act = data.actions.new(name)
    else:
        act.fcurves.clear()
    act.use_fake_user = True
    if id_block.animation_data is None:
        id_block.animation_data_create()
    id_block.animation_data.action = act
    return act


def _set_curve(act, id_block, path, index, frame_nums, values, group):
    fc = act.fcurve_ensure_for_datablock(id_block, path, index=index)
    kp = fc.keyframe_points
    if len(kp):
        kp.clear()
    n = len(values)
    kp.add(n)
    co = []
    for f, v in zip(frame_nums, values):
        co.append(float(f))
        co.append(float(v))
    kp.foreach_set("co", co)
    for k in kp:
        k.interpolation = "LINEAR"
    fc.update()
    return fc


def _encode_samples(raw: List[Sample]):
    out = []
    for s in raw:
        m = [round(s.world[r][c], 6) for r in range(4) for c in range(4)]
        p = [round(x, 6) for x in s.phone] if s.phone is not None else None
        out.append([round(s.t, 6), m, round(s.focal, 4), bool(s.ok), p])
    return out


def _decode_samples(rows) -> List[Sample]:
    out = []
    for t, m, focal, ok, p in rows:
        mat = Matrix([m[0:4], m[4:8], m[8:12], m[12:16]])
        out.append(Sample(t=t, world=mat, focal=focal, ok=ok, phone=Vector(p) if p is not None else None))
    return out


def bake(cam_obj, frames: List[FrameSample], take_name: str, raw: Optional[List[Sample]],
         t0: float = 0.0, fps: float = 24.0, frame_start: int = 1, strength: float = 0.0,
         gaps: Optional[List[Tuple[int, int]]] = None):
    """Write frames as keyframes into Action `take_name` (+ `take_name_lens` on the camera data).

    `raw` = the raw samples to store for re-baking; None keeps the samples already stored.
    """
    import bpy

    data = bpy.data
    if gaps is None:
        gaps = gap_ranges(frames)
    cam_obj.rotation_mode = "QUATERNION"
    act = _fresh_action(data, cam_obj, take_name)
    nums = [f.frame for f in frames]
    for i in range(3):
        _set_curve(act, cam_obj, "location", i, nums, [f.loc[i] for f in frames], "Object Transforms")
    for i in range(4):
        _set_curve(act, cam_obj, "rotation_quaternion", i, nums, [f.quat[i] for f in frames],
                   "Object Transforms")
    act["blendcam_take"] = True
    if cam_obj.type == "CAMERA":
        lens_act = _fresh_action(data, cam_obj.data, take_name + "_lens")
        default = cam_obj.data.lens
        _set_curve(lens_act, cam_obj.data, "lens", 0, nums,
                   [f.focal if f.focal > 0 else default for f in frames], "Camera")

    meta = {
        "take": take_name,
        "t0": t0,
        "fps": fps,
        "frame_start": frame_start,
        "frame_end": frames[-1].frame if frames else frame_start,
        "smooth": strength,
        "gaps": [list(g) for g in gaps],
        "camera": cam_obj.name,
    }
    txt = data.texts.get(text_name(take_name))
    if raw is not None:
        meta["samples"] = _encode_samples(raw)
    elif txt is not None:
        meta["samples"] = json.loads(txt.as_string()).get("samples", [])
    else:
        meta["samples"] = []
    if txt is None:
        txt = data.texts.new(text_name(take_name))
    txt.clear()
    txt.write(json.dumps(meta, separators=(",", ":")))
    return act


def load_raw(data, take_name):
    txt = data.texts.get(text_name(take_name))
    if txt is None:
        return None
    return json.loads(txt.as_string())


def take_info(data, take_name) -> Optional[dict]:
    meta = load_raw(data, take_name)
    if meta is None:
        return None
    meta = dict(meta)
    meta.pop("samples", None)
    return meta


def rebake(cam_obj, take_name: str, strength: float):
    import bpy

    meta = load_raw(bpy.data, take_name)
    if meta is None or not meta.get("samples"):
        raise ValueError("no raw samples for %s" % take_name)
    raw = _decode_samples(meta["samples"])
    frames, gaps = process(raw, meta["t0"], meta["fps"], meta["frame_start"], strength)
    return bake(cam_obj, frames, take_name, None, t0=meta["t0"], fps=meta["fps"],
                frame_start=meta["frame_start"], strength=strength, gaps=gaps)


def activate(cam_obj, take_name: str):
    import bpy

    act = bpy.data.actions.get(take_name)
    if act is None:
        raise ValueError(take_name)
    cam_obj.rotation_mode = "QUATERNION"
    if cam_obj.animation_data is None:
        cam_obj.animation_data_create()
    cam_obj.animation_data.action = act
    lens = bpy.data.actions.get(take_name + "_lens")
    if lens is not None and cam_obj.type == "CAMERA":
        if cam_obj.data.animation_data is None:
            cam_obj.data.animation_data_create()
        cam_obj.data.animation_data.action = lens
