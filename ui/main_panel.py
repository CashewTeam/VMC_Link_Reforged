import time

from ..runtime import driver as runtime
from ..runtime import network


def draw_receiver_controls(layout):
    row = layout.row(align=True)
    if network.is_session_active():
        pause_label = "继续接收" if network.is_paused() else "暂停接收"
        pause_icon = "PLAY" if network.is_paused() else "PAUSE"
        row.operator("vmc_link.pause_receiver", text=pause_label, icon=pause_icon)
        row.operator("vmc_link.stop_receiver", text="停止接收", icon="CANCEL")
    else:
        row.operator("vmc_link.start_receiver", text="启动接收", icon="PLAY")


def draw_main_panel(layout, context):
    scene = context.scene

    draw_receiver_controls(layout)

    if network.is_session_active():
        if network.is_paused():
            layout.label(text="已暂停", icon="PAUSE")
        else:
            last_pkt = runtime.get_latest_receiver_timestamp(scene)
            if last_pkt == 0.0:
                layout.label(text="等待连接", icon="TIME")
            elif (time.time() - last_pkt) <= 2.0:
                if getattr(scene, "vmc_link_live_preview", True):
                    layout.label(text="已连接", icon="CHECKMARK")
                else:
                    layout.label(text="仅更新预览层", icon="INFO")
            else:
                layout.label(text="连接中断", icon="ERROR")

    layout.separator()
    layout.label(text="接收设置", icon="PREFERENCES")

    col = layout.column(align=True)
    col.prop(scene, "vmc_link_bind_mode")
    if scene.vmc_link_bind_mode == "CUSTOM":
        col.prop(scene, "vmc_link_bind_address_custom")
    col.prop(scene, "vmc_link_port")
    col.prop(scene, "vmc_link_face_source")
    if runtime.is_arkit_face_source_enabled(scene):
        col.prop(scene, "vmc_link_arkit_port")
    else:
        col.prop(scene, "vmc_link_arkit_port", text="RhyLive 输入端口")
    col.prop(scene, "vmc_link_arkit_forward_enabled")
    if scene.vmc_link_arkit_forward_enabled:
        col.prop(scene, "vmc_link_arkit_forward_port")
        if scene.vmc_link_arkit_forward_port == scene.vmc_link_arkit_port:
            col.label(text="转发端口不能与 ARKit 接收端口相同", icon="ERROR")
        elif network.is_arkit_forwarding_running():
            col.label(text="RhyLive 本地转发运行中", icon="CHECKMARK")
    col.prop(scene, "vmc_link_rate_hz")
    col.prop(scene, "vmc_link_live_preview")
    col.prop(scene, "vmc_link_lock_to_center")

    layout.separator()
    layout.label(text="目标对象", icon="OUTLINER_OB_ARMATURE")

    col = layout.column(align=True)
    col.prop(scene, "vmc_link_armature")
    col.prop(scene, "vmc_link_face_object")

    row = layout.row(align=True)
    row.operator("vmc_link.rebuild_maps", text="重建目标映射", icon="FILE_REFRESH")
