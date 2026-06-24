import math
import time

import bpy
from mathutils import Matrix, Quaternion, Vector

from ..core import constants, helpers, state
from ..mapping import arp as mapping_arp
from ..mapping import mapper as mapping
from . import network, properties


def is_recording() -> bool:
    return state.recording


def get_recording_sample_count() -> int:
    return int(state.recording_sample_count)


def get_recording_start_frame(scene=None) -> int:
    if state.recording and state.recording_start_frame is not None:
        return int(state.recording_start_frame)
    scene = scene or getattr(bpy.context, "scene", None)
    return int(getattr(scene, "vmc_link_record_start_frame", 1)) if scene is not None else 1


def get_recording_end_frame(scene=None) -> int:
    if state.recording and state.recording_end_frame is not None:
        return int(state.recording_end_frame)
    scene = scene or getattr(bpy.context, "scene", None)
    return int(getattr(scene, "vmc_link_record_end_frame", get_recording_start_frame(scene))) if scene is not None else 1


def is_recording_transition_enabled(scene=None) -> bool:
    if state.recording:
        return bool(state.recording_transition_enabled)
    scene = scene or getattr(bpy.context, "scene", None)
    return bool(getattr(scene, "vmc_link_record_transition_enabled", True)) if scene is not None else True


def get_recording_transition_frames(scene=None) -> int:
    if state.recording:
        return int(state.recording_transition_frames)
    scene = scene or getattr(bpy.context, "scene", None)
    return int(getattr(scene, "vmc_link_record_transition_frames", 24)) if scene is not None else 24


def get_recording_range_error(scene) -> str:
    if scene is None:
        return "当前没有可用场景"
    frame_start = int(getattr(scene, "vmc_link_record_start_frame", 1))
    frame_end = int(getattr(scene, "vmc_link_record_end_frame", frame_start))
    if frame_end < frame_start:
        return "结束帧必须大于等于开始帧"
    if bool(getattr(scene, "vmc_link_record_transition_enabled", True)) and int(getattr(scene, "vmc_link_record_transition_frames", 24)) < 1:
        return "过渡帧数必须大于等于 1"
    return ""


def _current_recording_actions(scene):
    arm_action = state.recording_armature_action if state.recording else None
    face_action = state.recording_face_action if state.recording else None

    arm_obj = getattr(scene, "vmc_link_armature", None) if scene is not None else None
    if arm_action is None and mapping.has_pose_bones(arm_obj):
        animation_data = getattr(arm_obj, "animation_data", None)
        arm_action = getattr(animation_data, "action", None) if animation_data is not None else None

    face_obj = getattr(scene, "vmc_link_face_object", None) if scene is not None else None
    if face_action is None and mapping.has_shape_keys(face_obj):
        shape_keys = face_obj.data.shape_keys
        animation_data = getattr(shape_keys, "animation_data", None)
        face_action = getattr(animation_data, "action", None) if animation_data is not None else None

    return arm_action, face_action


def get_recording_action_labels(scene):
    arm_action, face_action = _current_recording_actions(scene)
    arm_obj = getattr(scene, "vmc_link_armature", None) if scene is not None else None
    face_obj = getattr(scene, "vmc_link_face_object", None) if scene is not None else None

    if mapping.has_pose_bones(arm_obj):
        arm_label = arm_action.name if arm_action is not None else "开始录制时自动创建"
    else:
        arm_label = "未绑定目标骨架"

    if mapping.has_shape_keys(face_obj):
        face_label = face_action.name if face_action is not None else "开始录制时自动创建"
    else:
        face_label = "未绑定目标面部"

    return {"armature": arm_label, "face": face_label}


def _validate_recording_config(scene):
    error = get_recording_range_error(scene)
    if error:
        raise RuntimeError(error)

    frame_start = int(getattr(scene, "vmc_link_record_start_frame", 1))
    frame_end = int(getattr(scene, "vmc_link_record_end_frame", frame_start))
    transition_enabled = bool(getattr(scene, "vmc_link_record_transition_enabled", True))
    transition_frames = int(getattr(scene, "vmc_link_record_transition_frames", 24))
    total_frames = max(1, frame_end - frame_start + 1)
    if transition_enabled:
        transition_frames = min(max(1, transition_frames), total_frames)
    else:
        transition_frames = 0

    return {
        "frame_start": frame_start,
        "frame_end": frame_end,
        "transition_enabled": transition_enabled and transition_frames > 0,
        "transition_frames": transition_frames,
    }


def start_recording(scene):
    if scene is None:
        raise RuntimeError("无法开始录制：当前没有可用场景")
    if state.recording:
        return
    if not bool(getattr(scene, "vmc_link_live_preview", True)):
        raise RuntimeError("请先开启“实时驱动目标对象”，录制只记录目标层结果")

    arm_obj = getattr(scene, "vmc_link_armature", None)
    face_obj = getattr(scene, "vmc_link_face_object", None)
    if not mapping.has_pose_bones(arm_obj) and not mapping.has_shape_keys(face_obj):
        raise RuntimeError("请先绑定目标骨架或目标面部")

    config = _validate_recording_config(scene)
    target_context = _build_receiver_target_context(scene) if mapping.has_pose_bones(arm_obj) else None
    record_bones = _recordable_target_bones(scene, arm_obj, target_context, set())
    record_shapes = _recordable_target_shapes(scene, face_obj, is_arkit_face_source_enabled(scene), set())
    transition_source_sample = _build_recording_sample(arm_obj, record_bones, face_obj, record_shapes, target_context)

    _prepare_recording_target_actions(arm_obj, face_obj)
    state.recording = True
    state.recording_start_frame = int(config["frame_start"])
    state.recording_end_frame = int(config["frame_end"])
    state.recording_frame = state.recording_start_frame
    state.recording_start_ts = time.perf_counter()
    state.recording_pause_started_ts = 0.0
    state.recording_paused_duration = 0.0
    state.recording_last_written_frame = state.recording_start_frame - 1
    state.recording_sample_count = 0
    state.recording_tracks = {}
    state.recording_last_sample = None
    state.recording_transition_enabled = bool(config["transition_enabled"])
    state.recording_transition_frames = int(config["transition_frames"])
    state.recording_transition_pending = bool(config["transition_enabled"])
    state.recording_transition_source_sample = transition_source_sample if config["transition_enabled"] else None
    state.recording_armature_ref = arm_obj if mapping.has_pose_bones(arm_obj) else None
    state.recording_face_ref = face_obj if mapping.has_shape_keys(face_obj) else None
    state.dirty = True


def stop_recording():
    written_frames = int(state.recording_sample_count)
    _bake_recording_tracks()
    if state.recording_armature_ref is not None and state.recording_armature_action is not None:
        arm = state.recording_armature_ref
        if getattr(arm, "type", None) == "ARMATURE":
            arm.animation_data_create()
            _bind_recorded_action(arm.animation_data, state.recording_armature_action, arm)
    if state.recording_face_ref is not None and state.recording_face_action is not None:
        face = state.recording_face_ref
        if mapping.has_shape_keys(face):
            shape_keys = face.data.shape_keys
            shape_keys.animation_data_create()
            _bind_recorded_action(shape_keys.animation_data, state.recording_face_action, shape_keys)
    state.recording = False
    state.recording_frame = None
    state.recording_start_frame = None
    state.recording_start_ts = 0.0
    state.recording_pause_started_ts = 0.0
    state.recording_paused_duration = 0.0
    state.recording_last_written_frame = None
    state.recording_end_frame = None
    state.recording_armature_ref = None
    state.recording_face_ref = None
    state.recording_armature_action = None
    state.recording_face_action = None
    state.recording_tracks = {}
    state.recording_last_sample = None
    state.recording_transition_enabled = False
    state.recording_transition_frames = 0
    state.recording_transition_pending = False
    state.recording_transition_source_sample = None
    state.recording_sample_count = 0
    return written_frames


def set_recording(value: bool, scene=None):
    if value:
        start_recording(scene or getattr(bpy.context, "scene", None))
    else:
        stop_recording()


def pause_recording_clock():
    if not state.recording or state.recording_pause_started_ts > 0.0:
        return
    state.recording_pause_started_ts = time.perf_counter()


def resume_recording_clock():
    if not state.recording or state.recording_pause_started_ts <= 0.0:
        return
    state.recording_paused_duration += time.perf_counter() - state.recording_pause_started_ts
    state.recording_pause_started_ts = 0.0


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
    bones = mapping.canonicalize_vmc_bones(state.bone_buf)
    source_name, raw = _select_root_motion_pose(state.root_buf, state.waist_buf, bones, include_hips=True)
    return source_name if raw is not None else "无"


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
    state.receiver_preview_context = _build_receiver_preview_context(scene)
    state.receiver_target_context = _build_receiver_target_context(scene)
    state.receiver_session_active = True
    state.receiver_paused = False


def _build_receiver_preview_context(scene):
    preview_arm = getattr(scene, "vmc_link_preview_armature", None)
    return {
        "preview": preview_arm,
        "preview_start_location": preview_arm.location.copy() if preview_arm is not None else None,
        "root_source": None,
        "root_baseline_location": None,
    }


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
        "arp_traj_bone": None,
        "arp_traj_start_location": None,
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
    if not analysis["is_arp"]:
        return context

    context["is_arp"] = True
    if mapping.has_pose_bones(arm_obj):
        traj_bone = arm_obj.pose.bones.get("c_traj")
        if traj_bone is not None:
            context["arp_traj_bone"] = traj_bone
            context["arp_traj_start_location"] = traj_bone.location.copy()

    if not mapping.has_pose_bones(preview_arm):
        return context

    runtime_map = mapping_arp.build_runtime_mapping(scene, arm_obj)
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


def _ensure_receiver_preview_context(scene, preview_arm):
    context = state.receiver_preview_context
    if context.get("preview") is preview_arm:
        return context
    context = _build_receiver_preview_context(scene)
    state.receiver_preview_context = context
    return context


def _root_motion_location(raw):
    if raw is None:
        return None
    location, _rotation = helpers.convert_vmc_pose(*raw)
    return location


def _root_motion_has_position(raw) -> bool:
    location = _root_motion_location(raw)
    return location is not None and location.length > constants.LOC_EPS


def _select_root_motion_pose(root, waist, bones, include_hips: bool):
    hips_pose = mapping.get_vmc_bone_pose(bones, "Hips") if include_hips else None
    if root is not None and (_root_motion_has_position(root) or hips_pose is None):
        return "Root/Pos", root
    if waist is not None and (_root_motion_has_position(waist) or hips_pose is None):
        return "Tra/Pos", waist
    if include_hips:
        if hips_pose is not None:
            return "Bone/Pos:Hips", hips_pose
    if root is not None:
        return "Root/Pos", root
    if waist is not None:
        return "Tra/Pos", waist
    return None, None


def _apply_target_root_motion(arm_obj, root, waist, bones, context, lock_to_center: bool):
    if arm_obj is None or context.get("target_start_world") is None:
        return set()

    if lock_to_center and context.get("is_arp"):
        context["root_source"] = None
        context["root_baseline_location"] = None
        context["root_baseline_rotation"] = None
        return _apply_arp_traj_root_motion(arm_obj, context, Vector((0.0, 0.0, 0.0)))

    source_name, raw = _select_root_motion_pose(root, waist, bones, include_hips=not lock_to_center)
    if raw is None:
        return set()

    current_location, current_rotation = helpers.convert_vmc_pose(*raw)
    if context.get("root_source") != source_name:
        context["root_source"] = source_name
        context["root_baseline_location"] = current_location.copy()
        context["root_baseline_rotation"] = current_rotation.copy()

    baseline_location = context["root_baseline_location"]
    baseline_rotation = context["root_baseline_rotation"]
    delta_location = current_location - baseline_location
    if source_name == "Bone/Pos:Hips":
        delta_rotation = Matrix.Identity(3).to_quaternion()
    else:
        delta_rotation = current_rotation @ baseline_rotation.inverted()
        delta_rotation.normalize()
    if lock_to_center:
        delta_location = Vector((0.0, 0.0, 0.0))

    if context.get("is_arp"):
        return _apply_arp_traj_root_motion(arm_obj, context, delta_location)

    start_location, start_rotation, start_scale = context["target_start_world"].decompose()
    desired_world = Matrix.LocRotScale(
        start_location + delta_location,
        delta_rotation @ start_rotation,
        start_scale,
    )
    if arm_obj.matrix_world != desired_world:
        arm_obj.matrix_world = desired_world
    return set()


def _apply_arp_traj_root_motion(arm_obj, context, delta_location):
    traj_bone = context.get("arp_traj_bone")
    start_location = context.get("arp_traj_start_location")
    if traj_bone is None or start_location is None:
        return set()

    local_delta = arm_obj.matrix_world.to_3x3().inverted() @ delta_location
    local_delta = Vector((-local_delta.x, -local_delta.y, local_delta.z))
    desired_location = start_location + local_delta
    if not helpers.vec_changed(traj_bone.location, desired_location):
        return set()

    traj_bone.location = desired_location
    return {"c_traj"}


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


def _prepare_recording_target_actions(arm, face):
    if mapping.has_pose_bones(arm):
        arm.animation_data_create()
        action = arm.animation_data.action
        if action is None:
            action = bpy.data.actions.new(f"{arm.name}_VMC_Link_Action")
        action.use_fake_user = True
        state.recording_armature_action = action
        arm.animation_data.action = None

    if mapping.has_shape_keys(face):
        shape_keys = face.data.shape_keys
        shape_keys.animation_data_create()
        action = shape_keys.animation_data.action
        if action is None:
            action = bpy.data.actions.new(f"{face.name}_VMC_Link_ShapeKeys")
        action.use_fake_user = True
        state.recording_face_action = action
        shape_keys.animation_data.action = None


def _bind_recorded_action(animation_data, action, datablock=None):
    animation_data.action = action
    if action is None or not hasattr(animation_data, "action_slot") or not hasattr(action, "slots"):
        return
    try:
        if animation_data.action_slot is not None:
            return
        if datablock is not None:
            for slot in getattr(action, "slots", []):
                if getattr(slot, "target_id_type", None) == getattr(datablock, "id_type", None):
                    animation_data.action_slot = slot
                    return
        if len(action.slots) > 0:
            animation_data.action_slot = action.slots[0]
    except Exception as exc:
        helpers.debug(f"Failed to bind recorded action slot: {exc}")


def _find_or_create_datablock_fcurve(action, datablock, data_path: str, array_index: int, group: str = None):
    if action is None or datablock is None or not hasattr(action, "slots"):
        return None

    target_id_type = getattr(datablock, "id_type", None)
    slot = None
    for item in action.slots:
        if getattr(item, "target_id_type", None) == target_id_type:
            slot = item
            break
    if slot is None:
        slot = action.slots.new(target_id_type, datablock.name)

    layer = action.layers[0] if len(action.layers) > 0 else action.layers.new("Layer")
    strip = layer.strips[0] if len(layer.strips) > 0 else layer.strips.new(type="KEYFRAME")

    channelbag = None
    for item in strip.channelbags:
        if getattr(item, "slot", None) == slot:
            channelbag = item
            break
    if channelbag is None:
        channelbag = strip.channelbags.new(slot)

    fcurve = channelbag.fcurves.find(data_path, index=array_index)
    if fcurve is None:
        fcurve = channelbag.fcurves.new(data_path, index=array_index, group_name=group or "")
    return fcurve


def _find_or_create_action_fcurve(action, data_path: str, array_index: int, group: str = None, datablock=None):
    if action is None:
        return None
    if datablock is None:
        fcurve = action.fcurves.find(data_path, index=array_index)
        if fcurve is None:
            fcurve = action.fcurves.new(data_path, index=array_index, action_group=group)
        return fcurve
    return _find_or_create_datablock_fcurve(action, datablock, data_path, array_index, group)


def _find_existing_datablock_fcurve(action, datablock, data_path: str, array_index: int):
    if action is None or datablock is None or not hasattr(action, "slots"):
        return None

    target_id_type = getattr(datablock, "id_type", None)
    for slot in getattr(action, "slots", []):
        if getattr(slot, "target_id_type", None) != target_id_type:
            continue
        for layer in getattr(action, "layers", []):
            for strip in getattr(layer, "strips", []):
                for channelbag in getattr(strip, "channelbags", []):
                    if getattr(channelbag, "slot", None) != slot:
                        continue
                    fcurve = channelbag.fcurves.find(data_path, index=array_index)
                    if fcurve is not None:
                        return fcurve
    return None


def _find_existing_action_fcurve(action, data_path: str, array_index: int, datablock=None):
    if action is None:
        return None
    if datablock is None:
        return action.fcurves.find(data_path, index=array_index)
    return _find_existing_datablock_fcurve(action, datablock, data_path, array_index)


def _recording_track_key(action, datablock, data_path: str, array_index: int):
    action_key = action.as_pointer() if action is not None and hasattr(action, "as_pointer") else 0
    datablock_key = datablock.as_pointer() if datablock is not None and hasattr(datablock, "as_pointer") else 0
    return (action_key, datablock_key, data_path, int(array_index))


def _cache_recording_key(action, data_path: str, array_index: int, frame: int, value: float, group: str = None, datablock=None):
    if action is None:
        return False
    key = _recording_track_key(action, datablock, data_path, array_index)
    track = state.recording_tracks.get(key)
    if track is None:
        track = {
            "action": action,
            "datablock": datablock,
            "data_path": data_path,
            "array_index": int(array_index),
            "group": group,
            "points": [],
        }
        state.recording_tracks[key] = track

    points = track["points"]
    frame_value = int(frame)
    numeric_value = float(value)
    if not points:
        points.append((frame_value, numeric_value))
        return True

    last_frame, last_value = points[-1]
    if frame_value == last_frame:
        if last_value == numeric_value:
            return False
        points[-1] = (frame_value, numeric_value)
        return True

    points.append((frame_value, numeric_value))
    return True


def _clear_fcurve_frame_range(fcurve, frame_start: int, frame_end: int):
    removed = 0
    for keyframe in reversed(fcurve.keyframe_points):
        frame = float(keyframe.co.x)
        if frame_start <= frame <= frame_end:
            fcurve.keyframe_points.remove(keyframe, fast=True)
            removed += 1
    return removed


def _bake_recording_track(track):
    points = track.get("points") or []
    if not points:
        return 0

    fcurve = _find_or_create_action_fcurve(
        track.get("action"),
        track["data_path"],
        track["array_index"],
        track.get("group"),
        track.get("datablock"),
    )
    if fcurve is None:
        return 0

    frame_start = min(frame for frame, _value in points)
    frame_end = max(frame for frame, _value in points)
    _clear_fcurve_frame_range(fcurve, frame_start, frame_end)
    for frame, value in points:
        keyframe = fcurve.keyframe_points.insert(float(frame), float(value), options={"FAST"})
        if keyframe is not None:
            keyframe.interpolation = "LINEAR"
    fcurve.update()
    return len(points)


def _bake_recording_tracks():
    for track in tuple(state.recording_tracks.values()):
        _bake_recording_track(track)


def _record_vector(action, data_path: str, values, frame: int, group: str = None, datablock=None):
    recorded = False
    for index, value in enumerate(values):
        recorded = _cache_recording_key(action, data_path, index, frame, value, group, datablock) or recorded
    return recorded


def _as_float_tuple(values):
    return tuple(float(value) for value in values)


def _as_quaternion(values):
    quat = values.copy() if isinstance(values, Quaternion) else Quaternion(values)
    quat.normalize()
    return quat


def _lerp_tuple(start, end, factor: float):
    return tuple(float(a) + ((float(b) - float(a)) * factor) for a, b in zip(start, end))


def _slerp_quaternion_tuple(start, end, factor: float):
    start_quat = _as_quaternion(start)
    end_quat = _as_quaternion(end)
    interpolated = start_quat.slerp(end_quat, factor)
    interpolated.normalize()
    return _as_float_tuple(interpolated)


def _rotation_quaternion_from_object(item):
    rotation_mode = str(getattr(item, "rotation_mode", "XYZ"))
    if rotation_mode == "QUATERNION":
        return _as_quaternion(item.rotation_quaternion)
    if rotation_mode == "AXIS_ANGLE":
        angle = float(item.rotation_axis_angle[0])
        axis = Vector(item.rotation_axis_angle[1:4])
        if axis.length_squared <= 1e-12:
            return Quaternion()
        return _as_quaternion(Quaternion(axis.normalized(), angle))
    return _as_quaternion(item.rotation_euler.to_quaternion())


def _record_rotation_quaternion(action, prefix: str, rotation_mode: str, rotation_quaternion, frame: int, group: str = None):
    basis_quat = _as_quaternion(rotation_quaternion)
    if rotation_mode == "QUATERNION":
        return _record_vector(action, f"{prefix}rotation_quaternion", basis_quat, frame, group)
    if rotation_mode == "AXIS_ANGLE":
        axis, angle = basis_quat.to_axis_angle()
        return _record_vector(action, f"{prefix}rotation_axis_angle", (angle, axis.x, axis.y, axis.z), frame, group)
    return _record_vector(action, f"{prefix}rotation_euler", basis_quat.to_euler(rotation_mode), frame, group)


def _rotation_data_path_specs(prefix: str, rotation_mode: str):
    if rotation_mode == "QUATERNION":
        return [(f"{prefix}rotation_quaternion", index) for index in range(4)]
    if rotation_mode == "AXIS_ANGLE":
        return [(f"{prefix}rotation_axis_angle", index) for index in range(4)]
    return [(f"{prefix}rotation_euler", index) for index in range(3)]


def _recording_object_rotation_mode(item) -> str:
    snapshot = _receiver_armature_snapshot(item)
    if snapshot is not None:
        object_state = snapshot.get("object_state", {})
        return str(object_state.get("rotation_mode", getattr(item, "rotation_mode", "XYZ")))
    return str(getattr(item, "rotation_mode", "XYZ"))


def _record_object_rotation(action, item, prefix: str, frame: int, group: str = None):
    if item.rotation_mode == "QUATERNION":
        return _record_vector(action, f"{prefix}rotation_quaternion", item.rotation_quaternion, frame, group)
    elif item.rotation_mode == "AXIS_ANGLE":
        return _record_vector(action, f"{prefix}rotation_axis_angle", item.rotation_axis_angle, frame, group)
    else:
        return _record_vector(action, f"{prefix}rotation_euler", item.rotation_euler, frame, group)


def _receiver_armature_snapshot(arm):
    if arm is None:
        return None
    for snapshot in state.receiver_armature_snapshots:
        if snapshot.get("object") is arm:
            return snapshot
    return None


def _recording_pose_bone_rotation_mode(arm, bone_name: str, pose_bone) -> str:
    snapshot = _receiver_armature_snapshot(arm)
    if snapshot is not None:
        bone_snapshot = snapshot.get("pose_bones", {}).get(bone_name)
        if bone_snapshot is not None:
            return str(bone_snapshot.get("rotation_mode", pose_bone.rotation_mode))
    return str(pose_bone.rotation_mode)


def _record_pose_bone_rotation(action, arm, bone_name: str, pose_bone, prefix: str, frame: int, group: str = None):
    rotation_mode = _recording_pose_bone_rotation_mode(arm, bone_name, pose_bone)
    basis_quat = pose_bone.matrix_basis.to_quaternion()
    basis_quat.normalize()
    return _record_rotation_quaternion(action, prefix, rotation_mode, basis_quat, frame, group)


def _record_arp_fk_switches(action, arm, frame: int):
    if action is None or not mapping.has_pose_bones(arm):
        return False

    recorded = False
    for bone_name in mapping_arp.ARP_IK_FK_CONTROLS:
        pose_bone = arm.pose.bones.get(bone_name)
        if pose_bone is None or "ik_fk_switch" not in pose_bone:
            continue

        data_path = f'pose.bones["{bone_name}"]["ik_fk_switch"]'
        recorded = _cache_recording_key(action, data_path, 0, frame, 1.0, bone_name) or recorded
    return recorded


def _recordable_target_bones(scene, arm, context, driven_bones):
    if not mapping.has_pose_bones(arm):
        return set()

    pose = arm.pose.bones
    bone_names = {name for name in driven_bones if name in pose}
    if context and context.get("is_arp"):
        for _source_name, target_name, _source_bone, target_bone, _calibration in context.get("arp_runtime_entries", ()):
            if target_bone is not None and target_name in pose:
                bone_names.add(target_name)
        if context.get("arp_traj_bone") is not None and "c_traj" in pose:
            bone_names.add("c_traj")
        return bone_names

    for vmc_name in constants.BONE_ALIASES:
        actual = state.cached_bone_map.get(vmc_name) or mapping.find_bone_name(arm, vmc_name, scene)
        if actual and actual in pose:
            state.cached_bone_map[vmc_name] = actual
            bone_names.add(actual)
    return bone_names


def _recordable_target_shapes(scene, face, use_arkit_face, driven_shapes):
    if not mapping.has_shape_keys(face):
        return set()

    blocks = face.data.shape_keys.key_blocks
    shape_names = {name for name in driven_shapes if name in blocks}
    kind = constants.MAPPING_KIND_ARKIT_BLEND if use_arkit_face else constants.MAPPING_KIND_VMC_BLEND
    cache = state.cached_arkit_blend_map if use_arkit_face else state.cached_blend_map
    finder = mapping.find_arkit_shapekey_name if use_arkit_face else mapping.find_shapekey_name

    for source_name in mapping.mapping_keys(kind):
        actual = cache.get(source_name) or finder(face, source_name, scene)
        if actual and actual in blocks:
            cache[source_name] = actual
            shape_names.add(actual)
    return shape_names


def _collect_recording_channel_specs(scene):
    specs = {"armature": [], "face": []}
    arm_obj = getattr(scene, "vmc_link_armature", None)
    face_obj = getattr(scene, "vmc_link_face_object", None)
    preview_arm = getattr(scene, "vmc_link_preview_armature", None)
    use_arkit_face = is_arkit_face_source_enabled(scene)
    target_context = _ensure_receiver_target_context(scene, arm_obj, preview_arm) if mapping.has_pose_bones(arm_obj) else None

    if mapping.has_pose_bones(arm_obj):
        rotation_mode = _recording_object_rotation_mode(arm_obj)
        specs["armature"].extend(
            [{"data_path": "location", "array_index": index, "datablock": None} for index in range(3)]
        )
        specs["armature"].extend(
            {"data_path": data_path, "array_index": array_index, "datablock": None}
            for data_path, array_index in _rotation_data_path_specs("", rotation_mode)
        )

        record_bones = _recordable_target_bones(scene, arm_obj, target_context, set())
        for bone_name in sorted(record_bones):
            pose_bone = arm_obj.pose.bones.get(bone_name)
            if pose_bone is None:
                continue
            prefix = f'pose.bones["{bone_name}"].'
            specs["armature"].extend(
                {"data_path": f"{prefix}location", "array_index": index, "datablock": None}
                for index in range(3)
            )
            bone_rotation_mode = _recording_pose_bone_rotation_mode(arm_obj, bone_name, pose_bone)
            specs["armature"].extend(
                {"data_path": data_path, "array_index": array_index, "datablock": None}
                for data_path, array_index in _rotation_data_path_specs(prefix, bone_rotation_mode)
            )

        if target_context and target_context.get("is_arp"):
            for bone_name in mapping_arp.ARP_IK_FK_CONTROLS:
                pose_bone = arm_obj.pose.bones.get(bone_name)
                if pose_bone is None or "ik_fk_switch" not in pose_bone:
                    continue
                specs["armature"].append(
                    {
                        "data_path": f'pose.bones["{bone_name}"]["ik_fk_switch"]',
                        "array_index": 0,
                        "datablock": None,
                    }
                )

    if mapping.has_shape_keys(face_obj):
        shape_datablock = face_obj.data.shape_keys
        record_shapes = _recordable_target_shapes(scene, face_obj, use_arkit_face, set())
        for key_name in sorted(record_shapes):
            specs["face"].append(
                {
                    "data_path": f'key_blocks["{key_name}"].value',
                    "array_index": 0,
                    "datablock": shape_datablock,
                }
            )

    return specs


def clear_recording_range_keys(scene):
    if scene is None:
        raise RuntimeError("当前没有可用场景")
    if state.recording:
        raise RuntimeError("请先停止录制")

    error = get_recording_range_error(scene)
    if error:
        raise RuntimeError(error)

    frame_start = int(getattr(scene, "vmc_link_record_start_frame", 1))
    frame_end = int(getattr(scene, "vmc_link_record_end_frame", frame_start))
    specs = _collect_recording_channel_specs(scene)
    arm_action, face_action = _current_recording_actions(scene)

    result = {
        "frame_start": frame_start,
        "frame_end": frame_end,
        "armature_removed": 0,
        "face_removed": 0,
        "armature_action": arm_action.name if arm_action is not None else "",
        "face_action": face_action.name if face_action is not None else "",
    }

    if arm_action is not None:
        updated = []
        for spec in specs["armature"]:
            fcurve = _find_existing_action_fcurve(arm_action, spec["data_path"], spec["array_index"], spec["datablock"])
            if fcurve is None:
                continue
            removed = _clear_fcurve_frame_range(fcurve, frame_start, frame_end)
            if removed > 0:
                result["armature_removed"] += removed
                if fcurve not in updated:
                    updated.append(fcurve)
        for fcurve in updated:
            fcurve.update()

    if face_action is not None:
        updated = []
        for spec in specs["face"]:
            fcurve = _find_existing_action_fcurve(face_action, spec["data_path"], spec["array_index"], spec["datablock"])
            if fcurve is None:
                continue
            removed = _clear_fcurve_frame_range(fcurve, frame_start, frame_end)
            if removed > 0:
                result["face_removed"] += removed
                if fcurve not in updated:
                    updated.append(fcurve)
        for fcurve in updated:
            fcurve.update()

    return result


def _current_recording_frame(scene):
    if state.recording_start_frame is None:
        state.recording_start_frame = int(scene.frame_current)
    if state.recording_start_ts <= 0.0:
        state.recording_start_ts = time.perf_counter()

    fps_base = float(getattr(scene.render, "fps_base", 1.0) or 1.0)
    fps = float(getattr(scene.render, "fps", 24)) / fps_base
    paused_duration = float(state.recording_paused_duration)
    if state.recording_pause_started_ts > 0.0:
        paused_duration += time.perf_counter() - state.recording_pause_started_ts

    elapsed = max(0.0, time.perf_counter() - state.recording_start_ts - paused_duration)
    frame = int(state.recording_start_frame + round(elapsed * fps))
    state.recording_frame = frame
    return frame


def _build_recording_sample(arm, record_bones, face, record_shapes, target_context=None):
    sample = {
        "arm": None,
        "bones": {},
        "shape_datablock": None,
        "shapes": {},
        "ik_fk_switches": {},
    }

    if arm is not None:
        sample["arm"] = {
            "location": _as_float_tuple(arm.location),
            "rotation_mode": str(arm.rotation_mode),
            "rotation_quaternion": _as_float_tuple(_rotation_quaternion_from_object(arm)),
        }

        if target_context and target_context.get("is_arp") and mapping.has_pose_bones(arm):
            for bone_name in mapping_arp.ARP_IK_FK_CONTROLS:
                pose_bone = arm.pose.bones.get(bone_name)
                if pose_bone is None or "ik_fk_switch" not in pose_bone:
                    continue
                sample["ik_fk_switches"][bone_name] = float(pose_bone["ik_fk_switch"])

        pose = arm.pose.bones if getattr(arm, "pose", None) is not None else None
        if pose is not None:
            for bone_name in record_bones:
                pose_bone = pose.get(bone_name)
                if pose_bone is None:
                    continue
                basis_quat = pose_bone.matrix_basis.to_quaternion()
                basis_quat.normalize()
                sample["bones"][bone_name] = {
                    "location": _as_float_tuple(pose_bone.location),
                    "rotation_mode": _recording_pose_bone_rotation_mode(arm, bone_name, pose_bone),
                    "rotation_quaternion": _as_float_tuple(basis_quat),
                }

    if mapping.has_shape_keys(face):
        sample["shape_datablock"] = face.data.shape_keys
        blocks = face.data.shape_keys.key_blocks
        for key_name in record_shapes:
            key_block = blocks.get(key_name)
            if key_block is None:
                continue
            sample["shapes"][key_name] = float(key_block.value)

    return sample


def _interpolate_recording_sample(previous_sample, current_sample, factor: float):
    if previous_sample is None or factor >= 1.0:
        return current_sample
    if factor <= 0.0:
        return previous_sample

    sample = {
        "arm": None,
        "bones": {},
        "shape_datablock": current_sample.get("shape_datablock") or previous_sample.get("shape_datablock"),
        "shapes": {},
        "ik_fk_switches": dict(current_sample.get("ik_fk_switches", {})),
    }

    prev_arm = previous_sample.get("arm")
    curr_arm = current_sample.get("arm")
    if prev_arm is not None and curr_arm is not None:
        sample["arm"] = {
            "location": _lerp_tuple(prev_arm["location"], curr_arm["location"], factor),
            "rotation_mode": curr_arm["rotation_mode"],
            "rotation_quaternion": _slerp_quaternion_tuple(prev_arm["rotation_quaternion"], curr_arm["rotation_quaternion"], factor),
        }
    else:
        sample["arm"] = curr_arm or prev_arm

    bone_names = set(previous_sample.get("bones", {}).keys()) | set(current_sample.get("bones", {}).keys())
    for bone_name in bone_names:
        prev_bone = previous_sample.get("bones", {}).get(bone_name)
        curr_bone = current_sample.get("bones", {}).get(bone_name)
        if prev_bone is not None and curr_bone is not None:
            sample["bones"][bone_name] = {
                "location": _lerp_tuple(prev_bone["location"], curr_bone["location"], factor),
                "rotation_mode": curr_bone["rotation_mode"],
                "rotation_quaternion": _slerp_quaternion_tuple(prev_bone["rotation_quaternion"], curr_bone["rotation_quaternion"], factor),
            }
        else:
            sample["bones"][bone_name] = curr_bone or prev_bone

    shape_names = set(previous_sample.get("shapes", {}).keys()) | set(current_sample.get("shapes", {}).keys())
    for shape_name in shape_names:
        prev_value = previous_sample.get("shapes", {}).get(shape_name)
        curr_value = current_sample.get("shapes", {}).get(shape_name)
        if prev_value is not None and curr_value is not None:
            sample["shapes"][shape_name] = float(prev_value) + ((float(curr_value) - float(prev_value)) * factor)
        elif curr_value is not None:
            sample["shapes"][shape_name] = float(curr_value)
        elif prev_value is not None:
            sample["shapes"][shape_name] = float(prev_value)

    return sample


def _cache_recording_sample(sample, frame: int):
    recorded_any = False

    arm_sample = sample.get("arm")
    if arm_sample is not None:
        action = state.recording_armature_action
        recorded_any = _record_vector(action, "location", arm_sample["location"], frame, "Object") or recorded_any
        recorded_any = _record_rotation_quaternion(
            action,
            "",
            arm_sample["rotation_mode"],
            arm_sample["rotation_quaternion"],
            frame,
            "Object",
        ) or recorded_any

        for bone_name, switch_value in sample.get("ik_fk_switches", {}).items():
            data_path = f'pose.bones["{bone_name}"]["ik_fk_switch"]'
            recorded_any = _cache_recording_key(action, data_path, 0, frame, switch_value, bone_name) or recorded_any

        for bone_name, bone_sample in sample.get("bones", {}).items():
            prefix = f'pose.bones["{bone_name}"].'
            recorded_any = _record_vector(action, f"{prefix}location", bone_sample["location"], frame, bone_name) or recorded_any
            recorded_any = _record_rotation_quaternion(
                action,
                prefix,
                bone_sample["rotation_mode"],
                bone_sample["rotation_quaternion"],
                frame,
                bone_name,
            ) or recorded_any

    shape_datablock = sample.get("shape_datablock")
    if shape_datablock is not None:
        action = state.recording_face_action
        for key_name, shape_value in sample.get("shapes", {}).items():
            data_path = f'key_blocks["{key_name}"].value'
            recorded_any = _cache_recording_key(action, data_path, 0, frame, shape_value, key_name, shape_datablock) or recorded_any

    return recorded_any


def _write_transition_frames(current_sample):
    source_sample = state.recording_transition_source_sample or current_sample
    frame_start = int(state.recording_start_frame)
    frame_end = int(state.recording_end_frame if state.recording_end_frame is not None else frame_start)
    transition_last_frame = min(frame_end, frame_start + max(0, int(state.recording_transition_frames) - 1))
    span = max(1, transition_last_frame - frame_start)

    for frame in range(frame_start, transition_last_frame + 1):
        factor = 0.0 if transition_last_frame == frame_start else (frame - frame_start) / float(span)
        transition_sample = _interpolate_recording_sample(source_sample, current_sample, factor)
        _cache_recording_sample(transition_sample, frame)

    state.recording_last_sample = current_sample
    state.recording_last_written_frame = transition_last_frame
    state.recording_sample_count = max(0, transition_last_frame - frame_start + 1)
    state.recording_transition_pending = False
    state.recording_transition_source_sample = None
    return transition_last_frame


def record_current_sample(scene, arm, driven_bones, face, driven_shapes, target_context=None, use_arkit_face=False, has_valid_input=False):
    current_frame = _current_recording_frame(scene)
    frame_end = int(state.recording_end_frame if state.recording_end_frame is not None else current_frame)
    if state.recording_start_frame is not None and frame_end < state.recording_start_frame:
        stop_recording()
        return

    effective_frame = min(current_frame, frame_end)
    last_frame = state.recording_last_written_frame

    record_bones = _recordable_target_bones(scene, arm, target_context, driven_bones)
    record_shapes = _recordable_target_shapes(scene, face, use_arkit_face, driven_shapes)
    current_sample = _build_recording_sample(arm, record_bones, face, record_shapes, target_context)

    if state.recording_transition_pending:
        if not has_valid_input:
            if current_frame >= frame_end:
                stop_recording()
            return
        _write_transition_frames(current_sample)
        last_frame = state.recording_last_written_frame

    if not has_valid_input and state.recording_last_sample is None:
        if current_frame >= frame_end:
            stop_recording()
        return

    previous_sample = state.recording_last_sample if state.recording_last_sample is not None else current_sample
    recorded_any = False

    if last_frame is not None and previous_sample is not None and effective_frame > last_frame + 1:
        frame_span = float(effective_frame - last_frame)
        for frame in range(last_frame + 1, effective_frame):
            factor = (frame - last_frame) / frame_span
            interpolated_sample = _interpolate_recording_sample(previous_sample, current_sample, factor)
            recorded_any = _cache_recording_sample(interpolated_sample, frame) or recorded_any

    if effective_frame >= (last_frame if last_frame is not None else effective_frame):
        recorded_any = _cache_recording_sample(current_sample, effective_frame) or recorded_any
    if recorded_any:
        if last_frame is None:
            state.recording_sample_count += 1
        elif effective_frame > last_frame:
            state.recording_sample_count += effective_frame - last_frame
        state.recording_last_written_frame = effective_frame
        state.recording_last_sample = current_sample

    if current_frame >= frame_end:
        stop_recording()


def _apply_preview_root_motion(preview_arm, root, waist, bones, context, lock_to_center: bool):
    if preview_arm is None or getattr(preview_arm, "type", None) != "ARMATURE":
        return

    if lock_to_center:
        if helpers.vec_changed(preview_arm.location, Vector((0.0, 0.0, 0.0))):
            preview_arm.location = (0.0, 0.0, 0.0)
        return

    source_name, raw_root_motion = _select_root_motion_pose(root, waist, bones, include_hips=True)
    if raw_root_motion is None:
        return

    current_location, _rotation = helpers.convert_vmc_pose(*raw_root_motion)
    if context.get("root_source") != source_name or context.get("root_baseline_location") is None:
        context["root_source"] = source_name
        context["root_baseline_location"] = current_location.copy()
        if context.get("preview_start_location") is None:
            context["preview_start_location"] = preview_arm.location.copy()

    desired_location = context["preview_start_location"] + (current_location - context["root_baseline_location"])
    if helpers.vec_changed(preview_arm.location, desired_location):
        preview_arm.location = desired_location


def _apply_preview_armature(preview_arm, root, waist, bones, blends, lock_to_center: bool, context=None):
    if preview_arm is None or getattr(preview_arm, "type", None) != "ARMATURE":
        return

    if context is None:
        context = {"preview": preview_arm, "preview_start_location": preview_arm.location.copy()}
    _apply_preview_root_motion(preview_arm, root, waist, bones, context, lock_to_center)

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
    lock_to_center = bool(getattr(scene, "vmc_link_lock_to_center", True))
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

    preview_context = _ensure_receiver_preview_context(scene, preview_arm)
    _apply_preview_armature(preview_arm, root, waist, bones, blends, lock_to_center, preview_context)
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
    target_context = None

    if arm is not None:
        target_context = _ensure_receiver_target_context(scene, arm, preview_arm)
        driven_bones.update(_apply_target_root_motion(arm, root, waist, bones, target_context, lock_to_center))

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
        has_vmc_input = state.last_packet_ts > 0.0 and (root is not None or waist is not None or bool(bones) or bool(blends))
        has_arkit_input = use_arkit_face and state.arkit_last_packet_ts > 0.0
        record_current_sample(scene, arm, driven_bones, face, driven_shapes, target_context, use_arkit_face, has_vmc_input or has_arkit_input)

    return rate
