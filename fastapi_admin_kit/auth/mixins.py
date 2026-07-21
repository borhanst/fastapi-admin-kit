"""Mixin for custom user models to work with admin's built-in RBAC."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import Boolean, Column, String

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


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
    - ``has_perm(perm_name, session)`` → bool (check permission by name)
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

    async def has_perm(self, perm_name: str, session: AsyncSession) -> bool:
        """Check if this user has a permission by name (e.g. 'products_view').

        Returns True if any assigned role grants this permission,
        or if a direct user permission grants it. Superusers always return True.
        """
        if self.is_superuser:
            return True

        from sqlalchemy import select

        from fastapi_admin_kit.auth.models import (
            Permission,
            UserPermission,
            admin_role_permissions,
            admin_user_roles,
        )

        # Parse perm_name -> (table_name, action)
        # e.g. "products_view" -> ("products", "view")
        parts = perm_name.rsplit("_", 1)
        if len(parts) != 2:
            return False
        table_name, action = parts

        attr = f"can_{action}"
        if attr not in ("can_view", "can_create", "can_edit", "can_delete"):
            return False

        role_ids = self.role_ids
        if not role_ids and not self.id:
            return False

        # Check role-based permissions
        if role_ids:
            result = await session.execute(
                select(Permission)
                .join(
                    admin_role_permissions,
                    Permission.id == admin_role_permissions.c.permission_id,
                )
                .join(
                    admin_user_roles,
                    admin_role_permissions.c.role_id == admin_user_roles.c.role_id,
                )
                .where(admin_user_roles.c.user_id == self.id)
            )
            for perm in result.scalars():
                if perm.table_name == table_name and getattr(perm, attr, False):
                    return True

        # Check direct user permissions
        result = await session.execute(
            select(Permission)
            .join(UserPermission, UserPermission.permission_id == Permission.id)
            .where(UserPermission.user_id == self.id)
        )
        for perm in result.scalars():
            if perm.table_name == table_name and getattr(perm, attr, False):
                return True

        return False


# Backward-compatible alias
