import bpy
from bpy.app.handlers import persistent

from . import constants, dummy_vrm, mapping, mapping_arp, presets, state


def get_addon_preferences():
    addon_key = (__package__ or "vmc_link").split(".")[0]
    prefs_entry = bpy.context.preferences.addons.get(addon_key)
    if not prefs_entry:
        return None
    return getattr(prefs_entry, "preferences", None)


def resolve_bind_host(scene) -> str:
    mode = str(getattr(scene, "vmc_link_bind_mode", constants.BIND_MODE_THIS_PC))
    if mode == constants.BIND_MODE_LOCAL_NET:
        return "0.0.0.0"
    if mode == constants.BIND_MODE_CUSTOM:
        return str(getattr(scene, "vmc_link_bind_address_custom", "")).strip()
    return "127.0.0.1"


def get_connection_defaults():
    prefs = get_addon_preferences()
    if prefs is None:
        return {
            "bind_mode": constants.BIND_MODE_THIS_PC,
            "bind_custom": constants.DEFAULT_BIND_ADDRESS,
            "port": constants.DEFAULT_PORT,
            "rate_hz": constants.DEFAULT_RATE_HZ,
        }

    bind_address = str(getattr(prefs, "default_bind_address", constants.DEFAULT_BIND_ADDRESS)).strip() or constants.DEFAULT_BIND_ADDRESS
    port = int(getattr(prefs, "default_port", constants.DEFAULT_PORT))
    rate_hz = int(getattr(prefs, "default_rate_hz", constants.DEFAULT_RATE_HZ))

    if bind_address == "0.0.0.0":
        bind_mode = constants.BIND_MODE_LOCAL_NET
        bind_custom = constants.DEFAULT_BIND_ADDRESS
    elif bind_address == "127.0.0.1":
        bind_mode = constants.BIND_MODE_THIS_PC
        bind_custom = constants.DEFAULT_BIND_ADDRESS
    else:
        bind_mode = constants.BIND_MODE_CUSTOM
        bind_custom = bind_address

    return {
        "bind_mode": bind_mode,
        "bind_custom": bind_custom,
        "port": max(1, min(65535, port)),
        "rate_hz": max(1, min(240, rate_hz)),
    }


def persist_connection_defaults(scene):
    if scene is None:
        return
    prefs = get_addon_preferences()
    if prefs is None:
        return
    prefs.default_bind_address = resolve_bind_host(scene) or constants.DEFAULT_BIND_ADDRESS
    prefs.default_port = int(getattr(scene, "vmc_link_port", constants.DEFAULT_PORT))
    prefs.default_rate_hz = int(getattr(scene, "vmc_link_rate_hz", constants.DEFAULT_RATE_HZ))


def _on_receiver_endpoint_changed(self, _context):
    persist_connection_defaults(self)
    from . import network

    if network.is_running():
        network.restart_server(self)


def _on_connection_setting_changed(self, _context):
    persist_connection_defaults(self)
    state.next_tick_ts = 0.0


def _on_live_preview_changed(self, _context):
    if bool(getattr(self, "vmc_link_live_preview", True)):
        state.dirty = True


def _on_face_source_changed(self, _context):
    state.next_tick_ts = 0.0
    mapping.invalidate_blend_map_cache()
    from . import network

    if network.is_running():
        network.restart_server(self)


def _on_armature_changed(self, _context):
    mapping.handle_armature_changed(self)
    mapping_arp.clear_scene_report(self)


def _on_face_object_changed(self, _context):
    mapping.handle_face_object_changed(self)


FIXED_SCENE_PROPS = (
    "vmc_link_port",
    "vmc_link_bind_mode",
    "vmc_link_bind_address_custom",
    "vmc_link_rate_hz",
    "vmc_link_live_preview",
    "vmc_link_face_source",
    "vmc_link_arkit_port",
    "vmc_link_armature",
    "vmc_link_face_object",
    "vmc_link_preview_armature",
    "vmc_link_preview_face_object",
    "vmc_link_bone_map_preset",
    "vmc_link_bone_map_save_name",
    "vmc_link_vmc_blend_preset",
    "vmc_link_vmc_blend_save_name",
    "vmc_link_arkit_blend_preset",
    "vmc_link_arkit_blend_save_name",
    "vmc_link_arp_is_detected",
    "vmc_link_arp_report_title",
    "vmc_link_arp_report",
)


def ensure_scene_props():
    scene_type = bpy.types.Scene
    defaults = get_connection_defaults()

    scene_type.vmc_link_port = bpy.props.IntProperty(
        name="端口",
        description="接收 VMC/OSC 的 UDP 端口",
        default=defaults["port"],
        min=1,
        max=65535,
        update=_on_receiver_endpoint_changed,
    )
    scene_type.vmc_link_bind_mode = bpy.props.EnumProperty(
        name="接收地址",
        description="选择 UDP 接收器监听的网络接口",
        items=(
            (constants.BIND_MODE_THIS_PC, "仅本机", "绑定到 127.0.0.1 (localhost)"),
            (constants.BIND_MODE_LOCAL_NET, "任意网卡", "绑定到 0.0.0.0 (所有接口)"),
            (constants.BIND_MODE_CUSTOM, "自定义地址", "绑定到指定的本地 IP/地址"),
        ),
        default=defaults["bind_mode"],
        update=_on_receiver_endpoint_changed,
    )
    scene_type.vmc_link_bind_address_custom = bpy.props.StringProperty(
        name="自定义地址",
        description="UDP 接收器要绑定的自定义本地地址/接口",
        default=defaults["bind_custom"],
        update=_on_receiver_endpoint_changed,
    )
    scene_type.vmc_link_rate_hz = bpy.props.IntProperty(
        name="应用频率 (Hz)",
        description="将接收数据写入对象的频率",
        default=defaults["rate_hz"],
        min=1,
        max=240,
        update=_on_connection_setting_changed,
    )
    scene_type.vmc_link_live_preview = bpy.props.BoolProperty(
        name="实时驱动目标对象",
        description="是否将接收数据实时写入映射后的目标骨架和目标面部",
        default=True,
        update=_on_live_preview_changed,
    )
    scene_type.vmc_link_face_source = bpy.props.EnumProperty(
        name="面部来源",
        description="选择哪一路输入流提供面部表情数据",
        items=(
            (constants.FACE_SOURCE_VMC, "VMC", "使用 /VMC/Ext/Blend/Val 作为面部数据"),
            (constants.FACE_SOURCE_RHYLIVE_ARKIT, "RhyLive ARKit", "使用 RhyLive OSC /Face ARKit 系数"),
        ),
        default=constants.FACE_SOURCE_VMC,
        update=_on_face_source_changed,
    )
    scene_type.vmc_link_arkit_port = bpy.props.IntProperty(
        name="ARKit 端口",
        description="接收 RhyLive ARKit OSC /Face 数据的 UDP 端口",
        default=constants.DEFAULT_ARKIT_PORT,
        min=1,
        max=65535,
        update=_on_receiver_endpoint_changed,
    )
    scene_type.vmc_link_armature = bpy.props.PointerProperty(
        name="目标骨架",
        description="映射后要驱动的目标骨架",
        type=bpy.types.Object,
        poll=lambda _self, obj: obj is None or obj.type == "ARMATURE",
        update=_on_armature_changed,
    )
    scene_type.vmc_link_face_object = bpy.props.PointerProperty(
        name="目标面部",
        description="映射后要驱动的目标面部 Mesh（包含 Shape Key）",
        type=bpy.types.Object,
        poll=lambda _self, obj: obj is None or obj.type == "MESH",
        update=_on_face_object_changed,
    )
    scene_type.vmc_link_preview_armature = bpy.props.PointerProperty(
        name="VRM 预览骨架",
        description="中间层预览用的 VRM 骨架",
        type=bpy.types.Object,
        poll=lambda _self, obj: obj is None or obj.type == "ARMATURE",
    )
    scene_type.vmc_link_preview_face_object = bpy.props.PointerProperty(
        name="ARKit 预览面部",
        description="中间层预览用的 ARKit 调试面部 Mesh",
        type=bpy.types.Object,
        poll=lambda _self, obj: obj is None or obj.type == "MESH",
    )
    scene_type.vmc_link_bone_map_preset = bpy.props.EnumProperty(
        name="预设",
        description="已保存的骨骼映射预设",
        items=presets.enum_bone_map_preset_items,
    )
    scene_type.vmc_link_bone_map_save_name = bpy.props.StringProperty(
        name="保存名称",
        description="当前骨骼映射预设的文件名",
        default="",
    )
    scene_type.vmc_link_vmc_blend_preset = bpy.props.EnumProperty(
        name="预设",
        description="已保存的 VMC 表情映射预设",
        items=presets.enum_vmc_blend_preset_items,
    )
    scene_type.vmc_link_vmc_blend_save_name = bpy.props.StringProperty(
        name="保存名称",
        description="当前 VMC 表情映射预设的文件名",
        default="",
    )
    scene_type.vmc_link_arkit_blend_preset = bpy.props.EnumProperty(
        name="预设",
        description="已保存的 ARKit 表情映射预设",
        items=presets.enum_arkit_blend_preset_items,
    )
    scene_type.vmc_link_arkit_blend_save_name = bpy.props.StringProperty(
        name="保存名称",
        description="当前 ARKit 表情映射预设的文件名",
        default="",
    )
    scene_type.vmc_link_arp_is_detected = bpy.props.BoolProperty(
        name="ARP 识别结果",
        description="最近一次 Auto Rig Pro 检查是否通过",
        default=False,
        options={"HIDDEN"},
    )
    scene_type.vmc_link_arp_report_title = bpy.props.StringProperty(
        name="ARP 报告标题",
        description="最近一次 Auto Rig Pro 检查报告标题",
        default="",
        options={"HIDDEN"},
    )
    scene_type.vmc_link_arp_report = bpy.props.StringProperty(
        name="ARP 报告内容",
        description="最近一次 Auto Rig Pro 检查报告内容",
        default="",
        options={"HIDDEN"},
    )

    mapping.ensure_dynamic_scene_props(scene_type)


def unregister_scene_props():
    scene_type = bpy.types.Scene
    for prop_name in FIXED_SCENE_PROPS:
        if hasattr(scene_type, prop_name):
            delattr(scene_type, prop_name)
    mapping.unregister_dynamic_scene_props(scene_type)


def ensure_intermediate_defaults_for_scene(scene):
    preview_arm = getattr(scene, "vmc_link_preview_armature", None)
    target_arm = getattr(scene, "vmc_link_armature", None)
    if preview_arm is None and dummy_vrm.is_vrm_intermediate_rig(target_arm):
        scene.vmc_link_preview_armature = target_arm
        scene.vmc_link_armature = None
    elif preview_arm is None:
        for obj in scene.objects:
            if dummy_vrm.is_vrm_intermediate_rig(obj):
                scene.vmc_link_preview_armature = obj
                break

    preview_face = getattr(scene, "vmc_link_preview_face_object", None)
    target_face = getattr(scene, "vmc_link_face_object", None)
    if preview_face is None and dummy_vrm.is_arkit_preview_face(target_face):
        scene.vmc_link_preview_face_object = target_face
        scene.vmc_link_face_object = None
    elif preview_face is None:
        for obj in scene.objects:
            if dummy_vrm.is_arkit_preview_face(obj):
                scene.vmc_link_preview_face_object = obj
                break


@persistent
def _migrate_intermediate_scene_slots(_dummy):
    for scene in bpy.data.scenes:
        ensure_intermediate_defaults_for_scene(scene)


def register_scene_handlers():
    handlers = bpy.app.handlers.load_post
    if _migrate_intermediate_scene_slots not in handlers:
        handlers.append(_migrate_intermediate_scene_slots)


def unregister_scene_handlers():
    handlers = bpy.app.handlers.load_post
    if _migrate_intermediate_scene_slots in handlers:
        handlers.remove(_migrate_intermediate_scene_slots)
