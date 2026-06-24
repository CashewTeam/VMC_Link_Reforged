import bpy
from mathutils import Quaternion

from ..core import constants, helpers, state


def _build_canonical_bone_lookups():
    lowered = {}
    normalized = {}
    for canonical_name, aliases in constants.BONE_ALIASES.items():
        for candidate in (canonical_name, *aliases):
            lowered.setdefault(str(candidate).lower(), canonical_name)
            normalized.setdefault(helpers.normalize_bone_name(candidate), canonical_name)
    return lowered, normalized


_CANONICAL_BONE_BY_LOWER, _CANONICAL_BONE_BY_NORMALIZED = _build_canonical_bone_lookups()


def has_pose_bones(obj) -> bool:
    return bool(obj and getattr(obj, "type", None) == "ARMATURE" and getattr(obj, "pose", None) is not None)


def has_shape_keys(obj) -> bool:
    return bool(
        obj
        and getattr(obj, "type", None) == "MESH"
        and getattr(obj, "data", None) is not None
        and getattr(obj.data, "shape_keys", None) is not None
    )


def invalidate_bone_map_cache(_self=None, _context=None):
    state.cached_bone_map = {}


def invalidate_blend_map_cache(_self=None, _context=None):
    state.cached_blend_map = {}
    state.cached_arkit_blend_map = {}


def handle_armature_changed(scene):
    invalidate_bone_map_cache()
    arm = getattr(scene, "vmc_link_armature", None)
    if not has_pose_bones(arm):
        return
    from . import arp as mapping_arp

    if mapping_arp.analyze_armature(arm)["is_arp"]:
        mapping_arp.apply_standard_scene_mapping(scene)
        return
    autofill_empty_manual_overrides(scene, arm)


def handle_face_object_changed(_scene):
    invalidate_blend_map_cache()


def bone_override_prop_name(vmc_name: str) -> str:
    return f"vmc_link_bone_override_{vmc_name.lower()}"


def blend_override_prop_name(vmc_name: str) -> str:
    return f"vmc_link_blend_override_{vmc_name.lower()}"


def arkit_override_prop_name(arkit_key: str) -> str:
    return f"vmc_link_arkit_override_{helpers.normalize_identifier(arkit_key)}"


def ensure_dynamic_scene_props(scene_type):
    for vmc_name in constants.BONE_ALIASES:
        prop_name = bone_override_prop_name(vmc_name)
        if hasattr(scene_type, prop_name):
            continue
        setattr(
            scene_type,
            prop_name,
            bpy.props.StringProperty(
                name=vmc_name,
                description=f"VMC 骨骼 {vmc_name} 的手动映射",
                default="",
                update=invalidate_bone_map_cache,
            ),
        )

    for vmc_name in constants.BLEND_ALIASES:
        prop_name = blend_override_prop_name(vmc_name)
        if hasattr(scene_type, prop_name):
            continue
        setattr(
            scene_type,
            prop_name,
            bpy.props.StringProperty(
                name=vmc_name,
                description=f"VMC 表情 {vmc_name} 的手动映射",
                default="",
                update=invalidate_blend_map_cache,
            ),
        )

    for arkit_key in constants.ARKIT_BLENDSHAPE_KEYS:
        prop_name = arkit_override_prop_name(arkit_key)
        if hasattr(scene_type, prop_name):
            continue
        setattr(
            scene_type,
            prop_name,
            bpy.props.StringProperty(
                name=arkit_key,
                description=f"ARKit 表情 {arkit_key} 的手动映射",
                default="",
                update=invalidate_blend_map_cache,
            ),
        )


def unregister_dynamic_scene_props(scene_type):
    for vmc_name in constants.BONE_ALIASES:
        prop_name = bone_override_prop_name(vmc_name)
        if hasattr(scene_type, prop_name):
            delattr(scene_type, prop_name)

    for vmc_name in constants.BLEND_ALIASES:
        prop_name = blend_override_prop_name(vmc_name)
        if hasattr(scene_type, prop_name):
            delattr(scene_type, prop_name)

    for arkit_key in constants.ARKIT_BLENDSHAPE_KEYS:
        prop_name = arkit_override_prop_name(arkit_key)
        if hasattr(scene_type, prop_name):
            delattr(scene_type, prop_name)


def mapping_keys(kind: str):
    if kind == constants.MAPPING_KIND_BONE:
        return list(constants.BONE_ALIASES.keys())
    if kind == constants.MAPPING_KIND_VMC_BLEND:
        return list(constants.BLEND_ALIASES.keys())
    if kind == constants.MAPPING_KIND_ARKIT_BLEND:
        return list(constants.ARKIT_BLENDSHAPE_KEYS)
    raise KeyError(f"未知映射类型：{kind}")


def mapping_prop_name(kind: str, source_key: str) -> str:
    if kind == constants.MAPPING_KIND_BONE:
        return bone_override_prop_name(source_key)
    if kind == constants.MAPPING_KIND_VMC_BLEND:
        return blend_override_prop_name(source_key)
    if kind == constants.MAPPING_KIND_ARKIT_BLEND:
        return arkit_override_prop_name(source_key)
    raise KeyError(f"未知映射类型：{kind}")


def mapping_kind_label(kind: str) -> str:
    try:
        return constants.MAPPING_KIND_LABELS[kind]
    except KeyError as exc:
        raise KeyError(f"未知映射类型：{kind}") from exc


def get_mapping_override(scene, kind: str, source_key: str) -> str:
    if scene is None:
        return ""
    prop_name = mapping_prop_name(kind, source_key)
    if not hasattr(scene, prop_name):
        return ""
    return str(getattr(scene, prop_name, "")).strip()


def set_mapping_override(scene, kind: str, source_key: str, target_name: str):
    prop_name = mapping_prop_name(kind, source_key)
    if hasattr(scene, prop_name):
        setattr(scene, prop_name, str(target_name).strip())


def clear_mapping_overrides(scene, kind: str):
    for source_key in mapping_keys(kind):
        set_mapping_override(scene, kind, source_key, "")


def collect_mapping_entries(scene, kind: str):
    entries = {}
    for source_key in mapping_keys(kind):
        target_name = get_mapping_override(scene, kind, source_key)
        if target_name:
            entries[source_key] = target_name
    return entries


def apply_mapping_entries(scene, kind: str, entries: dict):
    clear_mapping_overrides(scene, kind)
    known_keys = set(mapping_keys(kind))
    for source_key, target_name in entries.items():
        if source_key not in known_keys or not isinstance(target_name, str):
            continue
        set_mapping_override(scene, kind, source_key, target_name)


def get_manual_bone_override(scene, wanted: str):
    if scene is None:
        return None
    prop_name = bone_override_prop_name(wanted)
    value = str(getattr(scene, prop_name, "")).strip() if hasattr(scene, prop_name) else ""
    return value if value else None


def get_manual_blend_override(scene, wanted: str):
    if scene is None:
        return None
    prop_name = blend_override_prop_name(wanted)
    value = str(getattr(scene, prop_name, "")).strip() if hasattr(scene, prop_name) else ""
    return value if value else None


def get_manual_arkit_override(scene, wanted: str):
    if scene is None:
        return None
    prop_name = arkit_override_prop_name(wanted)
    value = str(getattr(scene, prop_name, "")).strip() if hasattr(scene, prop_name) else ""
    return value if value else None


def autofill_empty_manual_overrides(scene, arm_obj: bpy.types.Object):
    if scene is None or not has_pose_bones(arm_obj):
        return 0

    filled = 0
    for vmc_name in constants.BONE_ALIASES:
        prop_name = bone_override_prop_name(vmc_name)
        if not hasattr(scene, prop_name):
            continue

        current = str(getattr(scene, prop_name, "")).strip()
        if current:
            continue

        auto_name = find_bone_name(arm_obj, vmc_name, None)
        if not auto_name:
            continue

        setattr(scene, prop_name, auto_name)
        filled += 1

    return filled


def candidate_vmc_bone_names(wanted: str):
    candidates = [wanted]
    wanted_lower = wanted.lower()
    wanted_norm = helpers.normalize_bone_name(wanted)

    for vmc_name, aliases in constants.BONE_ALIASES.items():
        if vmc_name == wanted:
            continue
        if wanted_lower == vmc_name.lower() or any(wanted_lower == alias.lower() for alias in aliases):
            candidates.append(vmc_name)
            continue
        if wanted_norm == helpers.normalize_bone_name(vmc_name):
            candidates.append(vmc_name)
            continue
        for alias in aliases:
            if helpers.normalize_bone_name(alias) == wanted_norm:
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


def get_vmc_bone_pose(raw_bones: dict, wanted: str):
    if not raw_bones:
        return None

    lowered = {str(name).lower(): raw for name, raw in raw_bones.items()}
    normalized = {helpers.normalize_bone_name(name): raw for name, raw in raw_bones.items()}

    for candidate in candidate_vmc_bone_names(wanted):
        if candidate in raw_bones:
            return raw_bones[candidate]
        candidate_lower = candidate.lower()
        if candidate_lower in lowered:
            return lowered[candidate_lower]
        candidate_norm = helpers.normalize_bone_name(candidate)
        if candidate_norm in normalized:
            return normalized[candidate_norm]
    return None


def canonicalize_vmc_bones(raw_bones: dict):
    if not raw_bones:
        return {}

    canonical = {}
    for raw_name, raw in raw_bones.items():
        source_name = _CANONICAL_BONE_BY_LOWER.get(str(raw_name).lower())
        if source_name is None:
            source_name = _CANONICAL_BONE_BY_NORMALIZED.get(helpers.normalize_bone_name(raw_name))
        if source_name is not None and source_name not in canonical:
            canonical[source_name] = raw
    return canonical


def is_root_motion_target(target_name: str) -> bool:
    lowered = str(target_name).strip().lower()
    if not lowered:
        return False
    leaf = lowered.rsplit("/", 1)[-1]
    return leaf in {"waist", "hips", "hip", "pelvis", "root", "center"}


def find_bone_name(arm_obj: bpy.types.Object, wanted: str, scene=None):
    pose = arm_obj.pose.bones

    for candidate in candidate_vmc_bone_names(wanted):
        manual = get_manual_bone_override(scene, candidate)
        if manual:
            if manual in pose:
                return manual
            manual_lower = manual.lower()
            for bone in pose:
                if bone.name.lower() == manual_lower:
                    return bone.name

        if candidate in pose:
            return candidate

        candidate_lower = candidate.lower()
        for bone in pose:
            if bone.name.lower() == candidate_lower:
                return bone.name

        for alias_lower in constants.BONE_ALIASES.get(candidate, []):
            for bone in pose:
                if bone.name.lower() == alias_lower.lower():
                    return bone.name

        wanted_keys = {helpers.normalize_bone_name(candidate)}
        for alias in constants.BONE_ALIASES.get(candidate, []):
            wanted_keys.add(helpers.normalize_bone_name(alias))

        for bone in pose:
            if helpers.normalize_bone_name(bone.name) in wanted_keys:
                return bone.name

    return None


def candidate_vmc_blend_names(wanted: str):
    candidates = [wanted]
    wanted_lower = wanted.lower()

    for vmc_name, aliases in constants.BLEND_ALIASES.items():
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


def get_blend_value(blends: dict, vmc_name: str) -> float:
    for candidate in candidate_vmc_blend_names(vmc_name):
        if candidate in blends:
            try:
                return float(blends[candidate])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def apply_eye_look_to_eye_bone(pose_bone, look_h: float, look_v: float):
    look_h = max(-1.0, min(1.0, look_h))
    look_v = max(-1.0, min(1.0, look_v))

    yaw = look_h * 1.0
    pitch = -look_v * 1.0

    q_yaw = Quaternion((0.0, 1.0, 0.0), yaw)
    q_pitch = Quaternion((1.0, 0.0, 0.0), pitch)

    pose_bone.rotation_mode = "QUATERNION"
    pose_bone.rotation_quaternion = q_yaw @ q_pitch


def find_shapekey_name(face_obj: bpy.types.Object, wanted: str, scene=None):
    if not has_shape_keys(face_obj):
        return None
    blocks = face_obj.data.shape_keys.key_blocks

    for candidate in candidate_vmc_blend_names(wanted):
        manual = get_manual_blend_override(scene, candidate)
        if manual:
            if manual in blocks:
                return manual
            manual_lower = manual.lower()
            for key in blocks:
                if key.name.lower() == manual_lower:
                    return key.name

        if candidate in blocks:
            return candidate

        candidate_lower = candidate.lower()
        for key in blocks:
            if key.name.lower() == candidate_lower:
                return key.name

        for alias in constants.BLEND_ALIASES.get(candidate, []):
            alias_lower = alias.lower()
            for key in blocks:
                if key.name.lower() == alias_lower:
                    return key.name

    return None


def find_arkit_shapekey_name(face_obj: bpy.types.Object, wanted: str, scene=None):
    if not has_shape_keys(face_obj):
        return None
    blocks = face_obj.data.shape_keys.key_blocks

    manual = get_manual_arkit_override(scene, wanted)
    if manual:
        if manual in blocks:
            return manual
        manual_lower = manual.lower()
        for key in blocks:
            if key.name.lower() == manual_lower:
                return key.name

    if wanted in blocks:
        return wanted

    wanted_lower = wanted.lower()
    for key in blocks:
        if key.name.lower() == wanted_lower:
            return key.name

    wanted_norm = helpers.normalize_identifier(wanted)
    for key in blocks:
        if helpers.normalize_identifier(key.name) == wanted_norm:
            return key.name

    return None


def rebuild_maps(scene):
    arm = scene.vmc_link_armature
    face = scene.vmc_link_face_object

    state.cached_bone_map = {}
    state.cached_blend_map = {}
    state.cached_arkit_blend_map = {}

    if arm is not None:
        from . import arp as mapping_arp

        arp_analysis = mapping_arp.analyze_armature(arm)
        if arp_analysis["is_arp"]:
            state.cached_bone_map = mapping_arp.build_runtime_mapping(scene, arm)
        else:
            filled = autofill_empty_manual_overrides(scene, arm)
            if filled:
                helpers.debug(f"Autofilled manual overrides: {filled}")

            for vmc_name in constants.BONE_ALIASES:
                actual = find_bone_name(arm, vmc_name, scene)
                if actual:
                    state.cached_bone_map[vmc_name] = actual

    if has_shape_keys(face):
        names = set(constants.BLEND_ALIASES.keys()) | set(state.blend_buf.keys())
        for vmc_name in names:
            actual = find_shapekey_name(face, vmc_name, scene)
            if actual:
                state.cached_blend_map[vmc_name] = actual

        names = set(constants.ARKIT_BLENDSHAPE_KEYS) | set(state.arkit_blend_buf.keys())
        for arkit_name in names:
            actual = find_arkit_shapekey_name(face, arkit_name, scene)
            if actual:
                state.cached_arkit_blend_map[arkit_name] = actual

    helpers.debug(
        "Rebuilt maps: "
        f"bones={len(state.cached_bone_map)} "
        f"vmc_blends={len(state.cached_blend_map)} "
        f"arkit_blends={len(state.cached_arkit_blend_map)}"
    )
