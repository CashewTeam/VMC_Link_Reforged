# VMC Link - configurable OSC/VMC receiver for Blender
#
# This project was originally inspired by HEVA Portal by ScaledTeam.
# https://github.com/scaledteam/HEVA_Portal

# Legacy
bl_info = {
    "name": "VMC Link",
    "author": "Internet Addict",
    "version": (0, 14, 3),
    "blender": (4, 2, 0),
    "location": "3D 视图 > 侧边栏 > VMC Link",
    "description": "接收 VMC 与 RhyLive ARKit OSC，预览原始数据，并管理映射预设",
    "category": "System",
}

import importlib
import importlib.util
import traceback
import bpy


# -------------------------
# Dependency helpers
# -------------------------

def _has_pythonosc() -> bool:
    return importlib.util.find_spec("pythonosc") is not None


# -------------------------
# Add-on preferences
# -------------------------


class VMC_LINK_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__ if __package__ else "vmc_link"

    default_bind_address: bpy.props.StringProperty(
        name="默认地址",
        description="VMC Link 默认使用的本地监听地址",
        default="127.0.0.1",
    )

    default_port: bpy.props.IntProperty(
        name="默认端口",
        description="VMC Link 默认使用的 UDP 端口",
        default=39539,
        min=1,
        max=65535,
    )

    default_rate_hz: bpy.props.IntProperty(
        name="默认应用频率 (Hz)",
        description="VMC Link 默认的驱动更新频率",
        default=60,
        min=1,
        max=240,
    )

    def draw(self, _context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="连接默认值")
        col.prop(self, "default_bind_address")
        col.prop(self, "default_port")
        col.prop(self, "default_rate_hz")


# -------------------------
# UI Panel
# -------------------------

_needs_reload = "bpy" in locals()
_main = locals().get("_main")
_last_import_error = ""


class VMC_LINK_PT_panel(bpy.types.Panel):
    """Sidebar UI for the addon"""
    bl_label = "接收器配置"
    bl_idname = "VMC_LINK_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "VMC Link"

    def draw(self, context):
        layout = self.layout

        if not _has_pythonosc():
            box = layout.box()
            box.label(text="缺少依赖：python-osc", icon="ERROR")
            return

        if _main is None:
            box = layout.box()
            box.label(text="接收器模块加载失败。", icon="ERROR")
            if _last_import_error:
                box.label(text=_last_import_error[:120], icon="INFO")
            box.label(text="请尝试禁用后重新启用扩展。", icon="INFO")
            return

        _main.draw_ui(layout, context)


# -------------------------
# Import / Reload main safely
# -------------------------

def _load_main_module():
    global _main, _last_import_error
    _last_import_error = ""

    if not _has_pythonosc():
        _main = None
        return

    try:
        if _needs_reload and _main is not None:
            _main = importlib.reload(_main)
        else:
            from .core import bootstrap as _imported_main
            _main = _imported_main
    except Exception as e:
        _main = None
        _last_import_error = f"导入失败：{e}"
        print("[VMC Link] Failed to import/reload main module")
        print(traceback.format_exc())


_load_main_module()


# -------------------------
# Register / Unregister
# -------------------------

classes = (
    VMC_LINK_Preferences,
    VMC_LINK_PT_panel,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)

    if _main is None:
        _load_main_module()
    if _main is not None:
        _main.register()


def unregister():
    if _main is not None:
        _main.unregister()

    for c in reversed(classes):
        bpy.utils.unregister_class(c)
