"""Mock 'game' process.

Stands in for the target application whose memory an external tool reads.
This process owns a block of shared memory laid out as `MockWorld` (see
shared_layout.py), spawns a handful of entities, and moves them around each
tick — so an external reader has something live to observe, the same way a
real game continuously updates its entity list every frame.

Run this in one terminal, then run external_reader.py in another.
"""

import math
import random
import time
from multiprocessing import shared_memory

from shared_layout import MAX_ENTITIES, SHM_NAME, MockWorld

TICK_HZ = 30


def make_world(shm) -> MockWorld:
    return MockWorld.from_buffer(shm.buf)


def init_entities(world: MockWorld) -> None:
    world.entity_count = MAX_ENTITIES
    world.local_player_index = 0
    for i in range(MAX_ENTITIES):
        e = world.entities[i]
        e.entity_id = i
        e.pos_x = random.uniform(-500, 500)
        e.pos_y = 0.0
        e.pos_z = random.uniform(-500, 500)
        e.team = 2 if i % 2 == 0 else 3
        e.health = 100.0
        e.alive = 1


def tick(world: MockWorld, t: float) -> None:
    """Simple circular-walk movement so positions visibly change over time."""
    for i in range(world.entity_count):
        e = world.entities[i]
        if not e.alive:
            continue
        radius = 50 + 20 * (i + 1)
        speed = 0.3 + 0.05 * i
        e.pos_x += math.cos(t * speed + i) * 2.0
        e.pos_z += math.sin(t * speed + i) * 2.0
        # Occasionally clip health to simulate combat, never below 0.
        if random.random() < 0.01:
            e.health = max(0.0, e.health - random.uniform(5, 20))
            if e.health <= 0:
                e.alive = 0


def main() -> None:
    size = ctypes_sizeof_world()
    try:
        shm = shared_memory.SharedMemory(name=SHM_NAME, create=True, size=size)
    except FileExistsError:
        # Leftover from a previous unclean shutdown — clean up and retry.
        stale = shared_memory.SharedMemory(name=SHM_NAME, create=False)
        stale.close()
        stale.unlink()
        shm = shared_memory.SharedMemory(name=SHM_NAME, create=True, size=size)

    world = make_world(shm)
    init_entities(world)

    print(f"[mock_game_process] shared memory '{SHM_NAME}' ready "
          f"({size} bytes, {MAX_ENTITIES} entities). Ctrl+C to stop.")

    t = 0.0
    try:
        while True:
            tick(world, t)
            t += 1.0 / TICK_HZ
            time.sleep(1.0 / TICK_HZ)
    except KeyboardInterrupt:
        pass
    finally:
        shm.close()
        shm.unlink()
        print("\n[mock_game_process] shared memory released.")


def ctypes_sizeof_world() -> int:
    import ctypes
    return ctypes.sizeof(MockWorld)


if __name__ == "__main__":
    main()
