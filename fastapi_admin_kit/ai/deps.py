"""Dependency injection for AI agents — AdminDeps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request


@dataclass
class AdminDeps:
    """Shared dependencies injected into every tool call and agent run."""

    session: Any
    admin_user: Any
    request: Any
    registry: Any
    permission_checker: Any


async def get_admin_deps(request: Request) -> AdminDeps:
    """Build AdminDeps from the current request."""
    from fastapi_admin_kit.auth.dependencies import (
        get_current_admin_user,
        get_permission_checker,
    )
    from fastapi_admin_kit.db import get_db_session

    db_session = get_db_session(request)
    admin_user = await get_current_admin_user(request)
    permission_checker = await get_permission_checker(request, admin_user, db_session)

    return AdminDeps(
        session=db_session,
        admin_user=admin_user,
        request=request,
        registry=request.app.state.admin_registry,
        permission_checker=permission_checker,
    )
