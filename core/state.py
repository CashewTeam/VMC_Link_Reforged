import threading

from .constants import ARKIT_BLENDSHAPE_KEYS


receiver_socket = None
dispatcher = None
arkit_receiver_socket = None
arkit_dispatcher = None
apply_timer_running = False
receiver_thread = None
receiver_stop_event = None
buffer_lock = threading.Lock()

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
frame_snapshot_deadline_ts = 0.0

recording = False
recording_frame = None
recording_sample_count = 0
recording_start_frame = None
recording_start_ts = 0.0
recording_pause_started_ts = 0.0
recording_paused_duration = 0.0
recording_last_written_frame = None
recording_end_frame = None
recording_armature_ref = None
recording_face_ref = None
recording_armature_action = None
recording_face_action = None
recording_tracks = {}
recording_last_sample = None
recording_interpolation_enabled = True
recording_transition_enabled = False
recording_transition_frames = 0
recording_transition_pending = False
recording_transition_source_sample = None
recording_transition_target_sample = None

receiver_session_active = False
receiver_paused = False
receiver_armature_snapshots = []
receiver_face_snapshots = []
receiver_preview_context = {}
receiver_target_context = {}


def reset_runtime_buffers():
    global root_buf, waist_buf, bone_buf, blend_buf, arkit_blend_buf
    global dirty, last_packet_ts, arkit_last_packet_ts, next_tick_ts, next_ui_redraw_ts, frame_snapshot_deadline_ts
    global cached_arkit_blend_map, preview_cached_bone_map, preview_cached_arkit_blend_map
    global preview_armature_ref, preview_face_ref

    with buffer_lock:
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
    frame_snapshot_deadline_ts = 0.0


def reset_receiver_session_state():
    global receiver_session_active, receiver_paused
    global receiver_armature_snapshots, receiver_face_snapshots, receiver_preview_context, receiver_target_context
    receiver_session_active = False
    receiver_paused = False
    receiver_armature_snapshots = []
    receiver_face_snapshots = []
    receiver_preview_context = {}
    receiver_target_context = {}
