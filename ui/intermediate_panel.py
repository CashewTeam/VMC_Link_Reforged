import bpy

from ..mapping import target_rig as mapping_target_rig
from ..preview import dummy_vrm
from ..runtime import driver as runtime


def _draw_status_rows(layout, rows):
    for left_entry, right_entry in rows:
        row = layout.row(align=True)
        row.label(text=left_entry[0], icon=left_entry[1])
        row.label(text=right_entry[0], icon=right_entry[1])


class VMC_LINK_PT_intermediate_panel(bpy.types.Panel):
    bl_label = "中间层预览"
    bl_idname = "VMC_LINK_PT_intermediate_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "VMC Link"
    bl_parent_id = "VMC_LINK_PT_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        status = dummy_vrm.collect_intermediate_status(scene)

        body_box = layout.box()
        body_col = body_box.column(align=True)
        body_col.label(text="VRM 预览骨架", icon="ARMATURE_DATA")
        calibration_info = mapping_target_rig.analyze_scene_target(scene, getattr(scene, "vmc_link_armature", None))
        selected_adapter = calibration_info["selected_adapter"]

        if status["armature"] is None:
            armature_status = "状态：未创建"
            armature_icon = "INFO"
        else:
            armature_status = "状态：标准骨架" if status["armature_is_intermediate"] else "状态：非标准骨架"
            armature_icon = "CHECKMARK" if status["armature_is_intermediate"] else "ERROR"

        _draw_status_rows(
            body_col,
            (
                ((armature_status, armature_icon), (f"校准：{selected_adapter.label}", "INFO")),
                ((f"必需：{status['required_present']} / {status['required_total']}", "BONE_DATA"), (f"手指：{status['optional_present']} / {status['optional_total']}", "BONE_DATA")),
                ((f"标记：{'是' if status['armature_tagged'] else '否'}", "BOOKMARKS"), (f"根位移：{runtime.get_root_motion_source()}", "EMPTY_ARROWS")),
            ),
        )
        if selected_adapter.rig_id != mapping_target_rig.TARGET_RIG_GENERIC and calibration_info["resolved_rig"] != selected_adapter.rig_id:
            body_col.label(text="当前目标骨架未通过所选类型识别，校准会被拒绝", icon="ERROR")
        if status["required_missing"]:
            missing_preview = ", ".join(status["required_missing"][:6])
            suffix = " ..." if len(status["required_missing"]) > 6 else ""
            body_col.label(text=f"缺失骨骼: {missing_preview}{suffix}", icon="INFO")

        body_col.operator("vmc_link.create_dummy_armature", text="创建/重建 VRM 预览骨架", icon="ARMATURE_DATA")
        body_col.operator("vmc_link.calibrate_dummy_armature_lengths", text="按目标骨架校准长度", icon="DRIVER_DISTANCE")

        face_box = layout.box()
        face_col = face_box.column(align=True)
        face_col.label(text="ARKit 52-Key 预览面部", icon="SHAPEKEY_DATA")
        if status["face_object"] is None:
            face_status = "状态：未导入"
            face_icon = "INFO"
            face_name = "对象：-"
        else:
            face_status = "状态：已绑定" if status["face_object_is_preview"] else "状态：非预览面部"
            face_icon = "CHECKMARK" if status["face_object_is_preview"] else "ERROR"
            face_name = f"对象：{status['face_object'].name}"

        _draw_status_rows(
            face_col,
            (
                ((face_status, face_icon), (f"来源：{runtime.get_face_source_label(scene)}", "INFO")),
                ((f"键覆盖：{status['arkit_shape_matches']} / {status['arkit_key_total']}", "SHAPEKEY_DATA"), (f"资产：{'可用' if status['arkit_debug_asset_exists'] else '缺失'}", "CHECKMARK" if status["arkit_debug_asset_exists"] else "ERROR")),
                ((f"实时驱动：{'是' if runtime.is_arkit_face_source_enabled(scene) else '否'}", "DRIVER"), (face_name, "OBJECT_DATA")),
            ),
        )
        face_col.operator("vmc_link.import_arkit_preview_face", text="导入 ARKit 调试面部", icon="IMPORT")
