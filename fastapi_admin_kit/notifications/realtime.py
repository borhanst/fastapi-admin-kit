"""Realtime in-app notification delivery hub.

Manages per-user WebSocket and SSE connections so new notifications are pushed
to connected clients instantly (no polling).  Supports:

- WebSocket connections (``WS /notifications/ws``)
- SSE fallback streams (``GET /notifications/stream``)
- Fallback hop: publish() never raises — a slow/broken connection is dropped
  and delivery continues to the remaining connections for that user.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger("fastapi_admin_kit.notifications")

_HEARTBEAT_INTERVAL = 30.0


class RealtimeNotificationHub:
    """In-memory hub of per-user notification subscribers.

    Connections are keyed by ``str(user_id)``.  For WebSockets we keep the
    raw ``WebSocket`` objects (Starlette/ToughWebSocket compatible); for SSE
    we keep ``asyncio.Queue`` objects that the SSE endpoint drains.
    """

    def __init__(self, heartbeat_interval: float = _HEARTBEAT_INTERVAL) -> None:
        self._ws: dict[str, set[Any]] = {}
        self._sse: dict[str, set[asyncio.Queue]] = {}
        self._last_active: dict[str, float] = {}
        self.heartbeat_interval = heartbeat_interval

    # -- connection management -------------------------------------------------

    def connect_ws(self, user_id: str | int, websocket: Any) -> None:
        key = str(user_id)
        self._ws.setdefault(key, set()).add(websocket)
        self._last_active[key] = time.monotonic()

    def disconnect_ws(self, user_id: str | int, websocket: Any) -> None:
        key = str(user_id)
        conns = self._ws.get(key)
        if conns is None:
            return
        conns.discard(websocket)
        if not conns:
            self._ws.pop(key, None)
            self._last_active.pop(key, None)

    def connect_sse(self, user_id: str | int, queue: asyncio.Queue) -> None:
        key = str(user_id)
        self._sse.setdefault(key, set()).add(queue)
        self._last_active[key] = time.monotonic()

    def disconnect_sse(self, user_id: str | int, queue: asyncio.Queue) -> None:
        key = str(user_id)
        queues = self._sse.get(key)
        if queues is None:
            return
        queues.discard(queue)
        if not queues:
            self._sse.pop(key, None)
            self._last_active.pop(key, None)

    def connection_count(self, user_id: str | int) -> int:
        key = str(user_id)
        ws = len(self._ws.get(key, set()))
        sse = len(self._sse.get(key, set()))
        return ws + sse

    # -- publish ---------------------------------------------------------------

    async def publish(self, user_id: str | int, payload: dict[str, Any]) -> int:
        """Push *payload* (JSON-serialisable) to every subscriber of *user_id*.

        Returns the number of connections the message was delivered to.
        """
        key = str(user_id)
        delivered = 0

        for ws in list(self._ws.get(key, ())):
            try:
                await ws.send_text(json.dumps(payload, default=str))
                delivered += 1
                self._last_active[key] = time.monotonic()
            except Exception:
                logger.debug("Dropping dead WebSocket for user %s", key, exc_info=True)
                self.disconnect_ws(key, ws)

        for queue in list(self._sse.get(key, ())):
            try:
                queue.put_nowait(payload)
                delivered += 1
            except asyncio.QueueFull:
                queue.get_nowait()  # drop oldest so we never block publishers
                queue.put_nowait(payload)
            except Exception:
                self.disconnect_sse(key, queue)

        return delivered

    # -- heartbeat / liveness --------------------------------------------------

    def is_connected(self, user_id: str | int) -> bool:
        key = str(user_id)
        return key in self._ws or key in self._sse

    def prune_stale(self, max_idle: float = _HEARTBEAT_INTERVAL * 3) -> int:
        """Remove connections idle longer than *max_idle* seconds.

        Intended to be called from a background task; returns the number of
        connections pruned.
        """
        now = time.monotonic()
        pruned = 0
        for key, last in list(self._last_active.items()):
            if now - last > max_idle:
                for ws in list(self._ws.get(key, ())):
                    try:
                        asyncio.get_running_loop().create_task(ws.close())
                    except Exception:
                        pass
                    pruned += 1
                self._ws.pop(key, None)
                for queue in list(self._sse.get(key, ())):
                    queue.put_nowait({"type": "close"})
                    pruned += 1
                self._sse.pop(key, None)
                self._last_active.pop(key, None)
        return pruned
