import os

import bpy
from mathutils import Vector

from ..core import constants, helpers


_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))


def _asset_path(file_name: str) -> str:
    return os.path.join(_PROJECT_ROOT, "assets", file_name)


def get_arkit_debug_asset_path() -> str:
    return _asset_path("Arkitface.blend")


def _get_role_tag(obj):
    getter = getattr(obj, "get", None)
    if getter is None:
        return None
    return getter(constants.INTERMEDIATE_RIG_PROP_ROLE)


def _has_child_collection(parent_collection, child_collection) -> bool:
    return parent_collection.children.get(child_collection.name) is not None


def _has_collection_object(collection, obj) -> bool:
    return collection.objects.get(obj.name) is not None


def ensure_plugin_collection(scene):
    plugin_collection = bpy.data.collections.get(constants.PLUGIN_COLLECTION_NAME)
    if plugin_collection is None:
        plugin_collection = bpy.data.collections.new(constants.PLUGIN_COLLECTION_NAME)
    if not _has_child_collection(scene.collection, plugin_collection):
        scene.collection.children.link(plugin_collection)
    return plugin_collection


def _move_object_to_plugin_collection(scene, obj):
    plugin_collection = ensure_plugin_collection(scene)
    if not _has_collection_object(plugin_collection, obj):
        plugin_collection.objects.link(obj)

    for collection in list(getattr(obj, "users_collection", ())):
        if collection == plugin_collection:
            continue
        try:
            collection.objects.unlink(obj)
        except RuntimeError:
            pass

    return plugin_collection


def _ensure_object_in_plugin_collection(scene, obj):
    plugin_collection = ensure_plugin_collection(scene)
    if not _has_collection_object(plugin_collection, obj):
        plugin_collection.objects.link(obj)
    return plugin_collection


def _place_collection_under_plugin(scene, child_collection):
    plugin_collection = ensure_plugin_collection(scene)
    if not _has_child_collection(plugin_collection, child_collection):
        plugin_collection.children.link(child_collection)
    if child_collection != plugin_collection and _has_child_collection(scene.collection, child_collection):
        scene.collection.children.unlink(child_collection)
    return plugin_collection


def _iter_collection_objects(collection):
    all_objects = getattr(collection, "all_objects", None)
    if all_objects is not None:
        return list(all_objects)
    return list(collection.objects)


def get_expected_intermediate_bone_names():
    return list(constants.INTERMEDIATE_REQUIRED_BONES) + list(constants.INTERMEDIATE_OPTIONAL_BONES)


def _pose_bone_names(arm_obj):
    pose = getattr(arm_obj, "pose", None)
    bones = getattr(pose, "bones", None)
    if bones is None:
        return set()
    return {bone.name for bone in bones}


def tag_intermediate_rig(arm_obj):
    if arm_obj is None:
        return
    arm_obj[constants.INTERMEDIATE_RIG_PROP_ROLE] = constants.INTERMEDIATE_RIG_ROLE
    arm_obj[constants.INTERMEDIATE_RIG_PROP_SCHEMA] = constants.INTERMEDIATE_RIG_SCHEMA_VERSION
    if getattr(arm_obj, "data", None) is not None:
        arm_obj.data[constants.INTERMEDIATE_RIG_PROP_ROLE] = constants.INTERMEDIATE_RIG_ROLE
        arm_obj.data[constants.INTERMEDIATE_RIG_PROP_SCHEMA] = constants.INTERMEDIATE_RIG_SCHEMA_VERSION


def tag_arkit_preview_face(face_obj):
    if face_obj is None:
        return
    face_obj[constants.INTERMEDIATE_RIG_PROP_ROLE] = constants.ARKIT_PREVIEW_FACE_ROLE
    face_obj[constants.INTERMEDIATE_RIG_PROP_SCHEMA] = constants.INTERMEDIATE_RIG_SCHEMA_VERSION
    if getattr(face_obj, "data", None) is not None:
        face_obj.data[constants.INTERMEDIATE_RIG_PROP_ROLE] = constants.ARKIT_PREVIEW_FACE_ROLE
        face_obj.data[constants.INTERMEDIATE_RIG_PROP_SCHEMA] = constants.INTERMEDIATE_RIG_SCHEMA_VERSION


def get_intermediate_rig_match_info(arm_obj):
    names = _pose_bone_names(arm_obj)
    required_present = [name for name in constants.INTERMEDIATE_REQUIRED_BONES if name in names]
    required_missing = [name for name in constants.INTERMEDIATE_REQUIRED_BONES if name not in names]
    optional_present = [name for name in constants.INTERMEDIATE_OPTIONAL_BONES if name in names]
    is_tagged = False
    if arm_obj is not None:
        is_tagged = (
            arm_obj.get(constants.INTERMEDIATE_RIG_PROP_ROLE) == constants.INTERMEDIATE_RIG_ROLE
            or getattr(getattr(arm_obj, "data", None), "get", lambda *_args, **_kwargs: None)(constants.INTERMEDIATE_RIG_PROP_ROLE)
            == constants.INTERMEDIATE_RIG_ROLE
        )
    return {
        "required_present": required_present,
        "required_missing": required_missing,
        "optional_present": optional_present,
        "is_tagged": bool(is_tagged),
    }


def is_vrm_intermediate_rig(arm_obj) -> bool:
    if arm_obj is None or getattr(arm_obj, "type", None) != "ARMATURE":
        return False
    info = get_intermediate_rig_match_info(arm_obj)
    return info["is_tagged"] or not info["required_missing"]


def _count_matching_arkit_keys(face_obj):
    shape_keys = getattr(getattr(face_obj, "data", None), "shape_keys", None)
    key_blocks = getattr(shape_keys, "key_blocks", None)
    if key_blocks is None:
        return 0

    arkit_key_set = {helpers.normalize_identifier(name) for name in constants.ARKIT_BLENDSHAPE_KEYS}
    return sum(1 for key in key_blocks if helpers.normalize_identifier(key.name) in arkit_key_set)


def is_arkit_preview_face(face_obj) -> bool:
    if face_obj is None or getattr(face_obj, "type", None) != "MESH":
        return False

    if _get_role_tag(face_obj) == constants.ARKIT_PREVIEW_FACE_ROLE:
        return True

    data = getattr(face_obj, "data", None)
    if data is not None:
        getter = getattr(data, "get", None)
        if getter is not None and getter(constants.INTERMEDIATE_RIG_PROP_ROLE) == constants.ARKIT_PREVIEW_FACE_ROLE:
            return True

    return _count_matching_arkit_keys(face_obj) >= len(constants.ARKIT_BLENDSHAPE_KEYS)


def _remove_object(obj):
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data and data.users == 0:
        if isinstance(data, bpy.types.Armature):
            bpy.data.armatures.remove(data)
        elif isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)


def _find_existing_dummy_armatures(scene):
    plugin_collection = bpy.data.collections.get(constants.PLUGIN_COLLECTION_NAME)
    if plugin_collection is None:
        return []

    matches = []
    for obj in _iter_collection_objects(plugin_collection):
        if getattr(obj, "type", None) != "ARMATURE":
            continue
        if obj.name == constants.DUMMY_ARMATURE_NAME or obj.name.startswith(constants.DUMMY_ARMATURE_NAME + "."):
            matches.append(obj)
    return matches


def _find_existing_arkit_preview_faces(scene):
    return [obj for obj in scene.objects if is_arkit_preview_face(obj)]


def create_intermediate_rig(context, rebuild: bool = False):
    scene = context.scene

    def add_bone(edit_bones, name: str, head, tail, parent=None, use_connect=False):
        bone = edit_bones.new(name)
        bone.head = Vector(head)
        bone.tail = Vector(tail)
        if parent is not None:
            bone.parent = parent
            bone.use_connect = use_connect
        return bone

    try:
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        if constants.DUMMY_DELETE_OLD or rebuild:
            for obj in list(_find_existing_dummy_armatures(scene)):
                _remove_object(obj)

        arm_data = bpy.data.armatures.new(constants.DUMMY_ARMATURE_NAME)
        arm_obj = bpy.data.objects.new(constants.DUMMY_ARMATURE_NAME, arm_data)
        _move_object_to_plugin_collection(scene, arm_obj)

        bpy.ops.object.select_all(action="DESELECT")
        context.view_layer.objects.active = arm_obj
        arm_obj.select_set(True)

        bpy.ops.object.mode_set(mode="EDIT")
        edit_bones = arm_data.edit_bones

        hips = add_bone(edit_bones, "Hips", (0.0, 0.0, 1.00), (0.0, 0.0, 1.18))
        spine = add_bone(edit_bones, "Spine", hips.tail, (0.0, 0.0, 1.36), parent=hips, use_connect=True)
        chest = add_bone(edit_bones, "Chest", spine.tail, (0.0, 0.0, 1.50), parent=spine, use_connect=True)
        upper_chest = add_bone(
            edit_bones,
            "UpperChest",
            chest.tail,
            (0.0, 0.0, 1.56),
            parent=chest,
            use_connect=True,
        )
        neck = add_bone(edit_bones, "Neck", upper_chest.tail, (0.0, 0.0, 1.68), parent=upper_chest, use_connect=True)
        head = add_bone(edit_bones, "Head", neck.tail, (0.0, 0.0, 1.88), parent=neck, use_connect=True)

        add_bone(edit_bones, "LeftEye", (0.04, -0.02, 1.82), (0.10, -0.02, 1.82), parent=head)
        add_bone(edit_bones, "RightEye", (-0.04, -0.02, 1.82), (-0.10, -0.02, 1.82), parent=head)

        def add_finger_chains(hand_bone, side_suffix: str, side_sign: float):
            finger_defs = (
                ("Thumb", (0, 1, 2), [(0.90, -0.03, 1.47), (0.94, -0.06, 1.46), (0.98, -0.08, 1.45), (1.02, -0.10, 1.44)]),
                ("IndexFinger", (1, 2, 3), [(0.90, 0.03, 1.48), (0.96, 0.03, 1.48), (1.01, 0.03, 1.48), (1.05, 0.03, 1.48)]),
                ("MiddleFinger", (1, 2, 3), [(0.90, 0.00, 1.48), (0.97, 0.00, 1.48), (1.03, 0.00, 1.48), (1.08, 0.00, 1.48)]),
                ("RingFinger", (1, 2, 3), [(0.90, -0.03, 1.48), (0.96, -0.03, 1.48), (1.01, -0.03, 1.48), (1.05, -0.03, 1.48)]),
                ("LittleFinger", (1, 2, 3), [(0.90, -0.06, 1.48), (0.95, -0.06, 1.48), (0.99, -0.06, 1.48), (1.03, -0.06, 1.48)]),
            )

            for finger_name, joint_indices, points in finger_defs:
                prev = hand_bone
                for idx, joint_idx in enumerate(joint_indices):
                    head_pos = (points[idx][0] * side_sign, points[idx][1], points[idx][2])
                    tail_pos = (points[idx + 1][0] * side_sign, points[idx + 1][1], points[idx + 1][2])
                    prev = add_bone(
                        edit_bones,
                        f"{finger_name}{joint_idx}_{side_suffix}",
                        head_pos,
                        tail_pos,
                        parent=prev,
                        use_connect=(idx > 0),
                    )

        def add_arm_and_hand(side_name: str, side_sign: float):
            shoulder = add_bone(
                edit_bones,
                f"{side_name}Shoulder",
                upper_chest.tail,
                (0.16 * side_sign, 0.0, 1.54),
                parent=upper_chest,
            )
            upper_arm = add_bone(edit_bones, f"{side_name}UpperArm", shoulder.tail, (0.46 * side_sign, 0.0, 1.54), parent=shoulder, use_connect=True)
            lower_arm = add_bone(edit_bones, f"{side_name}LowerArm", upper_arm.tail, (0.74 * side_sign, 0.0, 1.50), parent=upper_arm, use_connect=True)
            hand = add_bone(edit_bones, f"{side_name}Hand", lower_arm.tail, (0.88 * side_sign, 0.0, 1.48), parent=lower_arm, use_connect=True)
            add_finger_chains(hand, side_name[0], side_sign)

        def add_leg(side_name: str, side_sign: float):
            upper_leg = add_bone(edit_bones, f"{side_name}UpperLeg", (0.10 * side_sign, 0.0, 0.98), (0.10 * side_sign, 0.0, 0.58), parent=hips)
            lower_leg = add_bone(edit_bones, f"{side_name}LowerLeg", upper_leg.tail, (0.10 * side_sign, 0.0, 0.16), parent=upper_leg, use_connect=True)
            foot = add_bone(edit_bones, f"{side_name}Foot", lower_leg.tail, (0.10 * side_sign, -0.16, 0.05), parent=lower_leg, use_connect=True)
            add_bone(edit_bones, f"{side_name}ToeBase", foot.tail, (0.10 * side_sign, -0.30, 0.05), parent=foot, use_connect=True)

        add_arm_and_hand("Left", 1.0)
        add_arm_and_hand("Right", -1.0)
        add_leg("Left", 1.0)
        add_leg("Right", -1.0)

        bpy.ops.object.mode_set(mode="OBJECT")

        arm_obj.show_in_front = True
        arm_data.display_type = "STICK"
        arm_obj.location = (0.0, 0.0, 0.0)
        arm_obj.rotation_euler = (0.0, 0.0, 0.0)
        arm_obj.scale = (1.0, 1.0, 1.0)
        tag_intermediate_rig(arm_obj)
        scene.vmc_link_preview_armature = arm_obj
        return arm_obj
    except Exception:
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        raise


def _world_bone_length(arm_obj, pose_bone) -> float:
    head = arm_obj.matrix_world @ pose_bone.head
    tail = arm_obj.matrix_world @ pose_bone.tail
    return (tail - head).length


def calibrate_intermediate_rig_lengths(context):
    scene = context.scene
    preview_arm = getattr(scene, "vmc_link_preview_armature", None)
    target_arm = getattr(scene, "vmc_link_armature", None)
    if not is_vrm_intermediate_rig(preview_arm):
        raise RuntimeError("请先创建 VRM 预览骨架")
    if target_arm is None or getattr(target_arm, "type", None) != "ARMATURE" or getattr(target_arm, "pose", None) is None:
        raise RuntimeError("请先绑定目标骨架")

    from ..mapping import arp as mapping_arp

    analysis = mapping_arp.analyze_armature(target_arm)
    if not analysis["is_arp"]:
        raise RuntimeError("当前目标骨架不是可识别的 Auto Rig Pro 标准控制骨架")
    runtime_map = {
        source_name: analysis["resolved_default_targets"][source_name]
        for source_name in mapping_arp.ARP_RUNTIME_SOURCE_ORDER
        if source_name in analysis["resolved_default_targets"]
    }
    if not runtime_map:
        raise RuntimeError("当前目标骨架没有可用于长度校准的 ARP 映射")

    if context.object and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    bpy.ops.object.select_all(action="DESELECT")
    context.view_layer.objects.active = preview_arm
    preview_arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    edit_bones = preview_arm.data.edit_bones
    calibrated = []
    try:
        for source_name in mapping_arp.ARP_RUNTIME_SOURCE_ORDER:
            target_name = runtime_map.get(source_name)
            edit_bone = edit_bones.get(source_name)
            target_bone = target_arm.pose.bones.get(target_name) if target_name else None
            if edit_bone is None or target_bone is None:
                continue

            direction = edit_bone.tail - edit_bone.head
            if direction.length <= 0.00001:
                continue
            local_unit = direction.normalized()
            world_unit_length = (preview_arm.matrix_world.to_3x3() @ local_unit).length
            if world_unit_length <= 0.00001:
                continue
            target_world_length = _world_bone_length(target_arm, target_bone)
            desired_local_length = max(0.002, target_world_length / world_unit_length)
            edit_bone.tail = edit_bone.head + local_unit * desired_local_length
            calibrated.append(source_name)
        _align_intermediate_rig_anchor_bones(edit_bones)
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")

    tag_intermediate_rig(preview_arm)
    return calibrated


def _set_bone_head_preserve_length(edit_bone, new_head):
    direction = edit_bone.tail - edit_bone.head
    if direction.length <= 0.00001:
        return
    length = direction.length
    edit_bone.head = new_head
    edit_bone.tail = edit_bone.head + direction.normalized() * length


def _align_intermediate_rig_anchor_bones(edit_bones):
    upper_chest = edit_bones.get("UpperChest")
    if upper_chest is not None:
        for name in ("LeftShoulder", "RightShoulder"):
            shoulder = edit_bones.get(name)
            if shoulder is not None:
                _set_bone_head_preserve_length(shoulder, upper_chest.tail.copy())


def collect_intermediate_status(scene):
    arm_obj = getattr(scene, "vmc_link_preview_armature", None)
    face_obj = getattr(scene, "vmc_link_preview_face_object", None)

    arm_info = get_intermediate_rig_match_info(arm_obj) if arm_obj is not None else None
    matched_arkit_keys = _count_matching_arkit_keys(face_obj) if face_obj is not None else 0

    return {
        "armature": arm_obj,
        "armature_is_intermediate": is_vrm_intermediate_rig(arm_obj),
        "armature_tagged": bool(arm_info and arm_info["is_tagged"]),
        "required_present": len(arm_info["required_present"]) if arm_info else 0,
        "required_total": len(constants.INTERMEDIATE_REQUIRED_BONES),
        "optional_present": len(arm_info["optional_present"]) if arm_info else 0,
        "optional_total": len(constants.INTERMEDIATE_OPTIONAL_BONES),
        "required_missing": list(arm_info["required_missing"]) if arm_info else [],
        "face_object": face_obj,
        "face_object_is_preview": is_arkit_preview_face(face_obj),
        "arkit_shape_matches": matched_arkit_keys,
        "arkit_key_total": len(constants.ARKIT_BLENDSHAPE_KEYS),
        "arkit_debug_asset_path": get_arkit_debug_asset_path(),
        "arkit_debug_asset_exists": os.path.exists(get_arkit_debug_asset_path()),
    }


def import_arkit_preview_face(context):
    scene = context.scene
    existing_faces = _find_existing_arkit_preview_faces(scene)
    if existing_faces:
        face_obj = existing_faces[0]
        placed_in_asset_collection = False
        for collection in getattr(face_obj, "users_collection", ()):
            if collection.name == constants.ARKIT_ASSET_COLLECTION_NAME:
                _place_collection_under_plugin(scene, collection)
                placed_in_asset_collection = True
                break
        if not placed_in_asset_collection:
            _ensure_object_in_plugin_collection(scene, face_obj)
        tag_arkit_preview_face(face_obj)
        scene.vmc_link_preview_face_object = face_obj
        return face_obj

    asset_path = get_arkit_debug_asset_path()
    if not os.path.exists(asset_path):
        raise RuntimeError(f"ARKit 调试资产不存在: {asset_path}")

    with bpy.data.libraries.load(asset_path, link=False) as (data_from, data_to):
        if constants.ARKIT_ASSET_COLLECTION_NAME not in data_from.collections:
            raise RuntimeError(f"ARKit 调试资产中缺少集合：{constants.ARKIT_ASSET_COLLECTION_NAME}")
        data_to.collections = [constants.ARKIT_ASSET_COLLECTION_NAME]

    imported_collection = next((collection for collection in data_to.collections if collection is not None), None)
    if imported_collection is None:
        raise RuntimeError("追加 ARKit 调试集合失败")

    _place_collection_under_plugin(scene, imported_collection)

    mesh_candidates = [
        obj
        for obj in _iter_collection_objects(imported_collection)
        if getattr(obj, "type", None) == "MESH"
    ]
    if not mesh_candidates:
        raise RuntimeError("ARKit 调试资产中未找到可用的面部模型")

    face_obj = max(mesh_candidates, key=_count_matching_arkit_keys)
    tag_arkit_preview_face(face_obj)
    scene.vmc_link_preview_face_object = face_obj
    return face_obj
