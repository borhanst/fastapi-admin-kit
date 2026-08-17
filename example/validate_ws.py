"""Validate the realtime notification WebSocket on a live server.

Usage:  python validate_ws.py [base_url] [email] [password]
Example: python validate_ws.py http://127.0.0.1:8080 admin@example.com admin
"""

import asyncio
import re
import sys

import requests
import websockets

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
EMAIL = sys.argv[2] if len(sys.argv) > 2 else "admin@example.com"
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else "admin"
WS_URL = BASE.replace("http://", "ws://").replace("https://", "wss://") + "/api/notifications/ws"

s = requests.Session()

# 1) GET the login page to obtain the CSRF token
r = s.get(f"{BASE}/admin/login", timeout=10)
m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
if not m:
    print("ERROR: csrf_token not found on the login page")
    sys.exit(1)
csrf = m.group(1)

# 2) POST credentials, capture the httponly session cookie
r = s.post(
    f"{BASE}/admin/login",
    data={"username": EMAIL, "password": PASSWORD, "csrf_token": csrf, "next": ""},
    allow_redirects=False,
    timeout=10,
)
cookie = s.cookies.get("admin_session")
print(f"login status={r.status_code}  session_cookie={bool(cookie)}")
if not cookie:
    print("ERROR: login failed — check credentials / CSRF")
    sys.exit(1)


async def probe(label: str, headers: dict | None = None) -> None:
    try:
        ws = await websockets.connect(WS_URL, additional_headers=headers or {}, open_timeout=5)
    except websockets.exceptions.ConnectionClosed as e:
        print(f"{label}: REJECTED during handshake  code={e.code} reason={e.reason!r}")
        return
    except Exception as e:
        print(f"{label}: HANDSHAKE FAILED  {type(e).__name__}: {e}")
        return

    try:
        await asyncio.wait_for(ws.recv(), timeout=2)
        print(f"{label}: OPEN but got a frame")
    except asyncio.TimeoutError:
        print(f"{label}: OK — connection stays OPEN after 2s")
    except websockets.exceptions.ConnectionClosed as e:
        print(f"{label}: closed  code={e.code} reason={e.reason!r}")
    finally:
        await ws.close()


async def main() -> None:
    print(f"\nvalidating {WS_URL}\n")
    # Unauthenticated (no cookie) -> must be rejected with 4401
    await probe("bare /ws (no cookie)")
    # Authenticated (session cookie) -> must stay open
    await probe("bare /ws (+ session cookie)", {"Cookie": f"admin_session={cookie}"})
    # Bypassed user_id -> must be rejected with 4401
    await probe("/ws?user_id=null", {"Cookie": f"admin_session={cookie}"})


asyncio.run(main())
