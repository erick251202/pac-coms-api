"""
PAC COMS API — FastAPI backend for Render
==========================================
Endpoints
---------
GET  /                  → status
GET  /health            → health check (200 OK) + keep-alive ping
GET  /api/config        → game constants (tile IDs, map size, avatar types)
GET  /api/planets       → list of planets with unlock rules
GET  /api/arena/{planet}/{num}  → procedural arena map (JSON)
GET  /api/leaderboard   → top scores
POST /api/leaderboard   → submit score  { player, score, planet, arena }
GET  /api/sessions      → list open/waiting sessions  [BUG #1 FIX]
POST /api/session       → create/join multiplayer room
POST /api/session/{id}/join → join by session ID     [BUG #2 FIX]
GET  /api/session/{id}  → room state
GET  /api/keepalive     → no-op endpoint for external keep-alive pings  [BUG #3 FIX]
WS   /ws/room/{room_id} → real-time game state sync channel
"""
import os
import uuid
import logging
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from game_config import (
    PLANETS, AVATAR_TYPES, AVATAR_COLORS,
    TILE_EMPTY, TILE_WALL, TILE_PELLET, TILE_POWER, TILE_EXIT,
    MAP_COLS, MAP_ROWS,
)
from arena_generator import get_arena

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="PAC COMS API", version="2.0.0", docs_url="/docs")

# BUG #6 FIX: Accept any *.vercel.app preview URL + main domain
_STATIC_ORIGINS = [
    "https://app.lecoms.com",
    "https://lecoms.com",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
]

CORS_ORIGINS_ENV = os.getenv("CORS_ORIGIN", "https://app.lecoms.com").split(",")

def _origin_allowed(origin: str) -> bool:
    """Allow static origins + *.vercel.app subdomains for preview deploys."""
    if origin in _STATIC_ORIGINS or origin in CORS_ORIGINS_ENV:
        return True
    if origin.endswith(".vercel.app"):
        return True
    if origin.endswith(".lecoms.com"):
        return True
    return False

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """Replace FastAPI's fixed-list CORS with a dynamic allow-all pattern."""
    async def dispatch(self, request: StarletteRequest, call_next):
        origin = request.headers.get("origin", "")
        response = await call_next(request)
        if _origin_allowed(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "*"
        return response

app.add_middleware(DynamicCORSMiddleware)

# Keep legacy CORSMiddleware for OPTIONS preflight handling
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # DynamicCORSMiddleware handles the fine-grained check
    allow_credentials=False,       # must be False when allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory stores ─────────────────────────────────────────────────────────
_leaderboard: list[dict] = []
_sessions:    dict[str, dict] = {}

# Session TTL: clean up sessions older than 20 minutes (BUG #3 FIX)
_SESSION_TTL_MINUTES = 20

def _purge_stale_sessions() -> None:
    """Remove sessions that were created more than SESSION_TTL ago."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_SESSION_TTL_MINUTES)
    to_delete = [
        sid for sid, s in _sessions.items()
        if datetime.fromisoformat(s["created"]) < cutoff
    ]
    for sid in to_delete:
        del _sessions[sid]
        log.info("Purged stale session %s", sid)

# ── Models ────────────────────────────────────────────────────────────────────
class ScoreEntry(BaseModel):
    player:  str
    score:   int
    planet:  str
    arena:   int
    stars:   Optional[int] = 1
    avatar:  Optional[str] = "Classic"

class SessionCreate(BaseModel):
    player_name: str
    planet:      str = "fire"
    arena:       int = 1
    mode:        str = "auto"

class JoinBody(BaseModel):
    player_name: str

# ── Root / health / keep-alive ────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "game": "PAC COMS", "version": "2.0.0", "docs": "/docs"}

@app.get("/health")
def health():
    _purge_stale_sessions()   # opportunistic cleanup on health checks
    return {
        "status":        "healthy",
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "active_sessions": len(_sessions),
        "active_rooms":    len(_ws_rooms),
    }

# BUG #3 FIX: Dedicated keep-alive endpoint for external cron pings
@app.get("/api/keepalive")
def keepalive():
    """
    Lightweight no-op endpoint.
    Ping this every 10 minutes from an external service (UptimeRobot, cron-job.org)
    to prevent Render Free from sleeping and losing session state.
    """
    _purge_stale_sessions()
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}

# ── Config ────────────────────────────────────────────────────────────────────
@app.get("/api/config")
def get_config():
    return {
        "map":    {"cols": MAP_COLS, "rows": MAP_ROWS},
        "tiles":  {
            "empty":  TILE_EMPTY,
            "wall":   TILE_WALL,
            "pellet": TILE_PELLET,
            "power":  TILE_POWER,
            "exit":   TILE_EXIT,
        },
        "avatars":       AVATAR_TYPES,
        "avatar_colors": AVATAR_COLORS,
    }

# ── Planets ───────────────────────────────────────────────────────────────────
@app.get("/api/planets")
def get_planets():
    return {"planets": PLANETS}

# ── Arena map ─────────────────────────────────────────────────────────────────
_VALID_PLANETS = {p["key"] for p in PLANETS}

@app.get("/api/arena/{planet}/{arena_num}")
def get_arena_data(planet: str, arena_num: int):
    if planet not in _VALID_PLANETS:
        raise HTTPException(status_code=404, detail=f"Unknown planet: {planet}")
    if not (1 <= arena_num <= 10):
        raise HTTPException(status_code=400, detail="arena_num must be 1-10")

    try:
        if planet == "fire" and arena_num <= 3:
            import importlib
            mod = importlib.import_module(f"handcrafted.fire_arena{arena_num}")
            arena = type("A", (), {
                "MAP":           mod.MAP,
                "PLAYER_START":  mod.PLAYER_START,
                "PLAYER2_START": getattr(mod, "PLAYER2_START", None),
                "GHOST_STARTS":  mod.GHOST_STARTS,
                "PLANET":        mod.PLANET,
                "ARENA":         mod.ARENA,
            })()
        else:
            arena = get_arena(planet, arena_num)
    except Exception as exc:
        log.warning("Falling back to generator for %s/%s: %s", planet, arena_num, exc)
        arena = get_arena(planet, arena_num)

    log.info("Served arena %s/%s", planet, arena_num)
    return {
        "planet":        arena.PLANET,
        "arena":         arena.ARENA,
        "map":           arena.MAP,
        "player_start":  arena.PLAYER_START,
        "player2_start": getattr(arena, "PLAYER2_START", None),
        "ghost_starts":  arena.GHOST_STARTS,
        "cols":          MAP_COLS,
        "rows":          MAP_ROWS,
    }

# ── Leaderboard ───────────────────────────────────────────────────────────────
@app.get("/api/leaderboard")
def get_leaderboard(limit: int = 20, planet: Optional[str] = None):
    board = _leaderboard
    if planet:
        board = [e for e in board if e["planet"] == planet]
    top = sorted(board, key=lambda e: e["score"], reverse=True)[:limit]
    return {"leaderboard": top, "total": len(board)}

@app.post("/api/leaderboard", status_code=201)
def post_score(entry: ScoreEntry):
    if entry.score < 0:
        raise HTTPException(status_code=400, detail="score must be ≥ 0")
    record = {
        **entry.model_dump(),
        "id":  str(uuid.uuid4())[:8],
        "ts":  datetime.now(timezone.utc).isoformat(),
    }
    _leaderboard.append(record)
    if len(_leaderboard) > 500:
        _leaderboard.sort(key=lambda e: e["score"], reverse=True)
        del _leaderboard[500:]
    log.info("Score submitted: %s %d", entry.player, entry.score)
    return {"ok": True, "id": record["id"]}

# ── Multiplayer sessions ───────────────────────────────────────────────────────

# BUG #1 FIX: GET /api/sessions — list open/waiting sessions
@app.get("/api/sessions")
def list_sessions(
    planet: Optional[str] = Query(None, description="Filter by planet"),
    state:  Optional[str] = Query(None, description="Filter by state (waiting, ready, playing)"),
):
    """
    Returns all sessions matching the optional filters.
    Used by the client matchmaking loop to find an open room to join.
    Previously this endpoint DID NOT EXIST — clients always created new rooms
    and never found each other.
    """
    _purge_stale_sessions()
    results = list(_sessions.values())
    if planet:
        results = [s for s in results if s["planet"] == planet]
    if state:
        results = [s for s in results if s["state"] == state]
    # Return lightweight view (not full map data)
    return [
        {
            "session_id": s["id"],
            "planet":     s["planet"],
            "arena":      s["arena"],
            "players":    s["players"],
            "state":      s["state"],
            "created":    s["created"],
        }
        for s in results
    ]

@app.post("/api/session", status_code=201)
def create_session(body: SessionCreate):
    _purge_stale_sessions()
    sid = str(uuid.uuid4())[:8].upper()
    _sessions[sid] = {
        "id":      sid,
        "planet":  body.planet,
        "arena":   body.arena,
        "mode":    body.mode,
        "players": [body.player_name],
        "state":   "waiting",
        "created": datetime.now(timezone.utc).isoformat(),
    }
    log.info("Session created: %s by %s (mode: %s)", sid, body.player_name, body.mode)
    return {"session_id": sid, "session": _sessions[sid]}

# BUG #2 FIX: Accept player_name both as query param AND as JSON body
@app.post("/api/session/{session_id}/join")
def join_session(
    session_id:  str,
    body:        Optional[JoinBody] = None,
    player_name: Optional[str]      = Query(None),
):
    """
    Join an existing session.
    Accepts player_name either as:
      - JSON body: { "player_name": "..." }
      - Query string: ?player_name=...  (URL-decoded by FastAPI automatically)
    Both methods are supported for backwards compatibility.
    """
    s = _sessions.get(session_id.upper())
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    if s["state"] not in ("waiting",):
        raise HTTPException(status_code=409, detail=f"Session is '{s['state']}', not joinable")
    
    if s["mode"] == "auto" and len(s["players"]) >= 2:
        raise HTTPException(status_code=409, detail="Session full (max 2 players)")

    # Resolve player name: body JSON takes priority, then query param
    name = (body.player_name if body else None) or player_name or "Player"
    # URL-decode in case the client sent an encoded string
    name = urllib.parse.unquote_plus(name)[:24]

    if name not in s["players"]:
        s["players"].append(name)
    
    if s["mode"] == "auto" and len(s["players"]) >= 2:
        s["state"] = "ready"

    log.info("Session %s joined by %s → state=%s", session_id, name, s["state"])
    return {"session": s}

@app.get("/api/session/{session_id}")
def get_session(session_id: str):
    s = _sessions.get(session_id.upper())
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": s}

# Allow players to mark a session as "playing" so it's no longer shown as joinable
@app.post("/api/session/{session_id}/start")
async def start_session(session_id: str):
    s = _sessions.get(session_id.upper())
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    if s["state"] in ("ready", "waiting"):
        s["state"] = "playing"
        await _ws_broadcast(session_id.upper(), None, {"type": "start_game"})
    return {"session": s}

# ── WebSocket rooms (real-time state sync) ─────────────────────────────────────

# room_id → list of connected WebSocket clients
_ws_rooms: dict[str, list[WebSocket]] = {}


@app.websocket("/ws/room/{room_id}")
async def ws_room(websocket: WebSocket, room_id: str):
    """
    Real-time room channel.
    Clients send JSON game state; server broadcasts to all peers in the room.

    Protocol messages (client → server → peers):
      { "type": "pos",      "x": float, "y": float, "dir": int,  "player": 1|2 }
      { "type": "collect",  "tile_x": int, "tile_y": int, "what": str }
      { "type": "death",    "player": 1|2, "lives": int }
      { "type": "win",      "player": 1|2, "score": int }
      { "type": "ping" }        → server echoes { "type": "pong" }
      { "type": "chat",     "msg": str }

    Server → client only:
      { "type": "peer_joined", "peers": int, "player_index": 1|2 }
      { "type": "peer_left",   "peers": int }
      { "type": "pong" }
    """
    await websocket.accept()
    room_id = room_id.upper()
    
    # Check limits if it's an auto mode session
    s = _sessions.get(room_id)
    if s and s["mode"] == "auto":
        if len(_ws_rooms.get(room_id, [])) >= 2:
            await websocket.close(code=1008, reason="Room is full")
            return

    _ws_rooms.setdefault(room_id, []).append(websocket)
    peer_count = len(_ws_rooms[room_id])
    player_index = peer_count   # 1st connection = player 1, 2nd = player 2, 3rd = 3...
    log.info("WS joined room %s  (peers: %d, index: %d)", room_id, peer_count, player_index)

    # Tell the joining client which player index they are
    try:
        await websocket.send_json({
            "type":         "peer_joined",
            "peers":        peer_count,
            "player_index": player_index,
        })
    except Exception:
        pass

    # Notify existing peers someone joined
    await _ws_broadcast(room_id, websocket,
                        {"type": "peer_joined", "peers": peer_count, "player_index": player_index})

    try:
        while True:
            msg = await websocket.receive_json()
            # Handle ping internally — don't broadcast pings
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            await _ws_broadcast(room_id, websocket, msg)
    except WebSocketDisconnect:
        _ws_rooms[room_id].remove(websocket)
        remaining = len(_ws_rooms[room_id])
        log.info("WS left room %s  (peers: %d)", room_id, remaining)
        await _ws_broadcast(room_id, None,
                            {"type": "peer_left", "peers": remaining})
        if not _ws_rooms[room_id]:
            del _ws_rooms[room_id]
            # Mark session as ended if it exists
            if room_id in _sessions:
                _sessions[room_id]["state"] = "ended"


async def _ws_broadcast(room_id: str, sender: WebSocket | None, msg: dict) -> None:
    for peer in list(_ws_rooms.get(room_id, [])):
        if peer is sender:
            continue
        try:
            await peer.send_json(msg)
        except Exception:
            pass
