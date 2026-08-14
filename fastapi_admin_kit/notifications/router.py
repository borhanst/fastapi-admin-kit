"""API routes for the notification system.

Endpoints (mounted at your chosen prefix, e.g. ``/admin/notifications`` or
``/api/notifications``):

- ``POST /send``                 — send a notification
- ``POST /send/batch``           — batch send to many recipients
- ``GET  /``                     — list in-app notifications for current user
- ``GET  /unread-count``         — number of unread in-app notifications
- ``PUT  /{id}/read``            — mark an in-app notification as read
- ``PUT  /preferences``          — update channel preferences
- ``WS   /ws``                   — realtime WebSocket stream
- ``GET  /stream``               — SSE fallback stream
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from fastapi_admin_kit.auth.identity import (
    get_current_user_from_bearer,
    get_current_user_from_cookie,
)
from fastapi_admin_kit.db import get_db_session
from fastapi_admin_kit.notifications.schemas import (
    BatchSendRequest,
    NotificationOut,
    NotificationResult,
    PreferenceUpdate,
    SendRequest,
)
from fastapi_admin_kit.notifications.service import NotificationService

logger = logging.getLogger("fastapi_admin_kit.notifications")

router = APIRouter(tags=["notifications"])


def _service(request: Request) -> NotificationService:
    service = getattr(request.app.state, "notification_service", None)
    if service is None:
        raise HTTPException(
            status_code=500,
            detail="Notification service is not configured.",
        )
    return service


def _session(request: Request, service: NotificationService) -> Any:
    """Resolve a DB session.

    Prefers the admin per-request session (when mounted inside the admin panel);
    falls back to the service's own ``session_factory`` for standalone use.
    """
    try:
        session = get_db_session(request)
        underlying = getattr(session, "session", None)
        if session is not None and underlying is not None:
            return session
    except Exception:
        pass
    if service.session_factory is not None:
        return service.session_factory()
    raise HTTPException(
        status_code=500,
        detail="No database session available — configure session_factory= on the service.",
    )


async def _current_user_id(request: Request) -> str:
    """Resolve the current user id from cookie session or bearer JWT."""
    user = await get_current_user_from_cookie(request)
    if user is None:
        user = await get_current_user_from_bearer(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return str(getattr(user, "id", user))


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------


@router.post("/send", response_model=NotificationResult)
async def send_notification(request: Request, body: SendRequest) -> Any:
    """Send a notification to a user via the requested channels."""
    service = _service(request)
    session = _session(request, service)
    result = await service.notify(
        body.user_id,
        body.message,
        channels=body.channels,
        title=body.title,
        template=body.template,
        context=body.context,
        data=body.data,
        email=body.email,
        phone=body.phone,
        session=session,
    )
    return NotificationResult(
        user_id=result.user_id,
        notification_id=result.notification_id,
        channels=[
            {
                "channel": c.channel,
                "provider": c.provider,
                "success": c.success,
                "message_id": c.message_id,
                "error": c.error,
            }
            for c in result.channels
        ],
    )


@router.post("/send/batch", response_model=list[NotificationResult])
async def send_batch(request: Request, body: BatchSendRequest) -> Any:
    """Send a notification to many recipients in one call."""
    service = _service(request)
    session = _session(request, service)
    results = await service.notify_many(
        body.recipients,
        body.message,
        channels=body.channels,
        title=body.title,
        template=body.template,
        context=body.context,
        data=body.data,
        session=session,
    )
    return [
        {
            "user_id": r.user_id,
            "notification_id": r.notification_id,
            "channels": [
                {
                    "channel": c.channel,
                    "provider": c.provider,
                    "success": c.success,
                    "message_id": c.message_id,
                    "error": c.error,
                }
                for c in r.channels
            ],
        }
        for r in results
    ]


# ---------------------------------------------------------------------------
# In-app list / read
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[NotificationOut])
async def list_notifications(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    unread_only: bool = Query(default=False),
) -> Any:
    """List in-app notifications for the current user."""
    user_id = await _current_user_id(request)
    service = _service(request)
    session = _session(request, service)
    rows = await service.list_notifications(
        user_id,
        limit=limit,
        offset=offset,
        unread_only=unread_only,
        session=session,
    )
    return [_serialize(n) for n in rows]


@router.get("/unread-count")
async def unread_count(request: Request) -> dict[str, int]:
    """Return the number of unread in-app notifications for the current user."""
    user_id = await _current_user_id(request)
    service = _service(request)
    session = _session(request, service)
    return {"count": await service.unread_count(user_id, session=session)}


@router.put("/{notification_id}/read")
async def mark_read(request: Request, notification_id: int) -> dict[str, bool]:
    """Mark an in-app notification as read."""
    user_id = await _current_user_id(request)
    service = _service(request)
    session = _session(request, service)
    ok = await service.mark_read(notification_id, user_id, session=session)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return {"success": True}


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------


@router.put("/preferences")
async def update_preferences(request: Request, body: PreferenceUpdate) -> dict[str, str | bool]:
    """Opt the current user in/out of a notification channel."""
    user_id = await _current_user_id(request)
    service = _service(request)
    session = _session(request, service)
    await service.set_preference(user_id, body.channel, body.enabled, session=session)
    return {"channel": body.channel, "enabled": body.enabled}


@router.get("/preferences")
async def get_preferences(request: Request) -> dict[str, bool]:
    """Return channel preferences for the current user."""
    user_id = await _current_user_id(request)
    service = _service(request)
    session = _session(request, service)
    return await service.get_preferences(user_id, session=session)


# ---------------------------------------------------------------------------
# Realtime — WebSocket + SSE
# ---------------------------------------------------------------------------


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, user_id: str | None = None) -> None:
    """Realtime notification stream over WebSocket.

    The user may be identified via a ``user_id`` query parameter or (fallback)
    ``?token=<jwt>``.  When neither is provided the endpoint accepts the
    connection but delivers nothing (safe fallback).
    """
    hub = _hub(websocket)
    if user_id is None:
        token = websocket.query_params.get("token")
        if token:
            try:
                from fastapi_admin_kit.api.auth import _get_secret_key, decode_access_token

                secret_key = _get_secret_key(websocket)
                payload = decode_access_token(token, secret_key)
                if payload:
                    user_id = str(payload.get("sub"))
            except Exception:
                user_id = None
        else:
            cookie_user = await _current_user_from_ws_cookie(websocket)
            user_id = str(getattr(cookie_user, "id", cookie_user)) if cookie_user else None

    await websocket.accept()
    if not user_id:
        await websocket.close(code=4401, reason="Unauthenticated")
        return

    hub.connect_ws(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # keep-alive + ping from client
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("WebSocket error for user %s", user_id, exc_info=True)
    finally:
        hub.disconnect_ws(user_id, websocket)


async def _current_user_from_ws_cookie(websocket: WebSocket) -> Any:
    """Resolve the current user from the session cookie on a WebSocket.

    WebSocket scopes are not HTTP scopes, so we decode the signed session
    cookie directly from ``websocket.cookies`` and load the user via the
    configured auth backend — without constructing an HTTP ``Request``
    (``Starlette.Request`` asserts ``scope["type"] == "http"`` and rejects
    WebSocket scopes with an exception that surfaces as a 403).
    """
    app = websocket.app
    session_backend = getattr(app.state, "admin_session_backend", None)
    if session_backend is None:
        return None
    cookie_name = getattr(session_backend, "cookie_name", "admin_session")
    token = websocket.cookies.get(cookie_name)
    payload = session_backend.decode(token)
    if not payload:
        return None
    user_id = payload.get("user_id")
    if user_id is None:
        return None

    auth_backend = getattr(app.state, "admin_auth_backend", None)
    if auth_backend is None:
        return None

    session = None
    try:
        service = getattr(app.state, "notification_service", None)
        if service is not None and service.session_factory is not None:
            session = service.session_factory()
        else:
            session = getattr(app.state, "admin_db_session", None)
        if session is None or not hasattr(session, "execute"):
            return None
        user = await auth_backend.get_user(user_id, session)
        if user is None or not getattr(user, "is_active", False):
            return None
        return user
    finally:
        if session is not None and hasattr(session, "close"):
            result = session.close()
            if hasattr(result, "__await__"):
                await result


def _hub(websocket: WebSocket) -> Any:
    service = getattr(websocket.app.state, "notification_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Notification service is not configured.")
    return service.hub


@router.get("/stream")
async def sse_stream(request: Request, user_id: str | None = None) -> StreamingResponse:
    """SSE fallback stream for realtime notifications.

    Clients with no WebSocket support can connect here and receive Server-Sent
    Events.  Connection drops are handled by the client reconnecting.
    """
    if user_id is None:
        from fastapi_admin_kit.auth.identity import (
            get_current_user_from_bearer,
            get_current_user_from_cookie,
        )

        user = await get_current_user_from_cookie(request)
        if user is None:
            user = await get_current_user_from_bearer(request)
        if user is None:
            raise HTTPException(status_code=401, detail="Not authenticated.")
        user_id = str(getattr(user, "id", user))

    hub = _hub_for_request(request)
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    async def event_source():
        hub.connect_sse(user_id, queue)
        try:
            yield ": connected\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(payload, default=str)}\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            hub.disconnect_sse(user_id, queue)

    return StreamingResponse(event_source(), media_type="text/event-stream")


def _hub_for_request(request: Request) -> Any:
    service = getattr(request.app.state, "notification_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Notification service is not configured.")
    return service.hub


def _serialize(n: Any) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        title=n.title,
        body=n.body,
        channels=n.channels or [],
        data=n.data,
        status=n.status,
        is_read=bool(n.is_read),
        created_at=n.created_at.isoformat() if n.created_at else None,
    )
