import threading
from collections import deque

from .constants import ARKIT_BLENDSHAPE_KEYS, VMC_ROTATION_FILTER_MIN_ALPHA


receiver_socket = None
dispatcher = None
arkit_receiver_socket = None
arkit_dispatcher = None
arkit_forward_enabled = False
arkit_forward_port = 0
arkit_forward_socket = None
arkit_forward_thread = None
arkit_forward_stop_event = None
apply_timer_running = False
receiver_thread = None
receiver_stop_event = None
buffer_lock = threading.Lock()
vmc_rotation_filter_alpha = VMC_ROTATION_FILTER_MIN_ALPHA

root_buf = None
waist_buf = None
root_raw_buf = None
waist_raw_buf = None
filtered_root_buf = None
filtered_waist_buf = None
bone_buf = {}
filtered_bone_buf = {}
canonical_bone_buf = {}
blend_buf = {}
canonical_vmc_blend_buf = {}
arkit_blend_buf = {key: 0.0 for key in ARKIT_BLENDSHAPE_KEYS}

cached_bone_map = {}
cached_blend_map = {}
cached_arkit_blend_map = {}
cached_blend_key_blocks = {}
cached_arkit_blend_key_blocks = {}
target_face_ref = None
preview_cached_bone_map = {}
preview_cached_arkit_blend_map = {}
preview_cached_arkit_key_blocks = {}
preview_armature_ref = None
preview_face_ref = None

dirty = False
last_packet_ts = 0.0
arkit_last_packet_ts = 0.0
next_tick_ts = 0.0
next_ui_redraw_ts = 0.0
view3d_redraw_signature = ()
view3d_redraw_areas = []
frame_snapshot_deadline_ts = 0.0
raw_frame_queue = deque()
raw_frame_sequence = 0
raw_frame_pending = False
raw_frame_first_packet_ts = 0.0
raw_frame_last_update_ts = 0.0
raw_frame_dirty_bone_names = set()
raw_frame_dirty_vmc_blend_names = set()
raw_frame_dirty_arkit_blend_names = set()
raw_frame_body_dirty = False
raw_frame_vmc_blend_dirty = False
raw_frame_vmc_eye_blend_dirty = False
raw_frame_arkit_blend_dirty = False

recording = False
recording_frame = None
recording_sample_count = 0
recording_start_frame = None
recording_start_ts = 0.0
recording_source_start_ts = 0.0
recording_pause_started_ts = 0.0
recording_paused_duration = 0.0
recording_source_pause_started_ts = 0.0
recording_source_paused_duration = 0.0
recording_source_pause_segments = []
recording_last_written_frame = None
recording_end_frame = None
recording_armature_ref = None
recording_face_ref = None
recording_armature_action = None
recording_face_action = None
recording_object_rotation_mode = ""
recording_bone_rotation_modes = {}
recording_pose_bones = {}
recording_shape_key_blocks = {}
recording_tracks = {}
recording_raw_frames = []
recording_last_sample = None
recording_interpolation_enabled = True
recording_motion_enabled = True
recording_shape_keys_enabled = True
recording_transition_enabled = False
recording_transition_frames = 0
recording_transition_pending = False
recording_transition_source_sample = None
recording_transition_target_sample = None
recording_mmd_root_motion_start_location = None
recording_bake_session = None

receiver_session_active = False
receiver_paused = False
receiver_armature_snapshots = []
receiver_face_snapshots = []
receiver_preview_context = {}
receiver_target_context = {}
receiver_target_apply_armature_ref = None
receiver_target_apply_face_ref = None
receiver_target_apply_arm_location = None
receiver_target_apply_arm_rotation = None
receiver_target_apply_bone_locations = {}
receiver_target_apply_bone_rotations = {}
receiver_target_apply_ik_fk_switches = {}
receiver_target_apply_shape_values = {}
receiver_preview_apply_armature_ref = None
receiver_preview_apply_face_ref = None
receiver_preview_apply_arm_location = None
receiver_preview_apply_arm_rotation = None
receiver_preview_apply_bone_rotations = {}
receiver_preview_apply_shape_values = {}


def reset_runtime_buffers():
    global root_buf, waist_buf, root_raw_buf, waist_raw_buf, filtered_root_buf, filtered_waist_buf, bone_buf, filtered_bone_buf, canonical_bone_buf, blend_buf, canonical_vmc_blend_buf, arkit_blend_buf
    global dirty, last_packet_ts, arkit_last_packet_ts, next_tick_ts, next_ui_redraw_ts, view3d_redraw_signature, view3d_redraw_areas, frame_snapshot_deadline_ts
    global raw_frame_queue, raw_frame_sequence, raw_frame_pending, raw_frame_first_packet_ts, raw_frame_last_update_ts
    global raw_frame_dirty_bone_names, raw_frame_dirty_vmc_blend_names, raw_frame_dirty_arkit_blend_names
    global raw_frame_body_dirty, raw_frame_vmc_blend_dirty, raw_frame_vmc_eye_blend_dirty, raw_frame_arkit_blend_dirty
    global cached_arkit_blend_map, cached_blend_key_blocks, cached_arkit_blend_key_blocks, target_face_ref
    global preview_cached_bone_map, preview_cached_arkit_blend_map, preview_cached_arkit_key_blocks
    global preview_armature_ref, preview_face_ref

    with buffer_lock:
        root_buf = None
        waist_buf = None
        root_raw_buf = None
        waist_raw_buf = None
        filtered_root_buf = None
        filtered_waist_buf = None
        bone_buf = {}
        filtered_bone_buf = {}
        canonical_bone_buf = {}
        blend_buf = {}
        canonical_vmc_blend_buf = {}
        arkit_blend_buf = {key: 0.0 for key in ARKIT_BLENDSHAPE_KEYS}
        raw_frame_queue = deque()
        raw_frame_sequence = 0
        raw_frame_pending = False
        raw_frame_first_packet_ts = 0.0
        raw_frame_last_update_ts = 0.0
        raw_frame_dirty_bone_names = set()
        raw_frame_dirty_vmc_blend_names = set()
        raw_frame_dirty_arkit_blend_names = set()
        raw_frame_body_dirty = False
        raw_frame_vmc_blend_dirty = False
        raw_frame_vmc_eye_blend_dirty = False
        raw_frame_arkit_blend_dirty = False
    cached_arkit_blend_map = {}
    cached_blend_key_blocks = {}
    cached_arkit_blend_key_blocks = {}
    target_face_ref = None
    preview_cached_bone_map = {}
    preview_cached_arkit_blend_map = {}
    preview_cached_arkit_key_blocks = {}
    preview_armature_ref = None
    preview_face_ref = None
    dirty = False
    last_packet_ts = 0.0
    arkit_last_packet_ts = 0.0
    next_tick_ts = 0.0
    next_ui_redraw_ts = 0.0
    view3d_redraw_signature = ()
    view3d_redraw_areas = []
    frame_snapshot_deadline_ts = 0.0


def reset_receiver_session_state():
    global receiver_session_active, receiver_paused
    global receiver_armature_snapshots, receiver_face_snapshots, receiver_preview_context, receiver_target_context
    global receiver_target_apply_armature_ref, receiver_target_apply_face_ref
    global receiver_target_apply_arm_location, receiver_target_apply_arm_rotation
    global receiver_target_apply_bone_locations, receiver_target_apply_bone_rotations
    global receiver_target_apply_ik_fk_switches, receiver_target_apply_shape_values
    global receiver_preview_apply_armature_ref, receiver_preview_apply_face_ref
    global receiver_preview_apply_arm_location, receiver_preview_apply_arm_rotation
    global receiver_preview_apply_bone_rotations, receiver_preview_apply_shape_values
    global view3d_redraw_signature, view3d_redraw_areas
    receiver_session_active = False
    receiver_paused = False
    receiver_armature_snapshots = []
    receiver_face_snapshots = []
    receiver_preview_context = {}
    receiver_target_context = {}
    receiver_target_apply_armature_ref = None
    receiver_target_apply_face_ref = None
    receiver_target_apply_arm_location = None
    receiver_target_apply_arm_rotation = None
    receiver_target_apply_bone_locations = {}
    receiver_target_apply_bone_rotations = {}
    receiver_target_apply_ik_fk_switches = {}
    receiver_target_apply_shape_values = {}
    receiver_preview_apply_armature_ref = None
    receiver_preview_apply_face_ref = None
    receiver_preview_apply_arm_location = None
    receiver_preview_apply_arm_rotation = None
    receiver_preview_apply_bone_rotations = {}
    receiver_preview_apply_shape_values = {}
    view3d_redraw_signature = ()
    view3d_redraw_areas = []
