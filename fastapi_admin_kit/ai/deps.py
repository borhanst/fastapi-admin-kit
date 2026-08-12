"""Dependency injection for AI agents — AdminDeps.

``session`` is the raw ORM session (any backend — SQLAlchemy AsyncSession,
Beananie Motor session, etc.).  The three optional backend adapters
(``query_backend`` / ``introspection_backend`` / ``audit_backend``) let tool
implementations remain ORM-agnostic; when one is ``None`` the tool falls back
to a direct SQLAlchemy implementation.

The duplicated fallback used to be copy-pasted through every data tool.  It
now lives once in :class:`~fastapi_admin_kit.ai.data_access.SqlAlchemyDataAccess`,
exposed as :attr:`AdminDeps.data_access`.  The per-concern facades
(:attr:`query`, :attr:`audit`, :attr:`identity`, :attr:`request`) are a thin
view over the same fields so call sites can address a single concern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import Request

from fastapi_admin_kit.ai.data_access import SqlAlchemyDataAccess

if TYPE_CHECKING:
    from fastapi_admin_kit.ai.data_access import DataAccess
    from fastapi_admin_kit.auth.permissions import PermissionChecker
    from fastapi_admin_kit.auth.protocol import AdminUserProtocol
    from fastapi_admin_kit.backends.protocols import (
        AuditBackend,
        IntrospectionBackend,
        QueryBackend,
        SessionBackend,
    )
    from fastapi_admin_kit.registry.core import AdminRegistry


@dataclass
class _QueryContext:
    """Narrow view over query/registry/data-access concerns."""

    registry: Any
    data_access: Any


@dataclass
class _AuditContext:
    """Narrow view over audit-logging concerns."""

    audit_backend: Any
    session: Any


@dataclass
class _IdentityContext:
    """Narrow view over the calling user and their permissions."""

    admin_user: Any
    permission_checker: Any


@dataclass
class _RequestContext:
    """Narrow view over transport concerns."""

    request: Request
    page_url: str | None
    debug: bool
    attachments: list[dict[str, object]] | None


@dataclass
class AdminDeps:
    """Shared dependencies injected into every tool call and agent run.

    ``session`` is the raw ORM session (any backend — SQLAlchemy AsyncSession,
    Beanie Motor session, etc.).  The three optional backend adapters allow
    tool implementations to remain ORM-agnostic:

    * ``query_backend``        — chainable select/where/limit builder
    * ``introspection_backend``— reflect PK, columns, and relationships
    * ``audit_backend``        — snapshot & diff for audit logging

    ``data_access`` is the single seam that owns the ``if query_backend is not
    None … else: direct SQLAlchemy`` fallback; tools should call it instead of
    re-implementing that branch.
    """

    session: Any
    admin_user: AdminUserProtocol
    request: Request
    registry: AdminRegistry
    permission_checker: PermissionChecker
    page_url: str | None = None
    debug: bool = False
    attachments: list[dict[str, object]] | None = field(default=None, repr=False)
    # ORM backend adapters — populated from request.app.state by get_admin_deps
    query_backend: QueryBackend | None = field(default=None, repr=False)
    introspection_backend: IntrospectionBackend | None = field(default=None, repr=False)
    audit_backend: AuditBackend | None = field(default=None, repr=False)
    # Composite backend (the same instance the Admin class configures) plus a
    # session-scoped adapter wrapping the per-request session.  When present,
    # the AI feature routes its own internal persistence through these rather
    # than importing SQLAlchemy directly, so a custom backend swaps in cleanly.
    backend: Any = field(default=None, repr=False)
    session_backend: SessionBackend | None = field(default=None, repr=False)
    # Single data-access seam (built in __post_init__ from the above).
    data_access: DataAccess = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.data_access = SqlAlchemyDataAccess(
            session=self.session,
            query_backend=self.query_backend,
            introspection_backend=self.introspection_backend,
            session_backend=self.session_backend,
        )

    @property
    def query(self) -> _QueryContext:
        return _QueryContext(registry=self.registry, data_access=self.data_access)

    @property
    def audit(self) -> _AuditContext:
        return _AuditContext(audit_backend=self.audit_backend, session=self.session)

    @property
    def identity(self) -> _IdentityContext:
        return _IdentityContext(
            admin_user=self.admin_user, permission_checker=self.permission_checker
        )

    @property
    def request_ctx(self) -> _RequestContext:
        return _RequestContext(
            request=self.request,
            page_url=self.page_url,
            debug=self.debug,
            attachments=self.attachments,
        )


async def get_admin_deps(request: Request) -> AdminDeps:
    """Build AdminDeps from the current request.

    Backend adapters are read from ``request.app.state`` where they are stored
    by :meth:`Admin.setup` during application startup.  They are ``None``-safe:
    if the app state does not expose them (e.g. a custom minimal setup) the
    tool implementations fall back to direct SQLAlchemy calls.
    """
    from fastapi_admin_kit.auth.dependencies import (
        get_current_admin_user,
        get_permission_checker,
    )
    from fastapi_admin_kit.db import get_db_session

    db_session = get_db_session(request)
    admin_user = await get_current_admin_user(request)
    permission_checker = await get_permission_checker(request, admin_user, db_session)

    debug = bool(getattr(request.app.state, "ai_debug", False))

    # Pull ORM backend adapters from app.state (set by Admin.setup).
    # Use getattr with None default so missing keys are safe.
    state = request.app.state
    query_backend = getattr(state, "admin_query_adapter", None)
    introspection_backend = getattr(state, "admin_introspection_adapter", None)
    audit_backend = getattr(state, "admin_audit_backend", None)

    # The composite backend configured on the Admin class, plus a session
    # adapter wrapping this request's session.  These let the AI feature's
    # internal persistence (conversations, messages, usage) use the very same
    # backend as the rest of the admin instead of raw SQLAlchemy.
    backend = getattr(state, "admin_backend", None)
    session_backend_class = getattr(state, "admin_session_backend_class", None)
    session_backend = (
        session_backend_class(db_session) if session_backend_class is not None else None
    )

    return AdminDeps(
        session=db_session,
        admin_user=admin_user,
        request=request,
        registry=getattr(state, "admin_registry", None),
        permission_checker=permission_checker,
        debug=debug,
        query_backend=query_backend,
        introspection_backend=introspection_backend,
        audit_backend=audit_backend,
        backend=backend,
        session_backend=session_backend,
    )
