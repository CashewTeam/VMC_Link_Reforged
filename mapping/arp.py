from ..core import constants
from . import mapper as mapping


ARP_BUILTIN_PRESET_FILE = "arp_fk_humanoid.json"

ARP_DETECTION_REQUIRED_TARGETS = (
    "c_root_master.x",
    "c_root_bend.x",
    "c_spine_01.x",
    "c_spine_02.x",
    "c_neck.x",
    "c_head.x",
    "c_arm_fk.l",
    "c_forearm_fk.l",
    "c_hand_fk.l",
    "c_arm_fk.r",
    "c_forearm_fk.r",
    "c_hand_fk.r",
    "c_thigh_fk.l",
    "c_leg_fk.l",
    "c_foot_fk.l",
    "c_thigh_fk.r",
    "c_leg_fk.r",
    "c_foot_fk.r",
)

ARP_REQUIRED_SOURCE_BONES = (
    "Hips",
    "Spine",
    "Chest",
    "UpperChest",
    "Neck",
    "Head",
    "LeftUpperArm",
    "LeftLowerArm",
    "LeftHand",
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

ARP_OPTIONAL_SOURCE_BONES = (
    "LeftShoulder",
    "RightShoulder",
    "LeftToeBase",
    "RightToeBase",
)

ARP_EYE_SOURCE_BONES = (
    "LeftEye",
    "RightEye",
)

ARP_DEFAULT_BONE_TARGETS = {
    "Hips": "c_root_bend.x",
    "Spine": "c_spine_01.x",
    "Chest": "c_spine_02.x",
    "UpperChest": "c_spine_03.x",
    "Neck": "c_neck.x",
    "Head": "c_head.x",
    "LeftEye": "c_eye.l",
    "RightEye": "c_eye.r",
    "LeftShoulder": "c_shoulder.l",
    "RightShoulder": "c_shoulder.r",
    "LeftUpperArm": "c_arm_fk.l",
    "LeftLowerArm": "c_forearm_fk.l",
    "LeftHand": "c_hand_fk.l",
    "RightUpperArm": "c_arm_fk.r",
    "RightLowerArm": "c_forearm_fk.r",
    "RightHand": "c_hand_fk.r",
    "LeftUpperLeg": "c_thigh_fk.l",
    "LeftLowerLeg": "c_leg_fk.l",
    "LeftFoot": "c_foot_fk.l",
    "LeftToeBase": "c_toes_fk.l",
    "RightUpperLeg": "c_thigh_fk.r",
    "RightLowerLeg": "c_leg_fk.r",
    "RightFoot": "c_foot_fk.r",
    "RightToeBase": "c_toes_fk.r",
}

_FINGER_PREFIX_BY_SOURCE = {
    "Thumb": "c_thumb",
    "IndexFinger": "c_index",
    "MiddleFinger": "c_middle",
    "RingFinger": "c_ring",
    "LittleFinger": "c_pinky",
}

for side_suffix, side_label in (("L", "l"), ("R", "r")):
    for finger_name, prefix in _FINGER_PREFIX_BY_SOURCE.items():
        joint_indices = (0, 1, 2) if finger_name == "Thumb" else (1, 2, 3)
        for joint_index in joint_indices:
            target_index = joint_index + 1 if finger_name == "Thumb" else joint_index
            ARP_DEFAULT_BONE_TARGETS[f"{finger_name}{joint_index}_{side_suffix}"] = f"{prefix}{target_index}.{side_label}"


ARP_OPTIONAL_TARGET_GROUPS = {
    "眼睛控制": ("c_eye.l", "c_eye.r"),
    "肩膀控制": ("c_shoulder.l", "c_shoulder.r"),
    "脚趾控制": ("c_toes_fk.l", "c_toes_fk.r"),
    "手指控制": tuple(
        f"{prefix}{joint_index}.{side_label}"
        for side_label in ("l", "r")
        for prefix in ("c_thumb", "c_index", "c_middle", "c_ring", "c_pinky")
        for joint_index in (1, 2, 3)
    ),
    "额外脊柱控制": ("c_root_master.x", "c_spine_03.x", "c_waist_bend.x", "c_spine_01_bend.x", "c_spine_02_bend.x"),
}

ARP_IK_FK_CONTROLS = (
    "c_hand_ik.l",
    "c_hand_ik.r",
    "c_foot_ik.l",
    "c_foot_ik.r",
)

ARP_RUNTIME_SOURCE_ORDER = (
    "Hips",
    "Spine",
    "Chest",
    "UpperChest",
    "Neck",
    "Head",
    "LeftShoulder",
    "RightShoulder",
    "LeftUpperArm",
    "RightUpperArm",
    "LeftLowerArm",
    "RightLowerArm",
    "LeftHand",
    "RightHand",
    "LeftUpperLeg",
    "RightUpperLeg",
    "LeftLowerLeg",
    "RightLowerLeg",
    "LeftFoot",
    "RightFoot",
    "LeftToeBase",
    "RightToeBase",
    *constants.INTERMEDIATE_OPTIONAL_BONES,
)

ARP_RUNTIME_SOURCE_GROUPS = (
    ("Hips", "Spine", "Chest", "UpperChest", "Neck", "Head"),
    ("LeftShoulder", "RightShoulder"),
    ("LeftUpperArm", "RightUpperArm", "LeftUpperLeg", "RightUpperLeg"),
    ("LeftLowerArm", "RightLowerArm", "LeftLowerLeg", "RightLowerLeg"),
    ("LeftHand", "RightHand", "LeftFoot", "RightFoot"),
    (
        "LeftToeBase",
        "RightToeBase",
        "Thumb0_L",
        "Thumb0_R",
        "IndexFinger1_L",
        "IndexFinger1_R",
        "MiddleFinger1_L",
        "MiddleFinger1_R",
        "RingFinger1_L",
        "RingFinger1_R",
        "LittleFinger1_L",
        "LittleFinger1_R",
    ),
    (
        "Thumb1_L",
        "Thumb1_R",
        "IndexFinger2_L",
        "IndexFinger2_R",
        "MiddleFinger2_L",
        "MiddleFinger2_R",
        "RingFinger2_L",
        "RingFinger2_R",
        "LittleFinger2_L",
        "LittleFinger2_R",
    ),
    (
        "Thumb2_L",
        "Thumb2_R",
        "IndexFinger3_L",
        "IndexFinger3_R",
        "MiddleFinger3_L",
        "MiddleFinger3_R",
        "RingFinger3_L",
        "RingFinger3_R",
        "LittleFinger3_L",
        "LittleFinger3_R",
    ),
)

ARP_ALLOWED_CONTROL_TARGETS = frozenset(ARP_DEFAULT_BONE_TARGETS.values())
ARP_DELTA_ROTATION_SOURCE_BONES = frozenset()
ARP_WORLD_ROTATION_SOURCE_BONES = frozenset((
    "LeftUpperArm",
    "RightUpperArm",
    "LeftLowerArm",
    "RightLowerArm",
    "LeftHand",
    "RightHand",
))


ARP_LOCAL_BASIS_DELTA_SOURCE_BONES = frozenset()
ARP_REST_AXIS_REMAP_SOURCE_BONES = frozenset(
    source_name
    for source_name in constants.INTERMEDIATE_OPTIONAL_BONES
    if source_name.startswith("Thumb")
)


def uses_delta_rotation(source_name: str) -> bool:
    return source_name in ARP_DELTA_ROTATION_SOURCE_BONES


def uses_world_rotation(source_name: str) -> bool:
    return source_name in ARP_WORLD_ROTATION_SOURCE_BONES


def uses_local_basis_delta(source_name: str) -> bool:
    return source_name in ARP_LOCAL_BASIS_DELTA_SOURCE_BONES


def uses_rest_axis_remap(source_name: str) -> bool:
    return source_name in ARP_REST_AXIS_REMAP_SOURCE_BONES


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


def _detect_conflicts(entries: dict):
    target_to_sources = {}
    for source_key, target_name in entries.items():
        target_to_sources.setdefault(target_name, []).append(source_key)

    conflicts = []
    for target_name, source_keys in sorted(target_to_sources.items()):
        if len(source_keys) > 1:
            conflicts.append(f"{target_name} <- {', '.join(source_keys)}")
    return conflicts


def analyze_armature(arm_obj):
    result = {
        "target_name": getattr(arm_obj, "name", ""),
        "is_target_valid": _has_pose_bones(arm_obj),
        "is_arp": False,
        "missing_detection_targets": [],
        "resolved_default_targets": {},
        "missing_default_sources": [],
        "conflicts": [],
        "ambiguities": [],
        "optional_groups": {},
    }

    if not result["is_target_valid"]:
        return result

    missing_detection_targets = []
    for target_name in ARP_DETECTION_REQUIRED_TARGETS:
        if _resolve_pose_bone_name(arm_obj, target_name) is None:
            missing_detection_targets.append(target_name)
    result["missing_detection_targets"] = missing_detection_targets
    result["is_arp"] = not missing_detection_targets

    resolved_default_targets = {}
    missing_default_sources = []
    for source_key, target_name in ARP_DEFAULT_BONE_TARGETS.items():
        actual_name = _resolve_pose_bone_name(arm_obj, target_name)
        if actual_name is None:
            missing_default_sources.append(source_key)
            continue
        resolved_default_targets[source_key] = actual_name

    result["resolved_default_targets"] = resolved_default_targets
    result["missing_default_sources"] = missing_default_sources
    result["conflicts"] = _detect_conflicts(resolved_default_targets)

    optional_groups = {}
    for label, target_names in ARP_OPTIONAL_TARGET_GROUPS.items():
        found = []
        missing = []
        for target_name in target_names:
            actual_name = _resolve_pose_bone_name(arm_obj, target_name)
            if actual_name is None:
                missing.append(target_name)
            else:
                found.append(actual_name)
        optional_groups[label] = {
            "found": found,
            "missing": missing,
            "total": len(target_names),
        }
    result["optional_groups"] = optional_groups
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
        "is_arp": analysis["is_arp"],
        "groups": {},
        "invalid_targets": [],
        "mismatched_defaults": [],
        "duplicate_targets": [],
    }

    if not analysis["is_target_valid"]:
        return validation

    groups = {
        "必需骨": ARP_REQUIRED_SOURCE_BONES,
        "可选骨": ARP_OPTIONAL_SOURCE_BONES,
        "眼睛": ARP_EYE_SOURCE_BONES,
        "手指": constants.INTERMEDIATE_OPTIONAL_BONES,
    }

    invalid_targets = []
    group_status = {}
    for label, source_keys in groups.items():
        status = _validation_group_status(scene, arm_obj, source_keys)
        invalid_targets.extend(status["invalid"])
        group_status[label] = status

    validation["groups"] = group_status
    validation["invalid_targets"] = invalid_targets
    entries = mapping.collect_mapping_entries(scene, constants.MAPPING_KIND_BONE)
    target_sources = {}
    for source_key, target_name in entries.items():
        target_sources.setdefault(target_name, []).append(source_key)
        expected = analysis["resolved_default_targets"].get(source_key)
        if expected is not None and target_name != expected:
            validation["mismatched_defaults"].append(f"{source_key} -> {target_name}，应为 {expected}")
        elif expected is None and target_name not in ARP_ALLOWED_CONTROL_TARGETS:
            validation["mismatched_defaults"].append(f"{source_key} -> {target_name}")
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
    if not analysis["is_arp"]:
        raise RuntimeError("当前目标骨架不是可识别的 Auto Rig Pro 标准控制骨架")

    mapping.clear_mapping_overrides(scene, constants.MAPPING_KIND_BONE)
    written = []
    for source_key in ARP_RUNTIME_SOURCE_ORDER:
        target_name = analysis["resolved_default_targets"].get(source_key)
        if target_name is None:
            continue
        mapping.set_mapping_override(scene, constants.MAPPING_KIND_BONE, source_key, target_name)
        written.append(f"{source_key} -> {target_name}")

    if hasattr(scene, "vmc_link_bone_map_preset"):
        scene.vmc_link_bone_map_preset = ARP_BUILTIN_PRESET_FILE
    mapping.invalidate_bone_map_cache()
    return {
        "analysis": analysis,
        "written": written,
        "validation": validate_scene_mapping(scene),
    }


def build_runtime_mapping(scene, arm_obj):
    analysis = analyze_armature(arm_obj)
    if not analysis["is_arp"]:
        return {}

    runtime_map = {}
    used_targets = set()
    for source_key in ARP_RUNTIME_SOURCE_ORDER:
        expected_target = analysis["resolved_default_targets"].get(source_key)
        if expected_target is None:
            continue
        configured_target = mapping.get_mapping_override(scene, constants.MAPPING_KIND_BONE, source_key)
        if configured_target != expected_target or configured_target in used_targets:
            continue
        runtime_map[source_key] = configured_target
        used_targets.add(configured_target)
    return runtime_map


def capture_session_state(arm_obj):
    if not analyze_armature(arm_obj)["is_arp"]:
        return None

    switches = {}
    for bone_name in ARP_IK_FK_CONTROLS:
        pose_bone = arm_obj.pose.bones.get(bone_name)
        if pose_bone is None or "ik_fk_switch" not in pose_bone:
            continue
        switches[bone_name] = float(pose_bone["ik_fk_switch"])
    return {"ik_fk_switches": switches}


def enable_fk_mode(arm_obj):
    if not analyze_armature(arm_obj)["is_arp"]:
        return
    for bone_name in ARP_IK_FK_CONTROLS:
        pose_bone = arm_obj.pose.bones.get(bone_name)
        if pose_bone is not None and "ik_fk_switch" in pose_bone:
            pose_bone["ik_fk_switch"] = 1.0


def enable_runtime_quaternion_mode(scene, arm_obj):
    if arm_obj is None or not analyze_armature(arm_obj)["is_arp"]:
        return []

    runtime_map = build_runtime_mapping(scene, arm_obj)
    changed = []
    for target_name in runtime_map.values():
        pose_bone = arm_obj.pose.bones.get(target_name)
        if pose_bone is None or pose_bone.rotation_mode == "QUATERNION":
            continue
        pose_bone.rotation_mode = "QUATERNION"
        changed.append(target_name)
    return changed


def restore_session_state(arm_obj, session_state):
    if arm_obj is None or not session_state:
        return
    for bone_name, value in session_state.get("ik_fk_switches", {}).items():
        pose_bone = arm_obj.pose.bones.get(bone_name)
        if pose_bone is not None and "ik_fk_switch" in pose_bone:
            pose_bone["ik_fk_switch"] = float(value)


def reset_runtime_control_transforms(scene):
    arm_obj = getattr(scene, "vmc_link_armature", None)
    analysis = analyze_armature(arm_obj)
    if not analysis["is_arp"]:
        return 0

    runtime_map = build_runtime_mapping(scene, arm_obj)
    if not runtime_map:
        runtime_map = analysis["resolved_default_targets"]

    pose = arm_obj.pose.bones
    target_names = {
        target_name
        for target_name in runtime_map.values()
        if target_name in pose
    }

    reset_count = 0
    for target_name in target_names:
        pose_bone = pose.get(target_name)
        if pose_bone is None:
            continue
        pose_bone.location = (0.0, 0.0, 0.0)
        pose_bone.rotation_mode = "QUATERNION"
        pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pose_bone.scale = (1.0, 1.0, 1.0)
        reset_count += 1

    traj_bone = pose.get("c_traj")
    if traj_bone is not None:
        traj_location = tuple(traj_bone.location)
        traj_bone.rotation_mode = "QUATERNION"
        traj_bone.location = traj_location
        traj_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        traj_bone.scale = (1.0, 1.0, 1.0)
        reset_count += 1

    return reset_count


def prepare_receiver_session(scene):
    arm_obj = getattr(scene, "vmc_link_armature", None)
    from . import target_rig as mapping_target_rig

    if mapping_target_rig.scene_target_rig_type(scene) != mapping_target_rig.TARGET_RIG_ARP:
        return analyze_armature(arm_obj)

    analysis = analyze_armature(arm_obj)
    if not analysis["is_arp"]:
        return analysis

    preview_arm = getattr(scene, "vmc_link_preview_armature", None)
    if not mapping.has_pose_bones(preview_arm) or "UpperChest" not in preview_arm.pose.bones:
        raise RuntimeError("ARP 驱动需要新版 VRM 预览骨架，请先点击“创建或重建 VRM 预览骨架”")

    apply_standard_scene_mapping(scene)
    enable_fk_mode(arm_obj)
    enable_runtime_quaternion_mode(scene, arm_obj)
    return analysis


def autofill_scene_mapping(scene):
    result = apply_standard_scene_mapping(scene)
    mapping.rebuild_maps(scene)
    result["skipped"] = []
    result["unresolved"] = result["analysis"]["missing_default_sources"]
    result["validation"] = validate_scene_mapping(scene)
    return result


def clear_scene_report(scene):
    if scene is None:
        return
    scene.vmc_link_arp_is_detected = False
    scene.vmc_link_arp_report_title = ""
    scene.vmc_link_arp_report = ""


def store_scene_report(scene, title: str, report_lines, is_arp: bool):
    if scene is None:
        return
    scene.vmc_link_arp_is_detected = bool(is_arp)
    scene.vmc_link_arp_report_title = str(title).strip()
    scene.vmc_link_arp_report = "\n".join(str(line).strip() for line in report_lines if str(line).strip())


def inspect_report_lines(analysis: dict):
    if not analysis["is_target_valid"]:
        return ["未绑定有效目标骨架"]

    lines = [
        f"目标骨架: {analysis['target_name']}",
        f"ARP 识别: {'通过' if analysis['is_arp'] else '失败'}",
        f"识别必需控制骨: {len(ARP_DETECTION_REQUIRED_TARGETS) - len(analysis['missing_detection_targets'])}/{len(ARP_DETECTION_REQUIRED_TARGETS)}",
        f"可自动填充映射: {len(analysis['resolved_default_targets'])}/{len(ARP_DEFAULT_BONE_TARGETS)}",
        f"缺失默认目标项: {len(analysis['missing_default_sources'])}",
        f"冲突项: {len(analysis['conflicts'])}",
        f"歧义项: {len(analysis['ambiguities'])}",
    ]

    if analysis["missing_detection_targets"]:
        lines.append("缺失识别骨: " + ", ".join(analysis["missing_detection_targets"][:8]))
    if analysis["missing_default_sources"]:
        lines.append("缺失源映射: " + ", ".join(analysis["missing_default_sources"][:8]))

    optional_groups = analysis["optional_groups"]
    for label in ("眼睛控制", "肩膀控制", "脚趾控制", "手指控制", "额外脊柱控制"):
        group = optional_groups.get(label)
        if group is None:
            continue
        lines.append(f"{label}: {len(group['found'])}/{group['total']}")
    return lines


def validation_report_lines(validation: dict):
    analysis = validation["analysis"]
    if not validation["is_target_valid"]:
        return ["未绑定有效目标骨架"]

    lines = [
        f"目标骨架: {analysis['target_name']}",
        f"ARP 识别: {'通过' if validation['is_arp'] else '失败'}",
    ]

    for label in ("必需骨", "可选骨", "眼睛", "手指"):
        group = validation["groups"].get(label)
        if group is None:
            continue
        ok_count = len(group["mapped"])
        total = group["total"]
        invalid_count = len(group["invalid"])
        lines.append(f"{label}: {ok_count}/{total}，无效 {invalid_count}")
        if group["missing"]:
            lines.append(f"{label}缺失: {', '.join(group['missing'][:8])}")
        if group["invalid"]:
            lines.append(f"{label}无效: {', '.join(group['invalid'][:4])}")

    if validation["mismatched_defaults"]:
        lines.append(f"非标准 ARP 目标: {len(validation['mismatched_defaults'])}")
        lines.append("错误目标: " + ", ".join(validation["mismatched_defaults"][:4]))
    if validation["duplicate_targets"]:
        lines.append(f"重复目标: {len(validation['duplicate_targets'])}")
        lines.append("重复项: " + ", ".join(validation["duplicate_targets"][:4]))

    return lines


def autofill_report_lines(result: dict):
    validation = result["validation"]
    lines = [
        f"新写入映射: {len(result['written'])}",
        f"保留已有映射: {len(result['skipped'])}",
        f"无法解析项: {len(result['unresolved'])}",
    ]
    if result["written"]:
        lines.append("已写入: " + ", ".join(result["written"][:6]))
    if result["unresolved"]:
        lines.append("未解析: " + ", ".join(result["unresolved"][:8]))
    lines.extend(validation_report_lines(validation))
    return lines


def brief_operator_message(report_lines):
    if not report_lines:
        return "已完成"
    return report_lines[0]
