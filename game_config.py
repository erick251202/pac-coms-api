# Tile constants (no pygame dependency)
TILE_EMPTY  = 0
TILE_WALL   = 1
TILE_PELLET = 2
TILE_POWER  = 3
TILE_EXIT   = 4

MAP_COLS = 21
MAP_ROWS = 17

PLANETS = [
    {"key": "fire",    "name": "Planet Fire",    "color": [220, 80,  20],  "locked_after": None,          "arenas": 10},
    {"key": "storm",   "name": "Planet Storm",   "color": [80,  80,  220], "locked_after": ["fire",    3], "arenas": 10},
    {"key": "ice",     "name": "Planet Ice",     "color": [80,  200, 240], "locked_after": ["storm",   3], "arenas": 10},
    {"key": "water",   "name": "Planet Water",   "color": [0,   120, 220], "locked_after": ["ice",     3], "arenas": 10},
    {"key": "crystal", "name": "Planet Crystal", "color": [180, 60,  255], "locked_after": ["water",   3], "arenas": 10},
    {"key": "lava",    "name": "Planet Lava",    "color": [255, 80,   0],  "locked_after": ["crystal", 3], "arenas": 10},
]

AVATAR_TYPES = {
    "Classic": {"speed_mult": 1.00, "lives_bonus": 0, "desc": "Balanced all-rounder."},
    "Heavy":   {"speed_mult": 0.80, "lives_bonus": 1, "desc": "Tougher but slower."},
    "Speed":   {"speed_mult": 1.35, "lives_bonus": 0, "desc": "Lightning fast, fragile."},
}

AVATAR_COLORS = {
    "yellow": [255, 220,   0],
    "red":    [220,  50,  50],
    "blue":   [ 50, 100, 220],
    "green":  [ 50, 200,  80],
    "purple": [150,  50, 220],
}
