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


def _has_pose_bones(obj) -> bool:
    return mapping.has_pose_bones(obj)


def _resolve_pose_bone_name(arm_obj, wanted: str):
    if not _has_pose_bones(arm_obj):
        return None

    pose_bones = arm_obj.pose.bones
    if wanted in pose_bones:
        return wanted

    wanted_lower = str(wanted).lower()
    for bone in pose_bones:
        if bone.name.lower() == wanted_lower:
            return bone.name
    return None


def analyze_armature(arm_obj):
    result = {
        "is_target_valid": _has_pose_bones(arm_obj),
        "is_mmd": False,
        "required_found": {},
        "required_missing": [],
        "optional_found": {},
        "optional_missing": {},
    }
    if not result["is_target_valid"]:
        return result

    for bone_name in MMD_DETECTION_REQUIRED_TARGETS:
        actual = _resolve_pose_bone_name(arm_obj, bone_name)
        if actual is None:
            result["required_missing"].append(bone_name)
            continue
        result["required_found"][bone_name] = actual

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
            key for key in MMD_DEFAULT_BONE_TARGETS if key.startswith(("Thumb", "IndexFinger", "MiddleFinger", "RingFinger", "LittleFinger"))
        ),
    }

    invalid_targets = []
    for label, source_keys in groups.items():
        status = _validation_group_status(scene, arm_obj, source_keys)
        invalid_targets.extend(status["invalid"])
        validation["groups"][label] = status

    entries = mapping.collect_mapping_entries(scene, "bone")
    target_sources = {}
    for source_key, target_name in entries.items():
        target_sources.setdefault(target_name, []).append(source_key)
        expected = MMD_DEFAULT_BONE_TARGETS.get(source_key)
        if expected is not None and target_name != expected:
            validation["mismatched_defaults"].append(f"{source_key} -> {target_name}，应为 {expected}")

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

    mapping.clear_mapping_overrides(scene, "bone")
    written = []
    unresolved = []
    for source_key, target_name in MMD_DEFAULT_BONE_TARGETS.items():
        actual_name = _resolve_pose_bone_name(arm_obj, target_name)
        if actual_name is None:
            unresolved.append(source_key)
            continue
        mapping.set_mapping_override(scene, "bone", source_key, actual_name)
        written.append(f"{source_key} -> {actual_name}")

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
        f"默认可映射项: {len(MMD_DEFAULT_BONE_TARGETS)}",
    ]
    if analysis["required_missing"]:
        lines.append("缺失识别骨: " + ", ".join(analysis["required_missing"][:8]))
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
        lines.append(f"非标准 MMD 目标: {len(validation['mismatched_defaults'])}")
        lines.append("错误目标: " + ", ".join(validation["mismatched_defaults"][:4]))
    if validation["duplicate_targets"]:
        lines.append(f"重复目标: {len(validation['duplicate_targets'])}")
        lines.append("重复项: " + ", ".join(validation["duplicate_targets"][:4]))
    return lines


def autofill_report_lines(result: dict):
    lines = [
        f"新写入映射: {len(result['written'])}",
        f"保留已有映射: {len(result['skipped'])}",
        f"无法解析项: {len(result['unresolved'])}",
    ]
    if result["written"]:
        lines.append("已写入: " + ", ".join(result["written"][:6]))
    if result["unresolved"]:
        lines.append("未解析: " + ", ".join(result["unresolved"][:8]))
    lines.extend(validation_report_lines(result["validation"]))
    return lines
