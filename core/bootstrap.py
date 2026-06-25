import importlib

import bpy


_needs_reload = "operators" in locals()

from . import constants, helpers, state
from ..mapping import arp as mapping_arp
from ..mapping import mapper as mapping
from ..mapping import mmd as mapping_mmd
from ..mapping import preset_store as presets
from ..mapping import target_rig as mapping_target_rig
from ..preview import dummy_vrm
from ..runtime import driver as runtime
from ..runtime import network, properties
from ..runtime import target_runtime
from ..ui import (
    intermediate_panel as ui_intermediate,
    main_panel as ui_main,
    mapping_panel as ui_mapping,
    operators,
    preview_panel as ui_preview,
    recording_panel as ui_recording,
)


if _needs_reload:
    for module in (
        constants,
        helpers,
        state,
        dummy_vrm,
        mapping,
        mapping_arp,
        mapping_mmd,
        mapping_target_rig,
        network,
        operators,
        presets,
        properties,
        runtime,
        target_runtime,
        ui_intermediate,
        ui_main,
        ui_mapping,
        ui_preview,
        ui_recording,
    ):
        importlib.reload(module)


CLASSES = (
    ui_intermediate.VMC_LINK_PT_intermediate_panel,
    *ui_recording.CLASSES,
    ui_mapping.VMC_LINK_PT_bone_mapping_panel,
    ui_mapping.VMC_LINK_PT_vmc_blend_mapping_panel,
    ui_mapping.VMC_LINK_PT_arkit_blend_mapping_panel,
    *ui_preview.CLASSES,
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
