import asyncio
import httpx
import websockets
import json

API_URL = "https://pac-coms-api.onrender.com"
WS_URL = "wss://pac-coms-api.onrender.com/ws/room/"

async def test_multiplayer():
    print("--- Starting Multiplayer Flow Test ---")
    
    async with httpx.AsyncClient() as client:
        # 1. Check keepalive (Bug 3)
        res = await client.get(f"{API_URL}/api/keepalive")
        print(f"Keepalive status: {res.status_code}")
        assert res.status_code == 200
        
        # 2. Check /api/sessions before (Bug 1)
        res = await client.get(f"{API_URL}/api/sessions")
        print(f"Initial sessions: {res.json()}")
        assert isinstance(res.json(), list)
        
        # 3. Create session (Player A)
        res = await client.post(f"{API_URL}/api/session", json={"player_name": "Alice", "planet": "fire", "arena": 1})
        print(f"Create session status: {res.status_code}")
        assert res.status_code == 201
        data = res.json()
        session_id = data["session_id"]
        print(f"Session ID: {session_id}")
        
        # 4. List sessions again, should see it (Bug 1)
        res = await client.get(f"{API_URL}/api/sessions?state=waiting")
        sessions = res.json()
        print(f"Sessions waiting: {sessions}")
        assert len([s for s in sessions if s["session_id"] == session_id]) == 1
        
        # 5. Join session (Player B) (Bug 2)
        res = await client.post(f"{API_URL}/api/session/{session_id}/join?player_name=Bob%20Space")
        print(f"Join session status: {res.status_code}")
        assert res.status_code == 200
        session = res.json()["session"]
        print(f"Session state after join: {session}")
        assert "Bob Space" in session["players"]
        assert session["state"] == "ready"

    # 6. Test WebSocket Sync (Bug 4)
    print("\n--- Testing WebSocket Real-Time Sync ---")
    async with websockets.connect(f"{WS_URL}{session_id}") as ws_alice:
        # Receive join message for Alice
        msg = await asyncio.wait_for(ws_alice.recv(), timeout=2.0)
        print(f"Alice received: {msg}")
        
        async with websockets.connect(f"{WS_URL}{session_id}") as ws_bob:
            # Bob receives his join message
            msg = await asyncio.wait_for(ws_bob.recv(), timeout=2.0)
            print(f"Bob received: {msg}")
            
            # Alice receives Bob's join message
            msg = await asyncio.wait_for(ws_alice.recv(), timeout=2.0)
            print(f"Alice received: {msg}")
            
            # Alice sends position
            pos_msg = {"type": "pos", "x": 100.5, "y": 200.5, "dir": 1, "player": 1}
            await ws_alice.send(json.dumps(pos_msg))
            print(f"Alice sent: {pos_msg}")
            
            # Bob should receive it
            msg = await asyncio.wait_for(ws_bob.recv(), timeout=2.0)
            print(f"Bob received: {msg}")
            recv_pos = json.loads(msg)
            assert recv_pos["type"] == "pos"
            assert recv_pos["x"] == 100.5
            
            # Bob sends collect
            collect_msg = {"type": "collect", "tile_x": 5, "tile_y": 5, "what": "pellet"}
            await ws_bob.send(json.dumps(collect_msg))
            print(f"Bob sent: {collect_msg}")
            
            # Alice should receive it
            msg = await asyncio.wait_for(ws_alice.recv(), timeout=2.0)
            print(f"Alice received: {msg}")
            recv_coll = json.loads(msg)
            assert recv_coll["type"] == "collect"
            assert recv_coll["tile_x"] == 5
            
    print("\nALL MULTIPLAYER TESTS PASSED SUCCESSFULLY! ✅")

if __name__ == "__main__":
    asyncio.run(test_multiplayer())
