from .constants import ARKIT_BLENDSHAPE_KEYS


receiver_socket = None
dispatcher = None
arkit_receiver_socket = None
arkit_dispatcher = None
apply_timer_running = False

root_buf = None
waist_buf = None
bone_buf = {}
blend_buf = {}
arkit_blend_buf = {key: 0.0 for key in ARKIT_BLENDSHAPE_KEYS}

cached_bone_map = {}
cached_blend_map = {}
cached_arkit_blend_map = {}
preview_cached_bone_map = {}
preview_cached_arkit_blend_map = {}
preview_armature_ref = None
preview_face_ref = None

dirty = False
last_packet_ts = 0.0
arkit_last_packet_ts = 0.0
next_tick_ts = 0.0
next_ui_redraw_ts = 0.0

recording = False


def reset_runtime_buffers():
    global root_buf, waist_buf, bone_buf, blend_buf, arkit_blend_buf
    global dirty, last_packet_ts, arkit_last_packet_ts, next_tick_ts, next_ui_redraw_ts
    global cached_arkit_blend_map, preview_cached_bone_map, preview_cached_arkit_blend_map
    global preview_armature_ref, preview_face_ref

    root_buf = None
    waist_buf = None
    bone_buf = {}
    blend_buf = {}
    arkit_blend_buf = {key: 0.0 for key in ARKIT_BLENDSHAPE_KEYS}
    cached_arkit_blend_map = {}
    preview_cached_bone_map = {}
    preview_cached_arkit_blend_map = {}
    preview_armature_ref = None
    preview_face_ref = None
    dirty = False
    last_packet_ts = 0.0
    arkit_last_packet_ts = 0.0
    next_tick_ts = 0.0
    next_ui_redraw_ts = 0.0
