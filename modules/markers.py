"""Markers module — reads player position, heading, and camera vectors from GTA5 memory."""
import math
import asyncio
import logging

from modules.fishing.memory import GTA5Memory

log = logging.getLogger(__name__)


async def markers_loop(state):
    mem = GTA5Memory()
    while True:
        if not state.markers_active:
            if mem.connected:
                mem.disconnect()
            state.markers_pos = None
            state.markers_yaw = None
            state.markers_pitch = None
            state.markers_cam_yaw = None
            state.markers_cam_pitch = None
            state.markers_cam_pos = None
            state.markers_cam_right = None
            state.markers_cam_fwd = None
            state.markers_cam_up = None
            await asyncio.sleep(0.5)
            continue

        if not mem.connected:
            if not mem.connect():
                await asyncio.sleep(1)
                continue

        state.markers_pos = mem.read_position()
        # Entity heading — for arrow compass
        state.markers_yaw = mem.read_heading()
        state.markers_pitch = None
        # Camera vectors — for world-to-screen projection
        cam = mem.read_camera_vectors()
        if cam:
            right, fwd, up, pos = cam
            state.markers_cam_right = right
            state.markers_cam_fwd = fwd
            state.markers_cam_up = up
            state.markers_cam_pos = pos
            state.markers_cam_yaw = math.degrees(math.atan2(fwd[0], fwd[1]))
            fwd_z = max(-1.0, min(1.0, fwd[2]))
            state.markers_cam_pitch = math.degrees(math.asin(fwd_z))
        else:
            state.markers_cam_right = None
            state.markers_cam_fwd = None
            state.markers_cam_up = None
            state.markers_cam_pos = None
            state.markers_cam_yaw = state.markers_yaw
            state.markers_cam_pitch = 0.0
        await asyncio.sleep(0.05)
