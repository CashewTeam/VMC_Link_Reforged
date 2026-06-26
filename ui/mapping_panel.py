import bpy

from ..core import constants
from ..mapping import arp as mapping_arp
from ..mapping import mapper as mapping
from ..mapping import mmd as mapping_mmd
from ..mapping import preset_store as presets
from ..mapping import target_rig as mapping_target_rig
from ..mapping import vrm as mapping_vrm


def draw_mapping_preset_controls(layout, scene, kind: str):
    preset_prop, save_prop = presets.mapping_preset_prop_names(kind)

    box = layout.box()
    col = box.column(align=True)
    col.label(text="JSON 预设", icon="FILE_FOLDER")

    row = col.row(align=True)
    row.prop(scene, preset_prop, text="预设")
    refresh_op = row.operator("vmc_link.refresh_mapping_presets", text="", icon="FILE_REFRESH")
    refresh_op.mapping_kind = kind

    load_row = col.row(align=True)
    load_op = load_row.operator("vmc_link.load_mapping_preset", text="加载", icon="IMPORT")
    load_op.mapping_kind = kind

    save_row = col.row(align=True)
    save_row.prop(scene, save_prop, text="保存名称")
    save_op = save_row.operator("vmc_link.save_mapping_preset", text="保存", icon="EXPORT")
    save_op.mapping_kind = kind


def draw_bone_mapping_entries(layout, scene):
    arm_for_search = scene.vmc_link_armature
    can_search_bones = mapping.has_pose_bones(arm_for_search)

    if not can_search_bones:
        layout.label(text="请选择目标骨架后再使用骨骼选择器", icon="INFO")

    col = layout.column(align=True)
    for vmc_name in mapping.mapping_keys(constants.MAPPING_KIND_BONE):
        prop_name = mapping.bone_override_prop_name(vmc_name)
        if can_search_bones:
            col.prop_search(scene, prop_name, arm_for_search.pose, "bones", text=vmc_name, icon="BONE_DATA")
        else:
            col.prop(scene, prop_name, text=vmc_name)


def draw_blend_mapping_entries(layout, scene, kind: str):
    face_for_search = scene.vmc_link_face_object
    can_search_blends = mapping.has_shape_keys(face_for_search)

    if not can_search_blends:
        layout.label(text="请选择带 Shape Key 的目标面部后再使用选择器", icon="INFO")

    col = layout.column(align=True)
    for blend_name in mapping.mapping_keys(kind):
        prop_name = mapping.mapping_prop_name(kind, blend_name)
        if can_search_blends:
            col.prop_search(scene, prop_name, face_for_search.data.shape_keys, "key_blocks", text=blend_name, icon="SHAPEKEY_DATA")
        else:
            col.prop(scene, prop_name, text=blend_name)


def _truncate_ui_line(text: str, limit: int = 96) -> str:
    value = str(text)
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "..."


def draw_arp_helper(layout, scene):
    box = layout.box()
    col = box.column(align=True)
    col.label(text="Auto Rig Pro 辅助", icon="ARMATURE_DATA")
    col.label(text=f"内建预设：{mapping_target_rig.adapter_by_id(mapping_target_rig.TARGET_RIG_ARP).builtin_preset_file}", icon="INFO")
    arm_obj = getattr(scene, "vmc_link_armature", None)
    preview_arm = getattr(scene, "vmc_link_preview_armature", None)
    if mapping_arp.analyze_armature(arm_obj)["is_arp"]:
        if not mapping.has_pose_bones(preview_arm) or "UpperChest" not in preview_arm.pose.bones:
            col.label(text="ARP 驱动需要重建新版 VRM 预览骨架", icon="ERROR")
        else:
            col.label(text="接收时自动切换四肢 FK，停止后恢复", icon="INFO")

    row = col.row(align=True)
    row.operator("vmc_link.inspect_arp_rig", text="检查 ARP 骨架", icon="VIEWZOOM")
    row.operator("vmc_link.autofill_arp_bone_map", text="应用标准 ARP 映射", icon="SHADERFX")

    validate_row = col.row(align=True)
    validate_row.operator("vmc_link.validate_arp_bone_map", text="校验当前映射", icon="CHECKMARK")

    report_title = str(getattr(scene, "vmc_link_arp_report_title", "")).strip()
    report_text = str(getattr(scene, "vmc_link_arp_report", "")).strip()
    if not report_text:
        col.label(text="先绑定目标骨架，再执行检查、自动填充或校验", icon="INFO")
        return

    report_box = col.box()
    icon = "CHECKMARK" if bool(getattr(scene, "vmc_link_arp_is_detected", False)) else "ERROR"
    report_box.label(text=report_title or "ARP 报告", icon=icon)
    for line in report_text.splitlines():
        report_box.label(text=_truncate_ui_line(line), icon="DOT")


def draw_mmd_helper(layout, scene):
    box = layout.box()
    col = box.column(align=True)
    col.label(text="MMD 辅助", icon="OUTLINER_OB_ARMATURE")
    col.label(text=f"内建预设：{mapping_target_rig.adapter_by_id(mapping_target_rig.TARGET_RIG_MMD).builtin_preset_file}", icon="INFO")
    col.label(text=f"默认名表: {len(mapping_mmd.MMD_DEFAULT_BONE_TARGETS)} 项", icon="INFO")
    col.label(text="支持标准 MMD 骨名与 .L/.R 侧别名解析", icon="INFO")
    col.label(text="根位移写入骨骼由 CenterMotion 映射项决定，MMD 默认使用 全ての親", icon="INFO")

    row = col.row(align=True)
    row.operator("vmc_link.inspect_mmd_rig", text="检查 MMD 骨架", icon="VIEWZOOM")
    row.operator("vmc_link.autofill_mmd_bone_map", text="应用标准 MMD 映射", icon="SHADERFX")

    validate_row = col.row(align=True)
    validate_row.operator("vmc_link.validate_mmd_bone_map", text="校验当前映射", icon="CHECKMARK")

    report_title = str(getattr(scene, "vmc_link_mmd_report_title", "")).strip()
    report_text = str(getattr(scene, "vmc_link_mmd_report", "")).strip()
    if not report_text:
        col.label(text="先绑定目标骨架，再执行检查、自动填充或校验", icon="INFO")
        return

    report_box = col.box()
    icon = "CHECKMARK" if bool(getattr(scene, "vmc_link_mmd_is_detected", False)) else "ERROR"
    report_box.label(text=report_title or "MMD 报告", icon=icon)
    for line in report_text.splitlines():
        report_box.label(text=_truncate_ui_line(line), icon="DOT")


def draw_vrm_helper(layout, scene):
    box = layout.box()
    col = box.column(align=True)
    col.label(text="VRM / 通用骨架辅助", icon="ARMATURE_DATA")
    col.label(text=f"内建预设：{mapping_target_rig.adapter_by_id(mapping_target_rig.TARGET_RIG_GENERIC).builtin_preset_file}", icon="INFO")
    col.label(text=f"默认名表: {len(mapping_vrm.VRM_DEFAULT_BONE_TARGETS)} 项", icon="INFO")
    col.label(text="目标预览和录制复用现有通用骨架链路", icon="INFO")

    row = col.row(align=True)
    row.operator("vmc_link.inspect_vrm_rig", text="检查 VRM 骨架", icon="VIEWZOOM")
    row.operator("vmc_link.autofill_vrm_bone_map", text="应用标准 VRM 映射", icon="SHADERFX")

    validate_row = col.row(align=True)
    validate_row.operator("vmc_link.validate_vrm_bone_map", text="校验当前映射", icon="CHECKMARK")

    report_title = str(getattr(scene, "vmc_link_vrm_report_title", "")).strip()
    report_text = str(getattr(scene, "vmc_link_vrm_report", "")).strip()
    if not report_text:
        col.label(text="先绑定目标骨架，再执行检查、自动填充或校验", icon="INFO")
        return

    report_box = col.box()
    icon = "CHECKMARK" if bool(getattr(scene, "vmc_link_vrm_is_detected", False)) else "ERROR"
    report_box.label(text=report_title or "VRM 报告", icon=icon)
    for line in report_text.splitlines():
        report_box.label(text=_truncate_ui_line(line), icon="DOT")


class VMC_LINK_PT_bone_mapping_panel(bpy.types.Panel):
    bl_label = "骨骼映射"
    bl_idname = "VMC_LINK_PT_bone_mapping_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "VMC Link"
    bl_parent_id = "VMC_LINK_PT_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.prop(scene, "vmc_link_target_rig_type", text="目标骨架类型")
        arm_obj = getattr(scene, "vmc_link_armature", None)
        rig_info = mapping_target_rig.analyze_scene_target(scene, arm_obj)
        rig_type = str(rig_info["selected_rig"]).upper()
        runtime_rig = str(rig_info["resolved_rig"]).upper()
        runtime_strategy = str(rig_info["runtime_strategy"]).upper()
        state_box = layout.box()
        state_box.label(text=f"运行时目标类型: {runtime_rig}", icon="INFO")
        state_box.label(text=f"运行时驱动策略: {runtime_strategy}", icon="INFO")
        if rig_type == "ARP" and rig_info["resolved_rig"] != mapping_target_rig.TARGET_RIG_ARP:
            state_box.label(text="当前目标骨架未识别为 ARP，运行时将回退到通用骨架路径", icon="ERROR")
        if rig_type == "MMD":
            if rig_info["resolved_rig"] != mapping_target_rig.TARGET_RIG_MMD:
                state_box.label(text="当前目标骨架未识别为 MMD，运行时将回退到通用骨架路径", icon="ERROR")
            else:
                state_box.label(text="当前 MMD 类型已接入专用运行时入口", icon="CHECKMARK")
        if rig_type == "ARP":
            draw_arp_helper(layout, scene)
        elif rig_type == "MMD":
            draw_mmd_helper(layout, scene)
        else:
            draw_vrm_helper(layout, scene)
        draw_mapping_preset_controls(layout, scene, constants.MAPPING_KIND_BONE)
        draw_bone_mapping_entries(layout, scene)


class VMC_LINK_PT_vmc_blend_mapping_panel(bpy.types.Panel):
    bl_label = "VMC 表情映射"
    bl_idname = "VMC_LINK_PT_vmc_blend_mapping_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "VMC Link"
    bl_parent_id = "VMC_LINK_PT_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        draw_mapping_preset_controls(layout, scene, constants.MAPPING_KIND_VMC_BLEND)
        draw_blend_mapping_entries(layout, scene, constants.MAPPING_KIND_VMC_BLEND)


class VMC_LINK_PT_arkit_blend_mapping_panel(bpy.types.Panel):
    bl_label = "ARKit 表情映射"
    bl_idname = "VMC_LINK_PT_arkit_blend_mapping_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "VMC Link"
    bl_parent_id = "VMC_LINK_PT_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        draw_mapping_preset_controls(layout, scene, constants.MAPPING_KIND_ARKIT_BLEND)
        draw_blend_mapping_entries(layout, scene, constants.MAPPING_KIND_ARKIT_BLEND)
