"""Admin JSON API — provides REST endpoints for external frontend apps."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from fastapi_admin_kit.api.auth import router as auth_router
from fastapi_admin_kit.api.crud import build_api_router
from fastapi_admin_kit.api.roles import router as roles_router
from fastapi_admin_kit.api.security import bearer_scheme


class AdminAPIRouter:
    """Builds and mounts the admin JSON API router.

    Shares the same RBAC system as the HTML admin, providing
    token-based authentication for external frontend apps.
    """

    def __init__(
        self,
        registry: Any = None,
        prefix: str = "/api",
    ):
        self.registry = registry
        self.prefix = prefix

    def build_router(self) -> APIRouter:
        """Build the complete API router with auth and CRUD endpoints."""
        router = APIRouter(prefix=self.prefix)

        # Auth routes (token obtain, refresh, logout, me)
        router.include_router(auth_router)

        # Role management routes (superuser only) — bearer protected
        router.include_router(roles_router, dependencies=[Depends(bearer_scheme)])

        # CRUD routes for all registered models — bearer protected
        if self.registry is not None:
            crud_router = build_api_router(self.registry)
            router.include_router(crud_router, dependencies=[Depends(bearer_scheme)])

        return router
