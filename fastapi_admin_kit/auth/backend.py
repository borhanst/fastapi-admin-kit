"""Auth backend — ABC + built-in implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import bcrypt

if TYPE_CHECKING:
    from fastapi_admin_kit.auth.protocol import AdminUserProtocol


class _PasswordHasher:
    """Thin wrapper around bcrypt for hash/verify."""

    @staticmethod
    def hash(password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def verify(password: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode(), hashed.encode())
        except (ValueError, TypeError):
            return False


pwd_context = _PasswordHasher()


class AuthBackend(ABC):
    """Abstract authentication backend — verify credentials & load users."""

    def __init__(self, auth_model: type | None = None) -> None:
        self._auth_model = auth_model

    @abstractmethod
    async def authenticate(
        self, credential: str, password: str, session: Any,
        login_field: str = "email",
    ) -> AdminUserProtocol | None:
        """Verify credentials. Return user object if valid, ``None`` otherwise."""
        ...

    @abstractmethod
    async def get_user(
        self, user_id: int | str, session: Any
    ) -> AdminUserProtocol | None:
        """Load user by PK. Return ``None`` if not found or inactive."""
        ...

    async def on_logout(self, user_id: int | str | None = None) -> None:
        """Called after a user logs out. Override to perform cleanup."""
        # Default implementation does nothing
        return None


class BuiltinAuthBackend(AuthBackend):
    """Default backend that works with the built-in ``User`` model or custom auth_model."""

    def _get_model(self) -> type:
        if self._auth_model is not None:
            return self._auth_model
        from fastapi_admin_kit.auth.models import User
        return User

    async def authenticate(
        self, credential: str, password: str, session: Any,
        login_field: str = "email",
    ) -> AdminUserProtocol | None:
        from sqlalchemy import select

        model = self._get_model()
        field = getattr(model, login_field, None)
        if field is None:
            field = getattr(model, "email", None)
        if field is None:
            return None

        result = await session.execute(
            select(model).where(field == credential, model.is_active.is_(True))
        )
        user = result.scalar_one_or_none()

        if not user:
            return None
        if not user.verify_password(password):
            return None
        return user

    async def get_user(
        self, user_id: int | str, session: Any
    ) -> AdminUserProtocol | None:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        model = self._get_model()
        query = select(model).where(model.id == user_id, model.is_active.is_(True))

        # Eagerly load roles if the model has a roles relationship
        if hasattr(model, "roles"):
            query = query.options(selectinload(model.roles))

        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def on_logout(self, user_id: int | str | None = None) -> None:
        """No-op for built-in backend."""
        return None
