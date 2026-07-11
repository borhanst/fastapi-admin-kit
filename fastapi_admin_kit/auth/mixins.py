"""Mixin for custom user models to work with admin's built-in RBAC."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import Boolean, Column, String

if TYPE_CHECKING:
    pass


class AuthModelMixin:
    """Mixin for custom user models to work with admin's built-in RBAC.

    Provides: hashed_password, is_active, is_superuser columns,
    role_ids property, verify_password() and hash_password() methods.

    Usage::

        from fastapi_admin_kit.auth.mixins import AutoModelMixin
        from fastapi_admin_kit.auth.models import admin_user_roles, Role
        from sqlalchemy.orm import relationship

        class MyUser(AutoModelMixin, Base):
            __tablename__ = "my_users"

            id = Column(Integer, primary_key=True)
            username = Column(String(255), unique=True)
            email = Column(String(255), unique=True)

            # Define roles relationship yourself (FK must match your table)
            roles = relationship(
                "Role", secondary=admin_user_roles, back_populates="users"
            )

    The mixin provides:
    - ``hashed_password`` column (String 255)
    - ``is_active`` column (Boolean, default True)
    - ``is_superuser`` column (Boolean, default False)
    - ``role_ids`` property → ``list[int]`` (reads from ``self.roles``)
    - ``verify_password(password)`` → bool
    - ``hash_password(password)`` → str (classmethod)
    - ``set_hasher(hasher)`` classmethod
    """

    _hasher: ClassVar[type | None] = None

    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)

    @property
    def role_ids(self) -> list[int]:
        """Return list of role IDs from the ``roles`` relationship."""
        roles = getattr(self, "roles", None)
        if roles is None:
            return []
        return [r.id for r in roles]

    def verify_password(self, password: str) -> bool:
        """Check if plaintext password matches the stored hash."""
        hasher = self._get_hasher()
        return hasher.verify(password, self.hashed_password)

    @classmethod
    def hash_password(cls, password: str) -> str:
        """Hash a plaintext password using the configured hasher."""
        hasher = cls._get_hasher()
        return hasher.hash(password)

    @classmethod
    def _get_hasher(cls) -> type:
        """Return the configured hasher class, or default BcryptHasher."""
        if cls._hasher is not None:
            return cls._hasher
        from fastapi_admin_kit.auth.hasher import BcryptHasher

        return BcryptHasher

    @classmethod
    def set_hasher(cls, hasher: type) -> None:
        """Set the password hasher class for this model."""
        cls._hasher = hasher


# Backward-compatible alias

