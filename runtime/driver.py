import time

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from ..core import constants, helpers, state
from ..mapping import arp as mapping_arp
from ..mapping import mapper as mapping
from ..mapping import mmd as mapping_mmd
from ..mapping import target_rig as mapping_target_rig
from . import network, properties
from . import target_runtime

RECORDING_BAKE_PROGRESS_TOTAL = 1000
RECORDING_BAKE_PREPARE_PROGRESS_SHARE = 80
RECORDING_BAKE_REBUILD_PROGRESS_SHARE = 750
RECORDING_BAKE_CHUNK_BUDGET_SEC = 0.005
RECORDING_BAKE_MAX_RAW_FRAMES_PER_TICK = 8
RECORDING_BAKE_MAX_KEYS_PER_TICK = 192
RECORDING_BAKE_MAX_CLEAR_KEYS_PER_TICK = 192
RECORDING_BAKE_TIMER_INTERVAL_SEC = 0.001
IDLE_UI_REDRAW_INTERVAL_SEC = 1.0

def is_recording() -> bool:
    return state.recording


def is_recording_bake_active() -> bool:
    return state.recording_bake_session is not None


def get_recording_sample_count() -> int:
    return int(state.recording_sample_count)


def get_recording_bake_status():
    session = state.recording_bake_session or {}
    return {
        "active": bool(session),
        "phase": str(session.get("phase", "")),
        "label": str(session.get("status_label", "")),
        "detail": str(session.get("status_detail", "")),
        "progress": int(session.get("progress_value", 0)),
        "progress_total": RECORDING_BAKE_PROGRESS_TOTAL,
    }


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


def is_recording_interpolation_enabled(scene=None) -> bool:
    if state.recording:
        return bool(state.recording_interpolation_enabled)
    scene = scene or getattr(bpy.context, "scene", None)
    return bool(getattr(scene, "vmc_link_record_interpolation_enabled", True)) if scene is not None else True


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


def _rebase_mmd_root_motion_location(target_context):
    if not target_context or target_context.get("target_runtime_strategy") != mapping_target_rig.RUNTIME_STRATEGY_MMD:
        return None
    root_motion_bone = target_context.get("mmd_root_motion_bone")
    if root_motion_bone is None:
        return None
    start_location = root_motion_bone.matrix.to_translation()
    target_context["mmd_root_motion_start_location"] = start_location.copy()
    return start_location.copy()


def _apply_mmd_root_motion_start_location(target_context, start_location):
    if not target_context or start_location is None:
        return
    if target_context.get("target_runtime_strategy") != mapping_target_rig.RUNTIME_STRATEGY_MMD:
        return
    target_context["mmd_root_motion_start_location"] = Vector(start_location)


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


def _validate_recording_config(scene):
    error = get_recording_range_error(scene)
    if error:
        raise RuntimeError(error)

    frame_start = int(getattr(scene, "vmc_link_record_start_frame", 1))
    frame_end = int(getattr(scene, "vmc_link_record_end_frame", frame_start))
    transition_enabled = bool(getattr(scene, "vmc_link_record_transition_enabled", True))
    transition_frames = int(getattr(scene, "vmc_link_record_transition_frames", 24))
    motion_enabled = bool(getattr(scene, "vmc_link_record_motion_enabled", True))
    shape_keys_enabled = bool(getattr(scene, "vmc_link_record_shape_keys_enabled", True))
    if not motion_enabled and not shape_keys_enabled:
        raise RuntimeError("请至少启用“动作录制”或“形态键录制”")
    total_frames = max(1, frame_end - frame_start + 1)
    if transition_enabled:
        transition_frames = min(max(1, transition_frames), total_frames)
    else:
        transition_frames = 0

    return {
        "frame_start": frame_start,
        "frame_end": frame_end,
        "interpolation_enabled": bool(getattr(scene, "vmc_link_record_interpolation_enabled", True)),
        "motion_enabled": motion_enabled,
        "shape_keys_enabled": shape_keys_enabled,
        "transition_enabled": transition_enabled and transition_frames > 0,
        "transition_frames": transition_frames,
    }


def start_recording(scene):
    if scene is None:
        raise RuntimeError("无法开始录制：当前没有可用场景")
    if is_recording_bake_active():
        raise RuntimeError("上一段录制结果仍在保存，请等待当前保存完成")
    if state.recording:
        return
    if not bool(getattr(scene, "vmc_link_live_preview", True)):
        raise RuntimeError("请先开启“实时驱动目标对象”，录制只记录目标层结果")

    arm_obj = getattr(scene, "vmc_link_armature", None)
    face_obj = getattr(scene, "vmc_link_face_object", None)

    config = _validate_recording_config(scene)
    record_motion = bool(config["motion_enabled"])
    record_shape_keys = bool(config["shape_keys_enabled"])
    if record_motion and not mapping.has_pose_bones(arm_obj):
        raise RuntimeError("动作录制需要先绑定目标骨架")
    if record_shape_keys and not mapping.has_shape_keys(face_obj):
        raise RuntimeError("形态键录制需要先绑定目标面部")
    frame_start = int(config["frame_start"])
    scene.frame_set(0)
    try:
        capture_receiver_start_state(scene)
    finally:
        scene.frame_set(frame_start)
    bpy.context.view_layer.update()

    preview_arm = getattr(scene, "vmc_link_preview_armature", None)
    target_context = _ensure_receiver_target_context(scene, arm_obj, preview_arm) if record_motion else None
    recording_mmd_root_motion_start_location = _rebase_mmd_root_motion_location(target_context)
    record_bones = _recordable_target_bones(scene, arm_obj, target_context) if record_motion else set()
    record_shapes = _recordable_target_shapes(scene, face_obj, is_arkit_face_source_enabled(scene)) if record_shape_keys else set()
    transition_source_sample = _build_recording_transition_source_sample(
        arm_obj if record_motion else None,
        record_bones,
        face_obj if record_shape_keys else None,
        record_shapes,
        target_context,
    )

    _prepare_recording_target_actions(scene, arm_obj if record_motion else None, face_obj if record_shape_keys else None)
    state.recording = True
    state.recording_start_frame = frame_start
    state.recording_end_frame = int(config["frame_end"])
    state.recording_frame = state.recording_start_frame
    state.recording_start_ts = time.perf_counter()
    state.recording_source_start_ts = 0.0
    state.recording_pause_started_ts = 0.0
    state.recording_paused_duration = 0.0
    state.recording_source_pause_started_ts = 0.0
    state.recording_source_paused_duration = 0.0
    state.recording_source_pause_segments = []
    state.recording_last_written_frame = state.recording_start_frame - 1
    state.recording_sample_count = 0
    state.recording_tracks = {}
    state.recording_raw_frames = []
    state.recording_last_sample = None
    state.recording_interpolation_enabled = bool(config["interpolation_enabled"])
    state.recording_motion_enabled = record_motion
    state.recording_shape_keys_enabled = record_shape_keys
    state.recording_transition_enabled = bool(config["transition_enabled"])
    state.recording_transition_frames = int(config["transition_frames"])
    state.recording_transition_pending = bool(config["transition_enabled"])
    state.recording_transition_source_sample = transition_source_sample if config["transition_enabled"] else None
    state.recording_transition_target_sample = None
    state.recording_mmd_root_motion_start_location = recording_mmd_root_motion_start_location
    state.recording_armature_ref = arm_obj if record_motion else None
    state.recording_face_ref = face_obj if record_shape_keys else None
    state.recording_object_rotation_mode = _recording_object_rotation_mode(arm_obj) if arm_obj is not None else ""
    state.recording_bone_rotation_modes = _build_recording_bone_rotation_mode_cache(arm_obj)
    state.recording_pose_bones = (
        {
            bone_name: pose_bone
            for bone_name in record_bones
            for pose_bone in (arm_obj.pose.bones.get(bone_name),)
            if pose_bone is not None
        }
        if mapping.has_pose_bones(arm_obj)
        else {}
    )
    state.recording_shape_key_blocks = (
        {
            key_name: key_block
            for key_name in record_shapes
            for key_block in (face_obj.data.shape_keys.key_blocks.get(key_name),)
            if key_block is not None
        }
        if mapping.has_shape_keys(face_obj)
        else {}
    )
    state.dirty = True


def stop_recording(scene=None):
    if not state.recording:
        return int(state.recording_sample_count)

    written_frames = int(state.recording_sample_count)
    scene = scene or getattr(bpy.context, "scene", None)
    state.recording = False
    state.recording_frame = None
    state.recording_pause_started_ts = 0.0
    state.recording_source_pause_started_ts = 0.0
    if scene is None:
        _rebuild_recording_tracks_from_raw_frames(None)
        _bake_recording_tracks()
        _finish_recording_bake_session()
        return written_frames

    _start_recording_bake_session(scene)
    return written_frames


def _stop_recording_session(scene):
    if network.is_session_active() or network.is_running():
        network.stop_server(scene)
        return
    if state.recording:
        stop_recording(scene)


def set_recording(value: bool, scene=None):
    if value:
        start_recording(scene or getattr(bpy.context, "scene", None))
    else:
        stop_recording(scene or getattr(bpy.context, "scene", None))


def pause_recording_clock():
    if not state.recording or state.recording_pause_started_ts > 0.0:
        return
    state.recording_pause_started_ts = time.perf_counter()
    state.recording_source_pause_started_ts = time.time()


def resume_recording_clock():
    if not state.recording or state.recording_pause_started_ts <= 0.0:
        return
    state.recording_paused_duration += time.perf_counter() - state.recording_pause_started_ts
    state.recording_pause_started_ts = 0.0
    if state.recording_source_pause_started_ts > 0.0:
        pause_ended_ts = time.time()
        state.recording_source_paused_duration += pause_ended_ts - state.recording_source_pause_started_ts
        state.recording_source_pause_segments.append((state.recording_source_pause_started_ts, pause_ended_ts))
        state.recording_source_pause_started_ts = 0.0


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
    bones = state.canonical_bone_buf
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


def _rotation_quaternion_from_snapshot(transform_state):
    if not transform_state:
        return Quaternion()

    rotation_mode = str(transform_state.get("rotation_mode", "XYZ"))
    if rotation_mode == "QUATERNION":
        return _as_quaternion(transform_state.get("rotation_quaternion", (1.0, 0.0, 0.0, 0.0)))
    if rotation_mode == "AXIS_ANGLE":
        axis_angle = transform_state.get("rotation_axis_angle", (0.0, 0.0, 1.0, 0.0))
        angle = float(axis_angle[0])
        axis = Vector(axis_angle[1:4])
        if axis.length_squared <= 1e-12:
            return Quaternion()
        return _as_quaternion(Quaternion(axis.normalized(), angle))
    return _as_quaternion(Euler(transform_state.get("rotation_euler", (0.0, 0.0, 0.0)), rotation_mode).to_quaternion())


def _receiver_armature_snapshot_for(arm_obj):
    if arm_obj is None:
        return None
    for snapshot in state.receiver_armature_snapshots:
        if snapshot.get("object") is arm_obj:
            return snapshot
    return None


def _pose_bone_snapshot_transform(armature_snapshot, bone_name: str):
    if not armature_snapshot:
        return None
    return armature_snapshot.get("pose_bones", {}).get(bone_name)


def _pose_bone_snapshot_basis_quaternion(pose_bone, armature_snapshot):
    transform_state = _pose_bone_snapshot_transform(armature_snapshot, pose_bone.name)
    if transform_state:
        rotation = _rotation_quaternion_from_snapshot(transform_state)
        rotation.normalize()
        return rotation
    rotation = pose_bone.matrix_basis.to_quaternion()
    rotation.normalize()
    return rotation


def _pose_bone_snapshot_matrix(pose_bone, armature_snapshot, cache):
    cached = cache.get(pose_bone.name)
    if cached is not None:
        return cached.copy()

    transform_state = _pose_bone_snapshot_transform(armature_snapshot, pose_bone.name)
    if transform_state:
        location = Vector(transform_state.get("location", tuple(pose_bone.location)))
        rotation = _rotation_quaternion_from_snapshot(transform_state)
        scale = Vector(transform_state.get("scale", tuple(pose_bone.scale)))
    else:
        location = pose_bone.location.copy()
        rotation = pose_bone.matrix_basis.to_quaternion()
        scale = pose_bone.scale.copy()
    rotation.normalize()
    basis_matrix = Matrix.LocRotScale(location, rotation, scale)

    bone_ref = pose_bone.bone
    matrix_local = bone_ref.matrix_local.copy()
    parent_bone = pose_bone.parent
    if parent_bone is None:
        pose_matrix = bone_ref.convert_local_to_pose(basis_matrix, matrix_local)
    else:
        parent_matrix = _pose_bone_snapshot_matrix(parent_bone, armature_snapshot, cache)
        pose_matrix = bone_ref.convert_local_to_pose(
            basis_matrix,
            matrix_local,
            parent_matrix=parent_matrix,
            parent_matrix_local=parent_bone.bone.matrix_local,
        )
    cache[pose_bone.name] = pose_matrix.copy()
    return pose_matrix


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


def _clear_target_apply_cache():
    state.receiver_target_apply_armature_ref = None
    state.receiver_target_apply_face_ref = None
    state.receiver_target_apply_arm_location = None
    state.receiver_target_apply_arm_rotation = None
    state.receiver_target_apply_bone_locations = {}
    state.receiver_target_apply_bone_rotations = {}
    state.receiver_target_apply_ik_fk_switches = {}
    state.receiver_target_apply_shape_values = {}


def capture_receiver_start_state(scene):
    armatures = []
    faces = []
    seen = set()

    _clear_target_apply_cache()
    state.receiver_preview_apply_armature_ref = None
    state.receiver_preview_apply_face_ref = None
    state.receiver_preview_apply_arm_location = None
    state.receiver_preview_apply_arm_rotation = None
    state.receiver_preview_apply_bone_rotations = {}
    state.receiver_preview_apply_shape_values = {}

    if mapping_target_rig.scene_target_rig_type(scene) == mapping_target_rig.TARGET_RIG_ARP:
        mapping_arp.reset_runtime_control_transforms(scene)
        bpy.context.view_layer.update()

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
    mapping_target_rig.prepare_scene_receiver_session(scene)
    bpy.context.view_layer.update()
    state.receiver_preview_context = _build_receiver_preview_context(scene)
    state.receiver_target_context = _build_receiver_target_context(scene)
    state.receiver_session_active = True
    state.receiver_paused = False


def capture_receiver_start_state_at_zero_frame(scene):
    frame_current = int(scene.frame_current)
    frame_subframe = float(scene.frame_subframe)
    scene.frame_set(0)
    try:
        capture_receiver_start_state(scene)
    finally:
        scene.frame_set(frame_current, subframe=frame_subframe)
    bpy.context.view_layer.update()


def _receiver_face_snapshot(face_obj):
    if face_obj is None:
        return None
    for snapshot in state.receiver_face_snapshots:
        if snapshot.get("object") is face_obj:
            return snapshot
    return None


def _build_receiver_preview_context(scene, preview_arm=None):
    if preview_arm is None:
        preview_arm = getattr(scene, "vmc_link_preview_armature", None)
    runtime_entries = []
    eye_left_name = None
    eye_right_name = None
    if mapping.has_pose_bones(preview_arm):
        pose = preview_arm.pose.bones
        for source_name in (*constants.INTERMEDIATE_REQUIRED_BONES, *constants.INTERMEDIATE_OPTIONAL_BONES):
            actual_name = state.preview_cached_bone_map.get(source_name) or mapping.find_bone_name(preview_arm, source_name, None)
            if not actual_name or actual_name not in pose:
                continue
            state.preview_cached_bone_map[source_name] = actual_name
            pose_bone = pose[actual_name]
            rest_rotation = pose_bone.bone.matrix_local.to_quaternion()
            rest_rotation.normalize()
            rest_rotation_inv = rest_rotation.inverted()
            runtime_entries.append((source_name, pose_bone, rest_rotation, rest_rotation_inv))
            if source_name == "LeftEye":
                eye_left_name = actual_name
            elif source_name == "RightEye":
                eye_right_name = actual_name
    return {
        "preview": preview_arm,
        "preview_start_location": preview_arm.location.copy() if preview_arm is not None else None,
        "root_source": None,
        "root_baseline_location": None,
        "rotation_modes_ready": False,
        "runtime_entries": tuple(runtime_entries),
        "runtime_entries_by_source": {
            source_name: (source_name, pose_bone, rest_rotation, rest_rotation_inv)
            for source_name, pose_bone, rest_rotation, rest_rotation_inv in runtime_entries
        },
        "eye_left_name": eye_left_name,
        "eye_right_name": eye_right_name,
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


def _build_receiver_target_context(scene, arm_obj=None, preview_arm=None):
    if arm_obj is None:
        arm_obj = getattr(scene, "vmc_link_armature", None)
    if preview_arm is None:
        preview_arm = getattr(scene, "vmc_link_preview_armature", None)
    context = {
        "target": arm_obj,
        "preview": preview_arm,
        "target_rig": mapping_target_rig.resolve_scene_runtime_rig(scene, arm_obj),
        "target_runtime_strategy": mapping_target_rig.resolve_scene_runtime_strategy(scene, arm_obj),
        "target_start_world": arm_obj.matrix_world.copy() if arm_obj is not None else None,
        "target_start_world_location": None,
        "target_start_world_rotation": None,
        "target_start_world_scale": None,
        "target_world_rotation_inv": None,
        "root_source": None,
        "root_baseline_location": None,
        "root_baseline_rotation": None,
        "is_arp": False,
        "arp_root_motion_bone": None,
        "arp_root_motion_start_location": None,
        "mmd_root_motion_bone": None,
        "mmd_root_motion_start_rotation": None,
        "mmd_root_motion_start_matrix": None,
        "mmd_root_motion_start_location": None,
        "generic_runtime_entries": (),
        "generic_runtime_entries_by_source": {},
        "eye_left_name": None,
        "eye_right_name": None,
        "mmd_runtime_entries": (),
        "mmd_runtime_entries_by_source": {},
        "preview_rest_rotations": {},
        "preview_rest_inverse_rotations": {},
        "target_rest_rotations": {},
        "target_rest_inverse_rotations": {},
        "preview_start_matrices": {},
        "target_start_matrices": {},
        "target_start_locations": {},
        "target_start_scales": {},
        "preview_start_rotations": {},
        "target_start_rotations": {},
        "preview_start_basis_rotations": {},
        "target_start_basis_rotations": {},
        "arp_rotation_calibrations": {},
        "arp_filtered_source_rotations": {},
        "arp_filtered_rotations": {},
        "arp_runtime_entries": (),
        "arp_runtime_entries_by_source": {},
        "arp_runtime_order_index_by_source": {},
        "arp_ik_fk_pose_bones": (),
        "arp_copy_transforms_targets": {},
        "arp_child_of_targets": {},
        "arp_copy_location_rules": {},
        "arp_target_pose_matrices": {},
        "arp_desired_target_matrices": {},
        "target_rotation_modes_ready": False,
    }
    if context["target_start_world"] is not None:
        start_location, start_rotation, start_scale = context["target_start_world"].decompose()
        start_rotation.normalize()
        context["target_start_world_location"] = start_location
        context["target_start_world_rotation"] = start_rotation
        context["target_start_world_scale"] = start_scale
        context["target_world_rotation_inv"] = context["target_start_world"].to_3x3().inverted()

    target_info = mapping_target_rig.analyze_scene_target(scene, arm_obj)
    analysis = target_info["analysis"]
    if context["target_runtime_strategy"] != mapping_target_rig.RUNTIME_STRATEGY_ARP or not analysis.get("is_arp"):
        if mapping.has_pose_bones(arm_obj):
            pose = arm_obj.pose.bones
            runtime_entries = []
            for source_name, actual_name in state.cached_bone_map.items():
                if not actual_name or actual_name not in pose:
                    continue
                pose_bone = pose[actual_name]
                target_rest = pose_bone.bone.matrix_local.to_quaternion()
                target_rest.normalize()
                target_rest_inv = target_rest.inverted()
                source_rest = None
                source_rest_inv = None
                if mapping.has_pose_bones(preview_arm):
                    source_bone = preview_arm.pose.bones.get(source_name)
                    if source_bone is not None:
                        source_rest = source_bone.bone.matrix_local.to_quaternion()
                        source_rest.normalize()
                        source_rest_inv = source_rest.inverted()
                context["target_rest_rotations"][pose_bone.name] = target_rest.copy()
                context["target_rest_inverse_rotations"][pose_bone.name] = target_rest_inv.copy()
                runtime_entries.append((source_name, pose_bone, source_rest, source_rest_inv, target_rest, target_rest_inv))
                if source_name == "LeftEye":
                    context["eye_left_name"] = actual_name
                elif source_name == "RightEye":
                    context["eye_right_name"] = actual_name
            context["generic_runtime_entries"] = tuple(runtime_entries)
            context["generic_runtime_entries_by_source"] = {
                source_name: (source_name, pose_bone, source_rest, source_rest_inv, target_rest, target_rest_inv)
                for source_name, pose_bone, source_rest, source_rest_inv, target_rest, target_rest_inv in context["generic_runtime_entries"]
            }
        if context["target_runtime_strategy"] == mapping_target_rig.RUNTIME_STRATEGY_MMD and mapping.has_pose_bones(arm_obj):
            root_motion_target = mapping_mmd.resolve_root_motion_target_name(scene, arm_obj)
            root_motion_bone = arm_obj.pose.bones.get(root_motion_target) if root_motion_target else None
            if root_motion_bone is not None:
                context["mmd_root_motion_bone"] = root_motion_bone
                context["mmd_root_motion_start_rotation"] = root_motion_bone.rotation_quaternion.copy()
                context["mmd_root_motion_start_matrix"] = root_motion_bone.matrix.copy()
                context["mmd_root_motion_start_location"] = root_motion_bone.matrix.to_translation()
            if mapping.has_pose_bones(preview_arm):
                runtime_map = mapping_target_rig.build_runtime_mapping_for_scene(scene, arm_obj)
                entries = []
                source_snapshot = _receiver_armature_snapshot_for(preview_arm)
                target_snapshot = _receiver_armature_snapshot_for(arm_obj)
                source_snapshot_matrix_cache = {}
                target_snapshot_matrix_cache = {}
                for source_name, target_name in runtime_map.items():
                    source_bone = preview_arm.pose.bones.get(source_name)
                    target_bone = arm_obj.pose.bones.get(target_name)
                    if source_bone is None or target_bone is None:
                        continue
                    source_rest = source_bone.bone.matrix_local.to_quaternion()
                    target_rest = target_bone.bone.matrix_local.to_quaternion()
                    source_rest.normalize()
                    target_rest.normalize()
                    source_rest_inv = source_rest.inverted()
                    target_rest_inv = target_rest.inverted()
                    source_start_basis_rotation = _pose_bone_snapshot_basis_quaternion(source_bone, source_snapshot)
                    target_start_basis_rotation = _pose_bone_snapshot_basis_quaternion(target_bone, target_snapshot)
                    source_start_basis_rotation.normalize()
                    target_start_basis_rotation.normalize()
                    source_start_basis_rotation_inv = source_start_basis_rotation.inverted()
                    source_start_matrix = _pose_bone_snapshot_matrix(
                        source_bone,
                        source_snapshot,
                        source_snapshot_matrix_cache,
                    )
                    target_start_matrix = _pose_bone_snapshot_matrix(
                        target_bone,
                        target_snapshot,
                        target_snapshot_matrix_cache,
                    )
                    source_start_rotation = source_start_matrix.to_quaternion()
                    target_start_rotation = target_start_matrix.to_quaternion()
                    source_start_rotation.normalize()
                    target_start_rotation.normalize()
                    source_axis = source_start_rotation @ Vector((0.0, 1.0, 0.0))
                    target_axis = target_start_rotation @ Vector((0.0, 1.0, 0.0))
                    target_to_source_axis = target_axis.rotation_difference(source_axis)
                    calibration = target_to_source_axis @ target_start_rotation @ source_start_rotation.inverted()
                    calibration.normalize()
                    target_bone_ref = target_bone.bone
                    parent_bone = target_bone.parent
                    entries.append(
                        (
                            source_name,
                            target_name,
                            source_bone,
                            target_bone,
                            mapping_mmd.uses_neutral_axis_calibration(source_name),
                            calibration.copy(),
                            source_rest.copy(),
                            source_rest_inv.copy(),
                            target_rest.copy(),
                            target_rest_inv.copy(),
                            source_start_basis_rotation.copy(),
                            source_start_basis_rotation_inv.copy(),
                            target_start_basis_rotation.copy(),
                            target_start_rotation.copy(),
                            target_bone_ref,
                            target_bone_ref.matrix_local.copy(),
                            parent_bone,
                            parent_bone is not None,
                            parent_bone.bone.matrix_local.copy() if parent_bone is not None else None,
                            target_start_matrix.to_translation(),
                            target_start_matrix.to_scale(),
                        )
                    )
                context["mmd_runtime_entries"] = tuple(entries)
                context["mmd_runtime_entries_by_source"] = {
                    entry[0]: entry
                    for entry in context["mmd_runtime_entries"]
                }
        return context

    context["target_rig"] = mapping_target_rig.TARGET_RIG_ARP
    context["target_runtime_strategy"] = mapping_target_rig.RUNTIME_STRATEGY_ARP
    context["is_arp"] = True
    if mapping.has_pose_bones(arm_obj):
        root_motion_target = mapping_arp.resolve_root_motion_target_name(scene, arm_obj)
        root_motion_bone = arm_obj.pose.bones.get(root_motion_target) if root_motion_target else None
        if root_motion_bone is not None:
            context["arp_root_motion_bone"] = root_motion_bone
            context["arp_root_motion_start_location"] = root_motion_bone.location.copy()

    if not mapping.has_pose_bones(preview_arm):
        return context

    arp_copy_transforms_targets = {}
    arp_child_of_targets = {}
    arp_copy_location_rules = {}
    for pose_bone in arm_obj.pose.bones:
        copy_transforms_target = None
        child_of_target = None
        copy_location_rules = []
        for constraint in pose_bone.constraints:
            if constraint.mute or float(constraint.influence) <= 0.0:
                continue
            if getattr(constraint, "target", None) is not arm_obj:
                continue
            subtarget = str(getattr(constraint, "subtarget", "")).strip()
            if not subtarget:
                continue
            if constraint.type == "COPY_TRANSFORMS" and copy_transforms_target is None:
                copy_transforms_target = subtarget
                continue
            if constraint.type == "CHILD_OF" and float(constraint.influence) >= 0.999 and child_of_target is None:
                child_of_target = subtarget
                continue
            if constraint.type == "COPY_LOCATION":
                copy_location_rules.append(
                    (
                        subtarget,
                        max(0.0, min(1.0, float(constraint.influence))),
                        bool(getattr(constraint, "use_x", True)),
                        bool(getattr(constraint, "use_y", True)),
                        bool(getattr(constraint, "use_z", True)),
                    )
                )
        if copy_transforms_target is not None:
            arp_copy_transforms_targets[pose_bone.name] = copy_transforms_target
        if child_of_target is not None:
            arp_child_of_targets[pose_bone.name] = child_of_target
        if copy_location_rules:
            arp_copy_location_rules[pose_bone.name] = tuple(copy_location_rules)

    runtime_map = mapping_target_rig.build_runtime_mapping_for_scene(scene, arm_obj)
    arp_entries_by_source = {}
    for source_name, target_name in runtime_map.items():
        source_bone = preview_arm.pose.bones.get(source_name)
        target_bone = arm_obj.pose.bones.get(target_name)
        if source_bone is None or target_bone is None:
            continue
        source_rest = source_bone.bone.matrix_local.to_quaternion()
        target_rest = target_bone.bone.matrix_local.to_quaternion()
        source_rest.normalize()
        target_rest.normalize()
        source_rest_inv = source_rest.inverted()
        target_rest_inv = target_rest.inverted()
        context["preview_rest_rotations"][source_name] = source_rest.copy()
        context["preview_rest_inverse_rotations"][source_name] = source_rest_inv.copy()
        context["target_rest_rotations"][target_name] = target_rest.copy()
        context["target_rest_inverse_rotations"][target_name] = target_rest_inv.copy()
        context["preview_start_matrices"][source_name] = source_bone.matrix.copy()
        context["target_start_matrices"][target_name] = target_bone.matrix.copy()
        source_start_rotation = source_bone.matrix.to_quaternion()
        target_start_rotation = target_bone.matrix.to_quaternion()
        source_start_rotation.normalize()
        target_start_rotation.normalize()
        source_start_rotation_inv = source_start_rotation.inverted()
        context["preview_start_rotations"][source_name] = source_start_rotation.copy()
        context["target_start_rotations"][target_name] = target_start_rotation.copy()
        source_start_basis_rotation = source_bone.matrix_basis.to_quaternion()
        target_start_basis_rotation = target_bone.matrix_basis.to_quaternion()
        source_start_basis_rotation.normalize()
        target_start_basis_rotation.normalize()
        context["preview_start_basis_rotations"][source_name] = source_start_basis_rotation.copy()
        context["target_start_basis_rotations"][target_name] = target_start_basis_rotation.copy()
        target_start_location = target_bone.matrix.to_translation()
        target_start_scale = target_bone.matrix.to_scale()
        context["target_start_locations"][target_name] = target_start_location.copy()
        context["target_start_scales"][target_name] = target_start_scale.copy()
        source_axis = source_start_rotation @ Vector((0.0, 1.0, 0.0))
        target_axis = target_start_rotation @ Vector((0.0, 1.0, 0.0))
        target_to_source_axis = target_axis.rotation_difference(source_axis)
        aligned_target_rotation = target_to_source_axis @ target_start_rotation
        calibration = source_start_rotation.inverted() @ aligned_target_rotation
        calibration.normalize()
        context["arp_rotation_calibrations"][source_name] = calibration
        target_bone_ref = target_bone.bone
        target_matrix_local = target_bone_ref.matrix_local.copy()
        parent_bone = target_bone.parent
        has_parent = parent_bone is not None
        parent_matrix_local = parent_bone.bone.matrix_local.copy() if parent_bone is not None else None
        arp_entries_by_source[source_name] = (
            source_name,
            target_name,
            source_bone,
            target_bone,
            calibration,
            mapping_arp.uses_local_basis_delta(source_name),
            mapping_arp.uses_delta_rotation(source_name),
            mapping_arp.uses_rest_axis_remap(source_name),
            source_start_basis_rotation.copy(),
            target_start_basis_rotation.copy(),
            source_start_rotation.copy(),
            source_start_rotation_inv.copy(),
            target_start_rotation.copy(),
            target_start_location.copy(),
            target_start_scale.copy(),
            target_bone_ref,
            target_matrix_local.copy() if hasattr(target_matrix_local, "copy") else target_matrix_local,
            parent_bone,
            has_parent,
            parent_matrix_local.copy() if hasattr(parent_matrix_local, "copy") else parent_matrix_local,
            False,
            source_rest.copy(),
            source_rest_inv.copy(),
            target_rest.copy(),
            target_rest_inv.copy(),
        )
    context["arp_runtime_entries"] = tuple(
        arp_entries_by_source[source_name]
        for source_name in mapping_arp.ARP_RUNTIME_SOURCE_ORDER
        if source_name in arp_entries_by_source
    )
    context["arp_runtime_entries_by_source"] = arp_entries_by_source
    context["arp_runtime_order_index_by_source"] = {
        source_name: order_index
        for order_index, source_name in enumerate(mapping_arp.ARP_RUNTIME_SOURCE_ORDER)
        if source_name in arp_entries_by_source
    }
    context["arp_ik_fk_pose_bones"] = tuple(
        (bone_name, pose_bone)
        for bone_name in mapping_arp.ARP_IK_FK_CONTROLS
        for pose_bone in (arm_obj.pose.bones.get(bone_name),)
        if pose_bone is not None and "ik_fk_switch" in pose_bone
    )
    context["arp_copy_transforms_targets"] = arp_copy_transforms_targets
    context["arp_child_of_targets"] = arp_child_of_targets
    context["arp_copy_location_rules"] = arp_copy_location_rules
    arp_required_pose_targets = set()
    for _source_name, _target_name, _source_bone, target_bone, _calibration, *_rest in context["arp_runtime_entries"]:
        parent_bone = target_bone.parent if target_bone is not None else None
        while parent_bone is not None:
            arp_required_pose_targets.add(parent_bone.name)
            parent_bone = parent_bone.parent
    arp_required_pose_targets.update(arp_copy_transforms_targets.values())
    arp_required_pose_targets.update(arp_child_of_targets.values())
    for rules in arp_copy_location_rules.values():
        for subtarget, _influence, _use_x, _use_y, _use_z in rules:
            arp_required_pose_targets.add(subtarget)
    if arp_required_pose_targets:
        context["arp_runtime_entries"] = tuple(
            (
                *entry[:18],
                entry[18],
                entry[19],
                entry[1] in arp_required_pose_targets,
                *entry[21:],
            )
            for entry in context["arp_runtime_entries"]
        )
        context["arp_runtime_entries_by_source"] = {
            entry[0]: entry
            for entry in context["arp_runtime_entries"]
        }
    return context


def refresh_receiver_target_context(scene):
    arm_obj = getattr(scene, "vmc_link_armature", None)
    preview_arm = getattr(scene, "vmc_link_preview_armature", None)
    if not mapping.has_pose_bones(arm_obj):
        state.receiver_target_context = {}
        _clear_target_apply_cache()
        return {}
    if not state.cached_bone_map:
        mapping.rebuild_maps(scene)
    context = _build_receiver_target_context(scene, arm_obj, preview_arm)
    state.receiver_target_context = context
    _clear_target_apply_cache()
    return context


def _ensure_receiver_target_context(scene, arm_obj, preview_arm):
    context = state.receiver_target_context
    if context.get("target") is arm_obj and context.get("preview") is preview_arm:
        runtime_strategy = mapping_target_rig.resolve_scene_runtime_strategy(scene, arm_obj)
        target_rig = mapping_target_rig.resolve_scene_runtime_rig(scene, arm_obj)
        context_strategy = context.get("target_runtime_strategy")
        context_rig = context.get("target_rig")
        needs_rebuild = context_strategy != runtime_strategy or context_rig != target_rig
        if not needs_rebuild:
            if runtime_strategy == mapping_target_rig.RUNTIME_STRATEGY_ARP:
                needs_rebuild = bool(mapping_target_rig.build_runtime_mapping_for_scene(scene, arm_obj)) and not context.get("arp_runtime_entries")
            elif runtime_strategy == mapping_target_rig.RUNTIME_STRATEGY_MMD:
                needs_rebuild = bool(mapping_target_rig.build_runtime_mapping_for_scene(scene, arm_obj)) and not context.get("mmd_runtime_entries")
            else:
                needs_rebuild = bool(state.cached_bone_map) and not context.get("generic_runtime_entries")
        if needs_rebuild:
            context = _build_receiver_target_context(scene, arm_obj, preview_arm)
            state.receiver_target_context = context
        return context
    context = _build_receiver_target_context(scene, arm_obj, preview_arm)
    state.receiver_target_context = context
    return context


def _ensure_receiver_preview_context(scene, preview_arm):
    context = state.receiver_preview_context
    if context.get("preview") is preview_arm:
        return context
    context = _build_receiver_preview_context(scene, preview_arm)
    state.receiver_preview_context = context
    return context


def _ensure_target_runtime_rotation_modes(arm_obj, context):
    if arm_obj is None or getattr(arm_obj, "type", None) != "ARMATURE":
        return
    if bool(context.get("target_rotation_modes_ready")):
        return

    if arm_obj.rotation_mode != "QUATERNION":
        arm_obj.rotation_mode = "QUATERNION"

    pose = getattr(arm_obj, "pose", None)
    if pose is None:
        context["target_rotation_modes_ready"] = True
        return

    driven_pose_bones = {}
    runtime_strategy = context.get("target_runtime_strategy")
    if runtime_strategy == mapping_target_rig.RUNTIME_STRATEGY_ARP:
        for _source_name, target_name, _source_bone, target_bone, *_rest in context.get("arp_runtime_entries", ()):
            if target_bone is not None:
                driven_pose_bones[target_bone.name] = target_bone
            elif target_name:
                pose_bone = pose.bones.get(target_name)
                if pose_bone is not None:
                    driven_pose_bones[pose_bone.name] = pose_bone
    elif runtime_strategy == mapping_target_rig.RUNTIME_STRATEGY_MMD:
        for _source_name, target_name, _source_bone, target_bone, *_rest in context.get("mmd_runtime_entries", ()):
            if target_bone is not None:
                driven_pose_bones[target_bone.name] = target_bone
            elif target_name:
                pose_bone = pose.bones.get(target_name)
                if pose_bone is not None:
                    driven_pose_bones[pose_bone.name] = pose_bone
        root_motion_bone = context.get("mmd_root_motion_bone")
        if root_motion_bone is not None:
            driven_pose_bones[root_motion_bone.name] = root_motion_bone
    else:
        for _source_name, pose_bone, _source_rest, _source_rest_inv, _target_rest, _target_rest_inv in context.get("generic_runtime_entries", ()):
            if pose_bone is not None:
                driven_pose_bones[pose_bone.name] = pose_bone

    for eye_name in (context.get("eye_left_name"), context.get("eye_right_name")):
        if not eye_name:
            continue
        pose_bone = pose.bones.get(eye_name)
        if pose_bone is not None:
            driven_pose_bones[pose_bone.name] = pose_bone

    for pose_bone in driven_pose_bones.values():
        if pose_bone.rotation_mode != "QUATERNION":
            pose_bone.rotation_mode = "QUATERNION"

    context["target_rotation_modes_ready"] = True


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


def clear_receiver_session_state():
    state.reset_receiver_session_state()


def _view3d_redraw_signature(window_manager):
    windows = getattr(window_manager, "windows", ())
    signature = []
    for window in windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        signature.append((int(window.as_pointer()), int(screen.as_pointer()), len(screen.areas)))
    return tuple(signature)


def _rebuild_view3d_redraw_areas(window_manager, signature):
    areas = []
    seen = set()
    for window in getattr(window_manager, "windows", ()):
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            area_ptr = int(area.as_pointer())
            if area_ptr in seen:
                continue
            seen.add(area_ptr)
            areas.append(area)
    state.view3d_redraw_signature = signature
    state.view3d_redraw_areas = areas
    return areas


def tag_view3d_ui_redraw():
    window_manager = getattr(bpy.context, "window_manager", None)
    if window_manager is None:
        return

    signature = _view3d_redraw_signature(window_manager)
    areas = state.view3d_redraw_areas
    if not areas or state.view3d_redraw_signature != signature:
        areas = _rebuild_view3d_redraw_areas(window_manager, signature)

    rebuild_required = False
    for area in areas:
        try:
            area.tag_redraw()
        except Exception:
            rebuild_required = True
            break

    if not rebuild_required:
        return

    areas = _rebuild_view3d_redraw_areas(window_manager, signature)
    for area in areas:
        try:
            area.tag_redraw()
        except Exception:
            continue


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
        state.preview_cached_arkit_key_blocks = {}


def _ensure_target_face_cache_target(face):
    if face is state.target_face_ref:
        return
    state.target_face_ref = face
    state.cached_blend_map = {}
    state.cached_blend_key_blocks = {}
    state.cached_arkit_blend_map = {}
    state.cached_arkit_blend_key_blocks = {}


def draw_preview_entries(layout, title: str, entries, empty_text: str):
    box = layout.box()
    col = box.column(align=True)
    col.label(text=title)
    if not entries:
        col.label(text=empty_text, icon="INFO")
        return
    for entry in entries:
        col.label(text=entry)


def _prepare_recording_target_actions(scene, arm, face):
    if mapping.has_pose_bones(arm):
        arm.animation_data_create()
        action = getattr(scene, "vmc_link_record_armature_action", None)
        if action is None:
            action = bpy.data.actions.new(f"{arm.name}_VMC_Link_Action")
        action.use_fake_user = True
        state.recording_armature_action = action
        arm.animation_data.action = None

    if mapping.has_shape_keys(face):
        shape_keys = face.data.shape_keys
        shape_keys.animation_data_create()
        action = getattr(scene, "vmc_link_record_face_action", None)
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


def _append_recording_key_points(fcurve, points, start_index: int, count: int):
    if fcurve is None or count <= 0:
        return 0

    keyframe_points = fcurve.keyframe_points
    old_count = len(keyframe_points)
    keyframe_points.add(count)
    for offset, (frame, value) in enumerate(points[start_index:start_index + count]):
        keyframe = keyframe_points[old_count + offset]
        keyframe.co = (float(frame), float(value))
        keyframe.interpolation = "LINEAR"
    return count


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
    _append_recording_key_points(fcurve, points, 0, len(points))
    fcurve.update()
    return len(points)


def _bake_recording_tracks():
    for track in tuple(state.recording_tracks.values()):
        _bake_recording_track(track)


def _is_recording_bake_timer_registered() -> bool:
    try:
        return bpy.app.timers.is_registered(_recording_bake_timer)
    except Exception:
        return False


def _recording_bake_status_text(session=None) -> str:
    session = session or state.recording_bake_session or {}
    label = str(session.get("status_label", ""))
    detail = str(session.get("status_detail", ""))
    if label and detail:
        return f"{label} | {detail}"
    return label or detail


def _recording_bake_progress_begin(session=None):
    session = session or state.recording_bake_session or {}
    window_manager = session.get("window_manager") or getattr(bpy.context, "window_manager", None)
    if window_manager is None:
        return
    try:
        window_manager.progress_begin(0, RECORDING_BAKE_PROGRESS_TOTAL)
    except Exception:
        return
    workspace = session.get("workspace") or getattr(bpy.context, "workspace", None)
    if workspace is None:
        return
    try:
        workspace.status_text_set(_recording_bake_status_text(session))
    except Exception:
        return


def _recording_bake_progress_update(value: int, session=None):
    session = session or state.recording_bake_session or {}
    window_manager = session.get("window_manager") or getattr(bpy.context, "window_manager", None)
    if window_manager is None:
        return
    try:
        window_manager.progress_update(max(0, min(RECORDING_BAKE_PROGRESS_TOTAL, int(value))))
    except Exception:
        pass
    workspace = session.get("workspace") or getattr(bpy.context, "workspace", None)
    if workspace is None:
        return
    try:
        workspace.status_text_set(_recording_bake_status_text(session))
    except Exception:
        return


def _recording_bake_progress_end(session=None):
    session = session or state.recording_bake_session or {}
    window_manager = session.get("window_manager") or getattr(bpy.context, "window_manager", None)
    if window_manager is None:
        pass
    else:
        try:
            window_manager.progress_end()
        except Exception:
            pass
    workspace = session.get("workspace") or getattr(bpy.context, "workspace", None)
    if workspace is None:
        return
    try:
        workspace.status_text_set(None)
    except Exception:
        return


def _clear_recording_runtime_state():
    state.recording = False
    state.recording_frame = None
    state.recording_sample_count = 0
    state.recording_start_frame = None
    state.recording_start_ts = 0.0
    state.recording_source_start_ts = 0.0
    state.recording_pause_started_ts = 0.0
    state.recording_paused_duration = 0.0
    state.recording_source_pause_started_ts = 0.0
    state.recording_source_paused_duration = 0.0
    state.recording_source_pause_segments = []
    state.recording_last_written_frame = None
    state.recording_end_frame = None
    state.recording_armature_ref = None
    state.recording_face_ref = None
    state.recording_armature_action = None
    state.recording_face_action = None
    state.recording_object_rotation_mode = ""
    state.recording_bone_rotation_modes = {}
    state.recording_pose_bones = {}
    state.recording_shape_key_blocks = {}
    state.recording_tracks = {}
    state.recording_raw_frames = []
    state.recording_last_sample = None
    state.recording_interpolation_enabled = True
    state.recording_motion_enabled = True
    state.recording_shape_keys_enabled = True
    state.recording_transition_enabled = False
    state.recording_transition_frames = 0
    state.recording_transition_pending = False
    state.recording_transition_source_sample = None
    state.recording_transition_target_sample = None
    state.recording_mmd_root_motion_start_location = None


def _start_recording_bake_session(scene):
    raw_frames = list(state.recording_raw_frames)
    state.recording_raw_frames = []
    frame_start = int(state.recording_start_frame if state.recording_start_frame is not None else getattr(scene, "frame_current", 1))
    frame_end = int(state.recording_end_frame if state.recording_end_frame is not None else frame_start)

    if state.recording_source_start_ts <= 0.0 and raw_frames:
        state.recording_source_start_ts = float(raw_frames[0].get("timestamp", time.time()))
    raw_frames = _coalesce_recording_raw_frames(scene, raw_frames, frame_start, frame_end)

    preview_arm = getattr(scene, "vmc_link_preview_armature", None)
    arm = state.recording_armature_ref
    transition_last_frame = min(frame_end, frame_start + max(0, int(state.recording_transition_frames) - 1))
    needs_restore = bool(state.receiver_armature_snapshots or state.receiver_face_snapshots)

    state.recording_tracks = {}
    state.recording_last_sample = None
    _set_recording_progress(frame_start, frame_start - 1)

    session = {
        "scene": scene,
        "arm": arm,
        "preview_arm": preview_arm,
        "window_manager": getattr(bpy.context, "window_manager", None),
        "workspace": getattr(bpy.context, "workspace", None),
        "target_context": None,
        "use_arkit_face": is_arkit_face_source_enabled(scene),
        "lock_to_center": bool(getattr(scene, "vmc_link_lock_to_center", True)),
        "raw_frames": raw_frames,
        "raw_index": 0,
        "raw_total": len(raw_frames),
        "frame_start": frame_start,
        "frame_end": frame_end,
        "transition_pending": bool(state.recording_transition_enabled),
        "transition_source_sample": state.recording_transition_source_sample,
        "transition_target_sample": None,
        "mmd_root_motion_start_location": state.recording_mmd_root_motion_start_location,
        "transition_last_frame": transition_last_frame,
        "last_sample": None,
        "last_written_frame": frame_start - 1,
        "interpolation_enabled": bool(state.recording_interpolation_enabled),
        "phase": "prepare",
        "prepare_step": 0,
        "needs_restore": needs_restore,
        "needs_view_layer_update": needs_restore,
        "status_label": "正在准备保存录制结果",
        "status_detail": "正在恢复录制前状态" if needs_restore else "正在准备录制目标上下文",
        "progress_value": 0,
        "track_items": (),
        "track_index": 0,
        "track_total": 0,
        "current_track": None,
        "current_track_points": (),
        "current_track_point_index": 0,
        "current_track_clear_index": -1,
        "current_track_clear_total": 0,
        "current_track_frame_start": 0,
        "current_track_frame_end": -1,
        "current_fcurve": None,
    }
    state.recording_bake_session = session
    _recording_bake_progress_begin(session)
    _recording_bake_progress_update(0, session)

    if not _is_recording_bake_timer_registered():
        bpy.app.timers.register(_recording_bake_timer, first_interval=RECORDING_BAKE_TIMER_INTERVAL_SEC)
    tag_view3d_ui_redraw_if_due(time.time(), force=True)


def _switch_recording_bake_to_rebuild_phase(session):
    raw_total = int(session.get("raw_total", 0))
    session["phase"] = "rebuild"
    session["status_label"] = "正在重建录制采样"
    session["status_detail"] = f"已处理采样帧 0 / {raw_total}"
    session["progress_value"] = RECORDING_BAKE_PREPARE_PROGRESS_SHARE
    _recording_bake_progress_update(RECORDING_BAKE_PREPARE_PROGRESS_SHARE, session)


def _switch_recording_bake_to_track_phase(session):
    track_items = tuple(state.recording_tracks.values())
    session["phase"] = "bake"
    session["status_label"] = "正在写入动作曲线"
    session["status_detail"] = f"已完成曲线通道 0 / {len(track_items)}"
    session["track_items"] = track_items
    session["track_index"] = 0
    session["track_total"] = len(track_items)
    session["current_track"] = None
    session["current_track_points"] = ()
    session["current_track_point_index"] = 0
    session["current_track_clear_index"] = -1
    session["current_track_clear_total"] = 0
    session["current_track_frame_start"] = 0
    session["current_track_frame_end"] = -1
    session["current_fcurve"] = None
    session["progress_value"] = RECORDING_BAKE_REBUILD_PROGRESS_SHARE
    _recording_bake_progress_update(RECORDING_BAKE_REBUILD_PROGRESS_SHARE, session)


def _process_recording_bake_prepare(session):
    step = int(session.get("prepare_step", 0))
    if step <= 0:
        if bool(session.get("needs_restore")):
            restore_receiver_start_state()
        session["prepare_step"] = 1
        session["status_detail"] = "正在刷新 Blender 视图层"
        progress = RECORDING_BAKE_PREPARE_PROGRESS_SHARE // 2
        session["progress_value"] = progress
        _recording_bake_progress_update(progress, session)
        return False

    if step == 1:
        if bool(session.get("needs_view_layer_update")):
            view_layer = getattr(bpy.context, "view_layer", None)
            if view_layer is not None:
                view_layer.update()
        session["prepare_step"] = 2
        session["status_detail"] = "正在构建录制目标上下文"
        session["progress_value"] = RECORDING_BAKE_PREPARE_PROGRESS_SHARE
        _recording_bake_progress_update(RECORDING_BAKE_PREPARE_PROGRESS_SHARE, session)
        return False

    scene = session.get("scene")
    arm = session.get("arm")
    preview_arm = session.get("preview_arm")
    session["target_context"] = _build_receiver_target_context(scene, arm, preview_arm) if arm is not None else None
    _apply_mmd_root_motion_start_location(
        session["target_context"],
        session.get("mmd_root_motion_start_location"),
    )
    _switch_recording_bake_to_rebuild_phase(session)
    return True


def _prepare_recording_bake_track(session):
    track_items = session.get("track_items", ())
    track_total = int(session.get("track_total", 0))
    while int(session.get("track_index", 0)) < track_total:
        track = track_items[int(session["track_index"])]
        points = tuple(track.get("points") or ())
        if not points:
            session["track_index"] += 1
            continue

        fcurve = _find_or_create_action_fcurve(
            track.get("action"),
            track["data_path"],
            track["array_index"],
            track.get("group"),
            track.get("datablock"),
        )
        if fcurve is None:
            session["track_index"] += 1
            continue

        frame_start = min(frame for frame, _value in points)
        frame_end = max(frame for frame, _value in points)
        session["current_track"] = track
        session["current_track_points"] = points
        session["current_track_point_index"] = 0
        session["current_track_clear_index"] = len(fcurve.keyframe_points) - 1
        session["current_track_clear_total"] = len(fcurve.keyframe_points)
        session["current_track_frame_start"] = frame_start
        session["current_track_frame_end"] = frame_end
        session["current_fcurve"] = fcurve
        return True
    return False


def _update_recording_bake_progress(session):
    phase = str(session.get("phase", ""))
    if phase == "rebuild":
        raw_total = max(1, int(session.get("raw_total", 0)))
        raw_index = int(session.get("raw_index", 0))
        rebuild_span = RECORDING_BAKE_REBUILD_PROGRESS_SHARE - RECORDING_BAKE_PREPARE_PROGRESS_SHARE
        progress = RECORDING_BAKE_PREPARE_PROGRESS_SHARE + int((raw_index / raw_total) * rebuild_span)
        session["status_detail"] = f"已处理采样帧 {raw_index} / {raw_total}"
    else:
        track_total = max(1, int(session.get("track_total", 0)))
        track_index = int(session.get("track_index", 0))
        clear_total = max(0, int(session.get("current_track_clear_total", 0)))
        clear_index = int(session.get("current_track_clear_index", -1))
        clear_fraction = 1.0
        if clear_total > 0:
            clear_fraction = min(1.0, float(clear_total - max(0, clear_index + 1)) / float(clear_total))
        point_fraction = 0.0
        current_points = session.get("current_track_points") or ()
        if current_points:
            point_fraction = min(1.0, float(session.get("current_track_point_index", 0)) / float(len(current_points)))
        if clear_index >= 0:
            track_fraction = 0.5 * clear_fraction
            session["status_detail"] = f"正在清理曲线通道 {min(track_total, track_index + 1)} / {track_total} 的旧关键帧"
        else:
            track_fraction = 0.5 + 0.5 * point_fraction
            session["status_detail"] = f"正在写入曲线通道 {min(track_total, track_index + 1)} / {track_total} 的新关键帧"
        progress_fraction = min(1.0, (track_index + track_fraction) / float(track_total))
        progress = RECORDING_BAKE_REBUILD_PROGRESS_SHARE + int(
            progress_fraction * (RECORDING_BAKE_PROGRESS_TOTAL - RECORDING_BAKE_REBUILD_PROGRESS_SHARE)
        )
    session["progress_value"] = progress
    _recording_bake_progress_update(progress, session)


def _clear_recording_bake_track_chunk(session, deadline: float):
    fcurve = session.get("current_fcurve")
    if fcurve is None:
        return True

    clear_index = int(session.get("current_track_clear_index", -1))
    if clear_index < 0:
        return True

    frame_start = int(session.get("current_track_frame_start", 0))
    frame_end = int(session.get("current_track_frame_end", -1))
    processed = 0

    while clear_index >= 0 and processed < RECORDING_BAKE_MAX_CLEAR_KEYS_PER_TICK and time.perf_counter() < deadline:
        keyframe_points = fcurve.keyframe_points
        if clear_index >= len(keyframe_points):
            clear_index = len(keyframe_points) - 1
            continue

        keyframe = keyframe_points[clear_index]
        frame = float(keyframe.co.x)
        if frame_start <= frame <= frame_end:
            keyframe_points.remove(keyframe, fast=True)
        clear_index -= 1
        processed += 1

    session["current_track_clear_index"] = clear_index
    return clear_index < 0


def _process_recording_bake_tracks_chunk(session):
    deadline = time.perf_counter() + RECORDING_BAKE_CHUNK_BUDGET_SEC
    inserted_keys = 0

    while time.perf_counter() < deadline and inserted_keys < RECORDING_BAKE_MAX_KEYS_PER_TICK:
        if session.get("current_fcurve") is None and not _prepare_recording_bake_track(session):
            return True

        if not _clear_recording_bake_track_chunk(session, deadline):
            _update_recording_bake_progress(session)
            return False

        points = session.get("current_track_points") or ()
        fcurve = session.get("current_fcurve")
        point_index = int(session.get("current_track_point_index", 0))
        limit = min(len(points), point_index + max(1, RECORDING_BAKE_MAX_KEYS_PER_TICK - inserted_keys))
        write_count = max(0, limit - point_index)
        if write_count > 0:
            inserted = _append_recording_key_points(fcurve, points, point_index, write_count)
            point_index += inserted
            inserted_keys += inserted

        session["current_track_point_index"] = point_index
        if point_index < len(points):
            _update_recording_bake_progress(session)
            return False

        fcurve.update()
        session["track_index"] = int(session.get("track_index", 0)) + 1
        session["current_track"] = None
        session["current_track_points"] = ()
        session["current_track_point_index"] = 0
        session["current_track_clear_index"] = -1
        session["current_track_clear_total"] = 0
        session["current_track_frame_start"] = 0
        session["current_track_frame_end"] = -1
        session["current_fcurve"] = None
        _update_recording_bake_progress(session)

    return False


def _finish_recording_bake_session():
    session = state.recording_bake_session or {}
    scene = session.get("scene")
    session["status_label"] = "正在完成录制保存"
    session["status_detail"] = "正在重新绑定动作数据"
    session["progress_value"] = max(int(session.get("progress_value", 0)), RECORDING_BAKE_PROGRESS_TOTAL - 5)
    _recording_bake_progress_update(session["progress_value"], session)

    if state.recording_armature_ref is not None and state.recording_armature_action is not None:
        arm = state.recording_armature_ref
        if getattr(arm, "type", None) == "ARMATURE":
            arm.animation_data_create()
            _bind_recorded_action(arm.animation_data, state.recording_armature_action, arm)
            if scene is not None:
                scene.vmc_link_record_armature_action = state.recording_armature_action
    if state.recording_face_ref is not None and state.recording_face_action is not None:
        face = state.recording_face_ref
        if mapping.has_shape_keys(face):
            shape_keys = face.data.shape_keys
            shape_keys.animation_data_create()
            _bind_recorded_action(shape_keys.animation_data, state.recording_face_action, shape_keys)
            if scene is not None:
                scene.vmc_link_record_face_action = state.recording_face_action

    if _is_recording_bake_timer_registered():
        bpy.app.timers.unregister(_recording_bake_timer)
    _recording_bake_progress_update(RECORDING_BAKE_PROGRESS_TOTAL, session)
    _recording_bake_progress_end(session)
    state.recording_bake_session = None
    _clear_recording_runtime_state()
    tag_view3d_ui_redraw_if_due(time.time(), force=True)


def _recording_bake_timer():
    session = state.recording_bake_session
    if session is None:
        return None

    try:
        phase = str(session.get("phase", ""))
        if phase == "prepare":
            if _process_recording_bake_prepare(session):
                if int(session.get("raw_total", 0)) <= 0:
                    _switch_recording_bake_to_track_phase(session)
                    if int(session.get("track_total", 0)) <= 0:
                        _finish_recording_bake_session()
                        return None
        elif phase == "rebuild":
            scene = session.get("scene")
            raw_frames = session.get("raw_frames", ())
            deadline = time.perf_counter() + RECORDING_BAKE_CHUNK_BUDGET_SEC
            processed = 0

            while int(session.get("raw_index", 0)) < int(session.get("raw_total", 0)):
                if processed >= RECORDING_BAKE_MAX_RAW_FRAMES_PER_TICK or time.perf_counter() >= deadline:
                    break
                raw_index = int(session["raw_index"])
                keep_processing = _process_recording_raw_frame(scene, session, raw_frames[raw_index])
                session["raw_index"] = raw_index + 1
                processed += 1
                _update_recording_bake_progress(session)
                if not keep_processing:
                    session["raw_index"] = int(session.get("raw_total", 0))
                    break

            state.recording_last_sample = session.get("last_sample")
            if int(session.get("raw_index", 0)) >= int(session.get("raw_total", 0)):
                _switch_recording_bake_to_track_phase(session)
                if int(session.get("track_total", 0)) <= 0:
                    _finish_recording_bake_session()
                    return None
        else:
            if _process_recording_bake_tracks_chunk(session):
                _finish_recording_bake_session()
                return None
    except Exception as exc:
        print(f"[VMC Link] Recording bake failed: {exc}")
        _recording_bake_progress_end(session)
        if _is_recording_bake_timer_registered():
            bpy.app.timers.unregister(_recording_bake_timer)
        state.recording_bake_session = None
        _clear_recording_runtime_state()
        tag_view3d_ui_redraw_if_due(time.time(), force=True)
        return None

    tag_view3d_ui_redraw_if_due(time.time(), force=True, interval=0.02)
    return RECORDING_BAKE_TIMER_INTERVAL_SEC


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
    if item is state.recording_armature_ref and state.recording_object_rotation_mode:
        return str(state.recording_object_rotation_mode)
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


def _build_recording_bone_rotation_mode_cache(arm):
    if not mapping.has_pose_bones(arm):
        return {}

    pose = arm.pose.bones
    snapshot = _receiver_armature_snapshot(arm)
    bone_snapshots = snapshot.get("pose_bones", {}) if snapshot is not None else {}
    return {
        bone_name: str(bone_snapshots.get(bone_name, {}).get("rotation_mode", pose_bone.rotation_mode))
        for bone_name, pose_bone in pose.items()
    }


def _recording_pose_bone_rotation_mode(arm, bone_name: str, pose_bone) -> str:
    if arm is state.recording_armature_ref:
        cached_mode = state.recording_bone_rotation_modes.get(bone_name)
        if cached_mode:
            return str(cached_mode)
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


def _recordable_target_bones(scene, arm, context):
    if not mapping.has_pose_bones(arm):
        return set()

    pose = arm.pose.bones
    bone_names = set()
    if context and context.get("is_arp"):
        for _source_name, target_name, _source_bone, target_bone, _calibration, *_rest in context.get("arp_runtime_entries", ()):
            if target_bone is not None and target_name in pose:
                bone_names.add(target_name)
        root_motion_bone = context.get("arp_root_motion_bone")
        if root_motion_bone is not None and root_motion_bone.name in pose:
            bone_names.add(root_motion_bone.name)
        return bone_names

    if context and context.get("target_runtime_strategy") == mapping_target_rig.RUNTIME_STRATEGY_MMD:
        for _source_name, target_name, _source_bone, target_bone, *_rest in context.get("mmd_runtime_entries", ()):
            if target_bone is not None and target_name in pose:
                bone_names.add(target_name)
        root_motion_bone = context.get("mmd_root_motion_bone")
        if root_motion_bone is not None and root_motion_bone.name in pose:
            bone_names.add(root_motion_bone.name)
        return bone_names

    for vmc_name in constants.BONE_ALIASES:
        actual = state.cached_bone_map.get(vmc_name) or mapping.find_bone_name(arm, vmc_name, scene)
        if actual and actual in pose:
            state.cached_bone_map[vmc_name] = actual
            bone_names.add(actual)
    return bone_names


def _recordable_target_shapes(scene, face, use_arkit_face):
    if not mapping.has_shape_keys(face):
        return set()

    blocks = face.data.shape_keys.key_blocks
    shape_names = set()
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

        record_bones = _recordable_target_bones(scene, arm_obj, target_context)
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
        record_shapes = _recordable_target_shapes(scene, face_obj, use_arkit_face)
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
    if is_recording_bake_active():
        raise RuntimeError("录制结果仍在保存，请等待当前保存完成")

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


def _recording_source_elapsed_seconds(source_timestamp: float) -> float:
    if state.recording_source_start_ts <= 0.0:
        state.recording_source_start_ts = float(source_timestamp)

    elapsed = max(0.0, float(source_timestamp) - float(state.recording_source_start_ts))
    paused_duration = 0.0
    for pause_started_ts, pause_ended_ts in state.recording_source_pause_segments:
        if source_timestamp <= pause_started_ts:
            continue
        paused_duration += max(0.0, min(float(source_timestamp), float(pause_ended_ts)) - float(pause_started_ts))
    if state.recording_source_pause_started_ts > 0.0 and source_timestamp > state.recording_source_pause_started_ts:
        paused_duration += max(0.0, float(source_timestamp) - float(state.recording_source_pause_started_ts))
    return max(0.0, elapsed - paused_duration)


def _current_recording_frame(scene, source_timestamp=None):
    if state.recording_start_frame is None:
        state.recording_start_frame = int(scene.frame_current)

    fps_base = float(getattr(scene.render, "fps_base", 1.0) or 1.0)
    fps = float(getattr(scene.render, "fps", 24)) / fps_base
    if source_timestamp is not None:
        elapsed = _recording_source_elapsed_seconds(float(source_timestamp))
    else:
        if state.recording_start_ts <= 0.0:
            state.recording_start_ts = time.perf_counter()
        paused_duration = float(state.recording_paused_duration)
        if state.recording_pause_started_ts > 0.0:
            paused_duration += time.perf_counter() - state.recording_pause_started_ts
        elapsed = max(0.0, time.perf_counter() - state.recording_start_ts - paused_duration)
    frame = int(state.recording_start_frame + round(elapsed * fps))
    state.recording_frame = frame
    return frame


def _recording_frame_for_timestamp(scene, source_timestamp, frame_start: int) -> int:
    fps_base = float(getattr(scene.render, "fps_base", 1.0) or 1.0)
    fps = float(getattr(scene.render, "fps", 24)) / fps_base
    elapsed = _recording_source_elapsed_seconds(float(source_timestamp))
    return int(frame_start + round(elapsed * fps))


def _coalesce_recording_raw_frames(scene, raw_frames, frame_start: int, frame_end: int):
    if not raw_frames:
        return []

    by_frame = {}
    for raw_frame in raw_frames:
        frame = _recording_frame_for_timestamp(scene, raw_frame.get("timestamp", time.time()), frame_start)
        effective_frame = min(frame, frame_end)
        by_frame[effective_frame] = raw_frame
        if frame >= frame_end:
            break
    return [by_frame[frame] for frame in sorted(by_frame)]


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
                pose_bone = state.recording_pose_bones.get(bone_name) or pose.get(bone_name)
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
        for key_name in record_shapes:
            key_block = state.recording_shape_key_blocks.get(key_name)
            if key_block is None:
                key_block = face.data.shape_keys.key_blocks.get(key_name)
            if key_block is None:
                continue
            sample["shapes"][key_name] = float(key_block.value)

    return sample


def _build_recording_sample_from_evaluated(arm, evaluated_sample):
    sample = {
        "arm": None,
        "bones": {},
        "shape_datablock": evaluated_sample.get("shape_datablock"),
        "shapes": dict(evaluated_sample.get("shapes", {})),
        "ik_fk_switches": dict(evaluated_sample.get("ik_fk_switches", {})),
    }

    arm_sample = evaluated_sample.get("arm")
    if arm is not None:
        location_source = arm_sample.get("location") if arm_sample is not None else None
        rotation_source = arm_sample.get("rotation_quaternion") if arm_sample is not None else None
        sample["arm"] = {
            "location": tuple(float(value) for value in location_source) if location_source is not None else _as_float_tuple(arm.location),
            "rotation_mode": _recording_object_rotation_mode(arm),
            "rotation_quaternion": tuple(float(value) for value in rotation_source) if rotation_source is not None else _as_float_tuple(_rotation_quaternion_from_object(arm)),
        }
    elif arm_sample is not None:
        sample["arm"] = {
            "location": tuple(float(value) for value in arm_sample.get("location", (0.0, 0.0, 0.0))),
            "rotation_mode": str(arm_sample.get("rotation_mode", "XYZ")),
            "rotation_quaternion": tuple(float(value) for value in arm_sample.get("rotation_quaternion", (1.0, 0.0, 0.0, 0.0))),
        }

    pose = arm.pose.bones if arm is not None and getattr(arm, "pose", None) is not None else None
    for bone_name, bone_sample in evaluated_sample.get("bones", {}).items():
        pose_bone = (state.recording_pose_bones.get(bone_name) if arm is state.recording_armature_ref else None) or (pose.get(bone_name) if pose is not None else None)
        location_source = bone_sample.get("location")
        rotation_source = bone_sample.get("rotation_quaternion")
        basis_quat = None
        if pose_bone is not None and rotation_source is None:
            basis_quat = pose_bone.matrix_basis.to_quaternion()
            basis_quat.normalize()
        sample["bones"][bone_name] = {
            "location": (
                tuple(float(value) for value in location_source)
                if location_source is not None
                else _as_float_tuple(pose_bone.location)
                if pose_bone is not None
                else tuple(float(value) for value in bone_sample.get("location", (0.0, 0.0, 0.0)))
            ),
            "rotation_mode": _recording_pose_bone_rotation_mode(arm, bone_name, pose_bone) if pose_bone is not None else str(bone_sample.get("rotation_mode", "XYZ")),
            "rotation_quaternion": (
                tuple(float(value) for value in rotation_source)
                if rotation_source is not None
                else _as_float_tuple(basis_quat)
                if basis_quat is not None
                else tuple(float(value) for value in bone_sample.get("rotation_quaternion", (1.0, 0.0, 0.0, 0.0)))
            ),
        }
    return sample


def _build_recording_transition_source_sample(arm, record_bones, face, record_shapes, target_context=None):
    return _build_recording_sample(arm, record_bones, face, record_shapes, target_context)


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
    state.recording_transition_target_sample = None
    return transition_last_frame


def _set_recording_progress(frame_start: int, last_written_frame):
    state.recording_last_written_frame = last_written_frame
    if last_written_frame is None or last_written_frame < frame_start:
        state.recording_sample_count = 0
        return 0
    state.recording_sample_count = int(last_written_frame - frame_start + 1)
    return int(state.recording_sample_count)


def _process_recording_raw_frame(scene, session, raw_frame):
    arm = state.recording_armature_ref
    face = state.recording_face_ref
    preview_arm = session.get("preview_arm")
    target_context = session.get("target_context")
    frame_start = int(session.get("frame_start", 1))
    frame_end = int(session.get("frame_end", frame_start))
    use_arkit_face = bool(session.get("use_arkit_face"))
    lock_to_center = bool(session.get("lock_to_center", True))
    current_frame = _current_recording_frame(scene, raw_frame.get("timestamp"))
    effective_frame = min(current_frame, frame_end)
    dirty_bone_names = () if raw_frame.get("body_dirty") else raw_frame.get("dirty_bone_names", ())

    evaluated_sample = target_runtime.evaluate_target_sample(
        scene,
        arm,
        face,
        preview_arm,
        raw_frame.get("root"),
        raw_frame.get("waist"),
        raw_frame.get("bones", {}),
        dirty_bone_names,
        raw_frame.get("vmc_blends", {}),
        raw_frame.get("canonical_vmc_blends", {}),
        raw_frame.get("arkit_blends", {}),
        raw_frame.get("dirty_vmc_blend_names", ()),
        raw_frame.get("dirty_arkit_blend_names", ()),
        lock_to_center,
        use_arkit_face,
        target_context,
    )
    current_sample = _build_recording_sample_from_evaluated(arm, evaluated_sample)
    has_vmc_input = bool(
        raw_frame.get("root") is not None
        or raw_frame.get("waist") is not None
        or raw_frame.get("bones")
        or raw_frame.get("vmc_blends")
    )
    has_arkit_input = use_arkit_face and bool(raw_frame.get("arkit_blends"))
    has_valid_input = has_vmc_input or has_arkit_input

    if session.get("transition_pending"):
        transition_target_sample = session.get("transition_target_sample")
        if has_valid_input:
            transition_target_sample = current_sample
            session["transition_target_sample"] = transition_target_sample
        elif transition_target_sample is None:
            return current_frame < frame_end

        transition_last_frame = int(session.get("transition_last_frame", frame_start))
        if effective_frame < transition_last_frame:
            return current_frame < frame_end

        transition_target_sample = transition_target_sample or current_sample
        transition_source_sample = session.get("transition_source_sample") or transition_target_sample
        span = max(1, transition_last_frame - frame_start)
        for frame in range(frame_start, transition_last_frame + 1):
            factor = 0.0 if transition_last_frame == frame_start else (frame - frame_start) / float(span)
            transition_sample = _interpolate_recording_sample(
                transition_source_sample,
                transition_target_sample,
                factor,
            )
            _cache_recording_sample(transition_sample, frame)
        session["last_sample"] = transition_target_sample
        session["last_written_frame"] = transition_last_frame
        _set_recording_progress(frame_start, transition_last_frame)
        session["transition_pending"] = False
        session["transition_source_sample"] = None
        session["transition_target_sample"] = None

    last_sample = session.get("last_sample")
    last_written_frame = int(session.get("last_written_frame", frame_start - 1))

    if not has_valid_input and last_sample is None:
        return current_frame < frame_end

    previous_sample = last_sample if last_sample is not None else current_sample
    if bool(session.get("interpolation_enabled")) and effective_frame > last_written_frame + 1:
        frame_span = float(effective_frame - last_written_frame)
        for frame in range(last_written_frame + 1, effective_frame):
            factor = (frame - last_written_frame) / frame_span
            interpolated_sample = _interpolate_recording_sample(previous_sample, current_sample, factor)
            _cache_recording_sample(interpolated_sample, frame)

    if effective_frame >= last_written_frame:
        _cache_recording_sample(current_sample, effective_frame)
        session["last_written_frame"] = effective_frame
        _set_recording_progress(frame_start, effective_frame)
        session["last_sample"] = current_sample

    return current_frame < frame_end


def _rebuild_recording_tracks_from_raw_frames(scene):
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        state.recording_tracks = {}
        state.recording_last_sample = None
        state.recording_sample_count = 0
        return 0

    raw_frames = list(state.recording_raw_frames)
    if state.recording_source_start_ts <= 0.0 and raw_frames:
        state.recording_source_start_ts = float(raw_frames[0].get("timestamp", time.time()))

    state.recording_tracks = {}
    frame_start = int(state.recording_start_frame if state.recording_start_frame is not None else getattr(scene, "frame_current", 1))
    frame_end = int(state.recording_end_frame if state.recording_end_frame is not None else frame_start)
    raw_frames = _coalesce_recording_raw_frames(scene, raw_frames, frame_start, frame_end)
    preview_arm = getattr(scene, "vmc_link_preview_armature", None)
    arm = state.recording_armature_ref
    session = {
        "scene": scene,
        "preview_arm": preview_arm,
        "target_context": _build_receiver_target_context(scene, arm, preview_arm) if arm is not None else None,
        "use_arkit_face": is_arkit_face_source_enabled(scene),
        "lock_to_center": bool(getattr(scene, "vmc_link_lock_to_center", True)),
        "frame_start": frame_start,
        "frame_end": frame_end,
        "transition_pending": bool(state.recording_transition_enabled),
        "transition_source_sample": state.recording_transition_source_sample,
        "transition_target_sample": None,
        "transition_last_frame": min(frame_end, frame_start + max(0, int(state.recording_transition_frames) - 1)),
        "last_sample": None,
        "last_written_frame": frame_start - 1,
        "interpolation_enabled": bool(state.recording_interpolation_enabled),
    }
    _apply_mmd_root_motion_start_location(
        session["target_context"],
        state.recording_mmd_root_motion_start_location,
    )
    state.recording_last_sample = None
    _set_recording_progress(frame_start, frame_start - 1)
    for raw_frame in raw_frames:
        if not _process_recording_raw_frame(scene, session, raw_frame):
            break

    state.recording_last_sample = session.get("last_sample")
    return int(state.recording_sample_count)


def record_current_sample(scene, source_timestamp=None):
    current_frame = _current_recording_frame(scene, source_timestamp)
    frame_end = int(state.recording_end_frame if state.recording_end_frame is not None else current_frame)
    if state.recording_start_frame is not None and frame_end < state.recording_start_frame:
        _stop_recording_session(scene)
        return

    effective_frame = min(current_frame, frame_end)
    if effective_frame > (state.recording_last_written_frame if state.recording_last_written_frame is not None else frame_end):
        _set_recording_progress(int(state.recording_start_frame), effective_frame)

    if current_frame >= frame_end:
        _stop_recording_session(scene)


def _apply_preview_root_motion(preview_arm, root, waist, bones, context, lock_to_center: bool):
    if preview_arm is None or getattr(preview_arm, "type", None) != "ARMATURE":
        return False

    changed = False

    if lock_to_center:
        desired_location = (0.0, 0.0, 0.0)
        cached_location = state.receiver_preview_apply_arm_location
        if cached_location is None:
            cached_location = _as_float_tuple(preview_arm.location)
        if _vec_values_changed(cached_location, desired_location):
            preview_arm.location = desired_location
            state.receiver_preview_apply_arm_location = desired_location
            changed = True
        else:
            state.receiver_preview_apply_arm_location = cached_location
        return changed

    source_name, raw_root_motion = _select_root_motion_pose(root, waist, bones, include_hips=True)
    if raw_root_motion is None:
        return changed

    current_location, _rotation = helpers.convert_vmc_pose(*raw_root_motion)
    if context.get("root_source") != source_name or context.get("root_baseline_location") is None:
        context["root_source"] = source_name
        context["root_baseline_location"] = current_location.copy()
        if context.get("preview_start_location") is None:
            context["preview_start_location"] = preview_arm.location.copy()

    desired_location = context["preview_start_location"] + (current_location - context["root_baseline_location"])
    cached_location = state.receiver_preview_apply_arm_location
    if cached_location is None:
        cached_location = _as_float_tuple(preview_arm.location)
    if _vec_values_changed(cached_location, desired_location):
        preview_arm.location = desired_location
        state.receiver_preview_apply_arm_location = (
            float(desired_location[0]),
            float(desired_location[1]),
            float(desired_location[2]),
        )
        changed = True
    else:
        state.receiver_preview_apply_arm_location = cached_location
    return changed


def _canonical_blend_value(canonical_blends, blends, name: str) -> float:
    if canonical_blends:
        try:
            return float(canonical_blends.get(name, 0.0))
        except (TypeError, ValueError):
            return 0.0
    return mapping.get_blend_value(blends, name)


def _as_float_tuple(values):
    return tuple(float(value) for value in values)


def _vec_values_changed(current, values, eps: float = constants.LOC_EPS) -> bool:
    dx = float(current[0]) - float(values[0])
    dy = float(current[1]) - float(values[1])
    dz = float(current[2]) - float(values[2])
    return (dx * dx + dy * dy + dz * dz) > (eps * eps)


def _quat_values_changed(current, values, eps: float = constants.ROT_EPS) -> bool:
    current_dot = (
        float(current[0]) * float(values[0])
        + float(current[1]) * float(values[1])
        + float(current[2]) * float(values[2])
        + float(current[3]) * float(values[3])
    )
    return (1.0 - abs(current_dot)) > eps


def _compute_eye_look_quaternion(look_h: float, look_v: float):
    look_h = max(-1.0, min(1.0, look_h))
    look_v = max(-1.0, min(1.0, look_v))
    yaw = look_h * 1.0
    pitch = -look_v * 1.0
    q_yaw = Quaternion((0.0, 1.0, 0.0), yaw)
    q_pitch = Quaternion((1.0, 0.0, 0.0), pitch)
    rotation = q_yaw @ q_pitch
    rotation.normalize()
    return rotation


def _ensure_preview_apply_cache(preview_arm, preview_face):
    if preview_arm is not None and state.receiver_preview_apply_armature_ref is not preview_arm:
        state.receiver_preview_apply_armature_ref = preview_arm
        state.receiver_preview_apply_arm_location = None
        state.receiver_preview_apply_arm_rotation = None
        state.receiver_preview_apply_bone_rotations = {}
    if preview_face is not None and state.receiver_preview_apply_face_ref is not preview_face:
        state.receiver_preview_apply_face_ref = preview_face
        state.receiver_preview_apply_shape_values = {}


def _apply_preview_armature(preview_arm, root, waist, bones, dirty_bone_names, blends, canonical_blends, lock_to_center: bool, context=None):
    if preview_arm is None or getattr(preview_arm, "type", None) != "ARMATURE":
        return False

    _ensure_preview_apply_cache(preview_arm, None)
    changed = False

    if context is None:
        context = {"preview": preview_arm, "preview_start_location": preview_arm.location.copy()}
    changed = _apply_preview_root_motion(preview_arm, root, waist, bones, context, lock_to_center) or changed

    runtime_entries = context.get("runtime_entries", ())
    if not bool(context.get("rotation_modes_ready")):
        if preview_arm.rotation_mode != "QUATERNION":
            preview_arm.rotation_mode = "QUATERNION"
        for _vmc_name, pose_bone, _rest_rotation, _rest_rotation_inv in runtime_entries:
            if pose_bone.rotation_mode != "QUATERNION":
                pose_bone.rotation_mode = "QUATERNION"
        context["rotation_modes_ready"] = True

    if root is not None:
        _, root_quat = helpers.convert_vmc_pose(*root)
        cached_rotation = state.receiver_preview_apply_arm_rotation
        if cached_rotation is None:
            cached_rotation = _as_float_tuple(preview_arm.rotation_quaternion)
        if _quat_values_changed(cached_rotation, root_quat):
            preview_arm.rotation_quaternion = root_quat
            state.receiver_preview_apply_arm_rotation = (
                float(root_quat[0]),
                float(root_quat[1]),
                float(root_quat[2]),
                float(root_quat[3]),
            )
            changed = True
        else:
            state.receiver_preview_apply_arm_rotation = cached_rotation

    pose = preview_arm.pose.bones
    eye_left_name = context.get("eye_left_name")
    eye_right_name = context.get("eye_right_name")
    eye_left_driven_by_bone = False
    eye_right_driven_by_bone = False

    if dirty_bone_names:
        entries_by_source = context.get("runtime_entries_by_source", {})
        entry_iter = (
            entry
            for source_name in dirty_bone_names
            for entry in (entries_by_source.get(source_name),)
            if entry is not None
        )
    else:
        entry_iter = runtime_entries

    for vmc_name, pose_bone, rest_rotation, rest_rotation_inv in entry_iter:
        raw = bones.get(vmc_name)
        if raw is None:
            continue
        px, py, pz, qx, qy, qz, qw = raw
        rotate_quat = helpers.convert_vmc_quaternion(qx, qy, qz, qw)
        local_q = rest_rotation_inv @ rotate_quat @ rest_rotation
        local_q.normalize()

        cached_rotation = state.receiver_preview_apply_bone_rotations.get(pose_bone.name)
        if cached_rotation is None:
            cached_rotation = _as_float_tuple(pose_bone.rotation_quaternion)
        if _quat_values_changed(cached_rotation, local_q):
            pose_bone.rotation_quaternion = local_q
            state.receiver_preview_apply_bone_rotations[pose_bone.name] = (
                float(local_q[0]),
                float(local_q[1]),
                float(local_q[2]),
                float(local_q[3]),
            )
            changed = True
        else:
            state.receiver_preview_apply_bone_rotations[pose_bone.name] = cached_rotation

        if eye_left_name and pose_bone.name == eye_left_name:
            eye_left_driven_by_bone = True
        if eye_right_name and pose_bone.name == eye_right_name:
            eye_right_driven_by_bone = True

    if blends or canonical_blends:
        if eye_left_name and eye_left_name in pose and not eye_left_driven_by_bone:
            left_h = (_canonical_blend_value(canonical_blends, blends, "LookRight_L") or _canonical_blend_value(canonical_blends, blends, "LookRight")) - (
                _canonical_blend_value(canonical_blends, blends, "LookLeft_L") or _canonical_blend_value(canonical_blends, blends, "LookLeft")
            )
            left_v = (_canonical_blend_value(canonical_blends, blends, "LookUp_L") or _canonical_blend_value(canonical_blends, blends, "LookUp")) - (
                _canonical_blend_value(canonical_blends, blends, "LookDown_L") or _canonical_blend_value(canonical_blends, blends, "LookDown")
            )
            eye_bone = pose[eye_left_name]
            desired_rotation = _compute_eye_look_quaternion(left_h, left_v)
            cached_rotation = state.receiver_preview_apply_bone_rotations.get(eye_bone.name)
            if cached_rotation is None:
                cached_rotation = _as_float_tuple(eye_bone.rotation_quaternion)
            if _quat_values_changed(cached_rotation, desired_rotation):
                eye_bone.rotation_mode = "QUATERNION"
                eye_bone.rotation_quaternion = desired_rotation
                state.receiver_preview_apply_bone_rotations[eye_bone.name] = (
                    float(desired_rotation[0]),
                    float(desired_rotation[1]),
                    float(desired_rotation[2]),
                    float(desired_rotation[3]),
                )
                changed = True
            else:
                state.receiver_preview_apply_bone_rotations[eye_bone.name] = cached_rotation

        if eye_right_name and eye_right_name in pose and not eye_right_driven_by_bone:
            right_h = (_canonical_blend_value(canonical_blends, blends, "LookRight_R") or _canonical_blend_value(canonical_blends, blends, "LookRight")) - (
                _canonical_blend_value(canonical_blends, blends, "LookLeft_R") or _canonical_blend_value(canonical_blends, blends, "LookLeft")
            )
            right_v = (_canonical_blend_value(canonical_blends, blends, "LookUp_R") or _canonical_blend_value(canonical_blends, blends, "LookUp")) - (
                _canonical_blend_value(canonical_blends, blends, "LookDown_R") or _canonical_blend_value(canonical_blends, blends, "LookDown")
            )
            eye_bone = pose[eye_right_name]
            desired_rotation = _compute_eye_look_quaternion(right_h, right_v)
            cached_rotation = state.receiver_preview_apply_bone_rotations.get(eye_bone.name)
            if cached_rotation is None:
                cached_rotation = _as_float_tuple(eye_bone.rotation_quaternion)
            if _quat_values_changed(cached_rotation, desired_rotation):
                eye_bone.rotation_mode = "QUATERNION"
                eye_bone.rotation_quaternion = desired_rotation
                state.receiver_preview_apply_bone_rotations[eye_bone.name] = (
                    float(desired_rotation[0]),
                    float(desired_rotation[1]),
                    float(desired_rotation[2]),
                    float(desired_rotation[3]),
                )
                changed = True
            else:
                state.receiver_preview_apply_bone_rotations[eye_bone.name] = cached_rotation
    return changed


def _apply_preview_face(preview_face, arkit_blends, dirty_arkit_blend_names=()):
    if not mapping.has_shape_keys(preview_face):
        return False

    _ensure_preview_apply_cache(None, preview_face)
    changed = False

    if dirty_arkit_blend_names:
        blend_iter = (
            (arkit_name, arkit_blends[arkit_name])
            for arkit_name in dirty_arkit_blend_names
            if arkit_name in arkit_blends
        )
    else:
        blend_iter = arkit_blends.items()

    for arkit_name, val in blend_iter:
        key_block = state.preview_cached_arkit_key_blocks.get(arkit_name)
        if key_block is None:
            actual = state.preview_cached_arkit_blend_map.get(arkit_name) or mapping.find_arkit_shapekey_name(preview_face, arkit_name, None)
            if not actual:
                continue
            blocks = preview_face.data.shape_keys.key_blocks
            key_block = blocks.get(actual)
            if key_block is None:
                continue
            state.preview_cached_arkit_blend_map[arkit_name] = actual
            state.preview_cached_arkit_key_blocks[arkit_name] = key_block
        try:
            numeric_val = float(val)
        except (TypeError, ValueError):
            continue
        cached_value = state.receiver_preview_apply_shape_values.get(key_block.name)
        if cached_value is None:
            cached_value = float(key_block.value)
        if abs(float(cached_value) - numeric_val) > constants.SHAPE_EPS:
            key_block.value = numeric_val
            state.receiver_preview_apply_shape_values[key_block.name] = numeric_val
            changed = True
        else:
            state.receiver_preview_apply_shape_values[key_block.name] = cached_value
    return changed


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

    with state.buffer_lock:
        has_queued_frames = bool(state.raw_frame_queue)

    if preview_arm is None and preview_face is None and arm is None and face is None:
        return rate
    if not state.dirty and not has_queued_frames:
        state.frame_snapshot_deadline_ts = 0.0
        if get_latest_receiver_timestamp(scene) > 0.0:
            tag_view3d_ui_redraw_if_due(now, interval=IDLE_UI_REDRAW_INTERVAL_SEC)
        return rate

    if not has_queued_frames:
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
    else:
        state.frame_snapshot_deadline_ts = 0.0

    latest_raw_frame = None
    with state.buffer_lock:
        if state.raw_frame_queue:
            latest_raw_frame = state.raw_frame_queue[-1]
            dirty_bone_from_frames = set()
            dirty_vmc_from_frames = set()
            dirty_arkit_from_frames = set()
            body_dirty_from_frames = False
            vmc_blends_dirty_from_frames = False
            vmc_eye_blends_dirty_from_frames = False
            arkit_blends_dirty_from_frames = False
            for frame in state.raw_frame_queue:
                dirty_bone_from_frames.update(frame.get("dirty_bone_names", ()))
                dirty_vmc_from_frames.update(frame.get("dirty_vmc_blend_names", ()))
                dirty_arkit_from_frames.update(frame.get("dirty_arkit_blend_names", ()))
                body_dirty_from_frames = body_dirty_from_frames or bool(frame.get("body_dirty"))
                vmc_blends_dirty_from_frames = vmc_blends_dirty_from_frames or bool(frame.get("vmc_blends_dirty"))
                vmc_eye_blends_dirty_from_frames = vmc_eye_blends_dirty_from_frames or bool(frame.get("vmc_eye_blends_dirty"))
                arkit_blends_dirty_from_frames = arkit_blends_dirty_from_frames or bool(frame.get("arkit_blends_dirty"))
            state.raw_frame_queue.clear()
        if latest_raw_frame is None:
            root = state.root_buf
            waist = state.waist_buf
            bones = dict(state.canonical_bone_buf)
            dirty_bone_names = state.raw_frame_dirty_bone_names
            dirty_vmc_blend_names = state.raw_frame_dirty_vmc_blend_names
            dirty_arkit_blend_names = state.raw_frame_dirty_arkit_blend_names
            blends = dict(state.blend_buf)
            canonical_vmc_blends = dict(state.canonical_vmc_blend_buf)
            arkit_blends = dict(state.arkit_blend_buf)
            body_dirty = bool(state.raw_frame_body_dirty)
            vmc_blends_dirty = bool(state.raw_frame_vmc_blend_dirty)
            vmc_eye_blends_dirty = bool(state.raw_frame_vmc_eye_blend_dirty)
            arkit_blends_dirty = bool(state.raw_frame_arkit_blend_dirty)
        else:
            root = latest_raw_frame.get("root")
            waist = latest_raw_frame.get("waist")
            bones = latest_raw_frame.get("bones", {})
            dirty_bone_names = dirty_bone_from_frames | state.raw_frame_dirty_bone_names
            dirty_vmc_blend_names = dirty_vmc_from_frames | state.raw_frame_dirty_vmc_blend_names
            dirty_arkit_blend_names = dirty_arkit_from_frames | state.raw_frame_dirty_arkit_blend_names
            blends = latest_raw_frame.get("vmc_blends", {})
            canonical_vmc_blends = latest_raw_frame.get("canonical_vmc_blends", {})
            arkit_blends = latest_raw_frame.get("arkit_blends", {})
            body_dirty = body_dirty_from_frames or bool(state.raw_frame_body_dirty)
            vmc_blends_dirty = vmc_blends_dirty_from_frames or bool(state.raw_frame_vmc_blend_dirty)
            vmc_eye_blends_dirty = vmc_eye_blends_dirty_from_frames or bool(state.raw_frame_vmc_eye_blend_dirty)
            arkit_blends_dirty = arkit_blends_dirty_from_frames or bool(state.raw_frame_arkit_blend_dirty)
        state.dirty = False
        state.raw_frame_dirty_bone_names = set()
        state.raw_frame_dirty_vmc_blend_names = set()
        state.raw_frame_dirty_arkit_blend_names = set()
        state.raw_frame_body_dirty = False
        state.raw_frame_vmc_blend_dirty = False
        state.raw_frame_vmc_eye_blend_dirty = False
        state.raw_frame_arkit_blend_dirty = False
    dirty_bone_names = frozenset(dirty_bone_names or ())

    _ensure_preview_cache_targets(preview_arm, preview_face)
    _ensure_target_face_cache_target(face)

    preview_context = _ensure_receiver_preview_context(scene, preview_arm) if preview_arm is not None else None
    preview_eye_look_enabled = bool(preview_context and (preview_context.get("eye_left_name") or preview_context.get("eye_right_name")))
    preview_armature_needs_update = bool(body_dirty or (vmc_eye_blends_dirty and preview_eye_look_enabled))
    preview_face_needs_update = bool(use_arkit_face and dirty_arkit_blend_names)
    any_runtime_write = False
    cached_target_context = state.receiver_target_context
    if cached_target_context.get("target") is not arm or cached_target_context.get("preview") is not preview_arm:
        cached_target_context = {}
    target_runtime_strategy = (
        str(cached_target_context.get("target_runtime_strategy", "")).strip().lower()
        if arm is not None
        else ""
    )
    if arm is not None and not target_runtime_strategy:
        target_runtime_strategy = mapping_target_rig.resolve_scene_runtime_strategy(scene, arm)
    target_root_motion_needs_update = bool(body_dirty)
    if target_runtime_strategy == mapping_target_rig.RUNTIME_STRATEGY_MMD and body_dirty:
        dirty_bone_names = frozenset()
    target_armature_needs_update = bool(
        dirty_bone_names
        or (
            body_dirty
            and target_runtime_strategy == mapping_target_rig.RUNTIME_STRATEGY_MMD
        )
        or (
            vmc_eye_blends_dirty
            and target_runtime_strategy != mapping_target_rig.RUNTIME_STRATEGY_ARP
        )
    )
    target_shape_needs_update = bool((not use_arkit_face and dirty_vmc_blend_names) or (use_arkit_face and dirty_arkit_blend_names))

    if preview_armature_needs_update:
        if preview_context is None:
            preview_context = _ensure_receiver_preview_context(scene, preview_arm)
        any_runtime_write = (
            _apply_preview_armature(preview_arm, root, waist, bones, dirty_bone_names, blends, canonical_vmc_blends, lock_to_center, preview_context)
            or any_runtime_write
        )
    if preview_face_needs_update:
        any_runtime_write = _apply_preview_face(preview_face, arkit_blends, dirty_arkit_blend_names) or any_runtime_write

    if any_runtime_write or state.recording:
        tag_view3d_ui_redraw_if_due(now)

    if not live_preview:
        return rate
    if arm is None and face is None:
        return rate

    if target_armature_needs_update and arm is not None and not state.cached_bone_map:
        mapping.rebuild_maps(scene)

    if target_shape_needs_update and (not use_arkit_face) and face is not None and not state.cached_blend_map:
        mapping.rebuild_maps(scene)
    elif target_shape_needs_update and use_arkit_face and face is not None and not state.cached_arkit_blend_map:
        mapping.rebuild_maps(scene)

    target_context = _ensure_receiver_target_context(scene, arm, preview_arm) if (arm is not None and (target_root_motion_needs_update or target_armature_needs_update)) else None
    if target_context is not None:
        _ensure_target_runtime_rotation_modes(arm, target_context)
    target_sample = None

    if target_root_motion_needs_update or target_armature_needs_update or target_shape_needs_update:
        target_sample = target_runtime.evaluate_target_sample(
            scene,
            arm,
            face,
            preview_arm,
            root,
            waist,
            bones,
            dirty_bone_names,
            blends,
            canonical_vmc_blends,
            arkit_blends,
            dirty_vmc_blend_names,
            dirty_arkit_blend_names,
            lock_to_center,
            use_arkit_face,
            target_context,
            evaluate_root_motion=target_root_motion_needs_update,
            evaluate_armature=target_armature_needs_update,
            evaluate_shapes=target_shape_needs_update,
        )
        any_runtime_write = target_runtime.apply_target_sample(arm, face, target_sample) or any_runtime_write

    if state.recording:
        has_vmc_input = state.last_packet_ts > 0.0 and (root is not None or waist is not None or bool(bones) or bool(blends))
        has_arkit_input = use_arkit_face and state.arkit_last_packet_ts > 0.0
        source_timestamp = None
        if latest_raw_frame is not None:
            source_timestamp = latest_raw_frame.get("timestamp")
        elif has_vmc_input:
            source_timestamp = float(state.last_packet_ts)
        elif has_arkit_input:
            source_timestamp = float(state.arkit_last_packet_ts)
        if source_timestamp is not None:
            record_current_sample(
                scene,
                source_timestamp,
            )
        if not state.recording:
            return rate
        tag_view3d_ui_redraw_if_due(now)

    if any_runtime_write:
        tag_view3d_ui_redraw_if_due(now)

    return rate
