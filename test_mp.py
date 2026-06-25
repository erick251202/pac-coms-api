import asyncio
import json
import uuid

# Start API in background, then run this to test
import urllib.request

API = "http://127.0.0.1:8000"

def test():
    # Create room
    req = urllib.request.Request(f"{API}/api/session", data=json.dumps({
        "player_name": "P1", "planet": "fire", "arena": 1, "mode": "auto"
    }).encode(), headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req).read().decode())
    sid = resp["session_id"]
    print(f"Room created: {sid}")

    # List open rooms
    resp2 = json.loads(urllib.request.urlopen(f"{API}/api/sessions?state=waiting").read().decode())
    print("Waiting rooms:", resp2)

    # Join room
    req3 = urllib.request.Request(f"{API}/api/session/{sid}/join", data=json.dumps({
        "player_name": "P2"
    }).encode(), headers={"Content-Type": "application/json"})
    resp3 = json.loads(urllib.request.urlopen(req3).read().decode())
    print("Joined room, state:", resp3["session"]["state"])

if __name__ == "__main__":
    test()
