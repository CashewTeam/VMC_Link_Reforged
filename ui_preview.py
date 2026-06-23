import time

import bpy

from . import constants, helpers, network, runtime, state


def draw_vmc_preview(layout):
    header = layout.box()
    col = header.column(align=True)
    col.label(text="VMC 原始流", icon="RADIOBUT_ON" if network.is_running() else "RADIOBUT_OFF")

    if network.is_running():
        if state.last_packet_ts > 0.0:
            age = time.time() - state.last_packet_ts
            col.label(text=f"最近数据包：{age:.2f} 秒前", icon="TIME")
        else:
            col.label(text="等待接收数据包", icon="TIME")
    elif network.is_paused():
        col.label(text="接收已暂停", icon="PAUSE")
    else:
        col.label(text="接收器已停止", icon="INFO")

    root_entries = []
    if state.root_buf is not None:
        root_entries.append(f"Root/Pos: {helpers.format_preview_pose(state.root_buf)}")
    if state.waist_buf is not None:
        root_entries.append(f"Tra/Pos: {helpers.format_preview_pose(state.waist_buf)}")
    runtime.draw_preview_entries(layout, "Root / Tra", root_entries, "尚未接收到 Root 或 Tra 数据")

    bone_entries = [f"{name}: {helpers.format_preview_pose(raw)}" for name, raw in sorted(state.bone_buf.items(), key=lambda item: str(item[0]).lower())]
    runtime.draw_preview_entries(layout, f"Bone/Pos ({len(state.bone_buf)})", bone_entries, "尚未接收到骨骼数据")

    blend_entries = [f"{name}: {helpers.format_preview_value(val)}" for name, val in sorted(state.blend_buf.items(), key=lambda item: str(item[0]).lower())]
    runtime.draw_preview_entries(layout, f"Blend/Val ({len(state.blend_buf)})", blend_entries, "尚未接收到表情数据")


def draw_arkit_preview(layout, scene):
    header = layout.box()
    col = header.column(align=True)
    source_enabled = runtime.is_arkit_face_source_enabled(scene)

    col.label(text="RhyLive OSC /Face", icon="RADIOBUT_ON" if source_enabled and network.is_running() else "RADIOBUT_OFF")

    if not source_enabled:
        col.label(text="将面部来源切换为 RhyLive ARKit 后可启用", icon="INFO")
    elif state.arkit_last_packet_ts > 0.0:
        age = time.time() - state.arkit_last_packet_ts
        col.label(text=f"最近数据包：{age:.2f} 秒前", icon="TIME")
    elif network.is_running():
        col.label(text="等待 /Face 数据包", icon="TIME")
    elif network.is_paused():
        col.label(text="接收已暂停", icon="PAUSE")
    else:
        col.label(text="接收器已停止", icon="INFO")

    preview_entries = [f"{name}: {helpers.format_preview_value(state.arkit_blend_buf.get(name, 0.0))}" for name in constants.ARKIT_BLENDSHAPE_KEYS]
    runtime.draw_preview_entries(layout, f"ARKit 系数 ({len(constants.ARKIT_BLENDSHAPE_KEYS)})", preview_entries, "尚未接收到 ARKit 系数")


class VMC_LINK_PT_preview_panel(bpy.types.Panel):
    bl_label = "数据预览"
    bl_idname = "VMC_LINK_PT_preview_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "VMC Link"
    bl_parent_id = "VMC_LINK_PT_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=False)
        vmc_col = row.column(align=True)
        arkit_col = row.column(align=True)

        draw_vmc_preview(vmc_col)
        draw_arkit_preview(arkit_col, context.scene)


CLASSES = (
    VMC_LINK_PT_preview_panel,
)
