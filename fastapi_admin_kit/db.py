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
    ``scope["state"]["admin_db_session"]`` (accessible via
    ``request.state.admin_db_session``).  Falls back to the legacy
    ``app.state.admin_db_session`` when the middleware is not active.
    """
    from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemySessionAdapter

    session = getattr(request.state, "admin_db_session", None)
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

        from starlette.datastructures import State

        state: State = scope.get("state", State())  # type: ignore[assignment]
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
            await self.app(scope, receive, send)
            return

        session = factory()
        scope["state"]["admin_db_session"] = session  # type: ignore[attr-defined]
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
                result = session.commit()
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
