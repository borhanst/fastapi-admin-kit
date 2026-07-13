"""Auth router — mounts login/logout views."""

from __future__ import annotations

from fastapi import APIRouter

from fastapi_admin_kit.auth import views

router = APIRouter()
router.include_router(views.router)
