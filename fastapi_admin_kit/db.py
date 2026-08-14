"""Per-request database session management.

Replaces the single shared ``AsyncSession`` on ``app.state`` with a
``sessionmaker`` factory and ASGI middleware that creates + tears down
a fresh session for every incoming request.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request


def create_session_factory(
    engine: Any,
) -> async_sessionmaker[AsyncSession]:
    """Create an ``async_sessionmaker`` bound to *engine*."""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


def _wrap_session(session: Any) -> Any:
    """Wrap a raw session in ``SqlAlchemySessionAdapter``."""
    from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemySessionAdapter

    return SqlAlchemySessionAdapter(session)


def get_db_session(request: Request) -> Any:
    """Return the per-request ``SqlAlchemySessionAdapter`` (implements ``SessionBackend``).

    The session is created by :class:`SessionMiddleware` and stored on
    ``scope["state"]["admin_db_session"]``.  ``scope["state"]`` may be a plain
    ``dict`` (uvicorn/Starlette) or a Starlette ``State`` object, so we read it
    via ``.get(...)`` which works for both.  Falls back to the legacy
    ``app.state.admin_db_session`` when the middleware is not active.
    """
    from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemySessionAdapter

    state = request.state
    session = (
        state.get("admin_db_session")
        if hasattr(state, "get")
        else getattr(state, "admin_db_session", None)
    )
    if session is not None:
        if isinstance(session, SqlAlchemySessionAdapter):
            return session
        return _wrap_session(session)
    real_app = getattr(request.scope, "app", None) or request.app
    legacy = getattr(real_app.state, "admin_db_session", None)
    if legacy is not None:
        if isinstance(legacy, SqlAlchemySessionAdapter):
            return legacy
        return _wrap_session(legacy)
    return _wrap_session(legacy)  # type: ignore[arg-type]


class SessionMiddleware:
    """Pure ASGI middleware — one session per request, one commit or rollback.

    The session factory is read from ``app.state.admin_session_factory``
    at request time (it is not available when middleware is registered).
    On success the session is committed.  On exception it is rolled back.
    The session is always closed when the request completes.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Ensure the per-request ``state`` mapping exists on the scope. Starlette
        # only lazily creates ``scope["state"]`` when a Request object is built
        # (which happens *after* this middleware runs), and in some ASGI servers
        # ``scope["state"]`` is a plain ``dict`` rather than a ``State``. Use
        # dict-item assignment below so it works either way.
        state = scope.setdefault("state", {})  # type: ignore[assignment]
        factory = getattr(state, "admin_session_factory", None)
        if factory is None:
            real_app = scope.get("app")
            if real_app is not None:
                factory = getattr(real_app.state, "admin_session_factory", None)
        if factory is None:
            app_state = getattr(self.app, "state", None)
            if app_state is not None:
                factory = getattr(app_state, "admin_session_factory", None)
        if factory is None:
            # No session factory configured — pass through without managing a session.
            await self.app(scope, receive, send)
            return

        session = factory()
        state["admin_db_session"] = session  # type: ignore[index]
        try:
            await self.app(scope, receive, send)
        except Exception:
            if hasattr(session, "rollback"):
                result = session.rollback()
                if hasattr(result, "__await__"):
                    await result
            raise
        else:
            if hasattr(session, "commit"):
                try:
                    result = session.commit()
                    if hasattr(result, "__await__"):
                        await result
                except Exception:
                    if hasattr(session, "rollback"):
                        result = session.rollback()
                        if hasattr(result, "__await__"):
                            await result
        finally:
            if hasattr(session, "close"):
                result = session.close()
                if hasattr(result, "__await__"):
                    await result


class SyncSessionWrapper:
    """Wraps a sync SQLAlchemy Session to provide an async-compatible interface.

    Also implements :class:`SessionBackend` (via ``SqlAlchemySessionAdapter``).
    """

    def __init__(self, session: Any) -> None:
        self._session = session
        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemySessionAdapter

        self._adapter = SqlAlchemySessionAdapter(session)

    @property
    def adapter(self) -> Any:
        return self._adapter

    def get(self, model: type, pk: Any) -> Any | None:
        return self._adapter.get(model, pk)

    def add(self, obj: Any) -> None:
        self._adapter.add(obj)

    def flush(self) -> None:
        self._adapter.flush()

    def delete(self, obj: Any) -> None:
        self._adapter.delete(obj)

    def refresh(self, obj: Any, attributes: Sequence[str] | None = None) -> None:
        self._adapter.refresh(obj, attributes)

    def commit(self) -> None:
        self._adapter.commit()

    def rollback(self) -> None:
        self._adapter.rollback()

    def close(self) -> None:
        self._adapter.close()

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        return self._session.execute(*args, **kwargs)

    async def merge(self, *args: Any, **kwargs: Any) -> Any:
        return self._session.merge(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


async def rollback_if_needed(session: Any) -> None:
    """Roll back *session* to clear any pending-rollback state.

    SQLAlchemy marks a session with a ``PendingRollbackError`` after a flush
    raises: every later operation on that session fails until it is rolled
    back.  This helper calls ``rollback()`` unconditionally because the
    cost on a clean session is negligible, while the benefit of clearing a
    pending-rollback state is essential.
    """
    try:
        result = session.rollback()
        if hasattr(result, "__await__"):
            await result
    except Exception:
        pass


async def flush_with_rollback(session: Any) -> None:
    """``flush()`` that never leaves the session in a pending-rollback state.

    If the flush raises, the session is rolled back (making it reusable) and
    the original exception is re-raised so callers know the write did not
    persist.
    """
    try:
        result = session.flush()
        if hasattr(result, "__await__"):
            await result
    except Exception:
        try:
            result = session.rollback()
            if hasattr(result, "__await__"):
                await result
        except Exception:
            pass
        raise
