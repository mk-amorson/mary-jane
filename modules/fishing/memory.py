"""GTA5 memory reader for fishing bot.
Reads player heading from CPed entity matrix via pymem (external).
Falls back gracefully if pymem unavailable or GTA5 not found.
"""
import struct
import math
import logging

log = logging.getLogger(__name__)

try:
    import pymem
    import pymem.process
    _HAS_PYMEM = True
except ImportError:
    _HAS_PYMEM = False
    log.info("pymem not installed, memory reading disabled")


class GTA5Memory:
    """Read player data from GTA5 process memory."""

    def __init__(self):
        self._pm = None
        self._ped: int = 0
        self._viewport: int = 0  # camera view matrix base

    @property
    def connected(self) -> bool:
        return self._pm is not None and self._ped != 0

    def connect(self) -> bool:
        """Connect to GTA5.exe and find local CPed + camera viewport. Returns True on success."""
        if not _HAS_PYMEM:
            return False
        try:
            pm = pymem.Pymem("GTA5.exe")
            mod = pymem.process.module_from_name(pm.process_handle, "GTA5.exe")
            scan = pm.read_bytes(mod.lpBaseOfDll, mod.SizeOfImage)
            base = mod.lpBaseOfDll

            # --- CPedFactory pattern ---
            pat1, pat2 = b"\x48\x8B\x05", b"\x48\x8B\x48\x08"
            ped_found = False
            idx = 0
            while True:
                pos = scan.find(pat1, idx)
                if pos < 0:
                    break
                if pos + 11 <= len(scan) and scan[pos+7:pos+11] == pat2:
                    rip = base + pos + 7
                    rel = struct.unpack("<i", scan[pos+3:pos+7])[0]
                    try:
                        factory = pm.read_longlong(rip + rel)
                        ped = pm.read_longlong(factory + 8)
                        if ped > 0x10000:
                            self._pm = pm
                            self._ped = ped
                            ped_found = True
                            log.info("Connected to GTA5: CPed=0x%X", ped)
                            break
                    except Exception:
                        pass
                idx = pos + 1

            if not ped_found:
                pm.close_process()
                return False

            # --- Viewport pattern: 48 8B 15 ?? ?? ?? ?? 48 8D 2D ---
            vp_pat = b"\x48\x8B\x15"
            vp_suf = b"\x48\x8D\x2D"
            idx = 0
            while True:
                pos = scan.find(vp_pat, idx)
                if pos < 0:
                    break
                if pos + 10 <= len(scan) and scan[pos+7:pos+10] == vp_suf:
                    rip = base + pos + 7
                    rel = struct.unpack("<i", scan[pos+3:pos+7])[0]
                    try:
                        vp = pm.read_longlong(rip + rel)
                        if vp > 0x10000:
                            self._viewport = vp
                            log.info("Viewport found: 0x%X", vp)
                            break
                    except Exception:
                        pass
                idx = pos + 1

            return True
        except Exception:
            log.debug("Failed to connect to GTA5", exc_info=True)
        return False

    def disconnect(self):
        if self._pm:
            try:
                self._pm.close_process()
            except Exception:
                pass
            self._pm = None
            self._ped = 0
            self._viewport = 0

    def read_position(self) -> tuple[float, float, float] | None:
        """Read player position (x, y, z) from entity matrix.
        Returns None on failure.
        """
        if not self.connected:
            return None
        try:
            data = self._pm.read_bytes(self._ped + 0x90, 12)
            x, y, z = struct.unpack("<fff", data)
            return (x, y, z)
        except Exception:
            log.debug("Failed to read position", exc_info=True)
            self._pm = None
            self._ped = 0
            return None

    def read_camera_heading(self) -> float | None:
        """Read camera heading in degrees from viewport forward vector.
        Viewport matrix: +0x060 = forward.x, +0x064 = forward.y.
        Returns None if viewport not found.
        """
        if not self.connected or self._viewport == 0:
            return None
        try:
            data = self._pm.read_bytes(self._viewport + 0x60, 8)
            fwd_x, fwd_y = struct.unpack("<ff", data)
            return math.degrees(math.atan2(fwd_x, fwd_y))
        except Exception:
            log.debug("Failed to read camera heading", exc_info=True)
            self._viewport = 0
            return None

    def read_camera_rotation(self) -> tuple[float, float] | None:
        """Read camera yaw and pitch from viewport forward vector.
        Returns (yaw_degrees, pitch_degrees) or None.
        """
        if not self.connected or self._viewport == 0:
            return None
        try:
            data = self._pm.read_bytes(self._viewport + 0x60, 12)
            fwd_x, fwd_y, fwd_z = struct.unpack("<fff", data)
            yaw = math.degrees(math.atan2(fwd_x, fwd_y))
            fwd_z_clamped = max(-1.0, min(1.0, fwd_z))
            pitch = math.degrees(math.asin(fwd_z_clamped))
            return (yaw, pitch)
        except Exception:
            log.debug("Failed to read camera rotation", exc_info=True)
            self._viewport = 0
            return None

    def read_camera_vectors(self) -> tuple | None:
        """Read camera basis vectors + position from viewport.
        Layout: +0x50 right(vec4), +0x60 fwd(vec4), +0x70 up(vec4), +0x100 pos(vec3).
        Returns (right, fwd, up, pos) as 4 tuples of 3 floats, or None.
        """
        if not self.connected or self._viewport == 0:
            return None
        try:
            # right/fwd/up are 3 consecutive vec4s starting at +0x50
            vecs = self._pm.read_bytes(self._viewport + 0x50, 48)
            right = struct.unpack("<fff", vecs[0:12])    # +0x50
            fwd = struct.unpack("<fff", vecs[16:28])     # +0x60
            up = struct.unpack("<fff", vecs[32:44])      # +0x70
            pos_data = self._pm.read_bytes(self._viewport + 0x100, 12)
            pos = struct.unpack("<fff", pos_data)
            return (right, fwd, up, pos)
        except Exception:
            log.debug("Failed to read camera vectors", exc_info=True)
            self._viewport = 0
            return None

    def read_heading(self) -> float | None:
        """Read player heading in degrees from entity forward vector.
        Returns None on failure.
        """
        if not self.connected:
            return None
        try:
            fwd_x = struct.unpack("<f", self._pm.read_bytes(self._ped + 0x70, 4))[0]
            fwd_y = struct.unpack("<f", self._pm.read_bytes(self._ped + 0x74, 4))[0]
            return math.degrees(math.atan2(fwd_x, fwd_y))
        except Exception:
            log.debug("Failed to read heading", exc_info=True)
            self._pm = None
            self._ped = 0
            return None


class HeadingTracker:
    """Detect camera pan direction via CPed heading changes.
    Replacement for CameraTracker (optical flow) — reads memory instead of pixels.

    During reel phase, the player entity rotates with the camera:
    - heading increasing → camera pans right → hold A
    - heading decreasing → camera pans left  → hold D

    Tuned from 5 real fishing cycles: heading changes ~1-2 deg per 50ms
    during reel, 0 during cast/strike/take. Wraps around ±180°.
    """

    def __init__(self, mem: GTA5Memory):
        self._mem = mem
        self._prev_heading: float | None = None
        self._last_dir: str | None = None
        self._accum: float = 0.0  # accumulated heading change
        self._moving: bool = False
        self._stable_ticks: int = 0

    @property
    def moving(self) -> bool:
        """True when heading is actively changing (reel in progress)."""
        return self._moving

    def reset(self):
        self._prev_heading = None
        self._last_dir = None
        self._accum = 0.0
        self._moving = False
        self._stable_ticks = 0

    def update(self) -> str | None:
        """Read heading, compute direction. Returns 'left', 'right', or None."""
        heading = self._mem.read_heading()
        if heading is None:
            return self._last_dir

        if self._prev_heading is None:
            self._prev_heading = heading
            return None

        # Compute delta with wrap-around (-180..180)
        delta = heading - self._prev_heading
        if delta > 180:
            delta -= 360
        elif delta < -180:
            delta += 360
        self._prev_heading = heading

        # Exponential moving average: fast response, filters noise
        # alpha=0.4 gives ~2-3 sample effective window
        self._accum = 0.4 * delta + 0.6 * self._accum

        # Track moving/stable state
        if abs(self._accum) > 0.2:
            self._moving = True
            self._stable_ticks = 0
        else:
            self._stable_ticks += 1
            if self._stable_ticks >= 30:  # ~1.5s at 50ms ticks
                self._moving = False

        if self._accum > 0.3:
            d = "right"
        elif self._accum < -0.3:
            d = "left"
        else:
            d = self._last_dir

        if d and d != self._last_dir:
            log.info("Heading direction: %s (accum=%.2f, delta=%.2f)", d, self._accum, delta)
            self._last_dir = d

        return d
