# Mock Memory-Reading / W2S Simulation

Fully self-contained, two-process simulation for learning the mechanics of
external memory reading and World-to-Screen (W2S) coordinate transforms —
without touching any real game.

- `shared_layout.py` — the struct layout (`MockEntity` / `MockWorld`), shared
  by both processes. This plays the role that reverse-engineered game struct
  offsets play in the real thing, except here we define the layout ourselves.
- `mock_game_process.py` — a stand-in "game": owns a block of shared memory,
  spawns 8 entities, and moves them every tick, the same way a real game
  continuously updates its entity list every frame.
- `external_reader.py` — the analysis tool: attaches to the mock process's
  shared memory (the cross-platform, permission-safe equivalent of
  `pymem`/`ReadProcessMemory` attaching to another process), parses the raw
  bytes back into `MockWorld`, and renders two tkinter panels:
  - a top-down **radar** (world x/z mapped directly to canvas coordinates)
  - a **camera view** panel showing entities projected through a hand-built
    view + perspective matrix (`world_to_screen`), the same clip-space →
    NDC → pixel math a real W2S implementation uses, just with our own
    camera and matrix code instead of a captured engine matrix.

## Running it

No third-party packages needed (see `requirements.txt`) — everything is
standard library.

Needs a Python built with Tk support. On Windows, the official python.org
installer bundles Tcl/Tk, so this works out of the box; on macOS, Homebrew's
`python3` often lacks Tk (`/usr/bin/python3` usually has it instead).

```bash
# terminal 1 (Windows: py mock_game_process.py)
python3 mock_game_process.py

# terminal 2 (Windows: py external_reader.py)
python3 external_reader.py
```

Close the tkinter window or Ctrl+C either process to stop; `mock_game_process.py`
releases the shared memory segment on exit.

## Scope, deliberately

This covers memory-layout parsing, coordinate math, and external rendering.
It does **not** include target-locking/aim math or input automation, and it
does not attach to or read any real application's memory — there is nothing
here to point at a live game.
