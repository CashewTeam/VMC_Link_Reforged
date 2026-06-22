# VMC Link - configurable OSC/VMC receiver for Blender
#
# This project was originally inspired by HEVA Portal by ScaledTeam.
# https://github.com/scaledteam/HEVA_Portal

# Legacy
bl_info = {
    "name": "VMC Link",
    "author": "Internet Addict",
    "version": (0, 5, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > VMC Link",
    "description": "Receives VMC and RhyLive ARKit OSC, previews raw data, and manages mapping presets",
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
        name="Default Address",
        description="Default local address/interface used by VMC Link",
        default="127.0.0.1",
    )

    default_port: bpy.props.IntProperty(
        name="Default Port",
        description="Default UDP port used by VMC Link",
        default=39539,
        min=1,
        max=65535,
    )

    default_rate_hz: bpy.props.IntProperty(
        name="Default Apply Rate (Hz)",
        description="Default apply/update rate used by VMC Link",
        default=60,
        min=1,
        max=240,
    )

    def draw(self, _context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="Connection Defaults")
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
    bl_label = "VMC Link"
    bl_idname = "VMC_LINK_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "VMC Link"

    def draw(self, context):
        layout = self.layout

        if not _has_pythonosc():
            box = layout.box()
            box.label(text="Missing dependency: python-osc", icon="ERROR") # This should never happen, assuming bundled .whl
            return

        if _main is None:
            box = layout.box()
            box.label(text="Receiver module failed to load.", icon="ERROR")
            if _last_import_error:
                box.label(text=_last_import_error[:120], icon="INFO")
            box.label(text="Try disabling/enabling the extension.", icon="INFO")
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
            from . import main as _imported_main
            _main = _imported_main
    except Exception as e:
        _main = None
        _last_import_error = f"Import failed: {e}"
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
