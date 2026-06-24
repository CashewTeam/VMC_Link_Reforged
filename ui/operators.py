import bpy

from ..mapping import arp as mapping_arp
from ..mapping import mapper as mapping
from ..mapping import preset_store as presets
from ..preview import dummy_vrm
from ..runtime import driver as runtime
from ..runtime import network


class VMC_LINK_OT_toggle_receiver(bpy.types.Operator):
    bl_idname = "vmc_link.toggle_receiver"
    bl_label = "切换接收器"

    def execute(self, context):
        scene = context.scene
        try:
            if network.is_session_active():
                network.stop_server(scene)
                self.report({"INFO"}, "VMC Link 接收器已停止")
            else:
                network.start_server(scene)
                self.report({"INFO"}, f"VMC Link 接收器已启动：{runtime.describe_receiver_endpoints(scene)}")
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class VMC_LINK_OT_start_receiver(bpy.types.Operator):
    bl_idname = "vmc_link.start_receiver"
    bl_label = "启动接收"

    def execute(self, context):
        scene = context.scene
        try:
            network.start_server(scene)
            self.report({"INFO"}, f"VMC Link 接收器已启动：{runtime.describe_receiver_endpoints(scene)}")
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class VMC_LINK_OT_pause_receiver(bpy.types.Operator):
    bl_idname = "vmc_link.pause_receiver"
    bl_label = "暂停或继续接收"

    def execute(self, context):
        scene = context.scene
        try:
            if network.is_paused():
                network.resume_server(scene)
                self.report({"INFO"}, "VMC Link 接收器已继续")
            else:
                network.pause_server()
                self.report({"INFO"}, "VMC Link 接收器已暂停")
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class VMC_LINK_OT_stop_receiver(bpy.types.Operator):
    bl_idname = "vmc_link.stop_receiver"
    bl_label = "停止接收"

    def execute(self, context):
        scene = context.scene
        try:
            network.stop_server(scene)
            self.report({"INFO"}, "VMC Link 接收器已停止并恢复骨架初始状态")
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


class VMC_LINK_OT_calibrate_dummy_armature_lengths(bpy.types.Operator):
    bl_idname = "vmc_link.calibrate_dummy_armature_lengths"
    bl_label = "按目标骨架校准 VRM 预览骨架长度"

    def execute(self, context):
        try:
            calibrated = dummy_vrm.calibrate_intermediate_rig_lengths(context)
            self.report({"INFO"}, f"已校准 {len(calibrated)} 根 VRM 预览骨骼长度")
        except Exception as exc:
            self.report({"ERROR"}, f"校准 VRM 预览骨架长度失败：{exc}")
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


class VMC_LINK_OT_inspect_arp_rig(bpy.types.Operator):
    bl_idname = "vmc_link.inspect_arp_rig"
    bl_label = "检查 ARP 骨架"

    def execute(self, context):
        scene = context.scene
        analysis = mapping_arp.analyze_armature(getattr(scene, "vmc_link_armature", None))
        report_lines = mapping_arp.inspect_report_lines(analysis)
        mapping_arp.store_scene_report(scene, "ARP 骨架检查", report_lines, analysis["is_arp"])
        if not analysis["is_target_valid"]:
            self.report({"ERROR"}, "请先绑定目标骨架")
            return {"CANCELLED"}
        if not analysis["is_arp"]:
            self.report({"ERROR"}, "当前目标骨架不是可识别的 Auto Rig Pro 标准控制骨架")
            return {"CANCELLED"}
        self.report({"INFO"}, f"ARP 骨架检查通过：{analysis['target_name']}")
        return {"FINISHED"}


class VMC_LINK_OT_autofill_arp_bone_map(bpy.types.Operator):
    bl_idname = "vmc_link.autofill_arp_bone_map"
    bl_label = "应用标准 ARP 映射"

    def execute(self, context):
        scene = context.scene
        try:
            result = mapping_arp.autofill_scene_mapping(scene)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        report_lines = mapping_arp.autofill_report_lines(result)
        mapping_arp.store_scene_report(scene, "ARP 自动填充", report_lines, result["analysis"]["is_arp"])
        self.report({"INFO"}, f"已应用 {len(result['written'])} 项标准 ARP 映射")
        return {"FINISHED"}


class VMC_LINK_OT_validate_arp_bone_map(bpy.types.Operator):
    bl_idname = "vmc_link.validate_arp_bone_map"
    bl_label = "校验当前映射"

    def execute(self, context):
        scene = context.scene
        validation = mapping_arp.validate_scene_mapping(scene)
        report_lines = mapping_arp.validation_report_lines(validation)
        mapping_arp.store_scene_report(scene, "ARP 映射校验", report_lines, validation["is_arp"])
        if not validation["is_target_valid"]:
            self.report({"ERROR"}, "请先绑定目标骨架")
            return {"CANCELLED"}
        if not validation["is_arp"]:
            self.report({"ERROR"}, "当前目标骨架不是可识别的 Auto Rig Pro 标准控制骨架")
            return {"CANCELLED"}
        self.report({"INFO"}, "已完成 ARP 映射校验")
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
    VMC_LINK_OT_start_receiver,
    VMC_LINK_OT_pause_receiver,
    VMC_LINK_OT_stop_receiver,
    VMC_LINK_OT_refresh_mapping_presets,
    VMC_LINK_OT_save_mapping_preset,
    VMC_LINK_OT_load_mapping_preset,
    VMC_LINK_OT_create_dummy_armature,
    VMC_LINK_OT_calibrate_dummy_armature_lengths,
    VMC_LINK_OT_import_arkit_preview_face,
    VMC_LINK_OT_rebuild_maps,
    VMC_LINK_OT_inspect_arp_rig,
    VMC_LINK_OT_autofill_arp_bone_map,
    VMC_LINK_OT_validate_arp_bone_map,
    VMC_LINK_OT_toggle_recording,
)
