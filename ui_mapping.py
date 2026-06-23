import bpy

from . import constants, mapping, presets


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
    for vmc_name in constants.BONE_ALIASES:
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
