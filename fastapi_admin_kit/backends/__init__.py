"""Backend protocols and SQLAlchemy adapters for multi-ORM support.

Protocols::

    from fastapi_admin_kit.backends import (
        IntrospectionBackend,
        SessionBackend,
        QueryBackend,
        AuditBackend,
        DatabaseBackend,
    )

SQLAlchemy adapters::

    from fastapi_admin_kit.backends import (
        SqlAlchemyIntrospectionAdapter,
        SqlAlchemySessionAdapter,
        SqlAlchemyQueryAdapter,
        SqlAlchemyAuditBackend,
        SqlAlchemyDatabaseBackend,
        SqlAlchemyBackend,
    )
"""

from __future__ import annotations

from typing import Any

from fastapi_admin_kit.backends.memory import InMemoryBackend
from fastapi_admin_kit.backends.protocols import (
    AuditBackend,
    ColumnMetaType,
    DatabaseBackend,
    IntrospectionBackend,
    QueryBackend,
    QueryType,
    RelationMetaType,
    SessionBackend,
    SessionType,
)
from fastapi_admin_kit.backends.sqlalchemy import (
    SqlAlchemyAuditBackend,
    SqlAlchemyBackend,
    SqlAlchemyDatabaseBackend,
    SqlAlchemyIntrospectionAdapter,
    SqlAlchemyQueryAdapter,
    SqlAlchemySessionAdapter,
)

__all__ = [
    # Protocols
    "AuditBackend",
    "ColumnMetaType",
    "DatabaseBackend",
    "IntrospectionBackend",
    "QueryBackend",
    "QueryType",
    "RelationMetaType",
    "SessionBackend",
    "SessionType",
    # SQLAlchemy adapters
    "SqlAlchemyAuditBackend",
    "SqlAlchemyBackend",
    "SqlAlchemyDatabaseBackend",
    "SqlAlchemyIntrospectionAdapter",
    "SqlAlchemyQueryAdapter",
    "SqlAlchemySessionAdapter",
    # Reference (dependency-free) backend
    "InMemoryBackend",
]


def as_session_backend(
    session: object,
    *,
    adapter_class: type | None = None,
    backend: Any = None,
) -> Any:
    """Coerce *session* into a :class:`SessionBackend`.

    This is the single seam that turns a concrete ORM session into a
    backend-agnostic one, so the rest of the codebase only ever talks to the
    :class:`SessionBackend` protocol.

    Resolution order:

    1. ``None`` -> ``None`` (pass-through; callers may store a missing session).
    2. Already a :class:`SessionBackend` (any backend's adapter, e.g.
       ``SqlAlchemySessionAdapter`` or ``MemorySessionBackend``) -> returned
       **unchanged**.  Detection uses the protocol, so this is idempotent and
       works for every backend, not just SQLAlchemy.
    3. A raw ORM session -> wrapped with the matching adapter.  The adapter is
       resolved as ``adapter_class`` (explicit) -> ``backend.database
       .session_adapter_class`` (the configured backend's own adapter) ->
       ``SqlAlchemySessionAdapter`` (historical default for legacy call sites).

    By deferring to the configured backend's ``session_adapter_class`` instead
    of hard-coding SQLAlchemy, this helper stays ORM-agnostic: a memory or
    future ODM backend simply provides its own adapter and nothing else changes.
    """
    if session is None:
        return None
    if isinstance(session, SessionBackend):
        return session
    if adapter_class is None and backend is not None:
        adapter_class = getattr(getattr(backend, "database", None), "session_adapter_class", None)
    if adapter_class is None:
        adapter_class = SqlAlchemySessionAdapter
    return adapter_class(session)
