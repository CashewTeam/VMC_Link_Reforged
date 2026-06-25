from ..core import constants
from . import mapper as mapping


VRM_BUILTIN_PRESET_FILE = "vrm_humanoid.json"

VRM_REQUIRED_SOURCE_BONES = (
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

VRM_OPTIONAL_SOURCE_GROUPS = {
    "扩展骨": ("UpperChest", "LeftToeBase", "RightToeBase"),
    "眼睛": ("LeftEye", "RightEye"),
    "手指": constants.INTERMEDIATE_OPTIONAL_BONES,
}

VRM_DEFAULT_BONE_TARGETS = {
    source_name: source_name
    for source_name in (*constants.INTERMEDIATE_REQUIRED_BONES, *constants.INTERMEDIATE_OPTIONAL_BONES)
}


def _has_pose_bones(obj) -> bool:
    return mapping.has_pose_bones(obj)


def _resolve_pose_bone_name(arm_obj, wanted: str, scene=None):
    if not _has_pose_bones(arm_obj):
        return None
    return mapping.find_bone_name(arm_obj, wanted, scene)


def analyze_armature(arm_obj):
    result = {
        "is_target_valid": _has_pose_bones(arm_obj),
        "is_vrm": False,
        "required_found": {},
        "required_missing": [],
        "optional_found": {},
        "optional_missing": {},
        "resolved_default_targets": {},
    }
    if not result["is_target_valid"]:
        return result

    for source_name in (*constants.INTERMEDIATE_REQUIRED_BONES, *constants.INTERMEDIATE_OPTIONAL_BONES):
        actual_name = _resolve_pose_bone_name(arm_obj, source_name, None)
        if actual_name is not None:
            result["resolved_default_targets"][source_name] = actual_name

    for source_name in VRM_REQUIRED_SOURCE_BONES:
        actual_name = result["resolved_default_targets"].get(source_name)
        if actual_name is None:
            result["required_missing"].append(source_name)
            continue
        result["required_found"][source_name] = actual_name

    for group_name, source_names in VRM_OPTIONAL_SOURCE_GROUPS.items():
        found = []
        missing = []
        for source_name in source_names:
            actual_name = result["resolved_default_targets"].get(source_name)
            if actual_name is None:
                missing.append(source_name)
            else:
                found.append(actual_name)
        result["optional_found"][group_name] = tuple(found)
        result["optional_missing"][group_name] = tuple(missing)

    result["is_vrm"] = not result["required_missing"]
    return result


def _validation_group_status(scene, arm_obj, source_keys):
    mapped = []
    missing = []
    invalid = []

    for source_key in source_keys:
        target_name = mapping.get_mapping_override(scene, constants.MAPPING_KIND_BONE, source_key)
        if not target_name:
            missing.append(source_key)
            continue
        actual_name = _resolve_pose_bone_name(arm_obj, target_name, scene)
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
        "is_vrm": analysis["is_vrm"],
        "groups": {},
        "invalid_targets": [],
        "mismatched_defaults": [],
        "duplicate_targets": [],
    }
    if not analysis["is_target_valid"]:
        return validation

    groups = {
        "必需骨": VRM_REQUIRED_SOURCE_BONES,
        "可选骨": VRM_OPTIONAL_SOURCE_GROUPS["扩展骨"],
        "眼睛": VRM_OPTIONAL_SOURCE_GROUPS["眼睛"],
        "手指": VRM_OPTIONAL_SOURCE_GROUPS["手指"],
    }

    invalid_targets = []
    for label, source_keys in groups.items():
        status = _validation_group_status(scene, arm_obj, source_keys)
        invalid_targets.extend(status["invalid"])
        validation["groups"][label] = status

    entries = mapping.collect_mapping_entries(scene, constants.MAPPING_KIND_BONE)
    target_sources = {}
    for source_key, target_name in entries.items():
        actual_name = _resolve_pose_bone_name(arm_obj, target_name, scene)
        if actual_name is not None:
            target_sources.setdefault(actual_name, []).append(source_key)
        expected_actual = analysis["resolved_default_targets"].get(source_key)
        if expected_actual is not None and actual_name is not None and actual_name != expected_actual:
            validation["mismatched_defaults"].append(f"{source_key} -> {actual_name}，应为 {expected_actual}")

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
    if not analysis["is_vrm"]:
        raise RuntimeError("当前目标骨架不是可识别的 VRM / 通用 humanoid 骨架")

    mapping.clear_mapping_overrides(scene, constants.MAPPING_KIND_BONE)
    written = []
    unresolved = []
    for source_name in (*constants.INTERMEDIATE_REQUIRED_BONES, *constants.INTERMEDIATE_OPTIONAL_BONES):
        actual_name = analysis["resolved_default_targets"].get(source_name)
        if actual_name is None:
            unresolved.append(source_name)
            continue
        mapping.set_mapping_override(scene, constants.MAPPING_KIND_BONE, source_name, actual_name)
        written.append(f"{source_name} -> {actual_name}")

    mapping.invalidate_bone_map_cache()
    return {
        "analysis": analysis,
        "written": written,
        "skipped": [],
        "unresolved": unresolved,
        "validation": validate_scene_mapping(scene),
    }


def autofill_scene_mapping(scene):
    return apply_standard_scene_mapping(scene)


def clear_scene_report(scene):
    if scene is None:
        return
    scene.vmc_link_vrm_is_detected = False
    scene.vmc_link_vrm_report_title = ""
    scene.vmc_link_vrm_report = ""


def store_scene_report(scene, title: str, report_lines, is_vrm: bool):
    if scene is None:
        return
    scene.vmc_link_vrm_is_detected = bool(is_vrm)
    scene.vmc_link_vrm_report_title = str(title).strip()
    scene.vmc_link_vrm_report = "\n".join(str(line).strip() for line in report_lines if str(line).strip())


def inspect_report_lines(analysis: dict):
    if not analysis["is_target_valid"]:
        return ["未绑定有效目标骨架"]
    lines = [
        f"VRM / 通用骨架识别: {'通过' if analysis['is_vrm'] else '失败'}",
        f"识别必需骨: {len(VRM_REQUIRED_SOURCE_BONES) - len(analysis['required_missing'])}/{len(VRM_REQUIRED_SOURCE_BONES)}",
        f"默认可映射项: {len(VRM_DEFAULT_BONE_TARGETS)}",
    ]
    if analysis["required_missing"]:
        lines.append("缺失识别骨: " + ", ".join(analysis["required_missing"][:8]))
    for label, found in analysis["optional_found"].items():
        total = len(analysis["optional_found"].get(label, ())) + len(analysis["optional_missing"].get(label, ()))
        lines.append(f"{label}: {len(found)}/{total}")
    return lines


def autofill_report_lines(result: dict):
    analysis = result["analysis"]
    lines = [
        f"VRM / 通用骨架识别: {'通过' if analysis['is_vrm'] else '失败'}",
        f"新写入映射: {len(result['written'])}",
        f"未解析项: {len(result['unresolved'])}",
    ]
    if result["written"]:
        lines.append("已写入: " + ", ".join(result["written"][:6]))
    if result["unresolved"]:
        lines.append("未解析: " + ", ".join(result["unresolved"][:8]))
    return lines


def validation_report_lines(validation: dict):
    if not validation["is_target_valid"]:
        return ["未绑定有效目标骨架"]
    lines = [f"VRM / 通用骨架识别: {'通过' if validation['is_vrm'] else '失败'}"]
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
        lines.append(f"非标准 VRM 目标: {len(validation['mismatched_defaults'])}")
        lines.append("错误目标: " + ", ".join(validation["mismatched_defaults"][:4]))
    if validation["duplicate_targets"]:
        lines.append(f"重复目标: {len(validation['duplicate_targets'])}")
        lines.append("重复映射: " + ", ".join(validation["duplicate_targets"][:4]))
    return lines
