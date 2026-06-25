from ..core import helpers
from . import mapper as mapping


MMD_BUILTIN_PRESET_FILE = "mmd_humanoid.json"

MMD_DETECTION_REQUIRED_TARGETS = (
    "センター",
    "下半身",
    "上半身",
    "首",
    "頭",
    "左肩",
    "左腕",
    "左ひじ",
    "左手首",
    "右肩",
    "右腕",
    "右ひじ",
    "右手首",
    "左足",
    "左ひざ",
    "左足首",
    "右足",
    "右ひざ",
    "右足首",
)

MMD_OPTIONAL_TARGET_GROUPS = {
    "上半身扩展": ("上半身2", "上半身3"),
    "脚趾": ("左つま先", "右つま先"),
    "眼睛": ("左目", "右目"),
    "手指": (
        "左親指０",
        "左親指１",
        "左親指２",
        "左人指１",
        "左人指２",
        "左人指３",
        "左中指１",
        "左中指２",
        "左中指３",
        "左薬指１",
        "左薬指２",
        "左薬指３",
        "左小指１",
        "左小指２",
        "左小指３",
        "右親指０",
        "右親指１",
        "右親指２",
        "右人指１",
        "右人指２",
        "右人指３",
        "右中指１",
        "右中指２",
        "右中指３",
        "右薬指１",
        "右薬指２",
        "右薬指３",
        "右小指１",
        "右小指２",
        "右小指３",
    ),
}

MMD_DEFAULT_BONE_TARGETS = {
    "Hips": "下半身",
    "Spine": "上半身",
    "Chest": "上半身2",
    "UpperChest": "上半身3",
    "Neck": "首",
    "Head": "頭",
    "LeftEye": "左目",
    "RightEye": "右目",
    "LeftShoulder": "左肩",
    "LeftUpperArm": "左腕",
    "LeftLowerArm": "左ひじ",
    "LeftHand": "左手首",
    "RightShoulder": "右肩",
    "RightUpperArm": "右腕",
    "RightLowerArm": "右ひじ",
    "RightHand": "右手首",
    "LeftUpperLeg": "左足",
    "LeftLowerLeg": "左ひざ",
    "LeftFoot": "左足首",
    "LeftToeBase": "左つま先",
    "RightUpperLeg": "右足",
    "RightLowerLeg": "右ひざ",
    "RightFoot": "右足首",
    "RightToeBase": "右つま先",
}

MMD_NEUTRAL_AXIS_CALIBRATION_SOURCES = frozenset(
    (
        "LeftUpperArm",
        "LeftLowerArm",
        "LeftHand",
        "RightUpperArm",
        "RightLowerArm",
        "RightHand",
        "LeftUpperLeg",
        "LeftLowerLeg",
        "LeftFoot",
        "LeftToeBase",
        "RightUpperLeg",
        "RightLowerLeg",
        "RightFoot",
        "RightToeBase",
    )
)

MMD_RIGHT_ARM_SWING_CORRECTION_SOURCES = frozenset(
    (
        "RightUpperArm",
        "RightLowerArm",
        "RightHand",
    )
)

_FINGER_TARGETS = {
    ("Thumb", 0): "親指０",
    ("Thumb", 1): "親指１",
    ("Thumb", 2): "親指２",
    ("IndexFinger", 1): "人指１",
    ("IndexFinger", 2): "人指２",
    ("IndexFinger", 3): "人指３",
    ("MiddleFinger", 1): "中指１",
    ("MiddleFinger", 2): "中指２",
    ("MiddleFinger", 3): "中指３",
    ("RingFinger", 1): "薬指１",
    ("RingFinger", 2): "薬指２",
    ("RingFinger", 3): "薬指３",
    ("LittleFinger", 1): "小指１",
    ("LittleFinger", 2): "小指２",
    ("LittleFinger", 3): "小指３",
}

for side_suffix, side_label in (("L", "左"), ("R", "右")):
    for (finger_name, joint_index), target_name in _FINGER_TARGETS.items():
        MMD_DEFAULT_BONE_TARGETS[f"{finger_name}{joint_index}_{side_suffix}"] = f"{side_label}{target_name}"


_MMD_SIDE_SUFFIX = {
    "左": "L",
    "右": "R",
}

_MMD_EXACT_ALIASES = {
    "左目": ("目.L",),
    "右目": ("目.R",),
}


def _has_pose_bones(obj) -> bool:
    return mapping.has_pose_bones(obj)


def _unique_candidates(candidates):
    seen = set()
    unique = []
    for candidate in candidates:
        value = str(candidate).strip()
        if not value:
            continue
        key = (value.lower(), helpers.normalize_bone_name(value))
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return tuple(unique)


def _candidate_bone_names(wanted: str):
    raw = str(wanted).strip()
    if not raw:
        return ()

    candidates = [raw]
    candidates.extend(_MMD_EXACT_ALIASES.get(raw, ()))

    if raw.startswith(("左", "右")) and len(raw) > 1:
        side = raw[0]
        base = raw[1:]
        suffix = _MMD_SIDE_SUFFIX.get(side)
        if suffix:
            candidates.extend(
                (
                    f"{base}.{suffix}",
                    f"{base}_{suffix}",
                    f"{base}-{suffix}",
                    f"{base}{suffix}",
                )
            )
    return _unique_candidates(candidates)


def _resolve_pose_bone_name(arm_obj, wanted: str):
    if not _has_pose_bones(arm_obj):
        return None

    pose_bones = arm_obj.pose.bones
    candidates = _candidate_bone_names(wanted)
    normalized_candidates = {helpers.normalize_bone_name(candidate) for candidate in candidates}

    for candidate in candidates:
        if candidate in pose_bones:
            return candidate

    lowered_candidates = {candidate.lower() for candidate in candidates}
    for bone in pose_bones:
        if bone.name.lower() in lowered_candidates:
            return bone.name

    for bone in pose_bones:
        if helpers.normalize_bone_name(bone.name) in normalized_candidates:
            return bone.name
    return None


def _resolved_default_targets(arm_obj):
    resolved = {}
    unresolved = []
    alias_hits = []
    for source_key, wanted_target in MMD_DEFAULT_BONE_TARGETS.items():
        actual = _resolve_pose_bone_name(arm_obj, wanted_target)
        if actual is None:
            unresolved.append(source_key)
            continue
        resolved[source_key] = actual
        if actual != wanted_target:
            alias_hits.append(f"{wanted_target} -> {actual}")
    return resolved, unresolved, alias_hits


def analyze_armature(arm_obj):
    result = {
        "is_target_valid": _has_pose_bones(arm_obj),
        "is_mmd": False,
        "required_found": {},
        "required_missing": [],
        "required_aliases": [],
        "optional_found": {},
        "optional_missing": {},
        "resolved_default_targets": {},
        "default_unresolved": [],
        "default_aliases": [],
    }
    if not result["is_target_valid"]:
        return result

    for bone_name in MMD_DETECTION_REQUIRED_TARGETS:
        actual = _resolve_pose_bone_name(arm_obj, bone_name)
        if actual is None:
            result["required_missing"].append(bone_name)
            continue
        result["required_found"][bone_name] = actual
        if actual != bone_name:
            result["required_aliases"].append(f"{bone_name} -> {actual}")

    for group_name, bone_names in MMD_OPTIONAL_TARGET_GROUPS.items():
        found = []
        missing = []
        for bone_name in bone_names:
            actual = _resolve_pose_bone_name(arm_obj, bone_name)
            if actual is None:
                missing.append(bone_name)
            else:
                found.append(actual)
        result["optional_found"][group_name] = tuple(found)
        result["optional_missing"][group_name] = tuple(missing)

    resolved_default_targets, default_unresolved, default_aliases = _resolved_default_targets(arm_obj)
    result["resolved_default_targets"] = resolved_default_targets
    result["default_unresolved"] = default_unresolved
    result["default_aliases"] = default_aliases
    result["is_mmd"] = not result["required_missing"]
    return result


def _validation_group_status(scene, arm_obj, source_keys):
    mapped = []
    missing = []
    invalid = []

    for source_key in source_keys:
        target_name = mapping.get_mapping_override(scene, "bone", source_key)
        if not target_name:
            missing.append(source_key)
            continue
        actual_name = _resolve_pose_bone_name(arm_obj, target_name)
        if actual_name is None:
            invalid.append(f"{source_key} -> {target_name}")
            continue
        mapped.append(source_key)

    return {
        "mapped": mapped,
        "missing": missing,
        "invalid": invalid,
        "total": len(source_keys),
    }


def validate_scene_mapping(scene):
    arm_obj = getattr(scene, "vmc_link_armature", None)
    analysis = analyze_armature(arm_obj)
    validation = {
        "analysis": analysis,
        "is_target_valid": analysis["is_target_valid"],
        "is_mmd": analysis["is_mmd"],
        "groups": {},
        "invalid_targets": [],
        "mismatched_defaults": [],
        "stale_overrides": [],
        "duplicate_targets": [],
    }
    if not analysis["is_target_valid"]:
        return validation

    groups = {
        "必需骨": tuple(
            key
            for key in (
                "Hips",
                "Spine",
                "Chest",
                "Neck",
                "Head",
                "LeftShoulder",
                "LeftUpperArm",
                "LeftLowerArm",
                "LeftHand",
                "RightShoulder",
                "RightUpperArm",
                "RightLowerArm",
                "RightHand",
                "LeftUpperLeg",
                "LeftLowerLeg",
                "LeftFoot",
                "RightUpperLeg",
                "RightLowerLeg",
                "RightFoot",
            )
        ),
        "可选骨": ("UpperChest", "LeftToeBase", "RightToeBase"),
        "眼睛": ("LeftEye", "RightEye"),
        "手指": tuple(
            key
            for key in MMD_DEFAULT_BONE_TARGETS
            if key.startswith(("Thumb", "IndexFinger", "MiddleFinger", "RingFinger", "LittleFinger"))
        ),
    }

    invalid_targets = []
    for label, source_keys in groups.items():
        status = _validation_group_status(scene, arm_obj, source_keys)
        invalid_targets.extend(status["invalid"])
        validation["groups"][label] = status

    resolved_defaults = analysis.get("resolved_default_targets", {})
    entries = mapping.collect_mapping_entries(scene, "bone")
    target_sources = {}
    for source_key, target_name in entries.items():
        actual_name = _resolve_pose_bone_name(arm_obj, target_name)
        target_key = actual_name or target_name
        target_sources.setdefault(target_key, []).append(source_key)
        expected = resolved_defaults.get(source_key, MMD_DEFAULT_BONE_TARGETS.get(source_key))
        if expected is not None and target_key != expected:
            validation["mismatched_defaults"].append(f"{source_key} -> {target_name}，应为 {expected}")
            validation["stale_overrides"].append(f"{source_key}: 当前 {target_name}，应为 {expected}")

    validation["invalid_targets"] = invalid_targets
    validation["duplicate_targets"] = [
        f"{target_name} <- {', '.join(source_keys)}"
        for target_name, source_keys in sorted(target_sources.items())
        if len(source_keys) > 1
    ]
    return validation


def apply_standard_scene_mapping(scene):
    arm_obj = getattr(scene, "vmc_link_armature", None)
    analysis = analyze_armature(arm_obj)
    if not analysis["is_target_valid"]:
        raise RuntimeError("请先绑定目标骨架")
    if not analysis["is_mmd"]:
        raise RuntimeError("当前目标骨架不是可识别的 MMD 标准骨架")

    resolved_defaults = analysis["resolved_default_targets"]
    previous_entries = mapping.collect_mapping_entries(scene, "bone")
    mapping.clear_mapping_overrides(scene, "bone")
    written = []
    unresolved = []
    for source_key in MMD_DEFAULT_BONE_TARGETS:
        actual_name = resolved_defaults.get(source_key)
        if actual_name is None:
            unresolved.append(source_key)
            continue
        mapping.set_mapping_override(scene, "bone", source_key, actual_name)
        written.append(f"{source_key} -> {actual_name}")

    mapping.invalidate_bone_map_cache()
    return {
        "analysis": analysis,
        "cleared": len(previous_entries),
        "written": written,
        "unresolved": unresolved,
        "validation": validate_scene_mapping(scene),
    }


def autofill_scene_mapping(scene):
    return apply_standard_scene_mapping(scene)


def build_runtime_mapping(scene, arm_obj=None):
    if arm_obj is None and scene is not None:
        arm_obj = getattr(scene, "vmc_link_armature", None)
    if not _has_pose_bones(arm_obj):
        return {}

    runtime_map = {}
    for source_key, target_name in mapping.collect_mapping_entries(scene, "bone").items():
        actual_name = _resolve_pose_bone_name(arm_obj, target_name)
        if actual_name is None:
            continue
        runtime_map[source_key] = actual_name
    return runtime_map


def uses_neutral_axis_calibration(source_name: str) -> bool:
    return source_name in MMD_NEUTRAL_AXIS_CALIBRATION_SOURCES


def uses_right_arm_swing_correction(source_name: str) -> bool:
    return source_name in MMD_RIGHT_ARM_SWING_CORRECTION_SOURCES


def clear_scene_report(scene):
    if scene is None:
        return
    scene.vmc_link_mmd_is_detected = False
    scene.vmc_link_mmd_report_title = ""
    scene.vmc_link_mmd_report = ""


def store_scene_report(scene, title: str, report_lines, is_mmd: bool):
    if scene is None:
        return
    scene.vmc_link_mmd_is_detected = bool(is_mmd)
    scene.vmc_link_mmd_report_title = str(title).strip()
    scene.vmc_link_mmd_report = "\n".join(str(line).strip() for line in report_lines if str(line).strip())


def inspect_report_lines(analysis: dict):
    if not analysis["is_target_valid"]:
        return ["未绑定有效目标骨架"]
    lines = [
        f"MMD 识别: {'通过' if analysis['is_mmd'] else '失败'}",
        f"识别必需控制骨: {len(MMD_DETECTION_REQUIRED_TARGETS) - len(analysis['required_missing'])}/{len(MMD_DETECTION_REQUIRED_TARGETS)}",
        f"默认可映射项: {len(analysis['resolved_default_targets'])}/{len(MMD_DEFAULT_BONE_TARGETS)}",
    ]
    if analysis["required_missing"]:
        lines.append("缺失识别骨: " + ", ".join(analysis["required_missing"][:8]))
    if analysis["required_aliases"]:
        lines.append("已解析侧别名: " + ", ".join(analysis["required_aliases"][:6]))
    if analysis["default_aliases"]:
        lines.append("默认映射别名命中: " + ", ".join(analysis["default_aliases"][:6]))
    if analysis["default_unresolved"]:
        lines.append("默认未解析项: " + ", ".join(analysis["default_unresolved"][:8]))
    for label, found in analysis["optional_found"].items():
        total = len(analysis["optional_found"].get(label, ())) + len(analysis["optional_missing"].get(label, ()))
        lines.append(f"{label}: {len(found)}/{total}")
    return lines


def validation_report_lines(validation: dict):
    if not validation["is_target_valid"]:
        return ["未绑定有效目标骨架"]
    lines = [f"MMD 识别: {'通过' if validation['is_mmd'] else '失败'}"]
    for label in ("必需骨", "可选骨", "眼睛", "手指"):
        group = validation["groups"].get(label)
        if group is None:
            continue
        lines.append(f"{label}: {len(group['mapped'])}/{group['total']}，无效 {len(group['invalid'])}")
        if group["missing"]:
            lines.append(f"{label}缺失: {', '.join(group['missing'][:8])}")
        if group["invalid"]:
            lines.append(f"{label}无效: {', '.join(group['invalid'][:4])}")
    if validation["mismatched_defaults"]:
        lines.append(f"残留错误映射: {len(validation['mismatched_defaults'])}")
        lines.append("错误项: " + ", ".join(validation["stale_overrides"][:4]))
    if validation["duplicate_targets"]:
        lines.append(f"重复目标: {len(validation['duplicate_targets'])}")
        lines.append("重复项: " + ", ".join(validation["duplicate_targets"][:4]))
    return lines


def autofill_report_lines(result: dict):
    lines = [
        f"已清空旧映射: {int(result.get('cleared', 0))}",
        f"新写入映射: {len(result['written'])}",
        f"无法解析项: {len(result['unresolved'])}",
    ]
    if result["written"]:
        lines.append("已写入: " + ", ".join(result["written"][:6]))
    if result["unresolved"]:
        lines.append("未解析: " + ", ".join(result["unresolved"][:8]))
    lines.extend(validation_report_lines(result["validation"]))
    return lines
