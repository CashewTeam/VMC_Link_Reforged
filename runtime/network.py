import select
import socket
import threading
import time
import math

import bpy
from pythonosc.dispatcher import Dispatcher

from ..core import constants, helpers, state
from ..mapping import mapper as mapping
from . import driver as runtime
from . import properties


def is_running() -> bool:
    return state.receiver_socket is not None or state.arkit_receiver_socket is not None


def is_session_active() -> bool:
    return bool(state.receiver_session_active)


def is_paused() -> bool:
    return bool(state.receiver_session_active and state.receiver_paused)


def _is_arkit_face_source_enabled(scene) -> bool:
    return str(getattr(scene, "vmc_link_face_source", constants.FACE_SOURCE_VMC)) == constants.FACE_SOURCE_RHYLIVE_ARKIT


def _build_receiver_handles(scene):
    bind_host = properties.resolve_bind_host(scene).strip()
    if not bind_host:
        raise RuntimeError("接收地址不能为空")

    port = int(scene.vmc_link_port)
    vmc_socket = None
    arkit_socket = None
    try:
        vmc_socket = create_udp_socket(bind_host, port)
        vmc_dispatcher = build_vmc_dispatcher()
        arkit_dispatcher = None
        if _is_arkit_face_source_enabled(scene):
            arkit_socket = create_udp_socket(bind_host, int(scene.vmc_link_arkit_port))
            arkit_dispatcher = build_arkit_dispatcher()
    except Exception:
        if vmc_socket is not None:
            vmc_socket.close()
        if arkit_socket is not None:
            arkit_socket.close()
        raise

    return bind_host, vmc_socket, vmc_dispatcher, arkit_socket, arkit_dispatcher


def _assign_receiver_handles(vmc_socket, vmc_dispatcher, arkit_socket, arkit_dispatcher):
    state.receiver_socket = vmc_socket
    state.dispatcher = vmc_dispatcher
    state.arkit_receiver_socket = arkit_socket
    state.arkit_dispatcher = arkit_dispatcher
    _start_receiver_thread()

    if not bpy.app.timers.is_registered(runtime.apply_timer):
        bpy.app.timers.register(runtime.apply_timer, persistent=True)
    state.apply_timer_running = True


def _clear_pending_raw_frames():
    with state.buffer_lock:
        state.raw_frame_queue.clear()
        state.raw_frame_pending = False
        state.raw_frame_first_packet_ts = 0.0
        state.raw_frame_last_update_ts = 0.0
        state.raw_frame_dirty_bone_names = set()
        state.raw_frame_dirty_vmc_blend_names = set()
        state.raw_frame_dirty_arkit_blend_names = set()
        state.raw_frame_body_dirty = False
        state.raw_frame_vmc_blend_dirty = False
        state.raw_frame_vmc_eye_blend_dirty = False
        state.raw_frame_arkit_blend_dirty = False


def _is_apply_timer_registered() -> bool:
    try:
        return bpy.app.timers.is_registered(runtime.apply_timer)
    except Exception:
        return False


def _close_receiver_handles():
    _stop_receiver_thread()
    if state.receiver_socket is not None:
        state.receiver_socket.close()
    if state.arkit_receiver_socket is not None:
        state.arkit_receiver_socket.close()

    state.receiver_socket = None
    state.dispatcher = None
    state.arkit_receiver_socket = None
    state.arkit_dispatcher = None

    if _is_apply_timer_registered():
        bpy.app.timers.unregister(runtime.apply_timer)
    state.apply_timer_running = False


def normalize_runtime_state():
    running = is_running()
    paused = bool(state.receiver_session_active and state.receiver_paused)
    timer_registered = _is_apply_timer_registered()
    thread_alive = bool(state.receiver_thread is not None and state.receiver_thread.is_alive())

    if paused:
        if running:
            _close_receiver_handles()
        elif timer_registered:
            bpy.app.timers.unregister(runtime.apply_timer)
            state.apply_timer_running = False
        return

    if state.receiver_session_active and not running:
        if timer_registered:
            bpy.app.timers.unregister(runtime.apply_timer)
        state.apply_timer_running = False
        state.reset_runtime_buffers()
        runtime.clear_receiver_session_state()
        return

    if not running:
        if timer_registered:
            bpy.app.timers.unregister(runtime.apply_timer)
        state.apply_timer_running = False
        return

    if not thread_alive:
        _start_receiver_thread()
    if not timer_registered:
        bpy.app.timers.register(runtime.apply_timer, persistent=True)
    state.apply_timer_running = True


def _receiver_thread_loop(stop_event):
    while not stop_event.is_set():
        socket_pairs = [
            (state.receiver_socket, state.dispatcher, "OSC"),
            (state.arkit_receiver_socket, state.arkit_dispatcher, "ARKit OSC"),
        ]
        active_sockets = [sock for sock, dispatcher, _name in socket_pairs if sock is not None and dispatcher is not None]
        if not active_sockets:
            stop_event.wait(0.05)
            continue

        timeout = 0.05
        with state.buffer_lock:
            if state.raw_frame_pending:
                now = time.time()
                quiet_deadline = float(state.raw_frame_last_update_ts) + constants.RECEIVER_FRAME_QUIET_WINDOW_SEC
                max_deadline = float(state.raw_frame_first_packet_ts) + constants.RECEIVER_FRAME_MAX_DEFER_SEC
                next_deadline = min(quiet_deadline, max_deadline)
                timeout = max(0.0, min(timeout, next_deadline - now))

        try:
            readable, _writable, _errors = select.select(active_sockets, [], [], timeout)
        except (OSError, ValueError):
            if not stop_event.is_set():
                time.sleep(0.01)
            continue

        for sock, dispatcher, stream_name in socket_pairs:
            if sock in readable:
                poll_socket_packets(sock, dispatcher, stream_name)

        with state.buffer_lock:
            if not state.raw_frame_pending:
                continue
            now = time.time()
            quiet_elapsed = now - float(state.raw_frame_last_update_ts)
            pending_elapsed = now - float(state.raw_frame_first_packet_ts)
            if quiet_elapsed >= constants.RECEIVER_FRAME_QUIET_WINDOW_SEC or pending_elapsed >= constants.RECEIVER_FRAME_MAX_DEFER_SEC:
                _flush_raw_frame_locked()


def _start_receiver_thread():
    _stop_receiver_thread()
    stop_event = threading.Event()
    receiver_thread = threading.Thread(
        target=_receiver_thread_loop,
        args=(stop_event,),
        name="VMC Link Receiver",
        daemon=True,
    )
    state.receiver_stop_event = stop_event
    state.receiver_thread = receiver_thread
    receiver_thread.start()


def _stop_receiver_thread():
    stop_event = state.receiver_stop_event
    receiver_thread = state.receiver_thread
    if stop_event is not None:
        stop_event.set()
    if receiver_thread is not None and receiver_thread.is_alive() and receiver_thread is not threading.current_thread():
        receiver_thread.join(timeout=0.2)
    state.receiver_stop_event = None
    state.receiver_thread = None


def build_vmc_dispatcher():
    dispatcher = Dispatcher()
    dispatcher.map("/VMC/Ext/Root/Pos", on_vmc_root_pos)
    dispatcher.map("/VMC/Ext/Tra/Pos", on_vmc_tra_pos)
    dispatcher.map("/VMC/Ext/Bone/Pos", on_vmc_bone_pos)
    dispatcher.map("/VMC/Ext/Blend/Val", on_vmc_blend_val)
    return dispatcher


def build_arkit_dispatcher():
    dispatcher = Dispatcher()
    dispatcher.map("/Face", on_arkit_face)
    return dispatcher


def create_udp_socket(bind_host: str, port: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((bind_host, port))
    return sock


def restart_server(scene):
    if not is_running():
        return

    bind_host, new_socket, new_dispatcher, new_arkit_socket, new_arkit_dispatcher = _build_receiver_handles(scene)

    _stop_receiver_thread()
    old_socket = state.receiver_socket
    old_arkit_socket = state.arkit_receiver_socket
    state.receiver_socket = new_socket
    state.dispatcher = new_dispatcher
    state.arkit_receiver_socket = new_arkit_socket
    state.arkit_dispatcher = new_arkit_dispatcher
    _start_receiver_thread()

    state.reset_runtime_buffers()
    state.cached_bone_map = {}
    state.cached_blend_map = {}

    if old_socket is not None:
        old_socket.close()
    if old_arkit_socket is not None:
        old_arkit_socket.close()

    helpers.debug(f"Receiver rebound to UDP {bind_host}:{int(scene.vmc_link_port)}")
    if new_arkit_socket is not None:
        helpers.debug(f"ARKit face receiver rebound to UDP {bind_host}:{scene.vmc_link_arkit_port}")


def poll_socket_packets(sock, dispatcher, stream_name: str):
    if sock is None or dispatcher is None:
        return

    while True:
        try:
            data, client_addr = sock.recvfrom(65535)
        except BlockingIOError:
            break
        except OSError as exc:
            helpers.warn(f"{stream_name} socket receive failed", exc)
            break

        try:
            dispatcher.call_handlers_for_packet(data, client_addr)
        except Exception as exc:
            helpers.warn(f"Failed to process {stream_name} packet", exc)


def poll_osc_packets():
    poll_socket_packets(state.receiver_socket, state.dispatcher, "OSC")
    poll_socket_packets(state.arkit_receiver_socket, state.arkit_dispatcher, "ARKit OSC")


def _mark_raw_frame_activity_locked(packet_ts: float):
    if state.raw_frame_first_packet_ts <= 0.0:
        state.raw_frame_first_packet_ts = float(packet_ts)
    state.raw_frame_last_update_ts = float(packet_ts)
    state.raw_frame_pending = True


def _raw_pose_changed(previous_pose, current_pose) -> bool:
    if previous_pose is None:
        return True

    dx = float(previous_pose[0]) - float(current_pose[0])
    dy = float(previous_pose[1]) - float(current_pose[1])
    dz = float(previous_pose[2]) - float(current_pose[2])
    if (dx * dx + dy * dy + dz * dz) > (constants.LOC_EPS * constants.LOC_EPS):
        return True

    previous_quat = (
        float(previous_pose[6]),
        float(previous_pose[3]),
        float(previous_pose[4]),
        float(previous_pose[5]),
    )
    current_quat = (
        float(current_pose[6]),
        float(current_pose[3]),
        float(current_pose[4]),
        float(current_pose[5]),
    )
    dot = abs(
        previous_quat[0] * current_quat[0]
        + previous_quat[1] * current_quat[1]
        + previous_quat[2] * current_quat[2]
        + previous_quat[3] * current_quat[3]
    )
    return (1.0 - min(1.0, max(-1.0, dot))) > constants.ROT_EPS


def _normalize_quaternion(values):
    length = math.sqrt(sum(float(value) * float(value) for value in values))
    return tuple(float(value) / length for value in values)


def _slerp_quaternion(previous, current, factor: float):
    dot = sum(float(previous[index]) * float(current[index]) for index in range(4))
    if dot < 0.0:
        current = tuple(-float(value) for value in current)
        dot = -dot
    dot = min(1.0, max(-1.0, dot))
    if dot > 0.9995:
        blended = tuple(
            float(previous[index]) + ((float(current[index]) - float(previous[index])) * factor)
            for index in range(4)
        )
        return _normalize_quaternion(blended)

    theta = math.acos(dot)
    sin_theta = math.sin(theta)
    previous_weight = math.sin((1.0 - factor) * theta) / sin_theta
    current_weight = math.sin(factor * theta) / sin_theta
    return tuple(
        (float(previous[index]) * previous_weight) + (float(current[index]) * current_weight)
        for index in range(4)
    )


def _filter_pose_rotation(previous_pose, current_pose):
    current_rotation = _normalize_quaternion(current_pose[3:7])
    if previous_pose is None:
        return (*current_pose[:3], *current_rotation)

    previous_rotation = _normalize_quaternion(previous_pose[3:7])
    dot = abs(sum(previous_rotation[index] * current_rotation[index] for index in range(4)))
    dot = min(1.0, max(-1.0, dot))
    angle = math.degrees(2.0 * math.acos(dot))
    if angle <= constants.VMC_ROTATION_FILTER_DEADBAND_DEG:
        filtered_rotation = previous_rotation
    elif angle >= constants.VMC_ROTATION_FILTER_FAST_ANGLE_DEG:
        filtered_rotation = current_rotation
    else:
        filtered_rotation = _slerp_quaternion(
            previous_rotation,
            current_rotation,
            constants.VMC_ROTATION_FILTER_MIN_ALPHA,
        )
    return (*current_pose[:3], *filtered_rotation)


def _flush_raw_frame_locked():
    if not state.raw_frame_pending:
        return None

    timestamp = float(state.raw_frame_last_update_ts or time.time())
    state.raw_frame_sequence += 1
    raw_frame = {
        "timestamp": timestamp,
        "sequence_id": int(state.raw_frame_sequence),
        "root": state.root_buf,
        "waist": state.waist_buf,
        "bones": dict(state.canonical_bone_buf),
        "dirty_bone_names": tuple(state.raw_frame_dirty_bone_names),
        "dirty_vmc_blend_names": tuple(state.raw_frame_dirty_vmc_blend_names),
        "dirty_arkit_blend_names": tuple(state.raw_frame_dirty_arkit_blend_names),
        "vmc_blends": dict(state.blend_buf),
        "canonical_vmc_blends": dict(state.canonical_vmc_blend_buf),
        "arkit_blends": dict(state.arkit_blend_buf),
        "body_dirty": bool(state.raw_frame_body_dirty),
        "vmc_blends_dirty": bool(state.raw_frame_vmc_blend_dirty),
        "vmc_eye_blends_dirty": bool(state.raw_frame_vmc_eye_blend_dirty),
        "arkit_blends_dirty": bool(state.raw_frame_arkit_blend_dirty),
        "last_packet_ts": float(state.last_packet_ts),
        "arkit_last_packet_ts": float(state.arkit_last_packet_ts),
    }
    state.raw_frame_queue.append(raw_frame)
    while len(state.raw_frame_queue) > constants.RAW_FRAME_QUEUE_MAX:
        state.raw_frame_queue.popleft()
    if state.recording:
        state.recording_raw_frames.append(
            {
                "timestamp": raw_frame["timestamp"],
                "sequence_id": raw_frame["sequence_id"],
                "root": raw_frame["root"],
                "waist": raw_frame["waist"],
                "bones": dict(raw_frame["bones"]),
                "dirty_bone_names": tuple(raw_frame["dirty_bone_names"]),
                "dirty_vmc_blend_names": tuple(raw_frame["dirty_vmc_blend_names"]),
                "dirty_arkit_blend_names": tuple(raw_frame["dirty_arkit_blend_names"]),
                "vmc_blends": dict(raw_frame["vmc_blends"]),
                "canonical_vmc_blends": dict(raw_frame["canonical_vmc_blends"]),
                "arkit_blends": dict(raw_frame["arkit_blends"]),
                "body_dirty": bool(raw_frame["body_dirty"]),
                "vmc_blends_dirty": bool(raw_frame["vmc_blends_dirty"]),
                "vmc_eye_blends_dirty": bool(raw_frame["vmc_eye_blends_dirty"]),
                "arkit_blends_dirty": bool(raw_frame["arkit_blends_dirty"]),
                "last_packet_ts": raw_frame["last_packet_ts"],
                "arkit_last_packet_ts": raw_frame["arkit_last_packet_ts"],
            }
        )
    state.raw_frame_pending = False
    state.raw_frame_first_packet_ts = 0.0
    state.raw_frame_last_update_ts = 0.0
    state.raw_frame_dirty_bone_names = set()
    state.raw_frame_dirty_vmc_blend_names = set()
    state.raw_frame_dirty_arkit_blend_names = set()
    state.raw_frame_body_dirty = False
    state.raw_frame_vmc_blend_dirty = False
    state.raw_frame_vmc_eye_blend_dirty = False
    state.raw_frame_arkit_blend_dirty = False
    return raw_frame


def on_vmc_bone_pos(_address, *args):
    if not args or len(args) < 8:
        return
    bone_name = str(args[0])
    try:
        px, py, pz = float(args[1]), float(args[2]), float(args[3])
        qx, qy, qz, qw = float(args[4]), float(args[5]), float(args[6]), float(args[7])
    except (TypeError, ValueError):
        return

    with state.buffer_lock:
        pose = (px, py, pz, qx, qy, qz, qw)
        previous_pose = state.bone_buf.get(bone_name)
        if not _raw_pose_changed(previous_pose, pose):
            return
        packet_ts = time.time()
        state.last_packet_ts = packet_ts
        state.bone_buf[bone_name] = pose
        previous_filtered_pose = state.filtered_bone_buf.get(bone_name)
        filtered_pose = _filter_pose_rotation(previous_filtered_pose, pose)
        state.filtered_bone_buf[bone_name] = filtered_pose
        canonical_name = mapping.canonical_vmc_bone_name(bone_name)
        if canonical_name:
            if not _raw_pose_changed(state.canonical_bone_buf.get(canonical_name), filtered_pose):
                return
            state.canonical_bone_buf[canonical_name] = filtered_pose
            state.raw_frame_dirty_bone_names.add(canonical_name)
        state.raw_frame_body_dirty = True
        state.dirty = True
        _mark_raw_frame_activity_locked(packet_ts)


def on_vmc_root_pos(_address, *args):
    if not args or len(args) < 7:
        return

    offset = 1 if len(args) >= 8 else 0
    try:
        px, py, pz = float(args[offset + 0]), float(args[offset + 1]), float(args[offset + 2])
        qx, qy, qz, qw = float(args[offset + 3]), float(args[offset + 4]), float(args[offset + 5]), float(args[offset + 6])
    except (TypeError, ValueError):
        return

    with state.buffer_lock:
        pose = (px, py, pz, qx, qy, qz, qw)
        if not _raw_pose_changed(state.root_raw_buf, pose):
            return
        packet_ts = time.time()
        state.last_packet_ts = packet_ts
        state.root_raw_buf = pose
        filtered_pose = _filter_pose_rotation(state.filtered_root_buf, pose)
        state.filtered_root_buf = filtered_pose
        if not _raw_pose_changed(state.root_buf, filtered_pose):
            return
        state.root_buf = filtered_pose
        state.raw_frame_body_dirty = True
        state.dirty = True
        _mark_raw_frame_activity_locked(packet_ts)


def on_vmc_tra_pos(_address, *args):
    if not args or len(args) < 8:
        return
    if not mapping.is_root_motion_target(str(args[0]).lower()):
        return

    try:
        px, py, pz = float(args[1]), float(args[2]), float(args[3])
        qx, qy, qz, qw = float(args[4]), float(args[5]), float(args[6]), float(args[7])
    except (TypeError, ValueError):
        return

    with state.buffer_lock:
        pose = (px, py, pz, qx, qy, qz, qw)
        if not _raw_pose_changed(state.waist_raw_buf, pose):
            return
        packet_ts = time.time()
        state.last_packet_ts = packet_ts
        state.waist_raw_buf = pose
        filtered_pose = _filter_pose_rotation(state.filtered_waist_buf, pose)
        state.filtered_waist_buf = filtered_pose
        if not _raw_pose_changed(state.waist_buf, filtered_pose):
            return
        state.waist_buf = filtered_pose
        state.raw_frame_body_dirty = True
        state.dirty = True
        _mark_raw_frame_activity_locked(packet_ts)


def on_vmc_blend_val(_address, *args):
    if not args or len(args) < 2:
        return
    blend_name = str(args[0])
    try:
        val = float(args[1])
    except (TypeError, ValueError):
        return

    with state.buffer_lock:
        previous_raw = state.blend_buf.get(blend_name)
        raw_changed = previous_raw is None or abs(float(previous_raw) - val) > constants.SHAPE_EPS
        state.blend_buf[blend_name] = val
        canonical_name = mapping.canonical_vmc_blend_name(blend_name)
        canonical_changed = False
        if canonical_name:
            previous_canonical = state.canonical_vmc_blend_buf.get(canonical_name)
            canonical_changed = previous_canonical is None or abs(float(previous_canonical) - val) > constants.SHAPE_EPS
            state.canonical_vmc_blend_buf[canonical_name] = val
        if not raw_changed and not canonical_changed:
            return
        packet_ts = time.time()
        state.last_packet_ts = packet_ts
        state.raw_frame_vmc_blend_dirty = True
        state.raw_frame_dirty_vmc_blend_names.add(canonical_name or blend_name)
        if canonical_name in mapping.VMC_EYE_LOOK_BLEND_KEYS:
            state.raw_frame_vmc_eye_blend_dirty = True
        state.dirty = True
        _mark_raw_frame_activity_locked(packet_ts)


def on_arkit_face(_address, *args):
    if not args:
        return
    count = min(len(args), len(constants.ARKIT_BLENDSHAPE_KEYS))
    with state.buffer_lock:
        dirty_names = []
        for idx in range(count):
            try:
                val = float(args[idx])
            except (TypeError, ValueError):
                continue
            key_name = constants.ARKIT_BLENDSHAPE_KEYS[idx]
            previous_value = state.arkit_blend_buf.get(key_name, 0.0)
            if abs(float(previous_value) - val) <= constants.SHAPE_EPS:
                continue
            state.arkit_blend_buf[key_name] = val
            dirty_names.append(key_name)

        if dirty_names:
            packet_ts = time.time()
            state.arkit_last_packet_ts = packet_ts
            state.raw_frame_arkit_blend_dirty = True
            state.raw_frame_dirty_arkit_blend_names.update(dirty_names)
            state.dirty = True
            _mark_raw_frame_activity_locked(packet_ts)


def start_server(scene):
    normalize_runtime_state()
    if runtime.is_recording_bake_active():
        raise RuntimeError("上一段录制结果仍在保存，请等待当前保存完成")
    if is_paused():
        raise RuntimeError("接收器当前处于暂停状态，请点击“继续接收”或先停止接收")
    if is_session_active():
        raise RuntimeError("接收器已在运行")

    state.reset_runtime_buffers()
    state.cached_bone_map = {}
    state.cached_blend_map = {}
    vmc_socket = None
    arkit_socket = None
    try:
        bind_host, vmc_socket, vmc_dispatcher, arkit_socket, arkit_dispatcher = _build_receiver_handles(scene)
        runtime.capture_receiver_start_state_at_zero_frame(scene)
    except Exception:
        if vmc_socket is not None:
            vmc_socket.close()
        if arkit_socket is not None:
            arkit_socket.close()
        runtime.clear_receiver_session_state()
        raise

    _assign_receiver_handles(vmc_socket, vmc_dispatcher, arkit_socket, arkit_dispatcher)
    helpers.debug(f"Receiver started on UDP {bind_host}:{int(scene.vmc_link_port)}")
    if state.arkit_receiver_socket is not None:
        helpers.debug(f"ARKit face receiver started on UDP {bind_host}:{scene.vmc_link_arkit_port}")


def pause_server():
    normalize_runtime_state()
    if not is_session_active():
        raise RuntimeError("接收器尚未启动")
    if is_paused():
        raise RuntimeError("接收器已暂停")

    runtime.pause_recording_clock()
    _close_receiver_handles()
    _clear_pending_raw_frames()
    state.receiver_paused = True
    helpers.debug("Receiver paused")


def resume_server(scene):
    normalize_runtime_state()
    if runtime.is_recording_bake_active():
        raise RuntimeError("上一段录制结果仍在保存，请等待当前保存完成")
    if not is_session_active():
        raise RuntimeError("接收器尚未启动")
    if not is_paused():
        raise RuntimeError("接收器当前未暂停")

    bind_host, vmc_socket, vmc_dispatcher, arkit_socket, arkit_dispatcher = _build_receiver_handles(scene)
    _assign_receiver_handles(vmc_socket, vmc_dispatcher, arkit_socket, arkit_dispatcher)
    runtime.resume_recording_clock()
    state.receiver_paused = False
    state.next_tick_ts = 0.0
    helpers.debug(f"Receiver resumed on UDP {bind_host}:{int(scene.vmc_link_port)}")


def stop_server(_scene):
    normalize_runtime_state()
    if not is_session_active() and not is_running():
        return

    if runtime.is_recording():
        runtime.stop_recording(_scene)
    _close_receiver_handles()
    state.reset_runtime_buffers()
    runtime.restore_receiver_start_state()
    runtime.clear_receiver_session_state()
    helpers.debug("Receiver stopped")
