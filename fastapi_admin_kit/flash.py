"""Flash message helpers for the admin UI.

Stored in a signed session cookie so they survive exactly one redirect-safe read.
"""

from __future__ import annotations

from fastapi import Request

SESSION_KEY = "admin_flash"


async def add_flash(request: Request, level: str, message: str) -> None:
    session_backend = request.app.state.admin_session_backend
    cookie_name = getattr(session_backend, "cookie_name", "admin_session")
    data: dict[str, list[dict[str, str]]] | None = None
    raw = request.cookies.get(cookie_name)
    if raw and hasattr(session_backend, "load"):
        loaded = session_backend.load(raw)
        if isinstance(loaded, dict):
            data = loaded
    if data is None:
        data = {}
    data.setdefault(SESSION_KEY, []).append({"level": level, "text": message})
    if hasattr(session_backend, "save"):
        from starlette.responses import Response

        response = Response()
        session_backend.save(response, data)


async def get_flash_messages(request: Request) -> list[dict[str, str]]:
    session_backend = request.app.state.admin_session_backend
    cookie_name = getattr(session_backend, "cookie_name", "admin_session")
    raw = request.cookies.get(cookie_name)
    if not raw or not hasattr(session_backend, "load"):
        return []
    data = session_backend.load(raw)
    if not isinstance(data, dict):
        return []
    messages = data.pop(SESSION_KEY, []) if SESSION_KEY in data else []
    if hasattr(session_backend, "save"):
        from starlette.responses import Response

        response = Response()
        session_backend.save(response, data)
    return messages
