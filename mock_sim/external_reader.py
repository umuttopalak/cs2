"""External reader / analysis tool.

Attaches to the mock game process's shared memory (conceptually the same
role `pymem`/`ReadProcessMemory` play against a real process's address
space, just using a cross-platform, permission-safe mechanism instead of
opening another process's memory directly). It then:

  1. Parses the raw bytes into the `MockWorld` struct (memory -> data).
  2. Runs a generic World-to-Screen (W2S) transform using a hand-built
     view + projection matrix, to show the math independent of any real
     engine's matrix layout.
  3. Renders two tkinter panels: a top-down radar (world x/z straight to
     canvas coordinates) and a "camera view" panel (entities projected
     through the view-projection matrix, as a wallhack-style overlay would,
     but drawn in our own window rather than over any other application).

Run mock_game_process.py first, then this script.
"""

import math
import tkinter as tk
from dataclasses import dataclass
from multiprocessing import shared_memory

from shared_layout import SHM_NAME, MockWorld

RADAR_SIZE = 400
VIEW_SIZE = (500, 400)
WORLD_RADIUS = 600  # world units mapped to the radar's edge
REFRESH_MS = 33


# ---------------------------------------------------------------------------
# 1. Attach + parse
# ---------------------------------------------------------------------------

def attach() -> tuple[shared_memory.SharedMemory, MockWorld]:
    shm = shared_memory.SharedMemory(name=SHM_NAME, create=False)
    world = MockWorld.from_buffer(shm.buf)
    return shm, world


# ---------------------------------------------------------------------------
# 2. Generic view/projection matrix math (World-to-Screen)
# ---------------------------------------------------------------------------

Vec3 = tuple[float, float, float]
Mat4 = list[list[float]]


@dataclass
class Camera:
    pos: Vec3
    yaw_deg: float    # rotation around Y
    pitch_deg: float  # rotation around X
    fov_deg: float = 90.0
    aspect: float = VIEW_SIZE[0] / VIEW_SIZE[1]
    near: float = 1.0
    far: float = 2000.0


def _mat_identity() -> Mat4:
    return [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


def _mat_mul(a: Mat4, b: Mat4) -> Mat4:
    return [
        [sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)]
        for i in range(4)
    ]


def _mat_vec_mul(m: Mat4, v: tuple[float, float, float, float]) -> tuple:
    return tuple(sum(m[i][k] * v[k] for k in range(4)) for i in range(4))


def look_at_matrix(cam: Camera) -> Mat4:
    """Build a view matrix from camera position + yaw/pitch (degrees)."""
    yaw = math.radians(cam.yaw_deg)
    pitch = math.radians(cam.pitch_deg)

    # Forward vector from yaw/pitch (standard spherical -> cartesian).
    fx = math.cos(pitch) * math.sin(yaw)
    fy = math.sin(pitch)
    fz = math.cos(pitch) * math.cos(yaw)
    forward = (fx, fy, fz)

    world_up = (0.0, 1.0, 0.0)

    def cross(a, b):
        return (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

    def norm(v):
        length = math.sqrt(sum(c * c for c in v)) or 1.0
        return tuple(c / length for c in v)

    right = norm(cross(forward, world_up))
    up = norm(cross(right, forward))

    px, py, pz = cam.pos
    # Rotation part (rows = right/up/-forward), translation via dot products.
    return [
        [right[0], right[1], right[2], -(right[0] * px + right[1] * py + right[2] * pz)],
        [up[0], up[1], up[2], -(up[0] * px + up[1] * py + up[2] * pz)],
        [-forward[0], -forward[1], -forward[2], (forward[0] * px + forward[1] * py + forward[2] * pz)],
        [0.0, 0.0, 0.0, 1.0],
    ]


def perspective_matrix(cam: Camera) -> Mat4:
    fov_rad = math.radians(cam.fov_deg)
    f = 1.0 / math.tan(fov_rad / 2.0)
    nf = 1.0 / (cam.near - cam.far)
    return [
        [f / cam.aspect, 0.0, 0.0, 0.0],
        [0.0, f, 0.0, 0.0],
        [0.0, 0.0, (cam.far + cam.near) * nf, 2 * cam.far * cam.near * nf],
        [0.0, 0.0, -1.0, 0.0],
    ]


def world_to_screen(world_pos: Vec3, view_proj: Mat4, screen_w: int, screen_h: int):
    """Classic W2S: world -> clip space -> NDC -> pixel coords.

    Returns None if the point is behind the camera (w <= 0), matching how a
    real ESP skips off-screen/behind-camera entities.
    """
    clip = _mat_vec_mul(view_proj, (*world_pos, 1.0))
    x, y, _, w = clip
    if w <= 0.001:
        return None
    ndc_x, ndc_y = x / w, y / w
    screen_x = (ndc_x + 1.0) * 0.5 * screen_w
    screen_y = (1.0 - ndc_y) * 0.5 * screen_h
    return screen_x, screen_y


# ---------------------------------------------------------------------------
# 3. tkinter rendering
# ---------------------------------------------------------------------------

TEAM_COLORS = {2: "#4da3ff", 3: "#ff5c5c"}


class RadarApp:
    def __init__(self, root: tk.Tk, shm, world: MockWorld):
        self.shm = shm
        self.world = world
        self.camera = Camera(pos=(0.0, 50.0, -300.0), yaw_deg=0.0, pitch_deg=10.0)

        root.title("External Reader — Mock World Analysis")

        self.radar_canvas = tk.Canvas(root, width=RADAR_SIZE, height=RADAR_SIZE, bg="#101418")
        self.radar_canvas.grid(row=0, column=0, padx=8, pady=8)

        self.view_canvas = tk.Canvas(root, width=VIEW_SIZE[0], height=VIEW_SIZE[1], bg="#101418")
        self.view_canvas.grid(row=0, column=1, padx=8, pady=8)

        self.status = tk.Label(root, text="", anchor="w", justify="left", font=("Menlo", 10))
        self.status.grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        root.after(0, self.render)

    def render(self):
        self._draw_radar()
        self._draw_view()
        self.status.config(text=self._status_text())
        self.radar_canvas.after(REFRESH_MS, self.render)

    def _draw_radar(self):
        c = self.radar_canvas
        c.delete("all")
        cx, cy = RADAR_SIZE / 2, RADAR_SIZE / 2
        c.create_oval(4, 4, RADAR_SIZE - 4, RADAR_SIZE - 4, outline="#333")
        for i in range(self.world.entity_count):
            e = self.world.entities[i]
            if not e.alive:
                continue
            sx = cx + (e.pos_x / WORLD_RADIUS) * (RADAR_SIZE / 2)
            sy = cy + (e.pos_z / WORLD_RADIUS) * (RADAR_SIZE / 2)
            color = TEAM_COLORS.get(e.team, "#cccccc")
            r = 5
            c.create_oval(sx - r, sy - r, sx + r, sy + r, fill=color, outline="")
            c.create_text(sx, sy - 10, text=f"{int(e.health)}", fill=color, font=("Menlo", 8))

    def _draw_view(self):
        c = self.view_canvas
        c.delete("all")
        view = look_at_matrix(self.camera)
        proj = perspective_matrix(self.camera)
        view_proj = _mat_mul(proj, view)

        w, h = VIEW_SIZE
        for i in range(self.world.entity_count):
            e = self.world.entities[i]
            if not e.alive or i == self.world.local_player_index:
                continue
            screen = world_to_screen((e.pos_x, e.pos_y, e.pos_z), view_proj, w, h)
            if screen is None:
                continue
            sx, sy = screen
            if not (0 <= sx <= w and 0 <= sy <= h):
                continue
            color = TEAM_COLORS.get(e.team, "#cccccc")
            box = 12
            c.create_rectangle(sx - box / 2, sy - box, sx + box / 2, sy, outline=color, width=2)
            c.create_text(sx, sy - box - 6, text=f"id{e.entity_id} hp{int(e.health)}",
                          fill=color, font=("Menlo", 8))

    def _status_text(self) -> str:
        alive = sum(1 for i in range(self.world.entity_count) if self.world.entities[i].alive)
        return (f"entities: {self.world.entity_count}  alive: {alive}  "
                f"camera pos={self.camera.pos} yaw={self.camera.yaw_deg:.0f} pitch={self.camera.pitch_deg:.0f}")


def main():
    shm, world = attach()
    root = tk.Tk()
    app = RadarApp(root, shm, world)
    try:
        root.mainloop()
    finally:
        # `world` is a ctypes structure created from_buffer(shm.buf); it must
        # be released before shm.close(), or mmap raises BufferError for
        # "exported pointers exist".
        del app, world
        shm.close()


if __name__ == "__main__":
    main()
