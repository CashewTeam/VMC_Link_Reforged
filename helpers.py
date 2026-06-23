from mathutils import Quaternion, Vector

from . import constants


def debug(msg: str):
    if constants.DEBUG_LOGGING:
        print(f"[VMC Link] {msg}")


def warn(msg: str, exc: Exception = None):
    if exc is None:
        print(f"[VMC Link] {msg}")
        return
    print(f"[VMC Link] {msg}: {exc}")
    debug(repr(exc))


def normalize_identifier(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(name))


def normalize_bone_name(name: str) -> str:
    base = str(name).rsplit(":", 1)[-1]
    return "".join(ch for ch in base.lower() if ch.isalnum())


def convert_vmc_pose(px, py, pz, qx, qy, qz, qw):
    loc = Vector((-px, -pz, py))
    quat = Quaternion((qw, qx, qz, -qy))
    return loc, quat


def vec_changed(current: Vector, target: Vector, eps: float = constants.LOC_EPS) -> bool:
    return (current - target).length > eps


def quat_changed(current: Quaternion, target: Quaternion, eps: float = constants.ROT_EPS) -> bool:
    return (1.0 - abs(current.dot(target))) > eps


def format_preview_pose(raw_pose):
    px, py, pz, qx, qy, qz, qw = raw_pose
    return f"pos=({px:.4f}, {py:.4f}, {pz:.4f}) rot=({qx:.4f}, {qy:.4f}, {qz:.4f}, {qw:.4f})"


def format_preview_value(raw_value):
    try:
        return f"{float(raw_value):.4f}"
    except (TypeError, ValueError):
        return str(raw_value)
