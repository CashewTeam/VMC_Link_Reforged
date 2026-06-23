import bpy

from . import constants, dummy_vrm, mapping, network, presets, runtime


class VMC_LINK_OT_toggle_receiver(bpy.types.Operator):
    bl_idname = "vmc_link.toggle_receiver"
    bl_label = "切换接收器"

    def execute(self, context):
        scene = context.scene
        try:
            if network.is_running():
                network.stop_server(scene)
                self.report({"INFO"}, "VMC Link 接收器已停止")
            else:
                network.start_server(scene)
                self.report({"INFO"}, f"VMC Link 接收器已启动：{runtime.describe_receiver_endpoints(scene)}")
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class VMC_LINK_OT_refresh_mapping_presets(bpy.types.Operator):
    bl_idname = "vmc_link.refresh_mapping_presets"
    bl_label = "刷新映射预设"

    mapping_kind: bpy.props.StringProperty()

    def execute(self, context):
        kind = str(self.mapping_kind)
        try:
            presets.refresh_mapping_presets(context.scene, kind)
            self.report({"INFO"}, f"已刷新 {mapping.mapping_kind_label(kind)} 预设")
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class VMC_LINK_OT_save_mapping_preset(bpy.types.Operator):
    bl_idname = "vmc_link.save_mapping_preset"
    bl_label = "保存映射预设"

    mapping_kind: bpy.props.StringProperty()

    def execute(self, context):
        kind = str(self.mapping_kind)
        try:
            file_name = presets.save_mapping_preset(context.scene, kind)
            self.report({"INFO"}, f"已保存 {mapping.mapping_kind_label(kind)} 预设：{file_name}")
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class VMC_LINK_OT_load_mapping_preset(bpy.types.Operator):
    bl_idname = "vmc_link.load_mapping_preset"
    bl_label = "加载映射预设"

    mapping_kind: bpy.props.StringProperty()

    def execute(self, context):
        kind = str(self.mapping_kind)
        try:
            file_name = presets.load_mapping_preset(context.scene, kind)
            self.report({"INFO"}, f"已加载 {mapping.mapping_kind_label(kind)} 预设：{file_name}")
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class VMC_LINK_OT_create_dummy_armature(bpy.types.Operator):
    bl_idname = "vmc_link.create_dummy_armature"
    bl_label = "创建或重建 VRM 预览骨架"

    def execute(self, context):
        try:
            preview_arm = getattr(context.scene, "vmc_link_preview_armature", None)
            rebuild = dummy_vrm.is_vrm_intermediate_rig(preview_arm)
            arm_obj = dummy_vrm.create_intermediate_rig(context, rebuild=rebuild)
            self.report({"INFO"}, f"已{'重建' if rebuild else '创建'} VRM 预览骨架：{arm_obj.name}")
        except Exception as exc:
            self.report({"ERROR"}, f"创建 VRM 预览骨架失败：{exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class VMC_LINK_OT_import_arkit_preview_face(bpy.types.Operator):
    bl_idname = "vmc_link.import_arkit_preview_face"
    bl_label = "导入 ARKit 调试面部"

    def execute(self, context):
        try:
            face_obj = dummy_vrm.import_arkit_preview_face(context)
            self.report({"INFO"}, f"已绑定 ARKit 预览面部：{face_obj.name}")
        except Exception as exc:
            self.report({"ERROR"}, f"导入 ARKit 调试面部失败：{exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class VMC_LINK_OT_rebuild_maps(bpy.types.Operator):
    bl_idname = "vmc_link.rebuild_maps"
    bl_label = "重建目标映射"

    def execute(self, context):
        mapping.rebuild_maps(context.scene)
        self.report({"INFO"}, "已重建目标映射")
        return {"FINISHED"}


class VMC_LINK_OT_toggle_recording(bpy.types.Operator):
    bl_idname = "vmc_link.toggle_recording"
    bl_label = "切换录制"

    def execute(self, _context):
        runtime.set_recording(not runtime.is_recording())
        if runtime.is_recording():
            self.report({"INFO"}, "开始录制")
        else:
            self.report({"INFO"}, "停止录制")
        return {"FINISHED"}


CLASSES = (
    VMC_LINK_OT_toggle_receiver,
    VMC_LINK_OT_refresh_mapping_presets,
    VMC_LINK_OT_save_mapping_preset,
    VMC_LINK_OT_load_mapping_preset,
    VMC_LINK_OT_create_dummy_armature,
    VMC_LINK_OT_import_arkit_preview_face,
    VMC_LINK_OT_rebuild_maps,
    VMC_LINK_OT_toggle_recording,
)
