import bpy

from ..runtime import driver as runtime


class VMC_LINK_PT_recording_panel(bpy.types.Panel):
    bl_label = "录制"
    bl_idname = "VMC_LINK_PT_recording_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "VMC Link"
    bl_parent_id = "VMC_LINK_PT_panel"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        is_recording = runtime.is_recording()
        action_labels = runtime.get_recording_action_labels(scene)
        range_error = runtime.get_recording_range_error(scene)
        frame_start = runtime.get_recording_start_frame(scene)
        frame_end = runtime.get_recording_end_frame(scene)
        interpolation_enabled = runtime.is_recording_interpolation_enabled(scene)
        transition_enabled = runtime.is_recording_transition_enabled(scene)
        transition_frames = runtime.get_recording_transition_frames(scene)

        status_box = layout.box()
        status_col = status_box.column(align=True)
        status_col.label(text="录制状态", icon="REC")
        if is_recording:
            status_col.label(text=f"录制中：已缓存 {runtime.get_recording_sample_count()} 帧", icon="REC")
        else:
            status_col.label(text="当前未在录制", icon="INFO")
        status_col.label(text=f"输出范围：{frame_start} - {frame_end}")
        status_col.label(text=f"补帧插值：{'启用' if interpolation_enabled else '关闭'}")
        status_col.label(text=f"起始过渡：{'启用' if transition_enabled else '关闭'}")
        if transition_enabled:
            status_col.label(text=f"过渡帧数：{transition_frames}")
        status_col.label(text=f"目标骨架 Action：{action_labels['armature']}")
        status_col.label(text=f"目标面部 Action：{action_labels['face']}")

        range_box = layout.box()
        range_col = range_box.column(align=True)
        range_col.label(text="帧范围", icon="PREVIEW_RANGE")
        range_col.prop(scene, "vmc_link_record_start_frame")
        range_col.prop(scene, "vmc_link_record_end_frame")
        range_row = range_col.row(align=True)
        range_row.operator("vmc_link.set_record_start_to_current_frame", text="当前帧设为开始", icon="SETTINGS")
        range_row.operator("vmc_link.set_record_end_to_current_frame", text="当前帧设为结束", icon="SETTINGS")
        if range_error:
            range_col.label(text=range_error, icon="ERROR")

        transition_box = layout.box()
        transition_col = transition_box.column(align=True)
        transition_col.label(text="录制采样", icon="IPO_EASE_IN_OUT")
        transition_col.prop(scene, "vmc_link_record_interpolation_enabled")
        transition_col.prop(scene, "vmc_link_record_transition_enabled")
        transition_col.prop(scene, "vmc_link_record_transition_frames")
        transition_col.label(text="关闭补帧插值后，只保留实际采样落点", icon="INFO")
        transition_col.label(text="从接收启动时的初始姿态过渡到过渡结束帧姿态", icon="INFO")

        action_box = layout.box()
        action_col = action_box.column(align=True)
        action_col.label(text="录制操作", icon="ACTION")
        button_row = action_col.row(align=True)
        button_row.enabled = not bool(range_error)
        rec_icon = "PAUSE" if is_recording else "REC"
        rec_label = "停止录制" if is_recording else "开始录制"
        button_row.operator("vmc_link.toggle_recording", text=rec_label, icon=rec_icon)

        clear_row = action_col.row(align=True)
        clear_row.enabled = (not is_recording) and (not bool(range_error))
        clear_row.operator("vmc_link.clear_recording_range_keys", text="清空范围内关键帧", icon="TRASH")
        action_col.label(text="不会删除范围外关键帧", icon="INFO")


CLASSES = (
    VMC_LINK_PT_recording_panel,
)
