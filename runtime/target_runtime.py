import math

from mathutils import Matrix, Quaternion, Vector

from ..core import constants, helpers, state
from ..mapping import arp as mapping_arp
from ..mapping import mapper as mapping
from ..mapping import mmd as mapping_mmd
from ..mapping import target_rig as mapping_target_rig

def _empty_target_sample(_arm_obj, face_obj):
    return {
        "arm": None,
        "bones": {},
        "shape_datablock": face_obj.data.shape_keys if mapping.has_shape_keys(face_obj) else None,
        "shapes": {},
        "ik_fk_switches": {},
        "ik_fk_pose_bones": {},
        "shape_blocks": {},
    }


def _ensure_arm_sample(sample):
    arm_sample = sample.get("arm")
    if arm_sample is not None:
        return arm_sample
    arm_sample = {}
    sample["arm"] = arm_sample
    return arm_sample


def _ensure_bone_sample(sample, pose_bone):
    bone_sample = sample["bones"].get(pose_bone.name)
    if bone_sample is not None:
        return bone_sample

    bone_sample = {
        "pose_bone": pose_bone,
    }
    sample["bones"][pose_bone.name] = bone_sample
    return bone_sample


def _select_root_motion_pose(root, waist, bones, include_hips: bool):
    hips_pose = mapping.get_vmc_bone_pose(bones, "Hips") if include_hips else None
    if root is not None and (_root_motion_has_position(root) or hips_pose is None):
        return "Root/Pos", root
    if waist is not None and (_root_motion_has_position(waist) or hips_pose is None):
        return "Tra/Pos", waist
    if include_hips and hips_pose is not None:
        return "Bone/Pos:Hips", hips_pose
    if root is not None:
        return "Root/Pos", root
    if waist is not None:
        return "Tra/Pos", waist
    return None, None


def _root_motion_location(raw):
    if raw is None:
        return None
    return helpers.convert_vmc_location(raw[0], raw[1], raw[2])


def _root_motion_has_position(raw) -> bool:
    location = _root_motion_location(raw)
    return location is not None and location.length > constants.LOC_EPS


def _quat_angle_degrees(a, b) -> float:
    dot = max(-1.0, min(1.0, abs(a.dot(b))))
    return 2.0 * math.degrees(math.acos(dot))


def _filter_rotation(filtered_rotations, key: str, desired_rotation):
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


def _source_local_rotation_from_pose(raw_pose, source_start_basis=None, source_rest=None, source_rest_inv=None, source_bone=None):
    if raw_pose is None:
        if source_start_basis is not None:
            return source_start_basis.copy()
        return Quaternion()

    world_rotation = helpers.convert_vmc_quaternion(raw_pose[3], raw_pose[4], raw_pose[5], raw_pose[6])
    if source_rest is None or source_rest_inv is None:
        if source_bone is None:
            return world_rotation
        source_rest = source_bone.bone.matrix_local.to_quaternion()
        source_rest.normalize()
        source_rest_inv = source_rest.inverted()
    local_rotation = source_rest_inv @ world_rotation @ source_rest
    local_rotation.normalize()
    return local_rotation


def _source_pose_matrix_from_raw(source_bone, raw_bones, start_basis_rotations, cache):
    bone_name = source_bone.name
    cached = cache.get(bone_name)
    if cached is not None:
        return cached.copy()

    source_rest = source_bone.bone.matrix_local.to_quaternion()
    source_rest.normalize()
    source_rest_inv = source_rest.inverted()
    local_rotation = _source_local_rotation_from_pose(
        raw_bones.get(bone_name),
        start_basis_rotations.get(bone_name),
        source_rest,
        source_rest_inv,
        source_bone,
    )
    basis_matrix = Matrix.LocRotScale(
        source_bone.location.copy(),
        local_rotation,
        source_bone.scale.copy(),
    )
    bone_ref = source_bone.bone
    matrix_local = bone_ref.matrix_local.copy()
    parent_bone = source_bone.parent
    if parent_bone is None:
        pose_matrix = bone_ref.convert_local_to_pose(
            basis_matrix,
            matrix_local,
        )
    else:
        parent_pose_matrix = _source_pose_matrix_from_raw(
            parent_bone,
            raw_bones,
            start_basis_rotations,
            cache,
        )
        pose_matrix = bone_ref.convert_local_to_pose(
            basis_matrix,
            matrix_local,
            parent_matrix=parent_pose_matrix,
            parent_matrix_local=parent_bone.bone.matrix_local,
        )
    cache[bone_name] = pose_matrix.copy()
    return pose_matrix


def _resolve_target_pose_matrix_from_sample(pose_bone, sample, cache):
    bone_name = pose_bone.name
    cached = cache.get(bone_name)
    if cached is not None:
        return cached.copy()

    bone_sample = sample.get("bones", {}).get(bone_name, {})
    location = bone_sample.get("location")
    if location is None:
        location = pose_bone.location.copy()
    rotation = bone_sample.get("rotation_quaternion")
    if rotation is None:
        rotation = pose_bone.rotation_quaternion.copy()
    scale = pose_bone.scale.copy()
    basis_matrix = Matrix.LocRotScale(location, rotation, scale)
    bone_ref = pose_bone.bone
    matrix_local = bone_ref.matrix_local.copy()
    parent_bone = pose_bone.parent
    if parent_bone is None:
        pose_matrix = bone_ref.convert_local_to_pose(
            basis_matrix,
            matrix_local,
        )
    else:
        parent_pose_matrix = _resolve_target_pose_matrix_from_sample(parent_bone, sample, cache)
        pose_matrix = bone_ref.convert_local_to_pose(
            basis_matrix,
            matrix_local,
            parent_matrix=parent_pose_matrix,
            parent_matrix_local=parent_bone.bone.matrix_local,
        )
    cache[bone_name] = pose_matrix.copy()
    return pose_matrix


def _remap_local_delta_with_rest_quaternions(source_rest, source_rest_inv, target_rest, target_rest_inv, source_delta):
    world_delta = source_rest @ source_delta @ source_rest_inv
    world_delta.normalize()
    target_delta = target_rest_inv @ world_delta @ target_rest
    target_delta.normalize()
    return target_delta


def _signed_projected_angle(from_vec, to_vec, axis) -> float:
    from_proj = from_vec - axis * from_vec.dot(axis)
    to_proj = to_vec - axis * to_vec.dot(axis)
    if from_proj.length_squared <= 1e-12 or to_proj.length_squared <= 1e-12:
        return 0.0
    from_proj.normalize()
    to_proj.normalize()
    angle = from_proj.angle(to_proj)
    if axis.dot(from_proj.cross(to_proj)) < 0.0:
        angle = -angle
    return angle


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


def _canonical_blend_value(canonical_blends, blends, name: str) -> float:
    if canonical_blends:
        try:
            return float(canonical_blends.get(name, 0.0))
        except (TypeError, ValueError):
            return 0.0
    return mapping.get_blend_value(blends, name)


def _mmd_root_motion_basis_location(sample, root_motion_bone, start_matrix, desired_location):
    desired_matrix = Matrix.LocRotScale(
        desired_location,
        start_matrix.to_quaternion(),
        start_matrix.to_scale(),
    )
    bone_ref = root_motion_bone.bone
    parent_bone = root_motion_bone.parent
    if parent_bone is None:
        basis_matrix = bone_ref.convert_local_to_pose(
            desired_matrix,
            bone_ref.matrix_local,
            invert=True,
        )
    else:
        parent_pose_matrix = _resolve_target_pose_matrix_from_sample(parent_bone, sample, {})
        basis_matrix = bone_ref.convert_local_to_pose(
            desired_matrix,
            bone_ref.matrix_local,
            parent_matrix=parent_pose_matrix,
            parent_matrix_local=parent_bone.bone.matrix_local,
            invert=True,
        )
    return basis_matrix.to_translation()


def _evaluate_target_root_motion(sample, arm_obj, root, waist, bones, context, lock_to_center: bool):
    if arm_obj is None or context.get("target_start_world") is None:
        return

    if lock_to_center and context.get("is_arp"):
        context["root_source"] = None
        context["root_baseline_location"] = None
        context["root_baseline_rotation"] = None
        root_motion_bone = context.get("arp_root_motion_bone")
        start_location = context.get("arp_root_motion_start_location")
        if root_motion_bone is not None and start_location is not None:
            bone_sample = _ensure_bone_sample(sample, root_motion_bone)
            bone_sample["location"] = start_location.copy()
        return
    if lock_to_center and context.get("target_runtime_strategy") == mapping_target_rig.RUNTIME_STRATEGY_MMD:
        root_motion_bone = context.get("mmd_root_motion_bone")
        start_matrix = context.get("mmd_root_motion_start_matrix")
        start_rotation = context.get("mmd_root_motion_start_rotation")
        start_location = context.get("mmd_root_motion_start_location")
        if root_motion_bone is not None and start_matrix is not None and start_rotation is not None:
            if start_location is None:
                start_location = start_matrix.to_translation()
            bone_sample = _ensure_bone_sample(sample, root_motion_bone)
            bone_sample["location"] = _mmd_root_motion_basis_location(
                sample,
                root_motion_bone,
                start_matrix,
                start_location,
            )
            bone_sample["rotation_quaternion"] = start_rotation.copy()
        return

    source_name, raw = _select_root_motion_pose(root, waist, bones, include_hips=not lock_to_center)
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
    if source_name == "Bone/Pos:Hips":
        delta_rotation = Matrix.Identity(3).to_quaternion()
    else:
        delta_rotation = current_rotation @ baseline_rotation.inverted()
        delta_rotation.normalize()
    if lock_to_center:
        delta_location = Vector((0.0, 0.0, 0.0))

    if context.get("is_arp"):
        root_motion_bone = context.get("arp_root_motion_bone")
        start_location = context.get("arp_root_motion_start_location")
        if root_motion_bone is None or start_location is None:
            return
        local_delta = (context.get("target_world_rotation_inv") or arm_obj.matrix_world.to_3x3().inverted()) @ delta_location
        local_delta = Vector((-local_delta.x, -local_delta.y, local_delta.z))
        bone_sample = _ensure_bone_sample(sample, root_motion_bone)
        bone_sample["location"] = start_location + local_delta
        return
    if context.get("target_runtime_strategy") == mapping_target_rig.RUNTIME_STRATEGY_MMD:
        root_motion_bone = context.get("mmd_root_motion_bone")
        start_matrix = context.get("mmd_root_motion_start_matrix")
        start_rotation = context.get("mmd_root_motion_start_rotation")
        start_location = context.get("mmd_root_motion_start_location")
        if root_motion_bone is None or start_matrix is None or start_rotation is None:
            return
        if start_location is None:
            start_location = start_matrix.to_translation()
        object_delta = (context.get("target_world_rotation_inv") or arm_obj.matrix_world.to_3x3().inverted()) @ delta_location
        target_start_rotation = context.get("target_start_world_rotation") or arm_obj.matrix_world.to_quaternion()
        object_delta_rotation = target_start_rotation.inverted() @ delta_rotation @ target_start_rotation
        root_rest_rotation = root_motion_bone.bone.matrix_local.to_quaternion()
        local_delta_rotation = root_rest_rotation.inverted() @ object_delta_rotation @ root_rest_rotation
        local_delta_rotation.normalize()
        desired_rotation = local_delta_rotation @ start_rotation
        desired_rotation.normalize()
        bone_sample = _ensure_bone_sample(sample, root_motion_bone)
        bone_sample["location"] = _mmd_root_motion_basis_location(
            sample,
            root_motion_bone,
            start_matrix,
            start_location + object_delta,
        )
        bone_sample["rotation_quaternion"] = desired_rotation
        return

    start_location = context.get("target_start_world_location")
    start_rotation = context.get("target_start_world_rotation")
    start_scale = context.get("target_start_world_scale")
    if start_location is None or start_rotation is None or start_scale is None:
        start_location, start_rotation, start_scale = context["target_start_world"].decompose()
    desired_world = Matrix.LocRotScale(
        start_location + delta_location,
        delta_rotation @ start_rotation,
        start_scale,
    )
    desired_location, desired_rotation, _desired_scale = desired_world.decompose()
    arm_sample = _ensure_arm_sample(sample)
    arm_sample["location"] = desired_location.copy()
    arm_sample["rotation_quaternion"] = desired_rotation


def _evaluate_generic_target_armature(scene, arm_obj, bones, dirty_bone_names, blends, canonical_blends, sample, target_context=None):
    if arm_obj is None or getattr(arm_obj, "pose", None) is None:
        return

    pose = arm_obj.pose.bones
    runtime_entries = (target_context or {}).get("generic_runtime_entries", ())
    eye_left_name = (target_context or {}).get("eye_left_name") or state.cached_bone_map.get("LeftEye") or mapping.find_bone_name(arm_obj, "LeftEye", scene)
    eye_right_name = (target_context or {}).get("eye_right_name") or state.cached_bone_map.get("RightEye") or mapping.find_bone_name(arm_obj, "RightEye", scene)
    if eye_left_name:
        state.cached_bone_map["LeftEye"] = eye_left_name
    if eye_right_name:
        state.cached_bone_map["RightEye"] = eye_right_name

    eye_left_driven_by_bone = False
    eye_right_driven_by_bone = False

    if runtime_entries:
        if dirty_bone_names:
            entries_by_source = (target_context or {}).get("generic_runtime_entries_by_source", {})
            entry_iter = (
                (*entry, bones.get(source_name))
                for source_name in dirty_bone_names
                for entry in (entries_by_source.get(source_name),)
                if entry is not None
            )
        else:
            entry_iter = (
                (vmc_name, pose_bone, source_rest, source_rest_inv, target_rest, target_rest_inv, bones.get(vmc_name))
                for vmc_name, pose_bone, source_rest, source_rest_inv, target_rest, target_rest_inv in runtime_entries
            )
    else:
        entry_iter = []
        for vmc_name, raw in bones.items():
            actual = state.cached_bone_map.get(vmc_name) or mapping.find_bone_name(arm_obj, vmc_name, scene)
            if not actual or actual not in pose:
                continue
            state.cached_bone_map[vmc_name] = actual
            pose_bone = pose[actual]
            source_rest = None
            source_rest_inv = None
            target_rest = pose_bone.bone.matrix_local.to_quaternion()
            target_rest.normalize()
            entry_iter.append((vmc_name, pose_bone, source_rest, source_rest_inv, target_rest, target_rest.inverted(), raw))

    for vmc_name, pose_bone, source_rest, source_rest_inv, target_rest, target_rest_inv, raw in entry_iter:
        if raw is None:
            continue
        px, py, pz, qx, qy, qz, qw = raw
        rotate_quat = helpers.convert_vmc_quaternion(qx, qy, qz, qw)
        if source_rest is not None and source_rest_inv is not None:
            source_local = source_rest_inv @ rotate_quat @ source_rest
            source_local.normalize()
            rest_delta = target_rest_inv @ source_rest
            rest_delta.normalize()
            local_q = rest_delta @ source_local @ rest_delta.inverted()
        else:
            local_q = target_rest_inv @ rotate_quat @ target_rest
        local_q.normalize()

        bone_sample = _ensure_bone_sample(sample, pose_bone)
        bone_sample["rotation_quaternion"] = local_q
        if eye_left_name and pose_bone.name == eye_left_name:
            eye_left_driven_by_bone = True
        if eye_right_name and pose_bone.name == eye_right_name:
            eye_right_driven_by_bone = True

    if not blends and not canonical_blends:
        return

    if eye_left_name and eye_left_name in pose and not eye_left_driven_by_bone:
        left_h = (_canonical_blend_value(canonical_blends, blends, "LookRight_L") or _canonical_blend_value(canonical_blends, blends, "LookRight")) - (
            _canonical_blend_value(canonical_blends, blends, "LookLeft_L") or _canonical_blend_value(canonical_blends, blends, "LookLeft")
        )
        left_v = (_canonical_blend_value(canonical_blends, blends, "LookUp_L") or _canonical_blend_value(canonical_blends, blends, "LookUp")) - (
            _canonical_blend_value(canonical_blends, blends, "LookDown_L") or _canonical_blend_value(canonical_blends, blends, "LookDown")
        )
        bone_sample = _ensure_bone_sample(sample, pose[eye_left_name])
        bone_sample["rotation_quaternion"] = _compute_eye_look_quaternion(left_h, left_v)

    if eye_right_name and eye_right_name in pose and not eye_right_driven_by_bone:
        right_h = (_canonical_blend_value(canonical_blends, blends, "LookRight_R") or _canonical_blend_value(canonical_blends, blends, "LookRight")) - (
            _canonical_blend_value(canonical_blends, blends, "LookLeft_R") or _canonical_blend_value(canonical_blends, blends, "LookLeft")
        )
        right_v = (_canonical_blend_value(canonical_blends, blends, "LookUp_R") or _canonical_blend_value(canonical_blends, blends, "LookUp")) - (
            _canonical_blend_value(canonical_blends, blends, "LookDown_R") or _canonical_blend_value(canonical_blends, blends, "LookDown")
        )
        bone_sample = _ensure_bone_sample(sample, pose[eye_right_name])
        bone_sample["rotation_quaternion"] = _compute_eye_look_quaternion(right_h, right_v)


def _evaluate_eye_look_target_bones(scene, arm_obj, blends, canonical_blends, sample, bones=None, target_context=None):
    if arm_obj is None or getattr(arm_obj, "pose", None) is None or (not blends and not canonical_blends):
        return

    pose = arm_obj.pose.bones
    eye_left_name = (target_context or {}).get("eye_left_name") or state.cached_bone_map.get("LeftEye") or mapping.find_bone_name(arm_obj, "LeftEye", scene)
    eye_right_name = (target_context or {}).get("eye_right_name") or state.cached_bone_map.get("RightEye") or mapping.find_bone_name(arm_obj, "RightEye", scene)
    if eye_left_name:
        state.cached_bone_map["LeftEye"] = eye_left_name
    if eye_right_name:
        state.cached_bone_map["RightEye"] = eye_right_name

    bones = bones or {}

    if eye_left_name and eye_left_name in pose and "LeftEye" not in bones:
        left_h = (_canonical_blend_value(canonical_blends, blends, "LookRight_L") or _canonical_blend_value(canonical_blends, blends, "LookRight")) - (
            _canonical_blend_value(canonical_blends, blends, "LookLeft_L") or _canonical_blend_value(canonical_blends, blends, "LookLeft")
        )
        left_v = (_canonical_blend_value(canonical_blends, blends, "LookUp_L") or _canonical_blend_value(canonical_blends, blends, "LookUp")) - (
            _canonical_blend_value(canonical_blends, blends, "LookDown_L") or _canonical_blend_value(canonical_blends, blends, "LookDown")
        )
        bone_sample = _ensure_bone_sample(sample, pose[eye_left_name])
        bone_sample["rotation_quaternion"] = _compute_eye_look_quaternion(left_h, left_v)

    if eye_right_name and eye_right_name in pose and "RightEye" not in bones:
        right_h = (_canonical_blend_value(canonical_blends, blends, "LookRight_R") or _canonical_blend_value(canonical_blends, blends, "LookRight")) - (
            _canonical_blend_value(canonical_blends, blends, "LookLeft_R") or _canonical_blend_value(canonical_blends, blends, "LookLeft")
        )
        right_v = (_canonical_blend_value(canonical_blends, blends, "LookUp_R") or _canonical_blend_value(canonical_blends, blends, "LookUp")) - (
            _canonical_blend_value(canonical_blends, blends, "LookDown_R") or _canonical_blend_value(canonical_blends, blends, "LookDown")
        )
        bone_sample = _ensure_bone_sample(sample, pose[eye_right_name])
        bone_sample["rotation_quaternion"] = _compute_eye_look_quaternion(right_h, right_v)


def _evaluate_mmd_target_armature(scene, arm_obj, bones, dirty_bone_names, blends, canonical_blends, sample, context):
    if arm_obj is None or getattr(arm_obj, "pose", None) is None:
        return

    entries = context.get("mmd_runtime_entries", ()) if context is not None else ()
    if not entries:
        _evaluate_generic_target_armature(scene, arm_obj, bones, dirty_bone_names, blends, canonical_blends, sample, context)
        return

    if dirty_bone_names:
        entries_by_source = (context or {}).get("mmd_runtime_entries_by_source", {})
        entry_iter = (
            entries_by_source[source_name]
            for source_name in dirty_bone_names
            if source_name in entries_by_source
        )
    else:
        entry_iter = entries

    source_pose_matrices = {}
    target_pose_matrices = {}
    for (
        source_name,
        _target_name,
        source_bone,
        target_bone,
        use_neutral_axis_calibration,
        calibration,
        source_rest,
        source_rest_inv,
        target_rest,
        target_rest_inv,
        source_start_basis_rotation,
        source_start_basis_rotation_inv,
        target_start_basis_rotation,
        _target_start_rotation,
        target_bone_ref,
        target_matrix_local,
        parent_bone,
        has_parent,
        parent_matrix_local,
        target_start_location,
        target_start_scale,
    ) in entry_iter:
        if source_bone is None or target_bone is None:
            continue

        if mapping_mmd.uses_stable_roll_calibration(source_name):
            source_rotation = _source_local_rotation_from_pose(
                bones.get(source_name),
                source_start_basis_rotation,
                source_rest,
                source_rest_inv,
                source_bone,
            )
            source_delta = source_rotation @ source_start_basis_rotation_inv
            source_delta.normalize()
            target_delta = _remap_local_delta_with_rest_quaternions(
                source_rest,
                source_rest_inv,
                target_rest,
                target_rest_inv,
                source_delta,
            )
            desired_rotation = target_delta @ target_start_basis_rotation
            desired_rotation.normalize()
            bone_sample = _ensure_bone_sample(sample, target_bone)
            bone_sample["rotation_quaternion"] = desired_rotation
            continue

        if use_neutral_axis_calibration:
            source_matrix = _source_pose_matrix_from_raw(
                source_bone,
                bones,
                context.get("preview_start_basis_rotations", {}),
                source_pose_matrices,
            )
            source_armature_q = source_matrix.to_quaternion()
            source_armature_q.normalize()
            source_axis = (source_matrix.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
            desired_armature_q = calibration @ source_armature_q
            desired_axis = (desired_armature_q @ Vector((0.0, 1.0, 0.0))).normalized()
            swing = desired_axis.rotation_difference(source_axis)
            desired_armature_q = swing @ desired_armature_q
            if mapping_mmd.uses_mirrored_arm_roll_correction(scene, source_name):
                desired_axis = (desired_armature_q @ Vector((0.0, 1.0, 0.0))).normalized()
                desired_x_axis = (desired_armature_q @ Vector((1.0, 0.0, 0.0))).normalized()
                # MMD mirrored-arm forearm bones keep Y aligned but mirror X/Z relative to the VRM source.
                source_x_axis = -(source_matrix.to_3x3() @ Vector((1.0, 0.0, 0.0))).normalized()
                roll_angle = _signed_projected_angle(desired_x_axis, source_x_axis, desired_axis)
                desired_armature_q = Quaternion(desired_axis, roll_angle) @ desired_armature_q
            desired_armature_q.normalize()
            desired_matrix = Matrix.LocRotScale(
                target_start_location,
                desired_armature_q,
                target_start_scale,
            )
            if not has_parent:
                basis_matrix = target_bone_ref.convert_local_to_pose(
                    desired_matrix,
                    target_matrix_local,
                    invert=True,
                )
            else:
                parent_pose_matrix = _resolve_target_pose_matrix_from_sample(
                    parent_bone,
                    sample,
                    target_pose_matrices,
                )
                basis_matrix = target_bone_ref.convert_local_to_pose(
                    desired_matrix,
                    target_matrix_local,
                    parent_matrix=parent_pose_matrix,
                    parent_matrix_local=parent_matrix_local,
                    invert=True,
                )
            desired_rotation = basis_matrix.to_quaternion()
            desired_rotation.normalize()
        else:
            source_rotation = _source_local_rotation_from_pose(
                bones.get(source_name),
                source_start_basis_rotation,
                source_rest,
                source_rest_inv,
                source_bone,
            )
            source_delta = source_rotation @ source_start_basis_rotation_inv
            source_delta.normalize()
            target_delta = _remap_local_delta_with_rest_quaternions(
                source_rest,
                source_rest_inv,
                target_rest,
                target_rest_inv,
                source_delta,
            )
            desired_rotation = target_delta @ target_start_basis_rotation
            desired_rotation.normalize()

        bone_sample = _ensure_bone_sample(sample, target_bone)
        bone_sample["rotation_quaternion"] = desired_rotation

    _evaluate_eye_look_target_bones(scene, arm_obj, blends, canonical_blends, sample, bones, context)


def _evaluate_target_shapes(scene, face_obj, use_arkit_face, blends, canonical_blends, arkit_blends, dirty_vmc_blend_names, dirty_arkit_blend_names, sample):
    if not mapping.has_shape_keys(face_obj):
        return

    if not use_arkit_face:
        source_blends = canonical_blends or blends
        if dirty_vmc_blend_names:
            blend_iter = (
                (vmc_name, source_blends[vmc_name])
                for vmc_name in dirty_vmc_blend_names
                if vmc_name in source_blends
            )
        else:
            blend_iter = source_blends.items()
        for vmc_name, value in blend_iter:
            key_block = state.cached_blend_key_blocks.get(vmc_name)
            actual = state.cached_blend_map.get(vmc_name)
            if key_block is None:
                actual = actual or mapping.find_shapekey_name(face_obj, vmc_name, scene)
                if not actual:
                    continue
                blocks = face_obj.data.shape_keys.key_blocks
                key_block = blocks.get(actual)
                if key_block is None:
                    continue
                state.cached_blend_map[vmc_name] = actual
                state.cached_blend_key_blocks[vmc_name] = key_block
            sample["shapes"][actual] = float(value)
            sample["shape_blocks"][actual] = key_block
        return

    if dirty_arkit_blend_names:
        blend_iter = (
            (arkit_name, arkit_blends[arkit_name])
            for arkit_name in dirty_arkit_blend_names
            if arkit_name in arkit_blends
        )
    else:
        blend_iter = arkit_blends.items()
    for arkit_name, value in blend_iter:
        key_block = state.cached_arkit_blend_key_blocks.get(arkit_name)
        actual = state.cached_arkit_blend_map.get(arkit_name)
        if key_block is None:
            actual = actual or mapping.find_arkit_shapekey_name(face_obj, arkit_name, scene)
            if not actual:
                continue
            blocks = face_obj.data.shape_keys.key_blocks
            key_block = blocks.get(actual)
            if key_block is None:
                continue
            state.cached_arkit_blend_map[arkit_name] = actual
            state.cached_arkit_blend_key_blocks[arkit_name] = key_block
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            continue
        sample["shapes"][actual] = numeric_value
        sample["shape_blocks"][actual] = key_block


def _evaluate_arp_target_armature(arm_obj, bones, dirty_bone_names, context, sample):
    if arm_obj is None or getattr(arm_obj, "pose", None) is None:
        return

    filtered_rotations = context.setdefault("arp_filtered_rotations", {})
    source_pose_matrices = {}
    target_pose_matrices = {}
    preview_start_basis_rotations = context.get("preview_start_basis_rotations", {})
    for bone_name, pose_bone in context.get("arp_ik_fk_pose_bones", ()):
        sample["ik_fk_switches"][bone_name] = 1.0
        sample["ik_fk_pose_bones"][bone_name] = pose_bone

    if dirty_bone_names:
        entries_by_source = context.get("arp_runtime_entries_by_source", {})
        order_index_by_source = context.get("arp_runtime_order_index_by_source", {})
        entry_iter = (
            entries_by_source[source_name]
            for source_name in sorted(
                (
                    source_name
                    for source_name in dirty_bone_names
                    if source_name in entries_by_source
                ),
                key=lambda source_name: order_index_by_source.get(source_name, 1 << 30),
            )
        )
    else:
        entry_iter = context.get("arp_runtime_entries", ())

    for (
        source_name,
        target_name,
        source_bone,
        target_bone,
        calibration,
        _uses_local_basis_delta,
        _uses_delta_rotation,
        _uses_rest_axis_remap,
        _source_start_basis_rotation,
        _target_start_basis_rotation,
        _source_start_rotation,
        _source_start_rotation_inv,
        target_start_rotation,
        start_location,
        start_scale,
        target_bone_ref,
        target_matrix_local,
        parent_bone,
        has_parent,
        parent_matrix_local,
        _needs_pose_target_matrix,
        _source_rest,
        _source_rest_inv,
        target_rest,
        target_rest_inv,
    ) in entry_iter:
        raw_pose = bones.get(source_name)
        if mapping_arp.uses_world_rotation(source_name):
            if raw_pose is None:
                continue
            if source_bone is None or target_bone_ref is None or target_matrix_local is None:
                continue
            source_matrix = _source_pose_matrix_from_raw(
                source_bone,
                bones,
                preview_start_basis_rotations,
                source_pose_matrices,
            )
            source_armature_q = source_matrix.to_quaternion()
            source_armature_q.normalize()
            target_armature_q = calibration.inverted() @ source_armature_q
            target_armature_q.normalize()
            if start_location is None or start_scale is None:
                start_matrix = target_bone.matrix.copy()
                start_location = start_matrix.to_translation()
                start_scale = start_matrix.to_scale()
            desired_matrix = Matrix.LocRotScale(
                start_location,
                target_armature_q,
                start_scale,
            )
            if not has_parent:
                basis_matrix = target_bone_ref.convert_local_to_pose(
                    desired_matrix,
                    target_matrix_local,
                    invert=True,
                )
            else:
                parent_pose_matrix = _resolve_target_pose_matrix_from_sample(
                    parent_bone,
                    sample,
                    target_pose_matrices,
                )
                basis_matrix = target_bone_ref.convert_local_to_pose(
                    desired_matrix,
                    target_matrix_local,
                    parent_matrix=parent_pose_matrix,
                    parent_matrix_local=parent_matrix_local,
                    invert=True,
                )
            basis_rotation = basis_matrix.to_quaternion()
            basis_rotation.normalize()
            basis_rotation = _filter_rotation(filtered_rotations, target_name, basis_rotation)
            bone_sample = _ensure_bone_sample(sample, target_bone)
            bone_sample["rotation_quaternion"] = basis_rotation
            continue
        if raw_pose is None:
            continue
        _px, _py, _pz, qx, qy, qz, qw = raw_pose
        desired_rotation = helpers.convert_vmc_quaternion(qx, qy, qz, qw)
        source_local = _source_rest_inv @ desired_rotation @ _source_rest
        source_local.normalize()
        rest_delta = target_rest_inv @ _source_rest
        rest_delta.normalize()
        desired_rotation = rest_delta @ source_local @ rest_delta.inverted()
        desired_rotation.normalize()
        desired_rotation = _filter_rotation(filtered_rotations, target_name, desired_rotation)
        bone_sample = _ensure_bone_sample(sample, target_bone)
        bone_sample["rotation_quaternion"] = desired_rotation


def _evaluate_target_armature(scene, arm_obj, preview_arm, bones, dirty_bone_names, blends, canonical_blends, target_context, sample):
    runtime_strategy = mapping_target_rig.resolve_runtime_strategy(arm_obj, target_context)
    if runtime_strategy == mapping_target_rig.RUNTIME_STRATEGY_ARP:
        _evaluate_arp_target_armature(arm_obj, bones, dirty_bone_names, target_context or {}, sample)
        return
    if runtime_strategy == mapping_target_rig.RUNTIME_STRATEGY_MMD:
        _evaluate_mmd_target_armature(scene, arm_obj, bones, dirty_bone_names, blends, canonical_blends, sample, target_context or {})
        return
    _evaluate_generic_target_armature(scene, arm_obj, bones, dirty_bone_names, blends, canonical_blends, sample, target_context or {})


def evaluate_target_sample(
    scene,
    arm_obj,
    face_obj,
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
    lock_to_center: bool,
    use_arkit_face: bool,
    target_context,
    evaluate_root_motion: bool = True,
    evaluate_armature: bool = True,
    evaluate_shapes: bool = True,
):
    sample = _empty_target_sample(arm_obj, face_obj)

    runtime_strategy = mapping_target_rig.resolve_runtime_strategy(arm_obj, target_context)
    defer_mmd_root_motion = runtime_strategy == mapping_target_rig.RUNTIME_STRATEGY_MMD
    if arm_obj is not None and evaluate_root_motion and not defer_mmd_root_motion:
        _evaluate_target_root_motion(sample, arm_obj, root, waist, bones, target_context or {}, lock_to_center)
    if arm_obj is not None and evaluate_armature:
        _evaluate_target_armature(scene, arm_obj, preview_arm, bones, dirty_bone_names, blends, canonical_vmc_blends, target_context, sample)
    if arm_obj is not None and evaluate_root_motion and defer_mmd_root_motion:
        _evaluate_target_root_motion(sample, arm_obj, root, waist, bones, target_context or {}, lock_to_center)

    if evaluate_shapes:
        _evaluate_target_shapes(
            scene,
            face_obj,
            use_arkit_face,
            blends,
            canonical_vmc_blends,
            arkit_blends,
            dirty_vmc_blend_names,
            dirty_arkit_blend_names,
            sample,
        )
    return sample


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


def _ensure_target_apply_cache(arm_obj, face_obj):
    if state.receiver_target_apply_armature_ref is not arm_obj:
        state.receiver_target_apply_armature_ref = arm_obj
        state.receiver_target_apply_arm_location = None
        state.receiver_target_apply_arm_rotation = None
        state.receiver_target_apply_bone_locations = {}
        state.receiver_target_apply_bone_rotations = {}
        state.receiver_target_apply_ik_fk_switches = {}
    if state.receiver_target_apply_face_ref is not face_obj:
        state.receiver_target_apply_face_ref = face_obj
        state.receiver_target_apply_shape_values = {}


def apply_target_sample(arm_obj, face_obj, sample):
    _ensure_target_apply_cache(arm_obj, face_obj)
    changed = False

    if arm_obj is not None:
        arm_sample = sample["arm"]
        if arm_sample is not None:
            desired_location = arm_sample.get("location")
            if desired_location is not None:
                cached_location = state.receiver_target_apply_arm_location
                if cached_location is None:
                    cached_location = _as_float_tuple(arm_obj.location)
                if _vec_values_changed(cached_location, desired_location):
                    arm_obj.location = desired_location
                    state.receiver_target_apply_arm_location = (
                        float(desired_location[0]),
                        float(desired_location[1]),
                        float(desired_location[2]),
                    )
                    changed = True
                else:
                    state.receiver_target_apply_arm_location = cached_location
            desired_rotation = arm_sample.get("rotation_quaternion")
            if desired_rotation is not None:
                cached_rotation = state.receiver_target_apply_arm_rotation
                if cached_rotation is None:
                    cached_rotation = _as_float_tuple(arm_obj.rotation_quaternion)
                if _quat_values_changed(cached_rotation, desired_rotation):
                    arm_obj.rotation_quaternion = desired_rotation
                    state.receiver_target_apply_arm_rotation = (
                        float(desired_rotation[0]),
                        float(desired_rotation[1]),
                        float(desired_rotation[2]),
                        float(desired_rotation[3]),
                    )
                    changed = True
                else:
                    state.receiver_target_apply_arm_rotation = cached_rotation

        ik_fk_pose_bones = sample.get("ik_fk_pose_bones", {})
        for bone_name, switch_value in sample.get("ik_fk_switches", {}).items():
            pose_bone = ik_fk_pose_bones.get(bone_name)
            if pose_bone is None or "ik_fk_switch" not in pose_bone:
                continue
            cached_switch = state.receiver_target_apply_ik_fk_switches.get(bone_name)
            if cached_switch is None:
                cached_switch = float(pose_bone["ik_fk_switch"])
            numeric_switch = float(switch_value)
            if abs(float(cached_switch) - numeric_switch) > constants.SHAPE_EPS:
                pose_bone["ik_fk_switch"] = float(switch_value)
                state.receiver_target_apply_ik_fk_switches[bone_name] = numeric_switch
                changed = True
            else:
                state.receiver_target_apply_ik_fk_switches[bone_name] = cached_switch

        for bone_name, bone_sample in sample.get("bones", {}).items():
            pose_bone = bone_sample.get("pose_bone")
            if pose_bone is None:
                continue
            desired_location = bone_sample.get("location")
            if desired_location is not None:
                cached_location = state.receiver_target_apply_bone_locations.get(bone_name)
                if cached_location is None:
                    cached_location = _as_float_tuple(pose_bone.location)
                if _vec_values_changed(cached_location, desired_location):
                    pose_bone.location = desired_location
                    state.receiver_target_apply_bone_locations[bone_name] = (
                        float(desired_location[0]),
                        float(desired_location[1]),
                        float(desired_location[2]),
                    )
                    changed = True
                else:
                    state.receiver_target_apply_bone_locations[bone_name] = cached_location
            desired_rotation = bone_sample.get("rotation_quaternion")
            if desired_rotation is not None:
                cached_rotation = state.receiver_target_apply_bone_rotations.get(bone_name)
                if cached_rotation is None:
                    cached_rotation = _as_float_tuple(pose_bone.rotation_quaternion)
                if _quat_values_changed(cached_rotation, desired_rotation):
                    pose_bone.rotation_quaternion = desired_rotation
                    state.receiver_target_apply_bone_rotations[bone_name] = (
                        float(desired_rotation[0]),
                        float(desired_rotation[1]),
                        float(desired_rotation[2]),
                        float(desired_rotation[3]),
                    )
                    changed = True
                else:
                    state.receiver_target_apply_bone_rotations[bone_name] = cached_rotation

    shape_blocks = sample.get("shape_blocks", {})
    for key_name, value in sample.get("shapes", {}).items():
        key_block = shape_blocks.get(key_name)
        if key_block is None:
            continue
        cached_value = state.receiver_target_apply_shape_values.get(key_name)
        numeric_value = float(value)
        if cached_value is None:
            cached_value = float(key_block.value)
        if abs(float(cached_value) - numeric_value) > constants.SHAPE_EPS:
            key_block.value = numeric_value
            state.receiver_target_apply_shape_values[key_name] = numeric_value
            changed = True
        else:
            state.receiver_target_apply_shape_values[key_name] = cached_value
    return changed
