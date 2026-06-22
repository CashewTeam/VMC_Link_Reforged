import bpy
import json
import os
import time
import traceback

import socket
from mathutils import Vector, Quaternion

from pythonosc.dispatcher import Dispatcher


DEFAULT_PORT = 39539
DEFAULT_BIND_ADDRESS = "127.0.0.1"
DEFAULT_RATE_HZ = 60
DEFAULT_ARKIT_PORT = 17890

# Tiny change thresholds to avoid needless Blender updates
LOC_EPS = 1e-5
ROT_EPS = 1e-6
SHAPE_EPS = 1e-4

BIND_MODE_THIS_PC = "THIS_PC"
BIND_MODE_LOCAL_NET = "LOCAL_NET"
BIND_MODE_CUSTOM = "CUSTOM"

FACE_SOURCE_VMC = "VMC"
FACE_SOURCE_RHYLIVE_ARKIT = "RHYLIVE_ARKIT"

DUMMY_ARMATURE_NAME = "VMC_TEST_DUMMY"
DUMMY_DELETE_OLD = True
DEBUG_LOGGING = False


# Common VMC bone names
BONE_ALIASES = {
    # Core
    "Hips": ["hips", "pelvis", "root"],
    "Spine": ["spine", "spine1", "spine_01"],
    "Chest": ["chest", "spine2", "spine_02", "upperchest", "spine3", "spine_03"],
    "Neck": ["neck"],
    "Head": ["head"],

    # Eyes
    "LeftEye": [
        "lefteye",
        "lefteyebone",
        "eye_l",
        "eye.l",
        "l_eye",
        "eyel",
        "left_eye",
        "left eye",
        "faceeye_l",
        "face_eye_l",
        "eyeleft",
    ],
    "RightEye": [
        "righteye",
        "righteyebone",
        "eye_r",
        "eye.r",
        "r_eye",
        "eyer",
        "right_eye",
        "right eye",
        "faceeye_r",
        "face_eye_r",
        "eyeright",
    ],

    # Shoulders
    "LeftShoulder": ["leftshoulder", "left shoulder", "shoulder_l", "shoulder.l"],
    "RightShoulder": ["rightshoulder", "right shoulder", "shoulder_r", "shoulder.r"],

    # Arms
    "LeftUpperArm": ["leftupperarm", "left arm", "upperarm_l", "upperarm.l"],
    "LeftLowerArm": ["leftlowerarm", "left elbow", "lowerarm_l", "lowerarm.l", "forearm_l", "forearm.l", "leftforearm", "left forearm"],
    "LeftHand": ["lefthand", "left wrist", "hand_l", "hand.l", "wrist_l", "wrist.l"],
    "RightUpperArm": ["rightupperarm", "right arm", "upperarm_r", "upperarm.r"],
    "RightLowerArm": ["rightlowerarm", "right elbow", "lowerarm_r", "lowerarm.r", "forearm_r", "forearm.r", "rightforearm", "right forearm"],
    "RightHand": ["righthand", "right wrist", "hand_r", "hand.r", "wrist_r", "wrist.r"],

    # Legs
    "LeftUpperLeg": ["leftupperleg", "left leg", "leftupleg", "upperleg_l", "upperleg.l", "thigh_l", "thigh.l"],
    "LeftLowerLeg": ["leftlowerleg", "left knee", "lowerleg_l", "lowerleg.l", "calf_l", "calf.l"],
    "LeftFoot": ["leftfoot", "left ankle", "foot_l", "foot.l", "ankle_l", "ankle.l"],
    "RightUpperLeg": ["rightupperleg", "right leg", "rightupleg", "upperleg_r", "upperleg.r", "thigh_r", "thigh.r"],
    "RightLowerLeg": ["rightlowerleg", "right knee", "lowerleg_r", "lowerleg.r", "calf_r", "calf.r"],
    "RightFoot": ["rightfoot", "right ankle", "foot_r", "foot.r", "ankle_r", "ankle.r"],
}


_FINGER_SPECS = {
    "Thumb": "thumb",
    "IndexFinger": "f_index",
    "MiddleFinger": "f_middle",
    "RingFinger": "f_ring",
    "LittleFinger": "f_pinky",
}

_FINGER_SEGMENTS = ("proximal", "intermediate", "distal")


def _build_finger_aliases(side_suffix: str):
    aliases = {}
    side_name = "left" if side_suffix == "L" else "right"
    side = side_suffix.lower()

    for finger_name, blender_prefix in _FINGER_SPECS.items():
        short_name = finger_name.replace("Finger", "").lower()
        is_thumb = finger_name == "Thumb"

        for joint_pos, segment in enumerate(_FINGER_SEGMENTS):
            vmc_idx = joint_pos if is_thumb else joint_pos + 1
            vmc_name = f"{finger_name}{vmc_idx}_{side_suffix}"

            row = [
                vmc_name.lower(),
                f"{side_name}{short_name}{segment}",
            ]

            # Support both numbering styles used by rigs: 0-based and 1-based chains.
            for idx in (joint_pos, joint_pos + 1):
                row.append(f"{blender_prefix}.{idx:02d}.{side}")
                row.append(f"{blender_prefix}_{idx:02d}_{side}")
                if not is_thumb:
                    row.append(f"{short_name}.{idx:02d}.{side}")
                    row.append(f"{short_name}_{idx:02d}_{side}")

            aliases[vmc_name] = row

    return aliases


BONE_ALIASES.update(_build_finger_aliases("L"))
BONE_ALIASES.update(_build_finger_aliases("R"))

def _bone_override_prop_name(vmc_name: str) -> str:
    return f"vmc_link_bone_override_{vmc_name.lower()}"


def _normalize_identifier(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(name))


def _normalize_bone_name(name: str) -> str:
    # Support namespaced rigs like mixamorig: and variants.
    base = name.rsplit(":", 1)[-1]
    return "".join(ch for ch in base.lower() if ch.isalnum())


# Common VMC blend keys
BLEND_ALIASES = {
    # Basic vowels
    "A": ["A", "a", "MTH_A", "mouth_a", "vrc.v_aa", "Viseme_AA", "viseme_aa"],
    "I": ["I", "i", "MTH_I", "mouth_i", "vrc.v_ih", "Viseme_IH", "viseme_ih"],
    "U": ["U", "u", "MTH_U", "mouth_u", "vrc.v_ou", "Viseme_OU", "viseme_ou"],
    "E": ["E", "e", "MTH_E", "mouth_e", "vrc.v_e", "Viseme_E", "viseme_e"],
    "O": ["O", "o", "MTH_O", "mouth_o", "vrc.v_oh", "Viseme_OH", "viseme_oh"],

    # Extra visemes
    "CH": ["CH", "ch", "MTH_CH", "mouth_ch", "vrc.v_ch", "Viseme_CH", "viseme_ch"],
    "DD": ["DD", "dd", "MTH_DD", "mouth_dd", "vrc.v_dd", "Viseme_DD", "viseme_dd"],
    "FF": ["FF", "ff", "MTH_FF", "mouth_ff", "vrc.v_ff", "Viseme_FF", "viseme_ff"],
    "KK": ["KK", "kk", "MTH_KK", "mouth_kk", "vrc.v_kk", "Viseme_KK", "viseme_kk"],
    "NN": ["NN", "nn", "MTH_NN", "mouth_nn", "vrc.v_nn", "Viseme_NN", "viseme_nn"],
    "PP": ["PP", "pp", "MTH_PP", "mouth_pp", "vrc.v_pp", "Viseme_PP", "viseme_pp"],
    "RR": ["RR", "rr", "MTH_RR", "mouth_rr", "vrc.v_rr", "Viseme_RR", "viseme_rr"],
    "SIL": ["SIL", "sil", "MTH_SIL", "mouth_sil", "vrc.v_sil", "Viseme_SIL", "viseme_sil"],
    "SS": ["SS", "ss", "MTH_SS", "mouth_ss", "vrc.v_ss", "Viseme_SS", "viseme_ss"],
    "TH": ["TH", "th", "MTH_TH", "mouth_th", "vrc.v_th", "Viseme_TH", "viseme_th"],

    # Core expression channels
    "Fun": ["Fun", "fun", "MTH_Fun", "Smile", "smile", "Happy", "happy", "face happy"],
    "Joy": ["Joy", "joy", "VMC_Joy", "face joy", "face happy"],
    "Sorrow": ["Sorrow", "sorrow", "Sad", "sad", "VMC_Sorrow", "face sad"],
    "Angry": ["Angry", "angry", "VMC_Angry", "face angry"],
    "Surprise": ["Surprise", "surprise", "Surprised", "surprised", "VMC_Surprise", "face surprised"],

    # Backward-compatible generic aliases
    "Sad": ["Sad", "sad", "face sad"],
    "Surprised": ["Surprised", "surprised", "face surprised"],

    # Blink
    "Blink": [
        "Blink",
        "blink",
        "blink both",
        "EYE_Close",
        "eyeBlink",
        "EyeBlink",
        "vrc.blink",
        "EyeClose",
    ],
    "Blink_L": [
        "Blink_L",
        "BlinkLeft",
        "blink_l",
        "blinkleft",
        "EYE_Close_L",
        "eyeBlinkLeft",
        "EyeBlinkLeft",
        "eyeBlink_L",
        "EyeBlink_L",
        "vrc.blink_left",
        "vrc.blink.L",
        "vrc.lowerlid_left",
        "eyeCloseLeft",
    ],
    "Blink_R": [
        "Blink_R",
        "BlinkRight",
        "blink_r",
        "blinkright",
        "EYE_Close_R",
        "eyeBlinkRight",
        "EyeBlinkRight",
        "eyeBlink_R",
        "EyeBlink_R",
        "vrc.blink_right",
        "vrc.blink.R",
        "vrc.lowerlid_right",
        "eyeCloseRight",
    ],

    # Eye look
    "LookUp": ["LookUp", "lookUp", "look_up", "look up", "EYE_LookUp", "eyeLookUp", "vrc.look_up", "vrc.lookUp", "vrc.look.U"],
    "LookDown": ["LookDown", "lookDown", "look_down", "look down", "EYE_LookDown", "eyeLookDown", "vrc.look_down", "vrc.lookDown", "vrc.look.D"],
    "LookLeft": ["LookLeft", "lookLeft", "look_left", "look left", "EYE_LookLeft", "eyeLookLeft", "vrc.look_left", "vrc.lookLeft", "vrc.look.L"],
    "LookRight": ["LookRight", "lookRight", "look_right", "look right", "EYE_LookRight", "eyeLookRight", "vrc.look_right", "vrc.lookRight", "vrc.look.R"],
    "LookUp_L": ["LookUp_L", "LookUpLeft", "lookUpLeft", "eyeLookUpLeft", "EyeLookUpLeft", "vrc.lookUp.L"],
    "LookUp_R": ["LookUp_R", "LookUpRight", "lookUpRight", "eyeLookUpRight", "EyeLookUpRight", "vrc.lookUp.R"],
    "LookDown_L": ["LookDown_L", "LookDownLeft", "lookDownLeft", "eyeLookDownLeft", "EyeLookDownLeft", "vrc.lookDown.L"],
    "LookDown_R": ["LookDown_R", "LookDownRight", "lookDownRight", "eyeLookDownRight", "EyeLookDownRight", "vrc.lookDown.R"],
    "LookLeft_L": ["LookLeft_L", "LookLeftLeft", "lookLeftLeft", "eyeLookLeftLeft", "EyeLookLeftLeft", "eyeLookOutLeft"],
    "LookLeft_R": ["LookLeft_R", "LookLeftRight", "lookLeftRight", "eyeLookLeftRight", "EyeLookLeftRight", "eyeLookInRight"],
    "LookRight_L": ["LookRight_L", "LookRightLeft", "lookRightLeft", "eyeLookRightLeft", "EyeLookRightLeft", "eyeLookInLeft"],
    "LookRight_R": ["LookRight_R", "LookRightRight", "lookRightRight", "eyeLookRightRight", "EyeLookRightRight", "eyeLookOutRight"],

    # Brows
    "BrowsDownUp": ["BrowsDownUp", "BRW_Up", "BrowUp", "browUp", "BrowsUp", "brows_up", "brow_raise", "browInnerUp", "eyebrow_up"],
    "BrowInnerUp": ["BrowInnerUp", "browInnerUp", "brow_inner_up", "brow up", "BRW_Up"],
    "BrowDown_L": ["BrowDown_L", "BrowDownLeft", "browDownLeft", "brow_down_l", "brow down left", "BRW_Down_L"],
    "BrowDown_R": ["BrowDown_R", "BrowDownRight", "browDownRight", "brow_down_r", "brow down right", "BRW_Down_R"],
    "BrowOuterUp_L": ["BrowOuterUp_L", "BrowOuterUpLeft", "browOuterUpLeft", "brow_outer_up_l", "brow outer up left", "BRW_Up_L"],
    "BrowOuterUp_R": ["BrowOuterUp_R", "BrowOuterUpRight", "browOuterUpRight", "brow_outer_up_r", "brow outer up right", "BRW_Up_R"],
}


ARKIT_BLENDSHAPE_KEYS = [
    "browDownLeft",
    "browDownRight",
    "browInnerUp",
    "browOuterUpLeft",
    "browOuterUpRight",
    "cheekPuff",
    "cheekSquintLeft",
    "cheekSquintRight",
    "eyeBlinkLeft",
    "eyeBlinkRight",
    "eyeLookDownLeft",
    "eyeLookDownRight",
    "eyeLookInLeft",
    "eyeLookInRight",
    "eyeLookOutLeft",
    "eyeLookOutRight",
    "eyeLookUpLeft",
    "eyeLookUpRight",
    "eyeSquintLeft",
    "eyeSquintRight",
    "eyeWideLeft",
    "eyeWideRight",
    "jawForward",
    "jawLeft",
    "jawOpen",
    "jawRight",
    "mouthClose",
    "mouthDimpleLeft",
    "mouthDimpleRight",
    "mouthFrownLeft",
    "mouthFrownRight",
    "mouthFunnel",
    "mouthLeft",
    "mouthLowerDownLeft",
    "mouthLowerDownRight",
    "mouthPressLeft",
    "mouthPressRight",
    "mouthPucker",
    "mouthRight",
    "mouthRollLower",
    "mouthRollUpper",
    "mouthShrugLower",
    "mouthShrugUpper",
    "mouthSmileLeft",
    "mouthSmileRight",
    "mouthStretchLeft",
    "mouthStretchRight",
    "mouthUpperUpLeft",
    "mouthUpperUpRight",
    "noseSneerLeft",
    "noseSneerRight",
    "tongueOut",
]

MAPPING_KIND_BONE = "bone"
MAPPING_KIND_VMC_BLEND = "vmc_blend"
MAPPING_KIND_ARKIT_BLEND = "arkit_blend"

PRESET_NONE_ID = "__NONE__"
PRESET_SCHEMA_VERSION = 1

MAPPING_KIND_LABELS = {
    MAPPING_KIND_BONE: "Bone Mapping",
    MAPPING_KIND_VMC_BLEND: "VMC Blend Mapping",
    MAPPING_KIND_ARKIT_BLEND: "ARKit Blend Mapping",
}

MAPPING_PRESET_SUBDIRS = {
    MAPPING_KIND_BONE: "bone_maps",
    MAPPING_KIND_VMC_BLEND: "vmc_blend_maps",
    MAPPING_KIND_ARKIT_BLEND: "arkit_blend_maps",
}

MAPPING_PRESET_PROP_NAMES = {
    MAPPING_KIND_BONE: ("vmc_link_bone_map_preset", "vmc_link_bone_map_save_name"),
    MAPPING_KIND_VMC_BLEND: ("vmc_link_vmc_blend_preset", "vmc_link_vmc_blend_save_name"),
    MAPPING_KIND_ARKIT_BLEND: ("vmc_link_arkit_blend_preset", "vmc_link_arkit_blend_save_name"),
}

_preset_items_cache = {
    MAPPING_KIND_BONE: [],
    MAPPING_KIND_VMC_BLEND: [],
    MAPPING_KIND_ARKIT_BLEND: [],
}


# -------------------------
# Scene properties (config)
# -------------------------

def _poll_armature(_self, obj):
    return obj is None or obj.type == "ARMATURE"


def _poll_mesh(_self, obj):
    return obj is None or obj.type == "MESH"


def _has_pose_bones(obj) -> bool:
    return bool(obj and getattr(obj, "type", None) == "ARMATURE" and getattr(obj, "pose", None) is not None)


def _has_shape_keys(obj) -> bool:
    return bool(
        obj
        and getattr(obj, "type", None) == "MESH"
        and getattr(obj, "data", None) is not None
        and getattr(obj.data, "shape_keys", None) is not None
    )


def _invalidate_bone_map_cache(_self=None, _context=None):
    global _cached_bone_map
    _cached_bone_map = {}


def _invalidate_blend_map_cache(_self=None, _context=None):
    global _cached_blend_map, _cached_arkit_blend_map
    _cached_blend_map = {}
    _cached_arkit_blend_map = {}


def _on_armature_changed(self, _context):
    _invalidate_bone_map_cache()

    arm = getattr(self, "vmc_link_armature", None)
    if not _has_pose_bones(arm):
        return

    _autofill_empty_manual_overrides(self, arm)


def _on_face_object_changed(self, _context):
    _invalidate_blend_map_cache()


def _ensure_bone_override_props(sc):
    for vmc_name in BONE_ALIASES:
        prop_name = _bone_override_prop_name(vmc_name)
        if hasattr(sc, prop_name):
            continue
        setattr(
            sc,
            prop_name,
            bpy.props.StringProperty(
                name=vmc_name,
                description=f"Manual mapping for VMC bone {vmc_name}",
                default="",
                update=_invalidate_bone_map_cache,
            ),
        )


def _blend_override_prop_name(vmc_name: str) -> str:
    return f"vmc_link_blend_override_{vmc_name.lower()}"


def _arkit_override_prop_name(arkit_key: str) -> str:
    return f"vmc_link_arkit_override_{_normalize_identifier(arkit_key)}"


def _ensure_blend_override_props(sc):
    for vmc_name in BLEND_ALIASES:
        prop_name = _blend_override_prop_name(vmc_name)
        if hasattr(sc, prop_name):
            continue
        setattr(
            sc,
            prop_name,
            bpy.props.StringProperty(
                name=vmc_name,
                description=f"Manual mapping for VMC blend {vmc_name}",
                default="",
                update=_invalidate_blend_map_cache,
            ),
        )


def _ensure_arkit_override_props(sc):
    for arkit_key in ARKIT_BLENDSHAPE_KEYS:
        prop_name = _arkit_override_prop_name(arkit_key)
        if hasattr(sc, prop_name):
            continue
        setattr(
            sc,
            prop_name,
            bpy.props.StringProperty(
                name=arkit_key,
                description=f"Manual mapping for ARKit blend {arkit_key}",
                default="",
                update=_invalidate_blend_map_cache,
            ),
        )


def _mapping_keys(kind: str):
    if kind == MAPPING_KIND_BONE:
        return list(BONE_ALIASES.keys())
    if kind == MAPPING_KIND_VMC_BLEND:
        return list(BLEND_ALIASES.keys())
    if kind == MAPPING_KIND_ARKIT_BLEND:
        return list(ARKIT_BLENDSHAPE_KEYS)
    raise KeyError(f"Unknown mapping kind: {kind}")


def _mapping_prop_name(kind: str, source_key: str) -> str:
    if kind == MAPPING_KIND_BONE:
        return _bone_override_prop_name(source_key)
    if kind == MAPPING_KIND_VMC_BLEND:
        return _blend_override_prop_name(source_key)
    if kind == MAPPING_KIND_ARKIT_BLEND:
        return _arkit_override_prop_name(source_key)
    raise KeyError(f"Unknown mapping kind: {kind}")


def _mapping_kind_label(kind: str) -> str:
    try:
        return MAPPING_KIND_LABELS[kind]
    except KeyError as exc:
        raise KeyError(f"Unknown mapping kind: {kind}") from exc


def _mapping_preset_dir(kind: str) -> str:
    try:
        subdir = MAPPING_PRESET_SUBDIRS[kind]
    except KeyError as exc:
        raise KeyError(f"Unknown mapping kind: {kind}") from exc
    return os.path.join(os.path.dirname(__file__), "presets", subdir)


def _ensure_mapping_preset_dir(kind: str) -> str:
    path = _mapping_preset_dir(kind)
    os.makedirs(path, exist_ok=True)
    return path


def _mapping_preset_prop_names(kind: str):
    try:
        return MAPPING_PRESET_PROP_NAMES[kind]
    except KeyError as exc:
        raise KeyError(f"Unknown mapping kind: {kind}") from exc


def _get_mapping_preset_selection(scene, kind: str) -> str:
    preset_prop, _ = _mapping_preset_prop_names(kind)
    return str(getattr(scene, preset_prop, PRESET_NONE_ID))


def _set_mapping_preset_selection(scene, kind: str, value: str):
    preset_prop, _ = _mapping_preset_prop_names(kind)
    setattr(scene, preset_prop, value)


def _get_mapping_preset_save_name(scene, kind: str) -> str:
    _, save_prop = _mapping_preset_prop_names(kind)
    return str(getattr(scene, save_prop, ""))


def _scan_mapping_presets(kind: str):
    preset_dir = _ensure_mapping_preset_dir(kind)
    items = [(PRESET_NONE_ID, "None", f"No {_mapping_kind_label(kind)} preset selected")]

    try:
        names = sorted(
            file_name
            for file_name in os.listdir(preset_dir)
            if file_name.lower().endswith(".json") and os.path.isfile(os.path.join(preset_dir, file_name))
        )
    except OSError as e:
        _warn(f"Failed to list {_mapping_kind_label(kind)} presets", e)
        names = []

    for file_name in names:
        label = os.path.splitext(file_name)[0]
        items.append((file_name, label, f"Load {_mapping_kind_label(kind)} preset '{label}'"))

    _preset_items_cache[kind] = items
    return items


def _enum_mapping_preset_items(kind: str):
    items = _preset_items_cache.get(kind) or []
    if not items:
        items = _scan_mapping_presets(kind)
    return items


def _enum_bone_map_preset_items(_self, _context):
    return _enum_mapping_preset_items(MAPPING_KIND_BONE)


def _enum_vmc_blend_preset_items(_self, _context):
    return _enum_mapping_preset_items(MAPPING_KIND_VMC_BLEND)


def _enum_arkit_blend_preset_items(_self, _context):
    return _enum_mapping_preset_items(MAPPING_KIND_ARKIT_BLEND)


def _refresh_all_mapping_preset_caches():
    for kind in MAPPING_KIND_LABELS:
        _scan_mapping_presets(kind)


def _sanitize_mapping_preset_filename(name: str) -> str:
    safe = str(name).strip().replace("/", "_").replace("\\", "_")
    if not safe:
        return ""
    if not safe.lower().endswith(".json"):
        safe += ".json"
    return safe


def _get_mapping_override(scene, kind: str, source_key: str) -> str:
    if scene is None:
        return ""

    prop_name = _mapping_prop_name(kind, source_key)
    if not hasattr(scene, prop_name):
        return ""
    return str(getattr(scene, prop_name, "")).strip()


def _set_mapping_override(scene, kind: str, source_key: str, target_name: str):
    prop_name = _mapping_prop_name(kind, source_key)
    if hasattr(scene, prop_name):
        setattr(scene, prop_name, str(target_name).strip())


def _clear_mapping_overrides(scene, kind: str):
    for source_key in _mapping_keys(kind):
        _set_mapping_override(scene, kind, source_key, "")


def _collect_mapping_entries(scene, kind: str):
    entries = {}
    for source_key in _mapping_keys(kind):
        target_name = _get_mapping_override(scene, kind, source_key)
        if target_name:
            entries[source_key] = target_name
    return entries


def _apply_mapping_entries(scene, kind: str, entries: dict):
    _clear_mapping_overrides(scene, kind)

    known_keys = set(_mapping_keys(kind))
    for source_key, target_name in entries.items():
        if source_key not in known_keys:
            continue
        if not isinstance(target_name, str):
            continue
        _set_mapping_override(scene, kind, source_key, target_name)


def _mapping_preset_payload(scene, kind: str):
    return {
        "version": PRESET_SCHEMA_VERSION,
        "mapping_kind": kind,
        "entries": _collect_mapping_entries(scene, kind),
    }


def _load_mapping_preset_payload(payload, kind: str):
    if not isinstance(payload, dict):
        raise RuntimeError("Preset JSON must be an object")

    if payload.get("version") != PRESET_SCHEMA_VERSION:
        raise RuntimeError(f"Unsupported preset version: {payload.get('version')}")

    if payload.get("mapping_kind") != kind:
        raise RuntimeError(f"Preset kind mismatch: expected '{kind}'")

    entries = payload.get("entries")
    if not isinstance(entries, dict):
        raise RuntimeError("Preset JSON field 'entries' must be an object")

    return entries


def _get_addon_preferences():
    try:
        addon_key = (__package__ or "vmc_link").split(".")[0]
        prefs_entry = bpy.context.preferences.addons.get(addon_key)
    except Exception as e:
        _warn("Failed to access addon preferences", e)
        return None

    if not prefs_entry:
        return None
    return getattr(prefs_entry, "preferences", None)


def _resolve_bind_host(scene) -> str:
    mode = str(getattr(scene, "vmc_link_bind_mode", BIND_MODE_THIS_PC))

    if mode == BIND_MODE_LOCAL_NET:
        return "0.0.0.0"

    if mode == BIND_MODE_CUSTOM:
        custom = str(getattr(scene, "vmc_link_bind_address_custom", "")).strip()
        return custom

    return "127.0.0.1"


def _get_connection_defaults():
    prefs = _get_addon_preferences()
    if prefs is None:
        return {
            "bind_mode": BIND_MODE_THIS_PC,
            "bind_custom": DEFAULT_BIND_ADDRESS,
            "port": DEFAULT_PORT,
            "rate_hz": DEFAULT_RATE_HZ,
        }

    bind_address = str(getattr(prefs, "default_bind_address", DEFAULT_BIND_ADDRESS)).strip() or DEFAULT_BIND_ADDRESS
    port = int(getattr(prefs, "default_port", DEFAULT_PORT))
    rate_hz = int(getattr(prefs, "default_rate_hz", DEFAULT_RATE_HZ))

    if bind_address == "0.0.0.0":
        bind_mode = BIND_MODE_LOCAL_NET
        bind_custom = DEFAULT_BIND_ADDRESS
    elif bind_address == "127.0.0.1":
        bind_mode = BIND_MODE_THIS_PC
        bind_custom = DEFAULT_BIND_ADDRESS
    else:
        bind_mode = BIND_MODE_CUSTOM
        bind_custom = bind_address

    return {
        "bind_mode": bind_mode,
        "bind_custom": bind_custom,
        "port": max(1, min(65535, port)),
        "rate_hz": max(1, min(240, rate_hz)),
    }


def _persist_connection_defaults(scene):
    if scene is None:
        return

    prefs = _get_addon_preferences()
    if prefs is None:
        return

    try:
        prefs.default_bind_address = _resolve_bind_host(scene) or DEFAULT_BIND_ADDRESS
        prefs.default_port = int(getattr(scene, "vmc_link_port", DEFAULT_PORT))
        prefs.default_rate_hz = int(getattr(scene, "vmc_link_rate_hz", DEFAULT_RATE_HZ))
    except Exception as e:
        _warn("Failed to persist connection defaults", e)


def _build_vmc_dispatcher():
    dispatcher = Dispatcher()
    dispatcher.map("/VMC/Ext/Root/Pos", _on_vmc_root_pos)
    dispatcher.map("/VMC/Ext/Tra/Pos", _on_vmc_tra_pos)
    dispatcher.map("/VMC/Ext/Bone/Pos", _on_vmc_bone_pos)
    dispatcher.map("/VMC/Ext/Blend/Val", _on_vmc_blend_val)
    return dispatcher


def _build_arkit_dispatcher():
    dispatcher = Dispatcher()
    dispatcher.map("/Face", _on_arkit_face)
    return dispatcher


def _create_udp_socket(bind_host: str, port: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((bind_host, port))
    return sock


def _restart_server(scene):
    """Restart the UDP receiver with current scene settings."""
    global _receiver_socket, _dispatcher, _arkit_receiver_socket, _arkit_dispatcher
    global _cached_bone_map, _cached_blend_map

    if not is_running():
        return

    bind_host = _resolve_bind_host(scene).strip()
    if not bind_host:
        raise RuntimeError("Address cannot be empty")

    port = int(scene.vmc_link_port)
    new_socket = None
    new_arkit_socket = None
    try:
        new_socket = _create_udp_socket(bind_host, port)
        new_dispatcher = _build_vmc_dispatcher()
        new_arkit_dispatcher = None

        if _is_arkit_face_source_enabled(scene):
            new_arkit_socket = _create_udp_socket(bind_host, int(scene.vmc_link_arkit_port))
            new_arkit_dispatcher = _build_arkit_dispatcher()
    except Exception:
        try:
            new_socket.close()
        except Exception:
            pass
        try:
            if new_arkit_socket is not None:
                new_arkit_socket.close()
        except Exception:
            pass
        raise

    old_socket = _receiver_socket
    old_arkit_socket = _arkit_receiver_socket
    _receiver_socket = new_socket
    _dispatcher = new_dispatcher
    _arkit_receiver_socket = new_arkit_socket
    _arkit_dispatcher = new_arkit_dispatcher

    _reset_runtime_buffers()
    _cached_bone_map = {}
    _cached_blend_map = {}

    try:
        if old_socket is not None:
            old_socket.close()
    except Exception as e:
        _warn("Failed to close old OSC socket cleanly", e)

    try:
        if old_arkit_socket is not None:
            old_arkit_socket.close()
    except Exception as e:
        _warn("Failed to close old ARKit OSC socket cleanly", e)

    _debug(f"Receiver rebound to UDP {bind_host}:{port}")
    if new_arkit_socket is not None:
        _debug(f"ARKit face receiver rebound to UDP {bind_host}:{scene.vmc_link_arkit_port}")


def _on_receiver_endpoint_changed(self, _context):
    """Persist settings and rebind socket when bind address or port changes."""
    _persist_connection_defaults(self)

    if is_running():
        try:
            _restart_server(self)
        except Exception as e:
            _warn("Failed to rebind receiver after endpoint change", e)


def _on_connection_setting_changed(self, _context):
    """Persist settings that do not require socket rebind."""
    global _next_tick_ts
    _persist_connection_defaults(self)
    _next_tick_ts = 0.0


def _on_live_preview_changed(self, _context):
    """Force a refresh when live preview is re-enabled."""
    global _dirty

    if bool(getattr(self, "vmc_link_live_preview", True)):
        _dirty = True


def _on_face_source_changed(self, _context):
    """Switch face input source without affecting the VMC body stream."""
    global _next_tick_ts
    _next_tick_ts = 0.0

    if is_running():
        try:
            _restart_server(self)
        except Exception as e:
            _warn("Failed to switch face source while receiver was running", e)


def _ensure_scene_props():
    sc = bpy.types.Scene
    defaults = _get_connection_defaults()

    sc.vmc_link_port = bpy.props.IntProperty(
        name="Port",
        description="UDP port to listen on for VMC/OSC",
        default=defaults["port"],
        min=1,
        max=65535,
        update=_on_receiver_endpoint_changed,
    )

    sc.vmc_link_bind_mode = bpy.props.EnumProperty(
        name="Receive On",
        description="Choose which interface the UDP receiver binds to",
        items=(
            (BIND_MODE_THIS_PC, "Only this PC", "Bind to 127.0.0.1 (localhost)"),
            (BIND_MODE_LOCAL_NET, "Any network interface", "Bind to 0.0.0.0 (All interfaces)"),
            (BIND_MODE_CUSTOM, "Custom address", "Bind to a specific custom IP/address"),
        ),
        default=defaults["bind_mode"],
        update=_on_receiver_endpoint_changed,
    )

    sc.vmc_link_bind_address_custom = bpy.props.StringProperty(
        name="Custom Address",
        description="Custom local address/interface to bind UDP receiver to",
        default=defaults["bind_custom"],
        update=_on_receiver_endpoint_changed,
    )

    sc.vmc_link_rate_hz = bpy.props.IntProperty(
        name="Apply Rate (Hz)",
        description="How often to apply received transforms to the rig",
        default=defaults["rate_hz"],
        min=1,
        max=240,
        update=_on_connection_setting_changed,
    )

    sc.vmc_link_live_preview = bpy.props.BoolProperty(
        name="Live Preview Targets",
        description="Apply received VMC data to the selected armature and face mesh in real time",
        default=True,
        update=_on_live_preview_changed,
    )

    sc.vmc_link_face_source = bpy.props.EnumProperty(
        name="Face Source",
        description="Choose which incoming stream provides face blend data",
        items=(
            (FACE_SOURCE_VMC, "VMC", "Use /VMC/Ext/Blend/Val for face data"),
            (FACE_SOURCE_RHYLIVE_ARKIT, "RhyLive ARKit", "Use RhyLive OSC /Face ARKit coefficients"),
        ),
        default=FACE_SOURCE_VMC,
        update=_on_face_source_changed,
    )

    sc.vmc_link_arkit_port = bpy.props.IntProperty(
        name="ARKit Port",
        description="UDP port to listen on for RhyLive ARKit OSC /Face data",
        default=DEFAULT_ARKIT_PORT,
        min=1,
        max=65535,
        update=_on_receiver_endpoint_changed,
    )

    sc.vmc_link_armature = bpy.props.PointerProperty(
        name="Armature",
        description="Target armature to drive",
        type=bpy.types.Object,
        poll=_poll_armature,
        update=_on_armature_changed,
    )

    sc.vmc_link_face_object = bpy.props.PointerProperty(
        name="Face Mesh",
        description="Mesh object that contains shape keys",
        type=bpy.types.Object,
        poll=_poll_mesh,
        update=_on_face_object_changed,
    )

    sc.vmc_link_bone_map_preset = bpy.props.EnumProperty(
        name="Preset",
        description="Saved bone mapping preset",
        items=_enum_bone_map_preset_items,
    )

    sc.vmc_link_bone_map_save_name = bpy.props.StringProperty(
        name="Save Name",
        description="File name for the current bone mapping preset",
        default="",
    )

    sc.vmc_link_vmc_blend_preset = bpy.props.EnumProperty(
        name="Preset",
        description="Saved VMC blend mapping preset",
        items=_enum_vmc_blend_preset_items,
    )

    sc.vmc_link_vmc_blend_save_name = bpy.props.StringProperty(
        name="Save Name",
        description="File name for the current VMC blend mapping preset",
        default="",
    )

    sc.vmc_link_arkit_blend_preset = bpy.props.EnumProperty(
        name="Preset",
        description="Saved ARKit blend mapping preset",
        items=_enum_arkit_blend_preset_items,
    )

    sc.vmc_link_arkit_blend_save_name = bpy.props.StringProperty(
        name="Save Name",
        description="File name for the current ARKit blend mapping preset",
        default="",
    )

    _ensure_bone_override_props(sc)
    _ensure_blend_override_props(sc)
    _ensure_arkit_override_props(sc)


def _debug(msg: str):
    if DEBUG_LOGGING:
        print(f"[VMC Link] {msg}")


def _warn(msg: str, exc: Exception = None):
    if exc is None:
        print(f"[VMC Link] {msg}")
        return

    print(f"[VMC Link] {msg}: {exc}")
    _debug(traceback.format_exc())


def _convert_vmc_pose(px, py, pz, qx, qy, qz, qw):
    """Convert VMC pose values to Blender-space location/quaternion."""
    loc = Vector((-px, -pz, py))
    quat = Quaternion((qw, qx, qz, -qy))
    return loc, quat


def _vec_changed(current: Vector, target: Vector, eps: float = LOC_EPS) -> bool:
    return (current - target).length > eps


def _quat_changed(current: Quaternion, target: Quaternion, eps: float = ROT_EPS) -> bool:
    # q and -q represent the same rotation, so compare absolute dot.
    return (1.0 - abs(current.dot(target))) > eps


# -------------------------
# Runtime state
# -------------------------

_receiver_socket = None
_dispatcher = None
_arkit_receiver_socket = None
_arkit_dispatcher = None
_apply_timer_running = False

_root_buf = None
_waist_buf = None
_bone_buf = {}
_blend_buf = {}
_arkit_blend_buf = {key: 0.0 for key in ARKIT_BLENDSHAPE_KEYS}
_cached_bone_map = {}
_cached_blend_map = {}
_cached_arkit_blend_map = {}
_dirty = False

_last_packet_ts = 0.0
_arkit_last_packet_ts = 0.0
_next_tick_ts = 0.0

_recording = False


def _reset_runtime_buffers():
    global _root_buf, _waist_buf, _bone_buf, _blend_buf, _arkit_blend_buf, _dirty
    global _last_packet_ts, _arkit_last_packet_ts, _next_tick_ts, _cached_arkit_blend_map

    _root_buf = None
    _waist_buf = None
    _bone_buf = {}
    _blend_buf = {}
    _arkit_blend_buf = {key: 0.0 for key in ARKIT_BLENDSHAPE_KEYS}
    _cached_arkit_blend_map = {}
    _dirty = False
    _last_packet_ts = 0.0
    _arkit_last_packet_ts = 0.0
    _next_tick_ts = 0.0


def is_running() -> bool:
    return _receiver_socket is not None or _arkit_receiver_socket is not None


def is_recording() -> bool:
    return _recording


def _record_current_sample(scene, arm, driven_bones, face, driven_shapes):
    recorded_any = False

    if arm is not None:
        try:
            arm.keyframe_insert(data_path="location")
            if arm.rotation_mode == "QUATERNION":
                arm.keyframe_insert(data_path="rotation_quaternion")
            else:
                arm.keyframe_insert(data_path="rotation_euler")
            recorded_any = True
        except Exception as e:
            _debug(f"Failed to keyframe armature root: {e}")

        pose = arm.pose.bones if getattr(arm, "pose", None) is not None else None
        if pose is not None:
            for bone_name in driven_bones:
                pb = pose.get(bone_name)
                if pb is None:
                    continue
                try:
                    pb.keyframe_insert(data_path="rotation_quaternion")
                    recorded_any = True
                except Exception as e:
                    _debug(f"Failed to keyframe bone '{bone_name}': {e}")

    if _has_shape_keys(face):
        blocks = face.data.shape_keys.key_blocks
        for key_name in driven_shapes:
            kb = blocks.get(key_name)
            if kb is None:
                continue
            try:
                kb.keyframe_insert(data_path="value")
                recorded_any = True
            except Exception as e:
                _debug(f"Failed to keyframe shape key '{key_name}': {e}")

    if recorded_any and not bpy.context.screen.is_animation_playing:
        scene.frame_set(scene.frame_current + 1)


def _format_preview_pose(raw_pose):
    px, py, pz, qx, qy, qz, qw = raw_pose
    return (
        f"pos=({px:.4f}, {py:.4f}, {pz:.4f}) "
        f"rot=({qx:.4f}, {qy:.4f}, {qz:.4f}, {qw:.4f})"
    )


def _format_preview_value(raw_value):
    try:
        return f"{float(raw_value):.4f}"
    except (TypeError, ValueError):
        return str(raw_value)


def _draw_preview_entries(layout, title: str, entries, empty_text: str):
    box = layout.box()
    col = box.column(align=True)
    col.label(text=title)

    if not entries:
        col.label(text=empty_text, icon="INFO")
        return

    for entry in entries:
        col.label(text=entry)


def _get_face_source(scene) -> str:
    return str(getattr(scene, "vmc_link_face_source", FACE_SOURCE_VMC))


def _is_arkit_face_source_enabled(scene) -> bool:
    return _get_face_source(scene) == FACE_SOURCE_RHYLIVE_ARKIT


def _get_latest_receiver_timestamp(scene) -> float:
    if scene is not None and _is_arkit_face_source_enabled(scene):
        return max(_last_packet_ts, _arkit_last_packet_ts)
    return _last_packet_ts


def _describe_receiver_endpoints(scene) -> str:
    bind_host = _resolve_bind_host(scene)
    vmc_desc = f"UDP {bind_host}:{int(getattr(scene, 'vmc_link_port', DEFAULT_PORT))}"
    if scene is not None and _is_arkit_face_source_enabled(scene):
        return f"{vmc_desc} + ARKit {bind_host}:{int(getattr(scene, 'vmc_link_arkit_port', DEFAULT_ARKIT_PORT))}"
    return vmc_desc


def _tag_view3d_ui_redraw():
    window_manager = getattr(bpy.context, "window_manager", None)
    if window_manager is None:
        return

    for window in getattr(window_manager, "windows", []):
        screen = getattr(window, "screen", None)
        if screen is None:
            continue

        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue

            area.tag_redraw()

            for region in area.regions:
                if region.type == "UI":
                    region.tag_redraw()
                    break


class VMC_LINK_PT_preview_panel(bpy.types.Panel):
    """Preview the latest raw VMC packets"""
    bl_label = "Data Preview"
    bl_idname = "VMC_LINK_PT_preview_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "VMC Link"
    bl_parent_id = "VMC_LINK_PT_panel"

    def draw(self, context):
        layout = self.layout

        header = layout.box()
        col = header.column(align=True)
        col.label(text="Raw VMC Stream", icon="RADIOBUT_ON" if is_running() else "RADIOBUT_OFF")

        if is_running():
            if _last_packet_ts > 0.0:
                age = time.time() - _last_packet_ts
                col.label(text=f"Last packet {age:.2f}s ago", icon="TIME")
            else:
                col.label(text="Waiting for incoming packets", icon="TIME")
        else:
            col.label(text="Receiver is stopped", icon="INFO")

        root_entries = []
        if _root_buf is not None:
            root_entries.append(f"Root/Pos: {_format_preview_pose(_root_buf)}")
        if _waist_buf is not None:
            root_entries.append(f"Tra/Pos: {_format_preview_pose(_waist_buf)}")
        _draw_preview_entries(layout, "Root / Tra", root_entries, "No root or waist packets received yet")

        bone_entries = [
            f"{name}: {_format_preview_pose(raw)}"
            for name, raw in sorted(_bone_buf.items(), key=lambda item: str(item[0]).lower())
        ]
        _draw_preview_entries(layout, f"Bone/Pos ({len(_bone_buf)})", bone_entries, "No bone packets received yet")

        blend_entries = [
            f"{name}: {_format_preview_value(val)}"
            for name, val in sorted(_blend_buf.items(), key=lambda item: str(item[0]).lower())
        ]
        _draw_preview_entries(layout, f"Blend/Val ({len(_blend_buf)})", blend_entries, "No blend packets received yet")


class VMC_LINK_PT_arkit_preview_panel(bpy.types.Panel):
    """Preview the latest RhyLive ARKit OSC /Face packets"""
    bl_label = "ARKit Preview"
    bl_idname = "VMC_LINK_PT_arkit_preview_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "VMC Link"
    bl_parent_id = "VMC_LINK_PT_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        header = layout.box()
        col = header.column(align=True)
        source_enabled = _is_arkit_face_source_enabled(scene)

        col.label(text="RhyLive OSC /Face", icon="RADIOBUT_ON" if source_enabled and is_running() else "RADIOBUT_OFF")

        if not source_enabled:
            col.label(text="Switch Face Source to RhyLive ARKit to enable", icon="INFO")
        elif _arkit_last_packet_ts > 0.0:
            age = time.time() - _arkit_last_packet_ts
            col.label(text=f"Last packet {age:.2f}s ago", icon="TIME")
        elif is_running():
            col.label(text="Waiting for /Face packets", icon="TIME")
        else:
            col.label(text="Receiver is stopped", icon="INFO")

        preview_entries = [
            f"{name}: {_format_preview_value(_arkit_blend_buf.get(name, 0.0))}"
            for name in ARKIT_BLENDSHAPE_KEYS
        ]
        _draw_preview_entries(layout, f"ARKit Coefficients ({len(ARKIT_BLENDSHAPE_KEYS)})", preview_entries, "No ARKit coefficients received yet")


def _draw_mapping_preset_controls(layout, scene, kind: str):
    preset_prop, save_prop = _mapping_preset_prop_names(kind)

    box = layout.box()
    col = box.column(align=True)
    col.label(text="JSON Presets", icon="FILE_FOLDER")

    row = col.row(align=True)
    row.prop(scene, preset_prop, text="Preset")
    refresh_op = row.operator("vmc_link.refresh_mapping_presets", text="", icon="FILE_REFRESH")
    refresh_op.mapping_kind = kind

    load_row = col.row(align=True)
    load_op = load_row.operator("vmc_link.load_mapping_preset", text="Load", icon="IMPORT")
    load_op.mapping_kind = kind

    save_row = col.row(align=True)
    save_row.prop(scene, save_prop, text="Save Name")
    save_op = save_row.operator("vmc_link.save_mapping_preset", text="Save", icon="EXPORT")
    save_op.mapping_kind = kind


def _draw_bone_mapping_entries(layout, scene):
    arm_for_search = scene.vmc_link_armature
    can_search_bones = _has_pose_bones(arm_for_search)

    if not can_search_bones:
        layout.label(text="Select Armature to enable bone picker", icon="INFO")

    col = layout.column(align=True)
    for vmc_name in BONE_ALIASES:
        prop_name = _bone_override_prop_name(vmc_name)
        if can_search_bones:
            col.prop_search(scene, prop_name, arm_for_search.pose, "bones", text=vmc_name, icon="BONE_DATA")
        else:
            col.prop(scene, prop_name, text=vmc_name)


def _draw_blend_mapping_entries(layout, scene, kind: str):
    face_for_search = scene.vmc_link_face_object
    can_search_blends = _has_shape_keys(face_for_search)

    if not can_search_blends:
        layout.label(text="Select Face Mesh with shape keys to enable picker", icon="INFO")

    col = layout.column(align=True)
    for blend_name in _mapping_keys(kind):
        prop_name = _mapping_prop_name(kind, blend_name)
        if can_search_blends:
            col.prop_search(scene, prop_name, face_for_search.data.shape_keys, "key_blocks", text=blend_name, icon="SHAPEKEY_DATA")
        else:
            col.prop(scene, prop_name, text=blend_name)


class VMC_LINK_PT_bone_mapping_panel(bpy.types.Panel):
    bl_label = "Bone Mapping"
    bl_idname = "VMC_LINK_PT_bone_mapping_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "VMC Link"
    bl_parent_id = "VMC_LINK_PT_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        _draw_mapping_preset_controls(layout, scene, MAPPING_KIND_BONE)
        _draw_bone_mapping_entries(layout, scene)


class VMC_LINK_PT_vmc_blend_mapping_panel(bpy.types.Panel):
    bl_label = "VMC Blend Mapping"
    bl_idname = "VMC_LINK_PT_vmc_blend_mapping_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "VMC Link"
    bl_parent_id = "VMC_LINK_PT_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        _draw_mapping_preset_controls(layout, scene, MAPPING_KIND_VMC_BLEND)
        _draw_blend_mapping_entries(layout, scene, MAPPING_KIND_VMC_BLEND)


class VMC_LINK_PT_arkit_blend_mapping_panel(bpy.types.Panel):
    bl_label = "ARKit Blend Mapping"
    bl_idname = "VMC_LINK_PT_arkit_blend_mapping_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "VMC Link"
    bl_parent_id = "VMC_LINK_PT_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        _draw_mapping_preset_controls(layout, scene, MAPPING_KIND_ARKIT_BLEND)
        _draw_blend_mapping_entries(layout, scene, MAPPING_KIND_ARKIT_BLEND)


# -------------------------
# Mapping helpers
# -------------------------

def _get_manual_bone_override(scene, wanted: str):
    if scene is None:
        return None

    prop_name = _bone_override_prop_name(wanted)
    if not hasattr(scene, prop_name):
        return None

    value = str(getattr(scene, prop_name, "")).strip()
    return value if value else None


def _get_manual_blend_override(scene, wanted: str):
    if scene is None:
        return None

    prop_name = _blend_override_prop_name(wanted)
    if not hasattr(scene, prop_name):
        return None

    value = str(getattr(scene, prop_name, "")).strip()
    return value if value else None


def _get_manual_arkit_override(scene, wanted: str):
    if scene is None:
        return None

    prop_name = _arkit_override_prop_name(wanted)
    if not hasattr(scene, prop_name):
        return None

    value = str(getattr(scene, prop_name, "")).strip()
    return value if value else None


def _autofill_empty_manual_overrides(scene, arm_obj: bpy.types.Object):
    if scene is None or not _has_pose_bones(arm_obj):
        return 0

    filled = 0
    for vmc_name in BONE_ALIASES:
        prop_name = _bone_override_prop_name(vmc_name)
        if not hasattr(scene, prop_name):
            continue

        current = str(getattr(scene, prop_name, "")).strip()
        if current:
            continue

        auto_name = _find_bone_name(arm_obj, vmc_name, None)
        if not auto_name:
            continue

        setattr(scene, prop_name, auto_name)
        filled += 1

    return filled


def _candidate_vmc_bone_names(wanted: str):
    candidates = [wanted]
    wanted_lower = wanted.lower()
    wanted_norm = _normalize_bone_name(wanted)

    for vmc_name, aliases in BONE_ALIASES.items():
        if vmc_name == wanted:
            continue

        if wanted_lower == vmc_name.lower() or any(wanted_lower == alias.lower() for alias in aliases):
            candidates.append(vmc_name)
            continue

        if wanted_norm == _normalize_bone_name(vmc_name):
            candidates.append(vmc_name)
            continue

        for alias in aliases:
            if _normalize_bone_name(alias) == wanted_norm:
                candidates.append(vmc_name)
                break

    seen = set()
    unique = []
    for name in candidates:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)

    return unique


def _get_vmc_bone_pose(raw_bones: dict, wanted: str):
    if not raw_bones:
        return None

    lowered = {str(name).lower(): raw for name, raw in raw_bones.items()}
    normalized = {_normalize_bone_name(name): raw for name, raw in raw_bones.items()}

    for candidate in _candidate_vmc_bone_names(wanted):
        if candidate in raw_bones:
            return raw_bones[candidate]

        candidate_lower = candidate.lower()
        if candidate_lower in lowered:
            return lowered[candidate_lower]

        candidate_norm = _normalize_bone_name(candidate)
        if candidate_norm in normalized:
            return normalized[candidate_norm]

    return None


def _is_root_motion_target(target_name: str) -> bool:
    lowered = str(target_name).strip().lower()
    if not lowered:
        return False

    leaf = lowered.rsplit("/", 1)[-1]
    return leaf in {"waist", "hips", "hip", "pelvis", "root", "center"}


def _find_bone_name(arm_obj: bpy.types.Object, wanted: str, scene=None):
    pose = arm_obj.pose.bones

    for candidate in _candidate_vmc_bone_names(wanted):
        manual = _get_manual_bone_override(scene, candidate)
        if manual:
            if manual in pose:
                return manual

            manual_lower = manual.lower()
            for b in pose:
                if b.name.lower() == manual_lower:
                    return b.name

        if candidate in pose:
            return candidate

        candidate_lower = candidate.lower()
        for b in pose:
            if b.name.lower() == candidate_lower:
                return b.name

        for alias_lower in BONE_ALIASES.get(candidate, []):
            for b in pose:
                if b.name.lower() == alias_lower.lower():
                    return b.name

        wanted_keys = {_normalize_bone_name(candidate)}
        for alias in BONE_ALIASES.get(candidate, []):
            wanted_keys.add(_normalize_bone_name(alias))

        for b in pose:
            if _normalize_bone_name(b.name) in wanted_keys:
                return b.name

    return None


def _candidate_vmc_blend_names(wanted: str):
    candidates = [wanted]
    wanted_lower = wanted.lower()

    for vmc_name, aliases in BLEND_ALIASES.items():
        if vmc_name == wanted:
            continue

        if wanted_lower == vmc_name.lower() or any(wanted_lower == alias.lower() for alias in aliases):
            candidates.append(vmc_name)

    seen = set()
    unique = []
    for name in candidates:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)

    return unique


def _get_blend_value(blends: dict, vmc_name: str) -> float:
    for candidate in _candidate_vmc_blend_names(vmc_name):
        if candidate in blends:
            try:
                return float(blends[candidate])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _apply_eye_look_to_eye_bone(pb, look_h: float, look_v: float):
    # Apply absolute eye look from blend channels (no accumulation drift).
    look_h = max(-1.0, min(1.0, look_h))
    look_v = max(-1.0, min(1.0, look_v))

    yaw = look_h * 1.0
    pitch = -look_v * 1.0

    q_yaw = Quaternion((0.0, 1.0, 0.0), yaw)
    q_pitch = Quaternion((1.0, 0.0, 0.0), pitch)

    pb.rotation_mode = "QUATERNION"
    pb.rotation_quaternion = q_yaw @ q_pitch


def _find_shapekey_name(face_obj: bpy.types.Object, wanted: str, scene=None):
    if not _has_shape_keys(face_obj):
        return None

    blocks = face_obj.data.shape_keys.key_blocks

    for candidate in _candidate_vmc_blend_names(wanted):
        manual = _get_manual_blend_override(scene, candidate)
        if manual:
            if manual in blocks:
                return manual

            manual_lower = manual.lower()
            for k in blocks:
                if k.name.lower() == manual_lower:
                    return k.name

        if candidate in blocks:
            return candidate

        candidate_lower = candidate.lower()
        for k in blocks:
            if k.name.lower() == candidate_lower:
                return k.name

        for alias in BLEND_ALIASES.get(candidate, []):
            alias_lower = alias.lower()
            for k in blocks:
                if k.name.lower() == alias_lower:
                    return k.name

    return None


def _find_arkit_shapekey_name(face_obj: bpy.types.Object, wanted: str, scene=None):
    if not _has_shape_keys(face_obj):
        return None

    blocks = face_obj.data.shape_keys.key_blocks

    manual = _get_manual_arkit_override(scene, wanted)
    if manual:
        if manual in blocks:
            return manual

        manual_lower = manual.lower()
        for k in blocks:
            if k.name.lower() == manual_lower:
                return k.name

    if wanted in blocks:
        return wanted

    wanted_lower = wanted.lower()
    for k in blocks:
        if k.name.lower() == wanted_lower:
            return k.name

    wanted_norm = _normalize_identifier(wanted)
    for k in blocks:
        if _normalize_identifier(k.name) == wanted_norm:
            return k.name

    return None


def _rebuild_maps(scene):
    global _cached_bone_map, _cached_blend_map, _cached_arkit_blend_map

    arm = scene.vmc_link_armature
    face = scene.vmc_link_face_object

    _cached_bone_map = {}
    _cached_blend_map = {}
    _cached_arkit_blend_map = {}

    if arm is not None:
        filled = _autofill_empty_manual_overrides(scene, arm)
        if filled:
            _debug(f"Autofilled manual overrides: {filled}")

        names = set(BONE_ALIASES.keys()) | set(_bone_buf.keys())
        for vmc_name in names:
            actual = _find_bone_name(arm, vmc_name, scene)
            if actual:
                _cached_bone_map[vmc_name] = actual

    if _has_shape_keys(face):
        names = set(BLEND_ALIASES.keys()) | set(_blend_buf.keys())
        for vmc_name in names:
            actual = _find_shapekey_name(face, vmc_name, scene)
            if actual:
                _cached_blend_map[vmc_name] = actual

        names = set(ARKIT_BLENDSHAPE_KEYS) | set(_arkit_blend_buf.keys())
        for arkit_name in names:
            actual = _find_arkit_shapekey_name(face, arkit_name, scene)
            if actual:
                _cached_arkit_blend_map[arkit_name] = actual

    _debug(
        f"Rebuilt maps: bones={len(_cached_bone_map)} vmc_blends={len(_cached_blend_map)} "
        f"arkit_blends={len(_cached_arkit_blend_map)}"
    )


# -------------------------
# OSC handlers (receiver thread)
# -------------------------

def _poll_socket_packets(sock, dispatcher, stream_name: str):
    """Read all pending UDP packets without blocking Blender."""
    if sock is None or dispatcher is None:
        return

    while True:
        try:
            data, client_addr = sock.recvfrom(65535)
        except BlockingIOError:
            break
        except OSError as e:
            _warn(f"{stream_name} socket receive failed", e)
            break

        try:
            dispatcher.call_handlers_for_packet(data, client_addr)
        except Exception as e:
            _warn(f"Failed to process {stream_name} packet", e)


def _poll_osc_packets():
    _poll_socket_packets(_receiver_socket, _dispatcher, "OSC")
    _poll_socket_packets(_arkit_receiver_socket, _arkit_dispatcher, "ARKit OSC")

def _on_vmc_bone_pos(_address, *args):
    global _dirty, _last_packet_ts

    # VMC: /VMC/Ext/Bone/Pos <bone> px py pz qx qy qz qw
    if not args or len(args) < 8:
        return

    bone_name = str(args[0])
    try:
        px, py, pz = float(args[1]), float(args[2]), float(args[3])
        qx, qy, qz, qw = float(args[4]), float(args[5]), float(args[6]), float(args[7])
    except (TypeError, ValueError):
        return

    _last_packet_ts = time.time()
    _bone_buf[bone_name] = (px, py, pz, qx, qy, qz, qw)
    _dirty = True


def _on_vmc_root_pos(_address, *args):
    global _dirty, _last_packet_ts, _root_buf

    # VMC: /VMC/Ext/Root/Pos [name] px py pz qx qy qz qw
    # Reference script expects args[1..7]; accept both with and without name.
    if not args or len(args) < 7:
        return

    offset = 1 if len(args) >= 8 else 0
    try:
        px, py, pz = float(args[offset + 0]), float(args[offset + 1]), float(args[offset + 2])
        qx, qy, qz, qw = float(args[offset + 3]), float(args[offset + 4]), float(args[offset + 5]), float(args[offset + 6])
    except (TypeError, ValueError):
        return

    _last_packet_ts = time.time()
    _root_buf = (px, py, pz, qx, qy, qz, qw)
    _dirty = True


def _on_vmc_tra_pos(_address, *args):
    global _dirty, _last_packet_ts, _waist_buf

    # VMC: /VMC/Ext/Tra/Pos <target> px py pz qx qy qz qw
    if not args or len(args) < 8:
        return

    target = str(args[0]).lower()
    if not _is_root_motion_target(target):
        return

    try:
        px, py, pz = float(args[1]), float(args[2]), float(args[3])
        qx, qy, qz, qw = float(args[4]), float(args[5]), float(args[6]), float(args[7])
    except (TypeError, ValueError):
        return

    _last_packet_ts = time.time()
    _waist_buf = (px, py, pz, qx, qy, qz, qw)
    _dirty = True


def _on_vmc_blend_val(_address, *args):
    global _dirty, _last_packet_ts

    if not args or len(args) < 2:
        return

    name = args[0]
    try:
        val = float(args[1])
    except (TypeError, ValueError):
        return

    _last_packet_ts = time.time()
    _blend_buf[name] = val
    _dirty = True


def _on_arkit_face(_address, *args):
    global _arkit_last_packet_ts, _dirty

    if not args:
        return

    count = min(len(args), len(ARKIT_BLENDSHAPE_KEYS))
    updated_any = False

    for idx in range(count):
        try:
            val = float(args[idx])
        except (TypeError, ValueError):
            continue

        _arkit_blend_buf[ARKIT_BLENDSHAPE_KEYS[idx]] = val
        updated_any = True

    if updated_any:
        _arkit_last_packet_ts = time.time()
        _dirty = True


# -------------------------
# Apply timer (main thread)
# -------------------------

def _apply_timer():
    global _dirty, _next_tick_ts

    if _receiver_socket is None and _arkit_receiver_socket is None:
        return None

    scene = getattr(bpy.context, "scene", None)
    if scene is None or not hasattr(scene, "vmc_link_rate_hz"):
        return 0.1

    rate = 1.0 / max(1, scene.vmc_link_rate_hz)
    now = time.time()

    if _next_tick_ts == 0.0:
        _next_tick_ts = now

    remaining = _next_tick_ts - now
    if remaining > 0.0:
        return min(rate, remaining)

    _next_tick_ts = now + rate

    _poll_osc_packets()
    _tag_view3d_ui_redraw()

    arm = scene.vmc_link_armature
    face = scene.vmc_link_face_object
    live_preview = bool(getattr(scene, "vmc_link_live_preview", True))
    use_vmc_face = not _is_arkit_face_source_enabled(scene)

    if arm is None and face is None:
        return rate

    if not _dirty:
        return rate

    root = _root_buf
    waist = _waist_buf
    bones = dict(_bone_buf)
    blends = dict(_blend_buf)
    arkit_blends = dict(_arkit_blend_buf)
    hips_pose = _get_vmc_bone_pose(bones, "Hips")
    _dirty = False

    if not live_preview:
        return rate

    if arm is not None and not _cached_bone_map:
        _rebuild_maps(scene)

    if use_vmc_face and face is not None and not _cached_blend_map:
        _rebuild_maps(scene)
    elif (not use_vmc_face) and face is not None and not _cached_arkit_blend_map:
        _rebuild_maps(scene)

    driven_bones = set()
    driven_shapes = set()

    if arm is not None:
        use_root_loc = False
        if root is not None:
            use_root_loc = any(abs(v) > 1e-6 for v in root[:3])

        # Location fallback order:
        # 1. Root/Pos translation
        # 2. Tra/Pos waist/hips translation
        # 3. Hips Bone/Pos translation for senders that encode locomotion there
        if use_root_loc:
            root_loc, _ = _convert_vmc_pose(*root)
            if _vec_changed(arm.location, root_loc):
                arm.location = root_loc
        elif waist is not None:
            waist_loc, _ = _convert_vmc_pose(*waist)
            if _vec_changed(arm.location, waist_loc):
                arm.location = waist_loc
        elif hips_pose is not None:
            hips_loc, _ = _convert_vmc_pose(*hips_pose)
            if _vec_changed(arm.location, hips_loc):
                arm.location = hips_loc

        # Keep root quaternion only when it is non-identity-ish to avoid forcing static identity.
        if root is not None:
            if any(abs(v) > 1e-6 for v in root[3:6]):
                _, root_quat = _convert_vmc_pose(*root)
                arm.rotation_mode = "QUATERNION"
                if _quat_changed(arm.rotation_quaternion, root_quat):
                    arm.rotation_quaternion = root_quat

        pose = arm.pose.bones

        eye_left_name = _cached_bone_map.get("LeftEye") or _find_bone_name(arm, "LeftEye", scene)
        eye_right_name = _cached_bone_map.get("RightEye") or _find_bone_name(arm, "RightEye", scene)
        if eye_left_name:
            _cached_bone_map["LeftEye"] = eye_left_name
        if eye_right_name:
            _cached_bone_map["RightEye"] = eye_right_name

        eye_left_driven_by_bone = False
        eye_right_driven_by_bone = False

        for vmc_name, raw in bones.items():
            actual = _cached_bone_map.get(vmc_name) or _find_bone_name(arm, vmc_name, scene)
            if not actual or actual not in pose:
                continue

            _cached_bone_map[vmc_name] = actual
            pb = pose[actual]

            px, py, pz, qx, qy, qz, qw = raw

            _, rotate_quat = _convert_vmc_pose(px, py, pz, qx, qy, qz, qw)

            parent_quat = pb.bone.matrix_local.to_quaternion()
            local_q = parent_quat.inverted() @ rotate_quat @ parent_quat
            local_q.normalize()

            pb.rotation_mode = "QUATERNION"
            if _quat_changed(pb.rotation_quaternion, local_q):
                pb.rotation_quaternion = local_q
                driven_bones.add(actual)

            if eye_left_name and actual == eye_left_name:
                eye_left_driven_by_bone = True
            if eye_right_name and actual == eye_right_name:
                eye_right_driven_by_bone = True

        # Bridge VMC look blend channels to eye bones when direct eye bone packets are missing.
        if blends:
            if eye_left_name and eye_left_name in pose and not eye_left_driven_by_bone:
                left_h = (_get_blend_value(blends, "LookRight_L") or _get_blend_value(blends, "LookRight")) - (_get_blend_value(blends, "LookLeft_L") or _get_blend_value(blends, "LookLeft"))
                left_v = (_get_blend_value(blends, "LookUp_L") or _get_blend_value(blends, "LookUp")) - (_get_blend_value(blends, "LookDown_L") or _get_blend_value(blends, "LookDown"))
                eye_pb = pose[eye_left_name]
                old_q = eye_pb.rotation_quaternion.copy()
                _apply_eye_look_to_eye_bone(eye_pb, left_h, left_v)
                if _quat_changed(old_q, eye_pb.rotation_quaternion):
                    driven_bones.add(eye_left_name)

            if eye_right_name and eye_right_name in pose and not eye_right_driven_by_bone:
                right_h = (_get_blend_value(blends, "LookRight_R") or _get_blend_value(blends, "LookRight")) - (_get_blend_value(blends, "LookLeft_R") or _get_blend_value(blends, "LookLeft"))
                right_v = (_get_blend_value(blends, "LookUp_R") or _get_blend_value(blends, "LookUp")) - (_get_blend_value(blends, "LookDown_R") or _get_blend_value(blends, "LookDown"))
                eye_pb = pose[eye_right_name]
                old_q = eye_pb.rotation_quaternion.copy()
                _apply_eye_look_to_eye_bone(eye_pb, right_h, right_v)
                if _quat_changed(old_q, eye_pb.rotation_quaternion):
                    driven_bones.add(eye_right_name)


    if use_vmc_face and _has_shape_keys(face):
        blocks = face.data.shape_keys.key_blocks

        for vmc_name, val in blends.items():
            actual = _cached_blend_map.get(vmc_name) or _find_shapekey_name(face, vmc_name, scene)
            if not actual or actual not in blocks:
                continue

            _cached_blend_map[vmc_name] = actual
            if abs(blocks[actual].value - val) > SHAPE_EPS:
                blocks[actual].value = val
                driven_shapes.add(actual)
    elif _has_shape_keys(face):
        blocks = face.data.shape_keys.key_blocks

        for arkit_name, val in arkit_blends.items():
            actual = _cached_arkit_blend_map.get(arkit_name) or _find_arkit_shapekey_name(face, arkit_name, scene)
            if not actual or actual not in blocks:
                continue

            _cached_arkit_blend_map[arkit_name] = actual
            try:
                numeric_val = float(val)
            except (TypeError, ValueError):
                continue

            if abs(blocks[actual].value - numeric_val) > SHAPE_EPS:
                blocks[actual].value = numeric_val
                driven_shapes.add(actual)

    if _recording:
        _record_current_sample(scene, arm, driven_bones, face, driven_shapes)

    return rate


# -------------------------
# Server lifecycle
# -------------------------

def _start_server(scene):
    global _receiver_socket, _dispatcher, _arkit_receiver_socket, _arkit_dispatcher, _apply_timer_running
    global _cached_bone_map, _cached_blend_map

    if is_running():
        raise RuntimeError("Receiver already running")

    _reset_runtime_buffers()
    _cached_bone_map = {}
    _cached_blend_map = {}

    bind_host = _resolve_bind_host(scene).strip()
    if not bind_host:
        raise RuntimeError("Address cannot be empty")

    port = int(scene.vmc_link_port)
    vmc_socket = None
    arkit_socket = None
    try:
        vmc_socket = _create_udp_socket(bind_host, port)
        vmc_dispatcher = _build_vmc_dispatcher()
        arkit_dispatcher = None

        if _is_arkit_face_source_enabled(scene):
            arkit_socket = _create_udp_socket(bind_host, int(scene.vmc_link_arkit_port))
            arkit_dispatcher = _build_arkit_dispatcher()
    except Exception:
        if vmc_socket is not None:
            try:
                vmc_socket.close()
            except Exception:
                pass
        if arkit_socket is not None:
            try:
                arkit_socket.close()
            except Exception:
                pass
        raise

    _receiver_socket = vmc_socket
    _dispatcher = vmc_dispatcher
    _arkit_receiver_socket = arkit_socket
    _arkit_dispatcher = arkit_dispatcher

    if not bpy.app.timers.is_registered(_apply_timer):
        bpy.app.timers.register(_apply_timer, persistent=True)

    _apply_timer_running = True
    _debug(f"Receiver started on UDP {bind_host}:{port}")
    if _arkit_receiver_socket is not None:
        _debug(f"ARKit face receiver started on UDP {bind_host}:{scene.vmc_link_arkit_port}")


def _stop_server(scene):
    global _receiver_socket, _dispatcher, _arkit_receiver_socket, _arkit_dispatcher, _apply_timer_running

    if not is_running():
        return

    try:
        if _receiver_socket is not None:
            _receiver_socket.close()
    except Exception as e:
        _warn("Failed to close OSC socket cleanly", e)

    try:
        if _arkit_receiver_socket is not None:
            _arkit_receiver_socket.close()
    except Exception as e:
        _warn("Failed to close ARKit OSC socket cleanly", e)

    _receiver_socket = None
    _dispatcher = None
    _arkit_receiver_socket = None
    _arkit_dispatcher = None
    _reset_runtime_buffers()

    try:
        if bpy.app.timers.is_registered(_apply_timer):
            bpy.app.timers.unregister(_apply_timer)
    except Exception as e:
        _warn("Failed to unregister apply timer", e)

    _apply_timer_running = False
    _debug("Receiver stopped")


# -------------------------
# Operators
# -------------------------

class VMC_LINK_OT_toggle_receiver(bpy.types.Operator):
    """Toggle OSC/VMC receiver on/off"""
    bl_idname = "vmc_link.toggle_receiver"
    bl_label = "Toggle Receiver"

    def execute(self, context):
        scene = context.scene

        try:
            if is_running():
                _stop_server(scene)
                self.report({"INFO"}, "VMC Link receiver stopped")
            else:
                _start_server(scene)
                self.report({"INFO"}, f"VMC Link receiver started on {_describe_receiver_endpoints(scene)}")
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        return {"FINISHED"}


class VMC_LINK_OT_refresh_mapping_presets(bpy.types.Operator):
    bl_idname = "vmc_link.refresh_mapping_presets"
    bl_label = "Refresh Mapping Presets"

    mapping_kind: bpy.props.StringProperty()

    def execute(self, context):
        kind = str(self.mapping_kind)
        scene = context.scene

        try:
            items = _scan_mapping_presets(kind)
            current = _get_mapping_preset_selection(scene, kind)
            valid_ids = {item[0] for item in items}
            if current not in valid_ids:
                _set_mapping_preset_selection(scene, kind, PRESET_NONE_ID)
            self.report({"INFO"}, f"Refreshed {_mapping_kind_label(kind)} presets")
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        return {"FINISHED"}


class VMC_LINK_OT_save_mapping_preset(bpy.types.Operator):
    bl_idname = "vmc_link.save_mapping_preset"
    bl_label = "Save Mapping Preset"

    mapping_kind: bpy.props.StringProperty()

    def execute(self, context):
        kind = str(self.mapping_kind)
        scene = context.scene

        try:
            file_name = _sanitize_mapping_preset_filename(_get_mapping_preset_save_name(scene, kind))
            if not file_name:
                raise RuntimeError("Save Name cannot be empty")

            preset_dir = _ensure_mapping_preset_dir(kind)
            path = os.path.join(preset_dir, file_name)
            payload = _mapping_preset_payload(scene, kind)

            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)

            _scan_mapping_presets(kind)
            _set_mapping_preset_selection(scene, kind, file_name)
            self.report({"INFO"}, f"Saved {_mapping_kind_label(kind)} preset '{file_name}'")
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        return {"FINISHED"}


class VMC_LINK_OT_load_mapping_preset(bpy.types.Operator):
    bl_idname = "vmc_link.load_mapping_preset"
    bl_label = "Load Mapping Preset"

    mapping_kind: bpy.props.StringProperty()

    def execute(self, context):
        kind = str(self.mapping_kind)
        scene = context.scene

        try:
            file_name = _get_mapping_preset_selection(scene, kind)
            if file_name == PRESET_NONE_ID:
                raise RuntimeError("Select a preset to load")

            path = os.path.join(_ensure_mapping_preset_dir(kind), file_name)
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)

            entries = _load_mapping_preset_payload(payload, kind)
            _apply_mapping_entries(scene, kind, entries)

            if kind == MAPPING_KIND_BONE:
                _invalidate_bone_map_cache()
                _rebuild_maps(scene)
            elif kind in {MAPPING_KIND_VMC_BLEND, MAPPING_KIND_ARKIT_BLEND}:
                _invalidate_blend_map_cache()
                _rebuild_maps(scene)

            self.report({"INFO"}, f"Loaded {_mapping_kind_label(kind)} preset '{file_name}'")
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        return {"FINISHED"}


class VMC_LINK_OT_create_dummy_armature(bpy.types.Operator):
    """Create a test armature with common VMC bone names"""
    bl_idname = "vmc_link.create_dummy_armature"
    bl_label = "Create Dummy Armature"

    def execute(self, context):
        scene = context.scene

        def remove_object(obj):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data and data.users == 0:
                if isinstance(data, bpy.types.Armature):
                    bpy.data.armatures.remove(data)
                elif isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)

        def add_bone(eb, name: str, head, tail, parent=None, use_connect=False):
            bone = eb.new(name)
            bone.head = Vector(head)
            bone.tail = Vector(tail)
            if parent is not None:
                bone.parent = parent
                bone.use_connect = use_connect
            return bone

        try:
            if context.object and context.object.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")

            if DUMMY_DELETE_OLD:
                for obj in list(bpy.data.objects):
                    if obj.name == DUMMY_ARMATURE_NAME or obj.name.startswith(DUMMY_ARMATURE_NAME + "_"):
                        remove_object(obj)

            arm_data = bpy.data.armatures.new(DUMMY_ARMATURE_NAME)
            arm_obj = bpy.data.objects.new(DUMMY_ARMATURE_NAME, arm_data)
            link_collection = context.collection or scene.collection
            link_collection.objects.link(arm_obj)

            bpy.ops.object.select_all(action="DESELECT")
            context.view_layer.objects.active = arm_obj
            arm_obj.select_set(True)

            bpy.ops.object.mode_set(mode="EDIT")
            eb = arm_data.edit_bones

            hips = add_bone(eb, "Hips", (0.0, 0.0, 1.00), (0.0, 0.0, 1.18))
            spine = add_bone(eb, "Spine", hips.tail, (0.0, 0.0, 1.36), parent=hips, use_connect=True)
            chest = add_bone(eb, "Chest", spine.tail, (0.0, 0.0, 1.56), parent=spine, use_connect=True)
            neck = add_bone(eb, "Neck", chest.tail, (0.0, 0.0, 1.68), parent=chest, use_connect=True)
            head = add_bone(eb, "Head", neck.tail, (0.0, 0.0, 1.88), parent=neck, use_connect=True)

            add_bone(eb, "LeftEye", (0.04, -0.02, 1.82), (0.10, -0.02, 1.82), parent=head)
            add_bone(eb, "RightEye", (-0.04, -0.02, 1.82), (-0.10, -0.02, 1.82), parent=head)

            def add_finger_chains(hand_bone, side_suffix: str, side_sign: float):
                finger_defs = (
                    ("Thumb", (0, 1, 2), [(0.90, -0.03, 1.47), (0.94, -0.06, 1.46), (0.98, -0.08, 1.45), (1.02, -0.10, 1.44)]),
                    ("IndexFinger", (1, 2, 3), [(0.90, 0.03, 1.48), (0.96, 0.03, 1.48), (1.01, 0.03, 1.48), (1.05, 0.03, 1.48)]),
                    ("MiddleFinger", (1, 2, 3), [(0.90, 0.00, 1.48), (0.97, 0.00, 1.48), (1.03, 0.00, 1.48), (1.08, 0.00, 1.48)]),
                    ("RingFinger", (1, 2, 3), [(0.90, -0.03, 1.48), (0.96, -0.03, 1.48), (1.01, -0.03, 1.48), (1.05, -0.03, 1.48)]),
                    ("LittleFinger", (1, 2, 3), [(0.90, -0.06, 1.48), (0.95, -0.06, 1.48), (0.99, -0.06, 1.48), (1.03, -0.06, 1.48)]),
                )

                for finger_name, joint_indices, points in finger_defs:
                    prev = hand_bone
                    for i, joint_idx in enumerate(joint_indices):
                        head = (points[i][0] * side_sign, points[i][1], points[i][2])
                        tail = (points[i + 1][0] * side_sign, points[i + 1][1], points[i + 1][2])
                        bone_name = f"{finger_name}{joint_idx}_{side_suffix}"
                        prev = add_bone(eb, bone_name, head, tail, parent=prev, use_connect=(i > 0))

            def add_arm_and_hand(side_name: str, side_sign: float):
                shoulder = add_bone(eb, f"{side_name}Shoulder", chest.tail, (0.16 * side_sign, 0.0, 1.54), parent=chest)
                upper_arm = add_bone(eb, f"{side_name}UpperArm", shoulder.tail, (0.46 * side_sign, 0.0, 1.54), parent=shoulder, use_connect=True)
                lower_arm = add_bone(eb, f"{side_name}LowerArm", upper_arm.tail, (0.74 * side_sign, 0.0, 1.50), parent=upper_arm, use_connect=True)
                hand = add_bone(eb, f"{side_name}Hand", lower_arm.tail, (0.88 * side_sign, 0.0, 1.48), parent=lower_arm, use_connect=True)
                add_finger_chains(hand, side_name[0], side_sign)

            def add_leg(side_name: str, side_sign: float):
                upper_leg = add_bone(eb, f"{side_name}UpperLeg", (0.10 * side_sign, 0.0, 0.98), (0.10 * side_sign, 0.0, 0.58), parent=hips)
                lower_leg = add_bone(eb, f"{side_name}LowerLeg", upper_leg.tail, (0.10 * side_sign, 0.0, 0.16), parent=upper_leg, use_connect=True)
                foot = add_bone(eb, f"{side_name}Foot", lower_leg.tail, (0.10 * side_sign, -0.16, 0.05), parent=lower_leg, use_connect=True)
                add_bone(eb, f"{side_name}ToeBase", foot.tail, (0.10 * side_sign, -0.30, 0.05), parent=foot, use_connect=True)

            add_arm_and_hand("Left", 1.0)
            add_arm_and_hand("Right", -1.0)
            add_leg("Left", 1.0)
            add_leg("Right", -1.0)

            bpy.ops.object.mode_set(mode="OBJECT")

            arm_obj.show_in_front = True
            arm_data.display_type = "STICK"
            arm_obj.location = (0.0, 0.0, 0.0)
            arm_obj.rotation_euler = (0.0, 0.0, 0.0)
            arm_obj.scale = (1.0, 1.0, 1.0)
            scene.vmc_link_armature = arm_obj
            _rebuild_maps(scene)
            self.report({"INFO"}, f"Created dummy armature: {DUMMY_ARMATURE_NAME}")
            return {"FINISHED"}
        except Exception as e:
            try:
                if context.object and context.object.mode != "OBJECT":
                    bpy.ops.object.mode_set(mode="OBJECT")
            except Exception as reset_error:
                _warn("Failed to return to OBJECT mode after dummy armature error", reset_error)
            self.report({"ERROR"}, f"Failed to create dummy armature: {e}")
            return {"CANCELLED"}


class VMC_LINK_OT_rebuild_maps(bpy.types.Operator):
    """Rebuild bone/shapekey mapping cache"""
    bl_idname = "vmc_link.rebuild_maps"
    bl_label = "Rebuild Mapping"

    def execute(self, context):
        _rebuild_maps(context.scene)
        self.report({"INFO"}, "Rebuilt mapping")
        return {"FINISHED"}


class VMC_LINK_OT_toggle_recording(bpy.types.Operator):
    """Toggle keyframe recording of incoming VMC animation"""
    bl_idname = "vmc_link.toggle_recording"
    bl_label = "Toggle Recording"

    def execute(self, context):
        global _recording

        _recording = not _recording
        if _recording:
            self.report({"INFO"}, "Recording started")
        else:
            self.report({"INFO"}, "Recording stopped")

        return {"FINISHED"}


# -------------------------
# UI entrypoint (called by __init__.py)
# -------------------------

def draw_ui(layout, context):
    scene = context.scene

    # Toggle
    row = layout.row(align=True)
    icon = "PAUSE" if is_running() else "PLAY"
    label = "Stop Receiver" if is_running() else "Start Receiver"
    row.operator("vmc_link.toggle_receiver", text=label, icon=icon)

    rec_row = layout.row(align=True)
    rec_icon = "REC" if not is_recording() else "PAUSE"
    rec_label = "Start Recording" if not is_recording() else "Stop Recording"
    rec_row.operator("vmc_link.toggle_recording", text=rec_label, icon=rec_icon)

    # Connection state
    if is_running():
        last_pkt = _get_latest_receiver_timestamp(scene)

        if last_pkt == 0.0:
            layout.label(text="Waiting for connection", icon="TIME")
        elif (time.time() - last_pkt) <= 2.0:
            if getattr(scene, "vmc_link_live_preview", True):
                layout.label(text="Connected", icon="CHECKMARK")
            else:
                layout.label(text="Receiving raw data only", icon="INFO")
        else:
            layout.label(text="Disconnected", icon="ERROR")

    layout.separator()
    layout.label(text="Receiver Config", icon="PREFERENCES")

    col = layout.column(align=True)
    col.prop(scene, "vmc_link_bind_mode")
    if scene.vmc_link_bind_mode == BIND_MODE_CUSTOM:
        col.prop(scene, "vmc_link_bind_address_custom")
    col.prop(scene, "vmc_link_port")
    col.prop(scene, "vmc_link_face_source")
    if _is_arkit_face_source_enabled(scene):
        col.prop(scene, "vmc_link_arkit_port")
    col.prop(scene, "vmc_link_rate_hz")
    col.prop(scene, "vmc_link_live_preview")

    layout.separator()
    layout.label(text="Targets", icon="OUTLINER_OB_ARMATURE")

    col = layout.column(align=True)
    col.prop(scene, "vmc_link_armature")
    col.prop(scene, "vmc_link_face_object")

    row = layout.row(align=True)
    row.operator("vmc_link.create_dummy_armature", icon="ARMATURE_DATA")
    row.operator("vmc_link.rebuild_maps", icon="FILE_REFRESH")


# -------------------------
# Registration
# -------------------------

_classes = (
    VMC_LINK_PT_preview_panel,
    VMC_LINK_PT_arkit_preview_panel,
    VMC_LINK_PT_bone_mapping_panel,
    VMC_LINK_PT_vmc_blend_mapping_panel,
    VMC_LINK_PT_arkit_blend_mapping_panel,
    VMC_LINK_OT_toggle_receiver,
    VMC_LINK_OT_refresh_mapping_presets,
    VMC_LINK_OT_save_mapping_preset,
    VMC_LINK_OT_load_mapping_preset,
    VMC_LINK_OT_toggle_recording,
    VMC_LINK_OT_create_dummy_armature,
    VMC_LINK_OT_rebuild_maps,
)


def register():
    _ensure_scene_props()
    _refresh_all_mapping_preset_caches()
    for c in _classes:
        bpy.utils.register_class(c)


def _unregister_scene_props():
    sc = bpy.types.Scene

    fixed_props = (
        "vmc_link_port",
        "vmc_link_bind_mode",
        "vmc_link_bind_address_custom",
        "vmc_link_rate_hz",
        "vmc_link_live_preview",
        "vmc_link_face_source",
        "vmc_link_arkit_port",
        "vmc_link_armature",
        "vmc_link_face_object",
        "vmc_link_bone_map_preset",
        "vmc_link_bone_map_save_name",
        "vmc_link_vmc_blend_preset",
        "vmc_link_vmc_blend_save_name",
        "vmc_link_arkit_blend_preset",
        "vmc_link_arkit_blend_save_name",
        "vmc_link_show_advanced",
    )

    for prop_name in fixed_props:
        if hasattr(sc, prop_name):
            try:
                delattr(sc, prop_name)
            except Exception as e:
                _warn(f"Failed to unregister scene property '{prop_name}'", e)

    for vmc_name in BONE_ALIASES:
        prop_name = _bone_override_prop_name(vmc_name)
        if hasattr(sc, prop_name):
            try:
                delattr(sc, prop_name)
            except Exception as e:
                _warn(f"Failed to unregister bone mapping property '{prop_name}'", e)

    for vmc_name in BLEND_ALIASES:
        prop_name = _blend_override_prop_name(vmc_name)
        if hasattr(sc, prop_name):
            try:
                delattr(sc, prop_name)
            except Exception as e:
                _warn(f"Failed to unregister blend mapping property '{prop_name}'", e)

    for arkit_key in ARKIT_BLENDSHAPE_KEYS:
        prop_name = _arkit_override_prop_name(arkit_key)
        if hasattr(sc, prop_name):
            try:
                delattr(sc, prop_name)
            except Exception as e:
                _warn(f"Failed to unregister ARKit blend mapping property '{prop_name}'", e)


def unregister():
    try:
        _stop_server(bpy.context.scene)
    except Exception as e:
        _warn("Failed while stopping receiver during unregister", e)

    _unregister_scene_props()

    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
