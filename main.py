import importlib

import bpy


_needs_reload = "operators" in locals()

from . import (
    dummy_vrm,
    mapping,
    network,
    operators,
    presets,
    properties,
    runtime,
    ui_intermediate,
    ui_main,
    ui_mapping,
    ui_preview,
)


if _needs_reload:
    for module in (
        dummy_vrm,
        mapping,
        network,
        operators,
        presets,
        properties,
        runtime,
        ui_intermediate,
        ui_main,
        ui_mapping,
        ui_preview,
    ):
        importlib.reload(module)


CLASSES = (
    ui_preview.VMC_LINK_PT_preview_panel,
    ui_preview.VMC_LINK_PT_arkit_preview_panel,
    ui_intermediate.VMC_LINK_PT_intermediate_panel,
    ui_mapping.VMC_LINK_PT_bone_mapping_panel,
    ui_mapping.VMC_LINK_PT_vmc_blend_mapping_panel,
    ui_mapping.VMC_LINK_PT_arkit_blend_mapping_panel,
    *operators.CLASSES,
)


def draw_ui(layout, context):
    ui_main.draw_main_panel(layout, context)


def register():
    properties.ensure_scene_props()
    properties.register_scene_handlers()
    presets.refresh_all_mapping_preset_caches()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        properties.ensure_intermediate_defaults_for_scene(scene)


def unregister():
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        network.stop_server(scene)
    properties.unregister_scene_handlers()
    properties.unregister_scene_props()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
