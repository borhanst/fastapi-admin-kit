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

    @abstractmethod
    async def authenticate(
        self, email: str, password: str, session: Any
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
    """Default backend that works with the built-in ``User`` model."""

    async def authenticate(
        self, email: str, password: str, session: Any
    ) -> AdminUserProtocol | None:
        from sqlalchemy import select

        from fastapi_admin_kit.auth.models import User

        result = await session.execute(
            select(User).where(
                User.email == email, User.is_active.is_(True)
            )
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

        from fastapi_admin_kit.auth.models import User

        result = await session.execute(
            select(User)
            .options(selectinload(User.roles))
            .where(User.id == user_id, User.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def on_logout(self, user_id: int | str | None = None) -> None:
        """No-op for built-in backend."""
        return None
