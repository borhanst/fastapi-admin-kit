"""Dependency injection for AI agents — AdminDeps."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import Request

if TYPE_CHECKING:
    from fastapi_admin_kit.auth.permissions import PermissionChecker
    from fastapi_admin_kit.auth.protocol import AdminUserProtocol
    from fastapi_admin_kit.backends.protocols import (
        AuditBackend,
        IntrospectionBackend,
        QueryBackend,
    )
    from fastapi_admin_kit.registry.core import AdminRegistry


@dataclass
class AdminDeps:
    """Shared dependencies injected into every tool call and agent run.

    ``session`` is the raw ORM session (any backend — SQLAlchemy AsyncSession,
    Beanie Motor session, etc.).  The three optional backend adapters allow
    tool implementations to remain ORM-agnostic:

    * ``query_backend``        — chainable select/where/limit builder
    * ``introspection_backend``— reflect PK, columns, and relationships
    * ``audit_backend``        — snapshot & diff for audit logging

    When a backend adapter is ``None`` the tool falls back to a direct
    SQLAlchemy implementation so existing setups continue to work unchanged.
    """

    session: Any
    admin_user: AdminUserProtocol
    request: Request
    registry: AdminRegistry
    permission_checker: PermissionChecker
    page_url: str | None = None
    debug: bool = False
    # ORM backend adapters — populated from request.app.state by get_admin_deps
    query_backend: QueryBackend | None = field(default=None, repr=False)
    introspection_backend: IntrospectionBackend | None = field(default=None, repr=False)
    audit_backend: AuditBackend | None = field(default=None, repr=False)


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
    )
