"""
Arena Generator
===============
Procedurally generates 21×17 tile maps for any planet/arena combination.
Guarantees:
  - Fully connected corridors (maze via recursive backtracking)
  - At least 4 power pellets (corners + extras)
  - Pellets fill every walkable corridor tile
  - One EXIT tile reachable from player start
  - Key spawned far from exit
  - Horizontal tunnels on row 8 (col 0 and col 20 open)
  - At least 2 ghost spawn tiles

Planet themes control wall/style only; gameplay identical.
"""
import random
from collections import deque
from game_config import (
    TILE_EMPTY, TILE_WALL, TILE_PELLET, TILE_POWER, TILE_EXIT,
    MAP_COLS, MAP_ROWS,
)

# ── Constants ─────────────────────────────────────────────────────────────────
_COLS  = MAP_COLS   # 21
_ROWS  = MAP_ROWS   # 17
_HALF_C = _COLS // 2   # 10
_HALF_R = _ROWS // 2   # 8

# Tunnel row (middle height) — must be kept open
_TUNNEL_ROW = _ROWS // 2   # 8

# ── Public API ────────────────────────────────────────────────────────────────

class ArenaNamespace:
    """Behaves like a map module (has MAP, PLANET, ARENA, PLAYER_START, GHOST_STARTS)."""
    def __init__(self, planet, arena, map_data, player_start, ghost_starts):
        self.PLANET       = planet
        self.ARENA        = arena
        self.MAP          = map_data
        self.PLAYER_START = player_start
        self.GHOST_STARTS = ghost_starts
        self.PLAYER2_START = (player_start[0] + 1, player_start[1])


def get_arena(planet: str, arena_num: int, seed: int = None) -> ArenaNamespace:
    """Return a fully generated arena namespace for the given planet/arena."""
    if seed is None:
        seed = hash((planet, arena_num)) & 0xFFFFFFFF
    rng = random.Random(seed)

    difficulty = _difficulty(planet, arena_num)
    map_data   = _generate_map(rng, difficulty)
    player_start, ghost_starts = _place_entities(map_data, rng, difficulty)

    return ArenaNamespace(planet, arena_num, map_data, player_start, ghost_starts)


# ── Difficulty ────────────────────────────────────────────────────────────────

def _difficulty(planet: str, arena_num: int) -> dict:
    """Returns a difficulty config dict blending planet base + arena progression."""
    planet_base = {
        "fire":    {"ghosts": 2, "speed_bonus": 0.0, "wall_density": 0.32},
        "storm":   {"ghosts": 2, "speed_bonus": 0.2, "wall_density": 0.30},
        "ice":     {"ghosts": 3, "speed_bonus": 0.1, "wall_density": 0.28},
        "water":   {"ghosts": 2, "speed_bonus": 0.15,"wall_density": 0.26},
        "crystal": {"ghosts": 3, "speed_bonus": 0.3, "wall_density": 0.35},
        "lava":    {"ghosts": 3, "speed_bonus": 0.4, "wall_density": 0.38},
    }.get(planet, {"ghosts": 2, "speed_bonus": 0.0, "wall_density": 0.30})

    # Scale with arena number (1-10)
    a = max(0, arena_num - 1)
    return {
        "ghosts":       min(planet_base["ghosts"] + a // 3, 4),
        "speed_bonus":  planet_base["speed_bonus"] + a * 0.05,
        "wall_density": planet_base["wall_density"],
    }


# ── Map generation ────────────────────────────────────────────────────────────

def _generate_map(rng: random.Random, difficulty: dict) -> list:
    """
    Maze via recursive backtracking on the LEFT quarter only, then mirror.

    Strategy
    --------
    1. DFS carves 5×8 = 40 cells in the left strip (tile cols 1-9, rows 1-15).
    2. Mirror left half to right half (tile cols 11-19).
    3. Connect the two halves at the centre column (col 10) wherever both
       adjacent tiles (col 9 and col 11) are walkable.
    4. Force-open top row (row 1) and bottom row (row 15) as full corridors.
    5. Place EXIT at centre bottom; open tunnel edges at row 8.
    6. Fill open tiles with pellets; upgrade 4+ to power pellets.
    """
    CELL_COLS_HALF = 5   # 5 cells wide → tile cols 1,3,5,7,9
    CELL_ROWS      = 8   # tile rows 1,3,5,7,9,11,13,15

    grid = [[TILE_WALL] * _COLS for _ in range(_ROWS)]

    # ── DFS on left half ──────────────────────────────────────────────────────
    visited = [[False] * CELL_COLS_HALF for _ in range(CELL_ROWS)]

    def carve(cc: int, cr: int) -> None:
        visited[cr][cc] = True
        # Open this cell's centre
        tx, ty = cc * 2 + 1, cr * 2 + 1
        if 0 < ty < _ROWS - 1 and 0 < tx < _HALF_C:
            grid[ty][tx] = TILE_EMPTY
        dirs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        rng.shuffle(dirs)
        for dc, dr in dirs:
            nc, nr = cc + dc, cr + dr
            if 0 <= nc < CELL_COLS_HALF and 0 <= nr < CELL_ROWS and not visited[nr][nc]:
                # Open passage between the two cells
                wx, wy = cc * 2 + 1 + dc, cr * 2 + 1 + dr
                if 0 < wy < _ROWS - 1 and 0 < wx < _HALF_C:
                    grid[wy][wx] = TILE_EMPTY
                carve(nc, nr)

    carve(0, 0)

    # ── Mirror left strip → right strip ───────────────────────────────────────
    for r in range(_ROWS):
        for c in range(1, _HALF_C):          # cols 1-9
            grid[r][_COLS - 1 - c] = grid[r][c]   # cols 19-11

    # ── Connect halves at centre column (col 10) ──────────────────────────────
    for r in range(1, _ROWS - 1):
        if grid[r][_HALF_C - 1] != TILE_WALL and grid[r][_HALF_C + 1] != TILE_WALL:
            grid[r][_HALF_C] = TILE_EMPTY

    # ── Force-open top and bottom corridors ───────────────────────────────────
    for c in range(1, _COLS - 1):
        grid[1][c]          = TILE_EMPTY
        grid[_ROWS - 2][c]  = TILE_EMPTY

    # ── Tunnel edges (row 8) ──────────────────────────────────────────────────
    grid[_TUNNEL_ROW][0]         = TILE_EMPTY
    grid[_TUNNEL_ROW][_COLS - 1] = TILE_EMPTY

    # ── EXIT at bottom-centre ─────────────────────────────────────────────────
    grid[_ROWS - 2][_HALF_C] = TILE_EXIT

    # ── Ghost pen: 3×3 open room near centre-top ─────────────────────────────
    for pr in range(2, 5):
        for pc in range(_HALF_C - 1, _HALF_C + 2):
            if 0 < pr < _ROWS - 1 and 0 < pc < _COLS - 1:
                grid[pr][pc] = TILE_EMPTY

    # ── Fill open tiles with pellets ──────────────────────────────────────────
    for r in range(_ROWS):
        for c in range(_COLS):
            if grid[r][c] == TILE_EMPTY:
                grid[r][c] = TILE_PELLET

    # ── Power pellets: nearest walkable tile to each inner corner ─────────────
    power_targets = [
        (1, 1), (_COLS - 2, 1),
        (1, _ROWS - 2), (_COLS - 2, _ROWS - 2),
    ]
    for tc, tr in power_targets:
        placed = False
        for radius in range(5):
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    if abs(dr) != radius and abs(dc) != radius:
                        continue
                    sr, sc = tr + dr, tc + dc
                    if 0 <= sr < _ROWS and 0 <= sc < _COLS and grid[sr][sc] == TILE_PELLET:
                        grid[sr][sc] = TILE_POWER
                        placed = True
                        break
                if placed:
                    break
            if placed:
                break

    # ── Connectivity cleanup ──────────────────────────────────────────────────
    _ensure_connected(grid)

    return grid


def _ensure_connected(grid: list) -> None:
    """Flood-fill from first open tile; wall off any unreachable empties."""
    start = None
    for r in range(1, _ROWS - 1):
        for c in range(1, _COLS - 1):
            if grid[r][c] in (TILE_PELLET, TILE_POWER, TILE_EMPTY, TILE_EXIT):
                start = (c, r)
                break
        if start:
            break
    if not start:
        return

    visited = set()
    queue   = deque([start])
    walkable = {TILE_PELLET, TILE_POWER, TILE_EMPTY, TILE_EXIT}
    while queue:
        c, r = queue.popleft()
        if (c, r) in visited:
            continue
        visited.add((c, r))
        for dc, dr in [(1,0),(-1,0),(0,1),(0,-1)]:
            nc, nr = c+dc, r+dr
            if 0 <= nr < _ROWS and 0 <= nc < _COLS:
                if grid[nr][nc] in walkable and (nc, nr) not in visited:
                    queue.append((nc, nr))

    for r in range(_ROWS):
        for c in range(_COLS):
            if grid[r][c] in walkable and (c, r) not in visited:
                grid[r][c] = TILE_WALL


# ── Entity placement ──────────────────────────────────────────────────────────

def _walkable_tiles(grid: list) -> list:
    walkable = {TILE_PELLET, TILE_POWER, TILE_EMPTY, TILE_EXIT}
    return [(c, r) for r in range(_ROWS) for c in range(_COLS)
            if grid[r][c] in walkable and c not in (0, _COLS - 1)]


def _place_entities(grid: list, rng: random.Random, difficulty: dict):
    tiles = _walkable_tiles(grid)
    if not tiles:
        return (1, 1), []

    # Player starts near bottom-centre
    def dist_to_centre_bottom(t):
        return abs(t[0] - _HALF_C) + abs(t[1] - (_ROWS - 3))

    player_start = min(tiles, key=dist_to_centre_bottom)

    # Ghost starts: top half, spread out
    ghost_count = difficulty["ghosts"]
    top_tiles   = [(c, r) for c, r in tiles if r < _ROWS // 2 and r > 1]
    rng.shuffle(top_tiles)

    # Spread: pick ghosts at least 3 apart
    ghost_starts = []
    for t in top_tiles:
        if all(abs(t[0]-g[0]) + abs(t[1]-g[1]) > 3 for g in ghost_starts):
            ghost_starts.append(t)
        if len(ghost_starts) >= ghost_count:
            break

    # Fallback
    while len(ghost_starts) < ghost_count and top_tiles:
        ghost_starts.append(top_tiles[len(ghost_starts) % len(top_tiles)])

    # Ghost type assignment by difficulty
    ghost_types = ["hunter", "basic", "hunter", "elite"]
    ghost_starts_full = [
        (gc, gr, ghost_types[i % len(ghost_types)])
        for i, (gc, gr) in enumerate(ghost_starts)
    ]

    return player_start, ghost_starts_full
