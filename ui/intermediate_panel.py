import bpy

from ..preview import dummy_vrm
from ..runtime import driver as runtime


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

        if status["armature"] is None:
            body_col.label(text="尚未创建 VRM 预览骨架", icon="INFO")
        else:
            body_col.label(
                text="已识别为标准中间层骨架" if status["armature_is_intermediate"] else "当前对象不是标准中间层骨架",
                icon="CHECKMARK" if status["armature_is_intermediate"] else "ERROR",
            )
            body_col.label(text=f"必需骨骼: {status['required_present']} / {status['required_total']}")
            body_col.label(text=f"手指骨骼: {status['optional_present']} / {status['optional_total']}")
            body_col.label(text=f"已写入角色标记: {'是' if status['armature_tagged'] else '否'}")
            body_col.label(text=f"根位移来源: {runtime.get_root_motion_source()}")
            if status["required_missing"]:
                missing_preview = ", ".join(status["required_missing"][:6])
                suffix = " ..." if len(status["required_missing"]) > 6 else ""
                body_col.label(text=f"缺失骨骼: {missing_preview}{suffix}", icon="INFO")

        body_col.operator("vmc_link.create_dummy_armature", text="创建/重建 VRM 预览骨架", icon="ARMATURE_DATA")
        body_col.operator("vmc_link.calibrate_dummy_armature_lengths", text="按目标骨架校准长度", icon="DRIVER_DISTANCE")

        face_box = layout.box()
        face_col = face_box.column(align=True)
        face_col.label(text="ARKit 52-Key 预览面部", icon="SHAPEKEY_DATA")
        face_col.label(text=f"面部来源: {runtime.get_face_source_label(scene)}")
        if status["face_object"] is None:
            face_col.label(text="尚未导入 ARKit 调试面部", icon="INFO")
        else:
            face_col.label(
                text="已绑定 ARKit 预览面部" if status["face_object_is_preview"] else "当前对象不是 ARKit 预览面部",
                icon="CHECKMARK" if status["face_object_is_preview"] else "ERROR",
            )
        face_col.label(text=f"ARKit 键覆盖数: {status['arkit_shape_matches']} / {status['arkit_key_total']}")
        face_col.label(
            text="调试资产可用" if status["arkit_debug_asset_exists"] else "调试资产缺失",
            icon="CHECKMARK" if status["arkit_debug_asset_exists"] else "ERROR",
        )
        if runtime.is_arkit_face_source_enabled(scene):
            face_col.label(text="当前会按 ARKit 52 Key 实时驱动该预览面部", icon="INFO")
        else:
            face_col.label(text="仅当面部来源为 RhyLive ARKit 时才会驱动该预览面部", icon="INFO")
        face_col.operator("vmc_link.import_arkit_preview_face", text="导入 ARKit 调试面部", icon="IMPORT")
        face_col.label(text=status["arkit_debug_asset_path"])
