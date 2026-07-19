import bpy

from ..runtime import driver as runtime
from .main_panel import draw_receiver_controls


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
        is_baking = runtime.is_recording_bake_active()
        bake_status = runtime.get_recording_bake_status()
        range_error = runtime.get_recording_range_error(scene)
        frame_start = runtime.get_recording_start_frame(scene)
        frame_end = runtime.get_recording_end_frame(scene)
        interpolation_enabled = runtime.is_recording_interpolation_enabled(scene)
        transition_enabled = runtime.is_recording_transition_enabled(scene)
        transition_frames = runtime.get_recording_transition_frames(scene)
        record_parts = []
        if bool(getattr(scene, "vmc_link_record_motion_enabled", True)):
            record_parts.append("动作")
        if bool(getattr(scene, "vmc_link_record_shape_keys_enabled", True)):
            record_parts.append("形态键")
        record_content = "+".join(record_parts) or "无"

        status_box = layout.box()
        status_col = status_box.column(align=True)
        status_col.label(text="录制状态", icon="REC")
        if is_recording:
            status_text = f"录制中：{runtime.get_recording_sample_count()} 帧"
            status_icon = "REC"
        elif is_baking:
            status_text = f"保存中：{bake_status['label']}"
            status_icon = "TIME"
        else:
            status_text = "当前未在录制"
            status_icon = "INFO"

        status_rows = (
            ((status_text, status_icon), (f"输出：{frame_start} - {frame_end}", "PREVIEW_RANGE")),
            ((f"内容：{record_content}", "ACTION"), (f"补帧：{'启用' if interpolation_enabled else '关闭'}", "IPO_EASE_IN_OUT")),
            ((f"过渡：{'启用' if transition_enabled else '关闭'}", "IPO_EASE_IN_OUT"), (f"过渡帧：{transition_frames if transition_enabled else '-'}", "TIME")),
        )
        for left_entry, right_entry in status_rows:
            row = status_col.row(align=True)
            row.label(text=left_entry[0], icon=left_entry[1])
            row.label(text=right_entry[0], icon=right_entry[1])

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
        transition_col.prop(scene, "vmc_link_record_fast_bake")
        transition_col.label(text="关闭补帧插值后，只保留实际采样落点", icon="INFO")
        transition_col.label(text="从接收启动时的初始姿态过渡到过渡结束帧姿态", icon="INFO")

        action_box = layout.box()
        action_col = action_box.column(align=True)
        action_col.label(text="录制操作", icon="ACTION")
        draw_receiver_controls(action_col)
        button_row = action_col.row(align=True)
        button_row.enabled = (not bool(range_error)) and (not is_baking)
        if is_baking:
            rec_icon = "SORTTIME"
            rec_label = "正在保存"
        else:
            rec_icon = "PAUSE" if is_recording else "REC"
            rec_label = "停止录制" if is_recording else "开始录制"
        button_row.operator("vmc_link.toggle_recording", text=rec_label, icon=rec_icon)

        record_mode_row = action_col.row(align=True)
        record_mode_row.enabled = (not is_recording) and (not is_baking)
        record_mode_row.prop(scene, "vmc_link_record_motion_enabled", text="动作录制")
        record_mode_row.prop(scene, "vmc_link_record_shape_keys_enabled", text="形态键录制")

        action_select_col = action_col.column(align=True)
        action_select_col.enabled = (not is_recording) and (not is_baking)
        action_select_col.label(text="录制 Action", icon="ACTION")
        armature_split = action_select_col.row(align=True).split(factor=0.18, align=True)
        armature_split.column(align=True).label(text="目标骨架")
        armature_action_row = armature_split.row(align=True)
        armature_action_row.prop(scene, "vmc_link_record_armature_action", text="")
        armature_new_row = armature_action_row.row(align=True)
        armature_new_row.scale_x = 0.65
        armature_new_row.operator("vmc_link.new_recording_action", text="新建", icon="ADD").target = "ARMATURE"
        face_split = action_select_col.row(align=True).split(factor=0.18, align=True)
        face_split.column(align=True).label(text="目标面部")
        face_action_row = face_split.row(align=True)
        face_action_row.prop(scene, "vmc_link_record_face_action", text="")
        face_new_row = face_action_row.row(align=True)
        face_new_row.scale_x = 0.65
        face_new_row.operator("vmc_link.new_recording_action", text="新建", icon="ADD").target = "FACE"
        action_select_col.label(text="留空会解除当前绑定；开始录制时自动新建", icon="INFO")

        clear_row = action_col.row(align=True)
        clear_row.enabled = (not is_recording) and (not is_baking) and (not bool(range_error))
        clear_row.operator("vmc_link.clear_recording_range_keys", text="清空范围内关键帧", icon="TRASH")
        action_col.label(text="不会删除范围外关键帧", icon="INFO")


CLASSES = (
    VMC_LINK_PT_recording_panel,
)
