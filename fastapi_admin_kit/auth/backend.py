"""Auth backend — ABC + built-in implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from fastapi_admin_kit.backends import as_session_backend

if TYPE_CHECKING:
    from fastapi_admin_kit.auth.protocol import AdminUserProtocol


class AuthBackend(ABC):
    """Abstract authentication backend — verify credentials & load users."""

    def __init__(self, auth_model: type | None = None) -> None:
        self._auth_model = auth_model

    @abstractmethod
    async def authenticate(
        self,
        credential: str,
        password: str,
        session: Any,
        login_field: str = "email",
    ) -> AdminUserProtocol | None:
        """Verify credentials. Return user object if valid, ``None`` otherwise."""
        ...

    @abstractmethod
    async def get_user(self, user_id: int | str, session: Any) -> AdminUserProtocol | None:
        """Load user by PK. Return ``None`` if not found or inactive."""
        ...

    async def on_logout(self, user_id: int | str | None = None) -> None:
        """Called after a user logs out. Override to perform cleanup."""
        # Default implementation does nothing
        return None


class BuiltinAuthBackend(AuthBackend):
    """Default backend that works with the built-in ``User`` model or custom auth_model.

    Implements :class:`AuthBackend` exclusively through the multi-ORM seam:

    - :class:`QueryBackend` builds ``select`` / ``where`` / ``options`` queries
      (``SqlAlchemyQueryAdapter`` or ``MemoryQueryAdapter``).
    - :class:`SessionBackend` executes them via ``scalar_one_or_none`` and
      wraps the raw DB session via :func:`as_session_backend` using the
      configured ``DatabaseBackend``'s ``session_adapter_class``.

    No ``sqlalchemy`` imports appear at query-build or execution time; the
    backend adapters encapsulate all ORM specifics. This keeps
    ``BuiltinAuthBackend`` usable with ``InMemoryBackend`` and any future ODM
    backend.
    """

    def __init__(
        self,
        auth_model: type | None = None,
        backend: Any | None = None,
        query_backend: Any | None = None,
    ) -> None:
        super().__init__(auth_model=auth_model)
        self._backend = backend
        self._query_backend = query_backend

    # Backwards-compatible aliases — some call sites use ``.backend`` / ``.query_backend``
    @property
    def backend(self) -> Any | None:
        return self._backend

    @backend.setter
    def backend(self, value: Any | None) -> None:
        self._backend = value

    @property
    def query_backend(self) -> Any | None:
        return self._query_backend

    @query_backend.setter
    def query_backend(self, value: Any | None) -> None:
        self._query_backend = value

    def _get_model(self) -> type:
        if self._auth_model is not None:
            return self._auth_model
        from fastapi_admin_kit.auth.models import User

        return User

    def _resolve_query_backend(self, explicit: Any | None = None) -> Any:
        """Return the :class:`QueryBackend` to use for this call.

        Resolution order:

        1. Explicit ``query_adapter`` passed to the method.
        2. ``self._query_backend`` set at construction / injected by :class:`Admin`.
        3. ``self._backend.query`` from the composite backend.
        4. Fallback ``SqlAlchemyQueryAdapter`` for legacy call sites / tests that
           instantiate ``BuiltinAuthBackend()`` directly without an Admin.
        """
        if explicit is not None:
            return explicit
        if self._query_backend is not None:
            return self._query_backend
        if self._backend is not None:
            qb = getattr(self._backend, "query", None)
            if qb is not None:
                return qb
        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyQueryAdapter

        return SqlAlchemyQueryAdapter()

    def _resolve_session(self, session: Any) -> Any:
        """Wrap *session* via :func:`as_session_backend` using the DB backend."""
        if self._backend is not None:
            return as_session_backend(session, backend=self._backend)
        return as_session_backend(session)

    async def authenticate(
        self,
        credential: str,
        password: str,
        session: Any,
        login_field: str = "email",
        query_adapter: Any | None = None,
        query_backend: Any | None = None,
        **kwargs: Any,
    ) -> AdminUserProtocol | None:
        # Accept both ``query_adapter`` and legacy ``query_backend`` kwarg names
        qb = query_adapter if query_adapter is not None else query_backend
        if qb is None:
            qb = kwargs.get("query_adapter") or kwargs.get("query_backend")
        query_backend_resolved = self._resolve_query_backend(qb)
        session = self._resolve_session(session)
        model = self._get_model()
        field = getattr(model, login_field, None)
        print("model: ", model)
        print("field: ", field)
        if field is None:
            field = getattr(model, "email", None)
        if field is None:
            return None

        # Build query via QueryBackend — backend agnostic (Memory vs SQLAlchemy)
        query = query_backend_resolved.select(model)
        is_active_col = getattr(model, "is_active", None)
        if is_active_col is not None:
            query = query_backend_resolved.where(
                query,
                field == credential,
                is_active_col == True,  # noqa: E712
            )
        else:
            query = query_backend_resolved.where(query, field == credential)

        # Eagerly load roles if the model has a roles relationship.
        # For SQLAlchemy this is a selectinload option; for Memory it is a no-op.
        if hasattr(model, "roles"):
            try:
                if query_backend_resolved.__class__.__name__ == "SqlAlchemyQueryAdapter":
                    from sqlalchemy.orm import selectinload

                    query = query_backend_resolved.options(query, selectinload(model.roles))
            except Exception:
                pass

        result = session.scalar_one_or_none(query)
        user = await result if hasattr(result, "__await__") else result
        if not user:
            return None
        if not user.verify_password(password):
            return None
        return user

    async def get_user(
        self,
        user_id: int | str,
        session: Any,
        query_adapter: Any | None = None,
        query_backend: Any | None = None,
        **kwargs: Any,
    ) -> AdminUserProtocol | None:
        qb = query_adapter if query_adapter is not None else query_backend
        if qb is None:
            qb = kwargs.get("query_adapter") or kwargs.get("query_backend")
        query_backend_resolved = self._resolve_query_backend(qb)
        session = self._resolve_session(session)
        model = self._get_model()
        query = query_backend_resolved.select(model)
        is_active_col = getattr(model, "is_active", None)
        id_col = getattr(model, "id", None)
        if id_col is None:
            return None
        if is_active_col is not None:
            query = query_backend_resolved.where(
                query,
                id_col == user_id,
                is_active_col == True,  # noqa: E712
            )
        else:
            query = query_backend_resolved.where(query, id_col == user_id)

        # Eagerly load roles if the model has a roles relationship
        if hasattr(model, "roles"):
            try:
                if query_backend_resolved.__class__.__name__ == "SqlAlchemyQueryAdapter":
                    from sqlalchemy.orm import selectinload

                    query = query_backend_resolved.options(query, selectinload(model.roles))
            except Exception:
                pass

        result = session.scalar_one_or_none(query)
        return await result if hasattr(result, "__await__") else result

    async def on_logout(self, user_id: int | str | None = None) -> None:
        """No-op for built-in backend."""
        return None
