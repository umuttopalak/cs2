"""Shared ctypes struct layout used by both the mock game process and the
external reader. This plays the role that game-specific struct offsets play
in the real thing, except the layout is ours: we define it, so there is
nothing to reverse-engineer and nothing tied to any real application's
memory.
"""

import ctypes

SHM_NAME = "cs2_mock_world"
MAX_ENTITIES = 8


class MockEntity(ctypes.Structure):
    _fields_ = [
        ("entity_id", ctypes.c_uint32),
        ("pos_x", ctypes.c_float),
        ("pos_y", ctypes.c_float),
        ("pos_z", ctypes.c_float),
        ("team", ctypes.c_uint32),   # 2 or 3, arbitrary team ids
        ("health", ctypes.c_float),  # 0.0 - 100.0
        ("alive", ctypes.c_uint32),  # 0 / 1
    ]


class MockWorld(ctypes.Structure):
    _fields_ = [
        ("entity_count", ctypes.c_uint32),
        ("local_player_index", ctypes.c_uint32),
        ("entities", MockEntity * MAX_ENTITIES),
    ]
