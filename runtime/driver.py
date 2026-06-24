import math
import time

import bpy
from mathutils import Matrix, Vector

from ..core import constants, helpers, state
from ..mapping import arp as mapping_arp
from ..mapping import mapper as mapping
from . import network, properties


def is_recording() -> bool:
    return state.recording


def set_recording(value: bool):
    state.recording = bool(value)


def get_face_source(scene) -> str:
    return str(getattr(scene, "vmc_link_face_source", constants.FACE_SOURCE_VMC))


def is_arkit_face_source_enabled(scene) -> bool:
    return get_face_source(scene) == constants.FACE_SOURCE_RHYLIVE_ARKIT


def get_face_source_label(scene) -> str:
    return "RhyLive ARKit" if is_arkit_face_source_enabled(scene) else "VMC"


def get_latest_receiver_timestamp(scene) -> float:
    if scene is not None and is_arkit_face_source_enabled(scene):
        return max(state.last_packet_ts, state.arkit_last_packet_ts)
    return state.last_packet_ts


def describe_receiver_endpoints(scene) -> str:
    bind_host = properties.resolve_bind_host(scene)
    vmc_desc = f"UDP {bind_host}:{int(getattr(scene, 'vmc_link_port', constants.DEFAULT_PORT))}"
    if scene is not None and is_arkit_face_source_enabled(scene):
        return f"{vmc_desc} + ARKit {bind_host}:{int(getattr(scene, 'vmc_link_arkit_port', constants.DEFAULT_ARKIT_PORT))}"
    return vmc_desc


def get_root_motion_source() -> str:
    if state.root_buf is not None:
        return "Root/Pos"
    if state.waist_buf is not None:
        return "Tra/Pos"
    if mapping.get_vmc_bone_pose(state.bone_buf, "Hips") is not None:
        return "Bone/Pos:Hips"
    return "无"


def get_receiver_status_label(scene) -> str:
    if not network.is_session_active():
        return "已停止"
    if network.is_paused():
        return "已暂停"
    last_pkt = get_latest_receiver_timestamp(scene)
    if last_pkt == 0.0:
        return "等待连接"
    if (time.time() - last_pkt) <= 2.0:
        return "已连接" if getattr(scene, "vmc_link_live_preview", True) else "仅更新预览层"
    return "已断开"


def _capture_transform_state(item):
    return {
        "rotation_mode": str(getattr(item, "rotation_mode", "QUATERNION")),
        "location": tuple(getattr(item, "location", (0.0, 0.0, 0.0))),
        "rotation_quaternion": tuple(getattr(item, "rotation_quaternion", (1.0, 0.0, 0.0, 0.0))),
        "rotation_euler": tuple(getattr(item, "rotation_euler", (0.0, 0.0, 0.0))),
        "rotation_axis_angle": tuple(getattr(item, "rotation_axis_angle", (0.0, 0.0, 1.0, 0.0))),
        "scale": tuple(getattr(item, "scale", (1.0, 1.0, 1.0))),
    }


def _restore_transform_state(item, snapshot):
    if item is None or not snapshot:
        return

    item.rotation_mode = snapshot["rotation_mode"]
    if hasattr(item, "location"):
        item.location = snapshot["location"]
    if hasattr(item, "rotation_quaternion"):
        item.rotation_quaternion = snapshot["rotation_quaternion"]
    if hasattr(item, "rotation_euler"):
        item.rotation_euler = snapshot["rotation_euler"]
    if hasattr(item, "rotation_axis_angle"):
        item.rotation_axis_angle = snapshot["rotation_axis_angle"]
    if hasattr(item, "scale"):
        item.scale = snapshot["scale"]


def _capture_armature_state(arm_obj):
    if not mapping.has_pose_bones(arm_obj):
        return None

    pose_bones = {}
    for pose_bone in arm_obj.pose.bones:
        pose_bones[pose_bone.name] = _capture_transform_state(pose_bone)

    return {
        "object": arm_obj,
        "object_state": _capture_transform_state(arm_obj),
        "pose_bones": pose_bones,
        "arp_state": mapping_arp.capture_session_state(arm_obj),
    }


def _capture_face_state(face_obj):
    if not mapping.has_shape_keys(face_obj):
        return None

    key_blocks = face_obj.data.shape_keys.key_blocks
    shape_keys = {}
    for key_block in key_blocks:
        shape_keys[key_block.name] = float(key_block.value)

    return {
        "object": face_obj,
        "shape_keys": shape_keys,
    }


def capture_receiver_start_state(scene):
    armatures = []
    faces = []
    seen = set()

    for prop_name in ("vmc_link_preview_armature", "vmc_link_armature"):
        arm_obj = getattr(scene, prop_name, None)
        if not mapping.has_pose_bones(arm_obj):
            continue
        key = arm_obj.as_pointer()
        if key in seen:
            continue
        seen.add(key)
        snapshot = _capture_armature_state(arm_obj)
        if snapshot is not None:
            armatures.append(snapshot)

    for prop_name in ("vmc_link_preview_face_object", "vmc_link_face_object"):
        face_obj = getattr(scene, prop_name, None)
        if not mapping.has_shape_keys(face_obj):
            continue
        key = face_obj.as_pointer()
        if key in seen:
            continue
        seen.add(key)
        snapshot = _capture_face_state(face_obj)
        if snapshot is not None:
            faces.append(snapshot)

    state.receiver_armature_snapshots = armatures
    state.receiver_face_snapshots = faces
    mapping_arp.prepare_receiver_session(scene)
    bpy.context.view_layer.update()
    state.receiver_target_context = _build_receiver_target_context(scene)
    state.receiver_session_active = True
    state.receiver_paused = False


def restore_receiver_start_state():
    for armature_snapshot in state.receiver_armature_snapshots:
        arm_obj = armature_snapshot.get("object")
        if arm_obj is None or getattr(arm_obj, "type", None) != "ARMATURE" or getattr(arm_obj, "pose", None) is None:
            continue

        mapping_arp.restore_session_state(arm_obj, armature_snapshot.get("arp_state"))
        _restore_transform_state(arm_obj, armature_snapshot.get("object_state"))
        for bone_name, bone_snapshot in armature_snapshot.get("pose_bones", {}).items():
            pose_bone = arm_obj.pose.bones.get(bone_name)
            if pose_bone is None:
                continue
            _restore_transform_state(pose_bone, bone_snapshot)

    for face_snapshot in state.receiver_face_snapshots:
        face_obj = face_snapshot.get("object")
        if not mapping.has_shape_keys(face_obj):
            continue

        key_blocks = face_obj.data.shape_keys.key_blocks
        for key_name, key_value in face_snapshot.get("shape_keys", {}).items():
            key_block = key_blocks.get(key_name)
            if key_block is None:
                continue
            if abs(float(key_block.value) - float(key_value)) > constants.SHAPE_EPS:
                key_block.value = float(key_value)

    tag_view3d_ui_redraw()


def _build_receiver_target_context(scene):
    arm_obj = getattr(scene, "vmc_link_armature", None)
    preview_arm = getattr(scene, "vmc_link_preview_armature", None)
    context = {
        "target": arm_obj,
        "preview": preview_arm,
        "target_start_world": arm_obj.matrix_world.copy() if arm_obj is not None else None,
        "root_source": None,
        "root_baseline_location": None,
        "root_baseline_rotation": None,
        "is_arp": False,
        "preview_start_matrices": {},
        "target_start_matrices": {},
        "preview_start_rotations": {},
        "target_start_rotations": {},
        "preview_start_basis_rotations": {},
        "target_start_basis_rotations": {},
        "arp_rotation_calibrations": {},
        "arp_filtered_source_rotations": {},
        "arp_filtered_rotations": {},
        "arp_runtime_entries": (),
    }

    analysis = mapping_arp.analyze_armature(arm_obj)
    if not analysis["is_arp"] or not mapping.has_pose_bones(preview_arm):
        return context

    runtime_map = mapping_arp.build_runtime_mapping(scene, arm_obj)
    context["is_arp"] = True
    for source_name, target_name in runtime_map.items():
        source_bone = preview_arm.pose.bones.get(source_name)
        target_bone = arm_obj.pose.bones.get(target_name)
        if source_bone is None or target_bone is None:
            continue
        context["preview_start_matrices"][source_name] = source_bone.matrix.copy()
        context["target_start_matrices"][target_name] = target_bone.matrix.copy()
        source_start_rotation = source_bone.matrix.to_quaternion()
        target_start_rotation = target_bone.matrix.to_quaternion()
        source_start_rotation.normalize()
        target_start_rotation.normalize()
        context["preview_start_rotations"][source_name] = source_start_rotation.copy()
        context["target_start_rotations"][target_name] = target_start_rotation.copy()
        source_start_basis_rotation = source_bone.matrix_basis.to_quaternion()
        target_start_basis_rotation = target_bone.matrix_basis.to_quaternion()
        source_start_basis_rotation.normalize()
        target_start_basis_rotation.normalize()
        context["preview_start_basis_rotations"][source_name] = source_start_basis_rotation.copy()
        context["target_start_basis_rotations"][target_name] = target_start_basis_rotation.copy()
        source_axis = source_start_rotation @ Vector((0.0, 1.0, 0.0))
        target_axis = target_start_rotation @ Vector((0.0, 1.0, 0.0))
        target_to_source_axis = target_axis.rotation_difference(source_axis)
        aligned_target_rotation = target_to_source_axis @ target_start_rotation
        calibration = source_start_rotation.inverted() @ aligned_target_rotation
        calibration.normalize()
        context["arp_rotation_calibrations"][source_name] = calibration
    context["arp_runtime_entries"] = tuple(
        (
            source_name,
            target_name,
            preview_arm.pose.bones.get(source_name),
            arm_obj.pose.bones.get(target_name),
            context["arp_rotation_calibrations"].get(source_name),
        )
        for source_name, target_name in runtime_map.items()
    )
    return context


def _ensure_receiver_target_context(scene, arm_obj, preview_arm):
    context = state.receiver_target_context
    if context.get("target") is arm_obj and context.get("preview") is preview_arm:
        return context
    context = _build_receiver_target_context(scene)
    state.receiver_target_context = context
    return context


def _apply_target_root_motion(arm_obj, root, waist, context):
    if arm_obj is None or context.get("target_start_world") is None:
        return

    source_name = None
    raw = None
    if root is not None:
        source_name = "Root/Pos"
        raw = root
    elif waist is not None:
        source_name = "Tra/Pos"
        raw = waist
    if raw is None:
        return

    current_location, current_rotation = helpers.convert_vmc_pose(*raw)
    if context.get("root_source") != source_name:
        context["root_source"] = source_name
        context["root_baseline_location"] = current_location.copy()
        context["root_baseline_rotation"] = current_rotation.copy()

    baseline_location = context["root_baseline_location"]
    baseline_rotation = context["root_baseline_rotation"]
    delta_location = current_location - baseline_location
    delta_rotation = current_rotation @ baseline_rotation.inverted()
    delta_rotation.normalize()

    start_location, start_rotation, start_scale = context["target_start_world"].decompose()
    desired_world = Matrix.LocRotScale(
        start_location + delta_location,
        delta_rotation @ start_rotation,
        start_scale,
    )
    if arm_obj.matrix_world != desired_world:
        arm_obj.matrix_world = desired_world


def _apply_arp_target_armature(scene, arm_obj, preview_arm, context):
    driven_bones = set()
    source_pose_matrices = {}
    target_pose_matrices = {}
    desired_target_matrices = {}
    entries_by_source = {
        source_name: (target_name, source_bone, target_bone, calibration)
        for source_name, target_name, source_bone, target_bone, calibration in context["arp_runtime_entries"]
    }

    for source_group in mapping_arp.ARP_RUNTIME_SOURCE_GROUPS:
        for source_name in source_group:
            entry = entries_by_source.get(source_name)
            if entry is None:
                continue
            target_name, source_bone, target_bone, calibration = entry
            if source_bone is None or target_bone is None or calibration is None:
                continue

            if mapping_arp.uses_local_basis_delta(source_name):
                if _apply_arp_local_basis_delta(source_name, target_name, source_bone, target_bone, context):
                    driven_bones.add(target_name)
                continue

            source_matrix = _calculate_pose_matrix(source_bone, source_pose_matrices)
            source_rotation = source_matrix.to_quaternion()
            source_rotation.normalize()
            source_rotation = _filter_arp_source_rotation(source_name, source_rotation, context)
            if mapping_arp.uses_delta_rotation(source_name):
                source_start_rotation = context["preview_start_rotations"].get(source_name)
                target_start_rotation = context["target_start_rotations"].get(target_name)
                if source_start_rotation is None or target_start_rotation is None:
                    continue
                source_delta = source_rotation @ source_start_rotation.inverted()
                source_delta.normalize()
                desired_rotation = source_delta @ target_start_rotation
            else:
                desired_rotation = source_rotation @ calibration
            desired_rotation.normalize()
            start_matrix = context["target_start_matrices"].get(target_name) or target_bone.matrix.copy()
            desired_matrix = Matrix.LocRotScale(
                start_matrix.to_translation(),
                desired_rotation,
                start_matrix.to_scale(),
            )
            parent_bone = target_bone.parent
            parent_matrix = None
            if parent_bone is None:
                basis_matrix = target_bone.bone.convert_local_to_pose(
                    desired_matrix,
                    target_bone.bone.matrix_local,
                    invert=True,
                )
            else:
                parent_matrix = _calculate_arp_target_pose_matrix(parent_bone, target_pose_matrices, desired_target_matrices, arm_obj)
                basis_matrix = target_bone.bone.convert_local_to_pose(
                    desired_matrix,
                    target_bone.bone.matrix_local,
                    parent_matrix=parent_matrix,
                    parent_matrix_local=parent_bone.bone.matrix_local,
                    invert=True,
                )

            basis_rotation = basis_matrix.to_quaternion()
            basis_rotation.normalize()
            basis_rotation = _filter_arp_basis_rotation(target_name, basis_rotation, context)
            filtered_basis_matrix = Matrix.LocRotScale(
                basis_matrix.to_translation(),
                basis_rotation,
                basis_matrix.to_scale(),
            )
            if parent_bone is None:
                effective_matrix = target_bone.bone.convert_local_to_pose(
                    filtered_basis_matrix,
                    target_bone.bone.matrix_local,
                )
            else:
                effective_matrix = target_bone.bone.convert_local_to_pose(
                    filtered_basis_matrix,
                    target_bone.bone.matrix_local,
                    parent_matrix=parent_matrix,
                    parent_matrix_local=parent_bone.bone.matrix_local,
                )
            desired_target_matrices[target_name] = _apply_arp_copy_location_matrix(
                target_bone,
                effective_matrix,
                desired_target_matrices,
                arm_obj,
            )
            current_rotation = (
                target_bone.rotation_quaternion.copy()
                if target_bone.rotation_mode == "QUATERNION"
                else target_bone.matrix_basis.to_quaternion()
            )
            if not helpers.quat_changed(current_rotation, basis_rotation):
                continue
            if target_bone.rotation_mode == "QUATERNION":
                target_bone.rotation_quaternion = basis_rotation
            else:
                target_bone.rotation_euler = basis_rotation.to_euler(target_bone.rotation_mode, target_bone.rotation_euler)
            driven_bones.add(target_name)

    return driven_bones


def _apply_arp_local_basis_delta(source_name: str, target_name: str, source_bone, target_bone, context) -> bool:
    source_start_rotation = context["preview_start_basis_rotations"].get(source_name)
    target_start_rotation = context["target_start_basis_rotations"].get(target_name)
    if source_start_rotation is None or target_start_rotation is None:
        return False

    source_rotation = source_bone.matrix_basis.to_quaternion()
    source_rotation.normalize()
    source_delta = source_rotation @ source_start_rotation.inverted()
    source_delta.normalize()
    if mapping_arp.uses_rest_axis_remap(source_name):
        source_delta = _remap_local_delta_between_rest_axes(source_bone, target_bone, source_delta)

    desired_rotation = source_delta @ target_start_rotation
    desired_rotation.normalize()
    desired_rotation = _filter_arp_basis_rotation(target_name, desired_rotation, context)

    current_rotation = (
        target_bone.rotation_quaternion.copy()
        if target_bone.rotation_mode == "QUATERNION"
        else target_bone.matrix_basis.to_quaternion()
    )
    current_rotation.normalize()
    if not helpers.quat_changed(current_rotation, desired_rotation):
        return False

    if target_bone.rotation_mode == "QUATERNION":
        target_bone.rotation_quaternion = desired_rotation
    else:
        target_bone.rotation_euler = desired_rotation.to_euler(target_bone.rotation_mode, target_bone.rotation_euler)
    return True


def _remap_local_delta_between_rest_axes(source_bone, target_bone, source_delta):
    source_rest = source_bone.bone.matrix_local.to_quaternion()
    target_rest = target_bone.bone.matrix_local.to_quaternion()
    source_rest.normalize()
    target_rest.normalize()

    world_delta = source_rest @ source_delta @ source_rest.inverted()
    world_delta.normalize()
    target_delta = target_rest.inverted() @ world_delta @ target_rest
    target_delta.normalize()
    return target_delta


def _quat_angle_degrees(a, b) -> float:
    dot = max(-1.0, min(1.0, abs(a.dot(b))))
    return 2.0 * math.degrees(math.acos(dot))


def _filter_arp_basis_rotation(target_name: str, desired_rotation, context):
    filtered_rotations = context.setdefault("arp_filtered_rotations", {})
    return _filter_arp_rotation(filtered_rotations, target_name, desired_rotation)


def _filter_arp_source_rotation(source_name: str, desired_rotation, context):
    filtered_rotations = context.setdefault("arp_filtered_source_rotations", {})
    return _filter_arp_rotation(filtered_rotations, source_name, desired_rotation)


def _filter_arp_rotation(filtered_rotations, key: str, desired_rotation):
    previous = filtered_rotations.get(key)
    if previous is None:
        filtered_rotations[key] = desired_rotation.copy()
        return desired_rotation

    angle = _quat_angle_degrees(previous, desired_rotation)
    if angle <= constants.ARP_ROTATION_FILTER_DEADBAND_DEG:
        return previous.copy()
    if angle >= constants.ARP_ROTATION_FILTER_FAST_ANGLE_DEG:
        filtered_rotations[key] = desired_rotation.copy()
        return desired_rotation

    t = angle / constants.ARP_ROTATION_FILTER_FAST_ANGLE_DEG
    alpha = constants.ARP_ROTATION_FILTER_MIN_ALPHA + (1.0 - constants.ARP_ROTATION_FILTER_MIN_ALPHA) * t
    filtered = previous.slerp(desired_rotation, alpha)
    filtered.normalize()
    filtered_rotations[key] = filtered.copy()
    return filtered


def _calculate_arp_target_pose_matrix(pose_bone, cache, desired_matrices, arm_obj):
    cached = cache.get(pose_bone.name)
    if cached is not None:
        return cached

    desired_matrix = desired_matrices.get(pose_bone.name)
    if desired_matrix is not None:
        cache[pose_bone.name] = desired_matrix
        return desired_matrix

    copied_matrix = _resolve_arp_copy_transforms_matrix(pose_bone, desired_matrices, arm_obj)
    if copied_matrix is not None:
        cache[pose_bone.name] = copied_matrix
        return copied_matrix

    child_of_matrix = _resolve_arp_child_of_matrix(pose_bone, desired_matrices, arm_obj)
    if child_of_matrix is not None:
        cache[pose_bone.name] = _apply_arp_copy_location_matrix(
            pose_bone,
            child_of_matrix,
            desired_matrices,
            arm_obj,
        )
        return cache[pose_bone.name]

    parent_bone = pose_bone.parent
    if parent_bone is None:
        matrix = pose_bone.bone.convert_local_to_pose(
            pose_bone.matrix_basis,
            pose_bone.bone.matrix_local,
        )
    else:
        matrix = pose_bone.bone.convert_local_to_pose(
            pose_bone.matrix_basis,
            pose_bone.bone.matrix_local,
            parent_matrix=_calculate_arp_target_pose_matrix(parent_bone, cache, desired_matrices, arm_obj),
            parent_matrix_local=parent_bone.bone.matrix_local,
        )
    cache[pose_bone.name] = _apply_arp_copy_location_matrix(pose_bone, matrix, desired_matrices, arm_obj)
    return cache[pose_bone.name]


def _resolve_arp_copy_transforms_matrix(pose_bone, desired_matrices, arm_obj):
    for constraint in pose_bone.constraints:
        if constraint.type != "COPY_TRANSFORMS" or constraint.mute or float(constraint.influence) <= 0.0:
            continue
        if getattr(constraint, "target", None) is not arm_obj:
            continue
        subtarget = str(getattr(constraint, "subtarget", "")).strip()
        if not subtarget:
            continue
        desired_matrix = desired_matrices.get(subtarget)
        if desired_matrix is not None:
            return desired_matrix
    return None


def _resolve_arp_child_of_matrix(pose_bone, desired_matrices, arm_obj):
    for constraint in pose_bone.constraints:
        if constraint.type != "CHILD_OF" or constraint.mute or float(constraint.influence) <= 0.0:
            continue
        if getattr(constraint, "target", None) is not arm_obj:
            continue
        subtarget = str(getattr(constraint, "subtarget", "")).strip()
        if not subtarget:
            continue
        desired_matrix = desired_matrices.get(subtarget)
        if desired_matrix is not None and float(constraint.influence) >= 0.999:
            return desired_matrix
    return None


def _apply_arp_copy_location_matrix(pose_bone, matrix, desired_matrices, arm_obj):
    location = matrix.to_translation()
    changed = False
    for constraint in pose_bone.constraints:
        if constraint.type != "COPY_LOCATION" or constraint.mute or float(constraint.influence) <= 0.0:
            continue
        if getattr(constraint, "target", None) is not arm_obj:
            continue
        subtarget = str(getattr(constraint, "subtarget", "")).strip()
        if not subtarget:
            continue
        target_matrix = desired_matrices.get(subtarget)
        if target_matrix is None:
            continue
        target_location = target_matrix.to_translation()
        influence = max(0.0, min(1.0, float(constraint.influence)))
        if bool(getattr(constraint, "use_x", True)):
            location.x = location.x + (target_location.x - location.x) * influence
            changed = True
        if bool(getattr(constraint, "use_y", True)):
            location.y = location.y + (target_location.y - location.y) * influence
            changed = True
        if bool(getattr(constraint, "use_z", True)):
            location.z = location.z + (target_location.z - location.z) * influence
            changed = True
    if not changed:
        return matrix
    return Matrix.LocRotScale(location, matrix.to_quaternion(), matrix.to_scale())


def _calculate_pose_matrix(pose_bone, cache):
    cached = cache.get(pose_bone.name)
    if cached is not None:
        return cached

    parent_bone = pose_bone.parent
    if parent_bone is None:
        matrix = pose_bone.bone.convert_local_to_pose(
            pose_bone.matrix_basis,
            pose_bone.bone.matrix_local,
        )
    else:
        matrix = pose_bone.bone.convert_local_to_pose(
            pose_bone.matrix_basis,
            pose_bone.bone.matrix_local,
            parent_matrix=_calculate_pose_matrix(parent_bone, cache),
            parent_matrix_local=parent_bone.bone.matrix_local,
        )
    cache[pose_bone.name] = matrix
    return matrix


def clear_receiver_session_state():
    state.reset_receiver_session_state()


def tag_view3d_ui_redraw():
    window_manager = getattr(bpy.context, "window_manager", None)
    if window_manager is None:
        return

    # Avoid forcing full viewport redraw on every receiver tick.
    for window in getattr(window_manager, "windows", []):
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for region in area.regions:
                if region.type == "UI":
                    region.tag_redraw()


def tag_view3d_ui_redraw_if_due(now: float, force: bool = False, interval: float = 0.1):
    if not force and now < state.next_ui_redraw_ts:
        return
    state.next_ui_redraw_ts = now + interval
    tag_view3d_ui_redraw()


def _ensure_preview_cache_targets(preview_arm, preview_face):
    if preview_arm is not state.preview_armature_ref:
        state.preview_armature_ref = preview_arm
        state.preview_cached_bone_map = {}

    if preview_face is not state.preview_face_ref:
        state.preview_face_ref = preview_face
        state.preview_cached_arkit_blend_map = {}


def draw_preview_entries(layout, title: str, entries, empty_text: str):
    box = layout.box()
    col = box.column(align=True)
    col.label(text=title)
    if not entries:
        col.label(text=empty_text, icon="INFO")
        return
    for entry in entries:
        col.label(text=entry)


def record_current_sample(scene, arm, driven_bones, face, driven_shapes):
    recorded_any = False

    if arm is not None:
        try:
            arm.keyframe_insert(data_path="location")
            if arm.rotation_mode == "QUATERNION":
                arm.keyframe_insert(data_path="rotation_quaternion")
            else:
                arm.keyframe_insert(data_path="rotation_euler")
            recorded_any = True
        except Exception as exc:
            helpers.debug(f"Failed to keyframe armature root: {exc}")

        pose = arm.pose.bones if getattr(arm, "pose", None) is not None else None
        if pose is not None:
            for bone_name in driven_bones:
                pose_bone = pose.get(bone_name)
                if pose_bone is None:
                    continue
                try:
                    if pose_bone.rotation_mode == "QUATERNION":
                        pose_bone.keyframe_insert(data_path="rotation_quaternion")
                    else:
                        pose_bone.keyframe_insert(data_path="rotation_euler")
                    recorded_any = True
                except Exception as exc:
                    helpers.debug(f"Failed to keyframe bone '{bone_name}': {exc}")

    if mapping.has_shape_keys(face):
        blocks = face.data.shape_keys.key_blocks
        for key_name in driven_shapes:
            key_block = blocks.get(key_name)
            if key_block is None:
                continue
            try:
                key_block.keyframe_insert(data_path="value")
                recorded_any = True
            except Exception as exc:
                helpers.debug(f"Failed to keyframe shape key '{key_name}': {exc}")

    if recorded_any and not bpy.context.screen.is_animation_playing:
        scene.frame_set(scene.frame_current + 1)


def _apply_preview_armature(preview_arm, root, waist, bones, blends):
    if preview_arm is None or getattr(preview_arm, "type", None) != "ARMATURE":
        return

    hips_pose = mapping.get_vmc_bone_pose(bones, "Hips")

    if root is not None:
        root_loc, _ = helpers.convert_vmc_pose(*root)
        if helpers.vec_changed(preview_arm.location, root_loc):
            preview_arm.location = root_loc
    elif waist is not None:
        waist_loc, _ = helpers.convert_vmc_pose(*waist)
        if helpers.vec_changed(preview_arm.location, waist_loc):
            preview_arm.location = waist_loc
    elif hips_pose is not None:
        hips_loc, _ = helpers.convert_vmc_pose(*hips_pose)
        if helpers.vec_changed(preview_arm.location, hips_loc):
            preview_arm.location = hips_loc

    if root is not None:
        _, root_quat = helpers.convert_vmc_pose(*root)
        preview_arm.rotation_mode = "QUATERNION"
        if helpers.quat_changed(preview_arm.rotation_quaternion, root_quat):
            preview_arm.rotation_quaternion = root_quat

    pose = preview_arm.pose.bones
    eye_left_name = state.preview_cached_bone_map.get("LeftEye") or mapping.find_bone_name(preview_arm, "LeftEye", None)
    eye_right_name = state.preview_cached_bone_map.get("RightEye") or mapping.find_bone_name(preview_arm, "RightEye", None)
    if eye_left_name:
        state.preview_cached_bone_map["LeftEye"] = eye_left_name
    if eye_right_name:
        state.preview_cached_bone_map["RightEye"] = eye_right_name
    eye_left_driven_by_bone = False
    eye_right_driven_by_bone = False

    for vmc_name, raw in bones.items():
        actual = state.preview_cached_bone_map.get(vmc_name) or mapping.find_bone_name(preview_arm, vmc_name, None)
        if not actual or actual not in pose:
            continue
        state.preview_cached_bone_map[vmc_name] = actual

        pose_bone = pose[actual]
        px, py, pz, qx, qy, qz, qw = raw
        _, rotate_quat = helpers.convert_vmc_pose(px, py, pz, qx, qy, qz, qw)
        parent_quat = pose_bone.bone.matrix_local.to_quaternion()
        local_q = parent_quat.inverted() @ rotate_quat @ parent_quat
        local_q.normalize()

        pose_bone.rotation_mode = "QUATERNION"
        if helpers.quat_changed(pose_bone.rotation_quaternion, local_q):
            pose_bone.rotation_quaternion = local_q

        if eye_left_name and actual == eye_left_name:
            eye_left_driven_by_bone = True
        if eye_right_name and actual == eye_right_name:
            eye_right_driven_by_bone = True

    if blends:
        if eye_left_name and eye_left_name in pose and not eye_left_driven_by_bone:
            left_h = (mapping.get_blend_value(blends, "LookRight_L") or mapping.get_blend_value(blends, "LookRight")) - (
                mapping.get_blend_value(blends, "LookLeft_L") or mapping.get_blend_value(blends, "LookLeft")
            )
            left_v = (mapping.get_blend_value(blends, "LookUp_L") or mapping.get_blend_value(blends, "LookUp")) - (
                mapping.get_blend_value(blends, "LookDown_L") or mapping.get_blend_value(blends, "LookDown")
            )
            mapping.apply_eye_look_to_eye_bone(pose[eye_left_name], left_h, left_v)

        if eye_right_name and eye_right_name in pose and not eye_right_driven_by_bone:
            right_h = (mapping.get_blend_value(blends, "LookRight_R") or mapping.get_blend_value(blends, "LookRight")) - (
                mapping.get_blend_value(blends, "LookLeft_R") or mapping.get_blend_value(blends, "LookLeft")
            )
            right_v = (mapping.get_blend_value(blends, "LookUp_R") or mapping.get_blend_value(blends, "LookUp")) - (
                mapping.get_blend_value(blends, "LookDown_R") or mapping.get_blend_value(blends, "LookDown")
            )
            mapping.apply_eye_look_to_eye_bone(pose[eye_right_name], right_h, right_v)


def _apply_preview_face(preview_face, arkit_blends):
    if not mapping.has_shape_keys(preview_face):
        return

    blocks = preview_face.data.shape_keys.key_blocks
    for arkit_name, val in arkit_blends.items():
        actual = state.preview_cached_arkit_blend_map.get(arkit_name) or mapping.find_arkit_shapekey_name(preview_face, arkit_name, None)
        if not actual or actual not in blocks:
            continue
        state.preview_cached_arkit_blend_map[arkit_name] = actual
        try:
            numeric_val = float(val)
        except (TypeError, ValueError):
            continue
        if abs(blocks[actual].value - numeric_val) > constants.SHAPE_EPS:
            blocks[actual].value = numeric_val


def apply_timer():
    if state.receiver_socket is None and state.arkit_receiver_socket is None:
        return None

    scene = getattr(bpy.context, "scene", None)
    if scene is None or not hasattr(scene, "vmc_link_rate_hz"):
        return 0.1

    rate = 1.0 / max(1, scene.vmc_link_rate_hz)
    now = time.time()
    if state.next_tick_ts == 0.0:
        state.next_tick_ts = now

    remaining = state.next_tick_ts - now
    if remaining > 0.0:
        return min(rate, remaining)

    state.next_tick_ts = now + rate

    preview_arm = getattr(scene, "vmc_link_preview_armature", None)
    preview_face = getattr(scene, "vmc_link_preview_face_object", None)
    arm = getattr(scene, "vmc_link_armature", None)
    face = getattr(scene, "vmc_link_face_object", None)
    live_preview = bool(getattr(scene, "vmc_link_live_preview", True))
    use_arkit_face = is_arkit_face_source_enabled(scene)

    if arm is preview_arm:
        arm = None
    if face is preview_face:
        face = None

    if preview_arm is None and preview_face is None and arm is None and face is None:
        return rate
    if not state.dirty:
        state.frame_snapshot_deadline_ts = 0.0
        tag_view3d_ui_redraw_if_due(now)
        return rate

    latest_packet_ts = max(state.last_packet_ts, state.arkit_last_packet_ts if use_arkit_face else 0.0)
    quiet_remaining = constants.RECEIVER_FRAME_QUIET_WINDOW_SEC - (now - latest_packet_ts)
    if latest_packet_ts > 0.0 and quiet_remaining > 0.0:
        if state.frame_snapshot_deadline_ts == 0.0:
            state.frame_snapshot_deadline_ts = now + constants.RECEIVER_FRAME_MAX_DEFER_SEC
        if now < state.frame_snapshot_deadline_ts:
            delay = min(rate, max(0.001, quiet_remaining))
            state.next_tick_ts = now + delay
            return delay
    state.frame_snapshot_deadline_ts = 0.0

    with state.buffer_lock:
        root = state.root_buf
        waist = state.waist_buf
        bones = mapping.canonicalize_vmc_bones(state.bone_buf)
        blends = dict(state.blend_buf)
        arkit_blends = dict(state.arkit_blend_buf)
        state.dirty = False
    _ensure_preview_cache_targets(preview_arm, preview_face)

    _apply_preview_armature(preview_arm, root, waist, bones, blends)
    if use_arkit_face:
        _apply_preview_face(preview_face, arkit_blends)

    tag_view3d_ui_redraw_if_due(now)

    if not live_preview:
        return rate

    if arm is not None and not state.cached_bone_map:
        mapping.rebuild_maps(scene)

    if (not use_arkit_face) and face is not None and not state.cached_blend_map:
        mapping.rebuild_maps(scene)
    elif use_arkit_face and face is not None and not state.cached_arkit_blend_map:
        mapping.rebuild_maps(scene)

    driven_bones = set()
    driven_shapes = set()

    if arm is not None:
        target_context = _ensure_receiver_target_context(scene, arm, preview_arm)
        _apply_target_root_motion(arm, root, waist, target_context)

        if target_context.get("is_arp") and mapping.has_pose_bones(preview_arm):
            driven_bones.update(_apply_arp_target_armature(scene, arm, preview_arm, target_context))
        else:
            pose = arm.pose.bones
            eye_left_name = state.cached_bone_map.get("LeftEye") or mapping.find_bone_name(arm, "LeftEye", scene)
            eye_right_name = state.cached_bone_map.get("RightEye") or mapping.find_bone_name(arm, "RightEye", scene)
            if eye_left_name:
                state.cached_bone_map["LeftEye"] = eye_left_name
            if eye_right_name:
                state.cached_bone_map["RightEye"] = eye_right_name

            eye_left_driven_by_bone = False
            eye_right_driven_by_bone = False

            for vmc_name, raw in bones.items():
                actual = state.cached_bone_map.get(vmc_name) or mapping.find_bone_name(arm, vmc_name, scene)
                if not actual or actual not in pose:
                    continue

                state.cached_bone_map[vmc_name] = actual
                pose_bone = pose[actual]
                px, py, pz, qx, qy, qz, qw = raw
                _, rotate_quat = helpers.convert_vmc_pose(px, py, pz, qx, qy, qz, qw)
                parent_quat = pose_bone.bone.matrix_local.to_quaternion()
                local_q = parent_quat.inverted() @ rotate_quat @ parent_quat
                local_q.normalize()

                pose_bone.rotation_mode = "QUATERNION"
                if helpers.quat_changed(pose_bone.rotation_quaternion, local_q):
                    pose_bone.rotation_quaternion = local_q
                    driven_bones.add(actual)

                if eye_left_name and actual == eye_left_name:
                    eye_left_driven_by_bone = True
                if eye_right_name and actual == eye_right_name:
                    eye_right_driven_by_bone = True

            if blends:
                if eye_left_name and eye_left_name in pose and not eye_left_driven_by_bone:
                    left_h = (mapping.get_blend_value(blends, "LookRight_L") or mapping.get_blend_value(blends, "LookRight")) - (
                        mapping.get_blend_value(blends, "LookLeft_L") or mapping.get_blend_value(blends, "LookLeft")
                    )
                    left_v = (mapping.get_blend_value(blends, "LookUp_L") or mapping.get_blend_value(blends, "LookUp")) - (
                        mapping.get_blend_value(blends, "LookDown_L") or mapping.get_blend_value(blends, "LookDown")
                    )
                    eye_pose_bone = pose[eye_left_name]
                    old_q = eye_pose_bone.rotation_quaternion.copy()
                    mapping.apply_eye_look_to_eye_bone(eye_pose_bone, left_h, left_v)
                    if helpers.quat_changed(old_q, eye_pose_bone.rotation_quaternion):
                        driven_bones.add(eye_left_name)

                if eye_right_name and eye_right_name in pose and not eye_right_driven_by_bone:
                    right_h = (mapping.get_blend_value(blends, "LookRight_R") or mapping.get_blend_value(blends, "LookRight")) - (
                        mapping.get_blend_value(blends, "LookLeft_R") or mapping.get_blend_value(blends, "LookLeft")
                    )
                    right_v = (mapping.get_blend_value(blends, "LookUp_R") or mapping.get_blend_value(blends, "LookUp")) - (
                        mapping.get_blend_value(blends, "LookDown_R") or mapping.get_blend_value(blends, "LookDown")
                    )
                    eye_pose_bone = pose[eye_right_name]
                    old_q = eye_pose_bone.rotation_quaternion.copy()
                    mapping.apply_eye_look_to_eye_bone(eye_pose_bone, right_h, right_v)
                    if helpers.quat_changed(old_q, eye_pose_bone.rotation_quaternion):
                        driven_bones.add(eye_right_name)

    if (not use_arkit_face) and mapping.has_shape_keys(face):
        blocks = face.data.shape_keys.key_blocks
        for vmc_name, val in blends.items():
            actual = state.cached_blend_map.get(vmc_name) or mapping.find_shapekey_name(face, vmc_name, scene)
            if not actual or actual not in blocks:
                continue
            state.cached_blend_map[vmc_name] = actual
            if abs(blocks[actual].value - val) > constants.SHAPE_EPS:
                blocks[actual].value = val
                driven_shapes.add(actual)
    elif mapping.has_shape_keys(face):
        blocks = face.data.shape_keys.key_blocks
        for arkit_name, val in arkit_blends.items():
            actual = state.cached_arkit_blend_map.get(arkit_name) or mapping.find_arkit_shapekey_name(face, arkit_name, scene)
            if not actual or actual not in blocks:
                continue
            state.cached_arkit_blend_map[arkit_name] = actual
            try:
                numeric_val = float(val)
            except (TypeError, ValueError):
                continue
            if abs(blocks[actual].value - numeric_val) > constants.SHAPE_EPS:
                blocks[actual].value = numeric_val
                driven_shapes.add(actual)

    if state.recording:
        record_current_sample(scene, arm, driven_bones, face, driven_shapes)

    return rate
