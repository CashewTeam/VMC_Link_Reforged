import socket
import time

import bpy
from pythonosc.dispatcher import Dispatcher

from . import constants, helpers, mapping, properties, runtime, state


def is_running() -> bool:
    return state.receiver_socket is not None or state.arkit_receiver_socket is not None


def _is_arkit_face_source_enabled(scene) -> bool:
    return str(getattr(scene, "vmc_link_face_source", constants.FACE_SOURCE_VMC)) == constants.FACE_SOURCE_RHYLIVE_ARKIT


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

    bind_host = properties.resolve_bind_host(scene).strip()
    if not bind_host:
        raise RuntimeError("接收地址不能为空")

    port = int(scene.vmc_link_port)
    new_socket = None
    new_arkit_socket = None
    try:
        new_socket = create_udp_socket(bind_host, port)
        new_dispatcher = build_vmc_dispatcher()
        new_arkit_dispatcher = None
        if _is_arkit_face_source_enabled(scene):
            new_arkit_socket = create_udp_socket(bind_host, int(scene.vmc_link_arkit_port))
            new_arkit_dispatcher = build_arkit_dispatcher()
    except Exception:
        if new_socket is not None:
            new_socket.close()
        if new_arkit_socket is not None:
            new_arkit_socket.close()
        raise

    old_socket = state.receiver_socket
    old_arkit_socket = state.arkit_receiver_socket
    state.receiver_socket = new_socket
    state.dispatcher = new_dispatcher
    state.arkit_receiver_socket = new_arkit_socket
    state.arkit_dispatcher = new_arkit_dispatcher

    state.reset_runtime_buffers()
    state.cached_bone_map = {}
    state.cached_blend_map = {}

    if old_socket is not None:
        old_socket.close()
    if old_arkit_socket is not None:
        old_arkit_socket.close()

    helpers.debug(f"Receiver rebound to UDP {bind_host}:{port}")
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


def on_vmc_bone_pos(_address, *args):
    if not args or len(args) < 8:
        return
    bone_name = str(args[0])
    try:
        px, py, pz = float(args[1]), float(args[2]), float(args[3])
        qx, qy, qz, qw = float(args[4]), float(args[5]), float(args[6]), float(args[7])
    except (TypeError, ValueError):
        return

    state.last_packet_ts = time.time()
    state.bone_buf[bone_name] = (px, py, pz, qx, qy, qz, qw)
    state.dirty = True


def on_vmc_root_pos(_address, *args):
    if not args or len(args) < 7:
        return

    offset = 1 if len(args) >= 8 else 0
    try:
        px, py, pz = float(args[offset + 0]), float(args[offset + 1]), float(args[offset + 2])
        qx, qy, qz, qw = float(args[offset + 3]), float(args[offset + 4]), float(args[offset + 5]), float(args[offset + 6])
    except (TypeError, ValueError):
        return

    state.last_packet_ts = time.time()
    state.root_buf = (px, py, pz, qx, qy, qz, qw)
    state.dirty = True


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

    state.last_packet_ts = time.time()
    state.waist_buf = (px, py, pz, qx, qy, qz, qw)
    state.dirty = True


def on_vmc_blend_val(_address, *args):
    if not args or len(args) < 2:
        return
    try:
        val = float(args[1])
    except (TypeError, ValueError):
        return

    state.last_packet_ts = time.time()
    state.blend_buf[args[0]] = val
    state.dirty = True


def on_arkit_face(_address, *args):
    if not args:
        return
    count = min(len(args), len(constants.ARKIT_BLENDSHAPE_KEYS))
    updated_any = False
    for idx in range(count):
        try:
            val = float(args[idx])
        except (TypeError, ValueError):
            continue
        state.arkit_blend_buf[constants.ARKIT_BLENDSHAPE_KEYS[idx]] = val
        updated_any = True

    if updated_any:
        state.arkit_last_packet_ts = time.time()
        state.dirty = True


def start_server(scene):
    if is_running():
        raise RuntimeError("接收器已在运行")

    state.reset_runtime_buffers()
    state.cached_bone_map = {}
    state.cached_blend_map = {}

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

    state.receiver_socket = vmc_socket
    state.dispatcher = vmc_dispatcher
    state.arkit_receiver_socket = arkit_socket
    state.arkit_dispatcher = arkit_dispatcher

    if not bpy.app.timers.is_registered(runtime.apply_timer):
        bpy.app.timers.register(runtime.apply_timer, persistent=True)

    state.apply_timer_running = True
    helpers.debug(f"Receiver started on UDP {bind_host}:{port}")
    if state.arkit_receiver_socket is not None:
        helpers.debug(f"ARKit face receiver started on UDP {bind_host}:{scene.vmc_link_arkit_port}")


def stop_server(_scene):
    if not is_running():
        return

    if state.receiver_socket is not None:
        state.receiver_socket.close()
    if state.arkit_receiver_socket is not None:
        state.arkit_receiver_socket.close()

    state.receiver_socket = None
    state.dispatcher = None
    state.arkit_receiver_socket = None
    state.arkit_dispatcher = None
    state.reset_runtime_buffers()

    if bpy.app.timers.is_registered(runtime.apply_timer):
        bpy.app.timers.unregister(runtime.apply_timer)

    state.apply_timer_running = False
    helpers.debug("Receiver stopped")
