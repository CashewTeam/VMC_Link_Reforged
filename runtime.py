import time

import bpy

from . import constants, helpers, mapping, network, properties, state


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
    if state.root_buf is not None and any(abs(val) > 1e-6 for val in state.root_buf[:3]):
        return "Root/Pos"
    if state.waist_buf is not None:
        return "Tra/Pos"
    if mapping.get_vmc_bone_pose(state.bone_buf, "Hips") is not None:
        return "Bone/Pos:Hips"
    return "无"


def get_receiver_status_label(scene) -> str:
    if not network.is_running():
        return "已停止"
    last_pkt = get_latest_receiver_timestamp(scene)
    if last_pkt == 0.0:
        return "等待连接"
    if (time.time() - last_pkt) <= 2.0:
        return "已连接" if getattr(scene, "vmc_link_live_preview", True) else "仅更新预览层"
    return "已断开"


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
                    pose_bone.keyframe_insert(data_path="rotation_quaternion")
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

    use_root_loc = bool(root is not None and any(abs(val) > 1e-6 for val in root[:3]))
    hips_pose = mapping.get_vmc_bone_pose(bones, "Hips")

    if use_root_loc:
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

    if root is not None and any(abs(val) > 1e-6 for val in root[3:6]):
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

    network.poll_osc_packets()
    tag_view3d_ui_redraw()

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
        tag_view3d_ui_redraw_if_due(now)
        return rate

    root = state.root_buf
    waist = state.waist_buf
    bones = dict(state.bone_buf)
    blends = dict(state.blend_buf)
    arkit_blends = dict(state.arkit_blend_buf)
    hips_pose = mapping.get_vmc_bone_pose(bones, "Hips")
    state.dirty = False
    _ensure_preview_cache_targets(preview_arm, preview_face)

    _apply_preview_armature(preview_arm, root, waist, bones, blends)
    if use_arkit_face:
        _apply_preview_face(preview_face, arkit_blends)

    tag_view3d_ui_redraw_if_due(now, force=True)

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
        use_root_loc = bool(root is not None and any(abs(val) > 1e-6 for val in root[:3]))
        if use_root_loc:
            root_loc, _ = helpers.convert_vmc_pose(*root)
            if helpers.vec_changed(arm.location, root_loc):
                arm.location = root_loc
        elif waist is not None:
            waist_loc, _ = helpers.convert_vmc_pose(*waist)
            if helpers.vec_changed(arm.location, waist_loc):
                arm.location = waist_loc
        elif hips_pose is not None:
            hips_loc, _ = helpers.convert_vmc_pose(*hips_pose)
            if helpers.vec_changed(arm.location, hips_loc):
                arm.location = hips_loc

        if root is not None and any(abs(val) > 1e-6 for val in root[3:6]):
            _, root_quat = helpers.convert_vmc_pose(*root)
            arm.rotation_mode = "QUATERNION"
            if helpers.quat_changed(arm.rotation_quaternion, root_quat):
                arm.rotation_quaternion = root_quat

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
