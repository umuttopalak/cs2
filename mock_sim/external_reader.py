"""
CS2 External Reader / ESP Analysis Tool
Gerçek CS2 process'inden ReadProcessMemory ile veri okur.
"""

import psutil
import ctypes
import ctypes.wintypes
import math
import tkinter as tk
from dataclasses import dataclass
from typing import Optional, Tuple
import struct
import time


import ctypes
import sys
class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_uint64),
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_int32),
        ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_char * 260),
    ]


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


if not is_admin():
    ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        sys.executable,
        " ".join(sys.argv),
        None,
        1,
    )
    sys.exit()


# ---------------------------------------------------------------------------
# Win32 API bindings
# ---------------------------------------------------------------------------

kernel32 = ctypes.windll.kernel32

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400


# GÜNCEL OFFSET'LER - cs2 her güncellemede değişir!
# https://github.com/a2x/cs2-offsets adresinden güncelle
class Offsets:
    # client.dll
    dwLocalPlayerController = 0x237EBA0  # placeholder - güncelle!
    dwEntityList = 0x254EE60  # placeholder - güncelle!
    dwViewMatrix = 0x23A9340  # placeholder - güncelle!

    # Entity offsets
    m_iHealth = 0x34C  # placeholder
    m_hPlayerPawn = 0x914  # placeholder
    m_iTeamNum = 0x3E7  # placeholder
    m_sSanitizedPlayerName = 0x868  # placeholder
    m_vecOrigin = 0x600  # placeholder
    m_vecViewOffset = 0xE78  # placeholder
    m_lifeState = 0x354  # placeholder


# ---------------------------------------------------------------------------
# Process / Memory helpers
# ---------------------------------------------------------------------------

# def find_process(process_name: str) -> Optional[int]:
#     """Toolhelp32 snapshot ile process bul."""
#     TH32CS_SNAPPROCESS = 0x00000002


#     snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
#     if snapshot == ctypes.c_void_p(-1).value:
#         return None

#     pe = PROCESSENTRY32()
#     pe.dwSize = ctypes.sizeof(PROCESSENTRY32)

#     if kernel32.Process32First(snapshot, ctypes.byref(pe)):
#         while True:
#             if pe.szExeFile.decode("utf-8", errors="ignore").lower() == process_name.lower():
#                 kernel32.CloseHandle(snapshot)
#                 return pe.th32ProcessID
#             if not kernel32.Process32Next(snapshot, ctypes.byref(pe)):
#                 break

#     kernel32.CloseHandle(snapshot)
#     return None


def find_process(process_name: str) -> Optional[int]:
    """psutil ile process bul."""
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info["name"] or "").lower() == process_name.lower():
                return proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return None


def get_module_base(process_id: int, module_name: str) -> Optional[int]:
    """Process'in modül base adresini al."""
    TH32CS_SNAPMODULE = 0x00000008
    TH32CS_SNAPMODULE32 = 0x00000010

    class MODULEENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_uint32),
            ("th32ModuleID", ctypes.c_uint32),
            ("th32ProcessID", ctypes.c_uint32),
            ("GlblcntUsage", ctypes.c_uint32),
            ("ProccntUsage", ctypes.c_uint32),
            ("modBaseAddr", ctypes.c_uint64),
            ("modBaseSize", ctypes.c_uint32),
            ("hModule", ctypes.c_void_p),
            ("szModule", ctypes.c_char * 256),
            ("szExePath", ctypes.c_char * 260),
        ]

    snapshot = kernel32.CreateToolhelp32Snapshot(
        TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, process_id
    )
    if snapshot == ctypes.c_void_p(-1).value:
        return None

    me = MODULEENTRY32()
    me.dwSize = ctypes.sizeof(MODULEENTRY32)

    if kernel32.Module32First(snapshot, ctypes.byref(me)):
        while True:
            mod = me.szModule.decode("utf-8", errors="ignore")

            print(mod)

            if mod.lower() == module_name.lower():
                kernel32.CloseHandle(snapshot)
                return me.modBaseAddr

            if not kernel32.Module32Next(snapshot, ctypes.byref(me)):
                break

    kernel32.CloseHandle(snapshot)
    return None


class CS2Memory:
    """CS2 process'ine bağlanıp bellek okuma."""

    def __init__(self):
        self.process_id = None
        self.handle = None
        self.client_base = None
        self.engine_base = None

    def attach(self) -> bool:
        """cs2.exe process'ine bağlan."""
        self.process_id = find_process("cs2.exe")
        print(self.process_id)
        if not self.process_id:
            print("[!] cs2.exe bulunamadı! Oyun çalışıyor mu?")
            return False

        self.handle = kernel32.OpenProcess(
            PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, self.process_id
        )
        if not self.handle:
            print("[!] Process açılamadı. Yönetici olarak çalıştırıyor musun?")
            return False

        self.client_base = get_module_base(self.process_id, "client.dll")
        self.engine_base = get_module_base(self.process_id, "engine2.dll")

        if not self.client_base:
            print("[!] client.dll bulunamadı!")
            return False

        print(f"[+] cs2.exe PID: {self.process_id}")
        print(f"[+] client.dll: 0x{self.client_base:X}")
        print(f"[+] engine2.dll: 0x{self.engine_base:X}")
        return True

    def read_bytes(self, address: int, size: int) -> Optional[bytearray]:
        """Adresten byte oku."""
        buf = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_ulong(0)

        if kernel32.ReadProcessMemory(
            self.handle, ctypes.c_void_p(address), buf, size, ctypes.byref(bytes_read)
        ):
            return bytearray(buf.raw[: bytes_read.value])
        return None

    def read_uint32(self, address: int) -> Optional[int]:
        data = self.read_bytes(address, 4)
        if data:
            return struct.unpack("<I", data)[0]
        return None

    def read_float(self, address: int) -> Optional[float]:
        data = self.read_bytes(address, 4)
        if data:
            return struct.unpack("<f", data)[0]
        return None

    def read_string(self, address: int, max_len: int = 32) -> str:
        data = self.read_bytes(address, max_len)
        if data:
            null_idx = data.find(b"\x00")
            if null_idx >= 0:
                data = data[:null_idx]
            return data.decode("utf-8", errors="ignore")
        return ""

    def read_vec3(self, address: int) -> Optional[Tuple[float, float, float]]:
        data = self.read_bytes(address, 12)
        if data:
            x, y, z = struct.unpack("<fff", data)
            return (x, y, z)
        return None

    def read_matrix_4x4(self, address: int) -> Optional[list]:
        """16 float = 64 byte matris oku."""
        data = self.read_bytes(address, 64)
        if data:
            vals = struct.unpack("<16f", data)
            return [list(vals[i : i + 4]) for i in range(0, 16, 4)]
        return None

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PlayerData:
    entity_id: int
    name: str
    health: int
    team: int
    position: Tuple[float, float, float]
    alive: bool
    distance: float = 0.0


# ---------------------------------------------------------------------------
# View / Projection math
# ---------------------------------------------------------------------------

Vec3 = Tuple[float, float, float]
Mat4 = list[list[float]]


@dataclass
class Camera:
    pos: Vec3
    yaw_deg: float = 0.0
    pitch_deg: float = 0.0
    fov_deg: float = 90.0
    aspect: float = 1.33
    near: float = 1.0
    far: float = 2000.0


def world_to_screen(
    world_pos: Vec3, view_matrix: Mat4, screen_w: int, screen_h: int
) -> Optional[Tuple[float, float]]:
    """
    CS2'nin kendi view matrix'i ile W2S dönüşümü.
    CS2'de view matrix doğrudan clip space'e çevirir.
    """
    x, y, z = world_pos

    # Clip space hesaplama
    clip_x = (
        x * view_matrix[0][0]
        + y * view_matrix[0][1]
        + z * view_matrix[0][2]
        + view_matrix[0][3]
    )
    clip_y = (
        x * view_matrix[1][0]
        + y * view_matrix[1][1]
        + z * view_matrix[1][2]
        + view_matrix[1][3]
    )
    clip_w = (
        x * view_matrix[3][0]
        + y * view_matrix[3][1]
        + z * view_matrix[3][2]
        + view_matrix[3][3]
    )

    if clip_w < 0.001:
        return None

    # NDC
    ndc_x = clip_x / clip_w
    ndc_y = clip_y / clip_w

    # Screen coords
    screen_x = (screen_w / 2.0) * ndc_x + (screen_w / 2.0)
    screen_y = -(screen_h / 2.0) * ndc_y + (screen_h / 2.0)

    return (screen_x, screen_y)


def get_player_distance(local_pos: Vec3, player_pos: Vec3) -> float:
    return math.sqrt(
        (local_pos[0] - player_pos[0]) ** 2
        + (local_pos[1] - player_pos[1]) ** 2
        + (local_pos[2] - player_pos[2]) ** 2
    )


# ---------------------------------------------------------------------------
# Reader logic
# ---------------------------------------------------------------------------


class CS2Reader:
    """CS2'den oyuncu verilerini okuyan ana sınıf."""

    def __init__(self, memory: CS2Memory):
        self.mem = memory
        self.view_matrix = None
        self.local_player = None
        self.players: list[PlayerData] = []

    def update(self):
        """Bir frame'lik veri oku."""
        if not self.mem.client_base:
            return

        # View matrix oku
        matrix_addr = self.mem.client_base + Offsets.dwViewMatrix
        self.view_matrix = self.mem.read_matrix_4x4(matrix_addr)
        if not self.view_matrix:
            return

        # Local player
        local_addr = self.mem.read_uint32(
            self.mem.client_base + Offsets.dwLocalPlayerController
        )
        if not local_addr:
            return

        local_pawn_handle = self.mem.read_uint32(local_addr + Offsets.m_hPlayerPawn)
        if not local_pawn_handle:
            return

        local_pawn = local_pawn_handle & 0xFFF  # index mask
        local_team = self.mem.read_uint32(local_addr + Offsets.m_iTeamNum)
        local_pos = self.mem.read_vec3(local_addr + Offsets.m_vecOrigin) or (0, 0, 0)

        self.local_player = PlayerData(
            entity_id=0,
            name="LOCAL",
            health=self.mem.read_uint32(local_addr + Offsets.m_iHealth) or 0,
            team=local_team or 0,
            position=local_pos,
            alive=True,
        )

        # Entity list
        entity_list = self.mem.read_uint32(self.mem.client_base + Offsets.dwEntityList)
        if not entity_list:
            return

        self.players = []

        # CS2'de max 64 oyuncu slotu
        for i in range(1, 65):
            controller_addr = self.mem.read_uint32(entity_list + (i * 0x10))
            if not controller_addr or controller_addr == 0:
                continue

            health = self.mem.read_uint32(controller_addr + Offsets.m_iHealth)
            if not health or health == 0 or health > 100:
                continue

            team = self.mem.read_uint32(controller_addr + Offsets.m_iTeamNum)

            # Kendini atla
            if team == local_team and controller_addr == local_addr:
                continue

            name = self.mem.read_string(
                controller_addr + Offsets.m_sSanitizedPlayerName
            )

            # Pawn pointer'dan pozisyon al
            pawn_handle = self.mem.read_uint32(controller_addr + Offsets.m_hPlayerPawn)
            if not pawn_handle:
                continue

            pawn_index = pawn_handle & 0xFFF
            list_entry = self.mem.read_uint32(
                entity_list + 0x8 * (pawn_index >> 9) + 0x10
            )
            if not list_entry:
                continue

            pawn_addr = self.mem.read_uint32(list_entry + 0x78 * (pawn_index & 0x1FF))
            if not pawn_addr:
                continue

            pos = self.mem.read_vec3(pawn_addr + Offsets.m_vecOrigin)
            if not pos:
                continue

            life_state = self.mem.read_uint32(pawn_addr + Offsets.m_lifeState) or 0

            dist = get_player_distance(local_pos, pos)

            self.players.append(
                PlayerData(
                    entity_id=i,
                    name=name,
                    health=health,
                    team=team or 0,
                    position=pos,
                    alive=(life_state == 0),
                    distance=dist,
                )
            )


# ---------------------------------------------------------------------------
# tkinter UI
# ---------------------------------------------------------------------------

TEAM_COLORS = {2: "#4da3ff", 3: "#ff5c5c"}
RADAR_SIZE = 400
VIEW_SIZE = (500, 400)
WORLD_RADIUS = 2000
REFRESH_MS = 33


class CS2Overlay:
    def __init__(self, root: tk.Tk, reader: CS2Reader):
        self.reader = reader

        root.title("CS2 External Reader")
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.radar = tk.Canvas(root, width=RADAR_SIZE, height=RADAR_SIZE, bg="#101418")
        self.radar.grid(row=0, column=0, padx=8, pady=8)

        self.view = tk.Canvas(
            root, width=VIEW_SIZE[0], height=VIEW_SIZE[1], bg="#101418"
        )
        self.view.grid(row=0, column=1, padx=8, pady=8)

        self.info = tk.Label(
            root, text="", anchor="w", justify="left", font=("Consolas", 9)
        )
        self.info.grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        self.running = True
        root.after(0, self._render)

    def _render(self):
        if not self.running:
            return

        self.reader.update()
        self._draw_radar()
        self._draw_view()
        self._update_info()

        self.radar.after(REFRESH_MS, self._render)

    def _draw_radar(self):
        c = self.radar
        c.delete("all")
        cx, cy = RADAR_SIZE / 2, RADAR_SIZE / 2
        c.create_oval(4, 4, RADAR_SIZE - 4, RADAR_SIZE - 4, outline="#333")

        local = self.reader.local_player
        if not local:
            return

        for p in self.reader.players:
            if not p.alive:
                continue
            dx = p.position[0] - local.position[0]
            dz = p.position[2] - local.position[2]

            sx = cx + (dx / WORLD_RADIUS) * (RADAR_SIZE / 2)
            sy = cy + (dz / WORLD_RADIUS) * (RADAR_SIZE / 2)

            if not (0 <= sx <= RADAR_SIZE and 0 <= sy <= RADAR_SIZE):
                continue

            color = TEAM_COLORS.get(p.team, "#ccc")
            r = 4
            c.create_oval(sx - r, sy - r, sx + r, sy + r, fill=color, outline="")
            c.create_text(
                sx, sy - 10, text=str(int(p.health)), fill=color, font=("Consolas", 7)
            )

    def _draw_view(self):
        c = self.view
        c.delete("all")

        local = self.reader.local_player
        if not local or not self.reader.view_matrix:
            return

        w, h = VIEW_SIZE

        for p in self.reader.players:
            if not p.alive:
                continue

            screen = world_to_screen(p.position, self.reader.view_matrix, w, h)
            if screen is None:
                continue

            sx, sy = screen
            if not (0 <= sx <= w and 0 <= sy <= h):
                continue

            color = TEAM_COLORS.get(p.team, "#ccc")

            # Distance-based box size
            dist = p.distance
            box_h = max(10, min(80, 300 / max(dist, 1)))
            box_w = box_h * 0.6

            # Box
            c.create_rectangle(
                sx - box_w, sy - box_h, sx + box_w, sy, outline=color, width=2
            )

            # Name
            c.create_text(
                sx, sy - box_h - 8, text=p.name, fill=color, font=("Consolas", 8)
            )

            # Health
            c.create_text(
                sx, sy + 2, text=f"{int(p.health)}HP", fill=color, font=("Consolas", 7)
            )

            # Distance
            c.create_text(
                sx, sy + 14, text=f"{int(dist)}m", fill="#888", font=("Consolas", 7)
            )

    def _update_info(self):
        local = self.reader.local_player
        if local:
            self.info.config(
                text=f"Local: HP={local.health} | "
                f"Players: {len(self.reader.players)} | "
                f"FPS: ~{1000//REFRESH_MS}"
            )
        else:
            self.info.config(text="CS2'ye bağlanılamadı...")

    def _on_close(self):
        self.running = False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("[*] CS2 External Reader başlatılıyor...")

    mem = CS2Memory()
    if not mem.attach():
        print("[!] cs2.exe'ye bağlanılamadı!")
        print("[*] 1. CS2'nin çalıştığından emin ol")
        print("[*] 2. Scripti yönetici olarak çalıştır")
        print("[*] 3. CS2'nin güncel olup olmadığını kontrol et")
        input("Enter'a basarak çık...")
        return

    reader = CS2Reader(mem)

    root = tk.Tk()
    app = CS2Overlay(root, reader)
    root.mainloop()

    mem.close()
    print("[*] Çıkıldı.")


if __name__ == "__main__":
    main()
