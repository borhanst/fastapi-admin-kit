"""Admin component classes for FastAPI Console."""

from fastapi_admin_kit.admin.admin_config import AdminConfig
from fastapi_admin_kit.admin.admin_database import AdminDatabase
from fastapi_admin_kit.admin.admin_router import AdminRouter
from fastapi_admin_kit.admin.admin_template import AdminTemplate
from fastapi_admin_kit.admin.core import Admin
from fastapi_admin_kit.admin.state import AdminState

__all__ = [
    "Admin",
    "AdminConfig",
    "AdminDatabase",
    "AdminRouter",
    "AdminState",
    "AdminTemplate",
]
