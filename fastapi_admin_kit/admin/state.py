"""Typed AdminState — replaces untyped app.state attributes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jinja2 import Environment
    from sqlalchemy.ext.asyncio import AsyncSession

    from fastapi_admin_kit.admin.core import Admin
    from fastapi_admin_kit.auth.backend import AuthBackend
    from fastapi_admin_kit.auth.session import SignedCookieSessionBackend
    from fastapi_admin_kit.registry import AdminRegistry
    from fastapi_admin_kit.storage.base import StorageBackend


@dataclass
class AdminState:
    """Typed container for admin state stored on ``app.state.admin_state``.

    Replaces the previous pattern of storing a dozen untyped attributes
    directly on ``app.state``.
    """

    engine: Any = None
    session_backend: SignedCookieSessionBackend | None = None
    auth_backend: AuthBackend | None = None
    storage: StorageBackend | None = None
    registry: AdminRegistry | None = None
    db_session: AsyncSession | None = None
    config: dict[str, Any] = field(default_factory=dict)
    jinja_env: Environment | None = None
    admin_instance: Admin | None = None
    # Unified signing-key source — used by signed-cookie sessions, CSRF, and JWT.
    secret_key: str = ""
    session_samesite: str = "strict"

    @classmethod
    def from_request(cls, request: Any) -> AdminState:
        """Get AdminState from a FastAPI Request object.

        Tries the typed ``app.state.admin_state`` first, then falls back
        to building from legacy individual attributes.
        """
        state = getattr(request.app.state, "admin_state", None)
        if isinstance(state, AdminState):
            return state
        return cls.from_app_state(request.app.state)

    @classmethod
    def from_app_state(cls, app_state: Any) -> AdminState:
        """Build an AdminState from a Starlette ``app.state`` object.

        Supports both the new typed format (``app.state.admin_state``) and
        legacy untyped attributes for backward compatibility.
        """
        # If already stored as typed object, return it directly
        typed = getattr(app_state, "admin_state", None)
        if isinstance(typed, AdminState):
            return typed

        # Legacy: build from individual attributes
        return cls(
            engine=getattr(app_state, "admin_engine", None),
            session_backend=getattr(app_state, "admin_session_backend", None),
            auth_backend=getattr(app_state, "admin_auth_backend", None),
            storage=getattr(app_state, "admin_storage", None),
            registry=getattr(app_state, "admin_registry", None),
            db_session=getattr(app_state, "admin_db_session", None),
            config=getattr(app_state, "admin_config", {}),
            jinja_env=getattr(app_state, "admin_jinja_env", None),
            admin_instance=getattr(app_state, "admin", None),
            secret_key=getattr(app_state, "admin_secret_key", ""),
        )
