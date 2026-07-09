"""RBAC permission checker — per-request, with in-memory caching."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi_admin_kit.auth.models import Permission, UserPermission
from fastapi_admin_kit.types import PermissionSet

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from fastapi_admin_kit.auth.protocol import AdminUserProtocol


class PermissionChecker:
    """Per-request permission checker.

    Instantiated once per request via ``Depends(get_permission_checker)``.
    Caches permission results in-memory for the lifetime of the request.

    Merges permissions from:
    1. All assigned roles (M2M via admin_user_roles)
    2. Direct per-user overrides (UserPermission)

    Role permissions are OR'd together, then direct overrides are OR'd on top.
    """

    def __init__(
        self,
        session: AsyncSession,
        user: AdminUserProtocol,
        *,
        user_snapshot: dict[str, object] | None = None,
    ) -> None:
        self.session = session
        self.user = user
        snap = user_snapshot or {}
        self._is_superuser: bool = (
            bool(snap["is_superuser"]) if "is_superuser" in snap else bool(user.is_superuser)
        )
        self._role_ids: list[int] = (
            snap["role_ids"] if "role_ids" in snap else getattr(user, "role_ids", [])
        )
        self._user_id: int | str | None = (
            snap.get("id") if snap else getattr(user, "id", None)
        )
        self._role_cache: dict[str, PermissionSet | None] | None = None
        self._direct_cache: dict[str, PermissionSet | None] | None = None
        self._cache: dict[tuple[str, str], bool] = {}
        self._field_cache: dict[tuple[str, str], set[str] | None] = {}

    async def _load_role_permissions(self) -> dict[str, PermissionSet | None]:
        """Load and cache all role-based permissions, merged with OR logic."""
        if self._role_cache is not None:
            return self._role_cache

        self._role_cache = {}
        if not self._role_ids:
            return self._role_cache

        from sqlalchemy import select

        result = await self.session.execute(
            select(Permission).where(
                Permission.role_id.in_(self._role_ids)
            )
        )
        for perm in result.scalars():
            table = perm.table_name
            if table not in self._role_cache:
                self._role_cache[table] = PermissionSet()
            ps = self._role_cache[table]
            if perm.can_view:
                ps.can_view = True
            if perm.can_create:
                ps.can_create = True
            if perm.can_edit:
                ps.can_edit = True
            if perm.can_delete:
                ps.can_delete = True

        return self._role_cache

    async def _load_direct_permissions(self) -> dict[str, PermissionSet | None]:
        """Load and cache direct per-user permission overrides."""
        if self._direct_cache is not None:
            return self._direct_cache

        self._direct_cache = {}
        if self._user_id is None:
            return self._direct_cache

        from sqlalchemy import select

        result = await self.session.execute(
            select(UserPermission).where(
                UserPermission.user_id == self._user_id
            )
        )
        for perm in result.scalars():
            table = perm.table_name
            if table not in self._direct_cache:
                self._direct_cache[table] = PermissionSet()
            ps = self._direct_cache[table]
            if perm.can_view:
                ps.can_view = True
            if perm.can_create:
                ps.can_create = True
            if perm.can_edit:
                ps.can_edit = True
            if perm.can_delete:
                ps.can_delete = True

        return self._direct_cache

    async def _get_merged_permission(self, table_name: str, action: str) -> bool:
        """Get merged permission for a table+action across roles and direct overrides."""
        role_perms = await self._load_role_permissions()
        direct_perms = await self._load_direct_permissions()

        attr = f"can_{action}"

        role_ps = role_perms.get(table_name)
        direct_ps = direct_perms.get(table_name)

        role_val = getattr(role_ps, attr, False) if role_ps else False
        direct_val = getattr(direct_ps, attr, False) if direct_ps else False

        return role_val or direct_val

    async def has_permission(self, table_name: str, action: str) -> bool:
        """Return True if the current user may perform *action* on *table_name*.

        Actions: ``"view"`` | ``"create"`` | ``"edit"`` | ``"delete"``

        Superusers always return True. Results are cached per-request.
        """
        if self._is_superuser:
            return True

        cache_key = (table_name, action)
        if cache_key in self._cache:
            return self._cache[cache_key]

        result_bool = await self._get_merged_permission(table_name, action)
        self._cache[cache_key] = result_bool
        return result_bool

    async def get_allowed_fields(self, table_name: str, mode: str) -> set[str] | None:
        """Return the set of field names the user may access, or ``None``.

        mode: ``"view"`` | ``"edit"``

        Semantics:
        - ``None`` → no field-level restrictions exist → all fields allowed.
        - Empty ``set()`` → restriction rows exist but none grant access → no fields.
        - Non-empty ``set()`` → only those field names are permitted.
        """
        if self._is_superuser:
            return None

        cache_key = (table_name, mode)
        if cache_key in self._field_cache:
            return self._field_cache[cache_key]

        # No role and no direct permissions → all fields restricted
        if not self._role_ids and self._user_id is None:
            self._field_cache[cache_key] = set()
            return set()

        # No field-level restrictions in this system anymore
        self._field_cache[cache_key] = None
        return None

    def permission_set(self, table_name: str) -> PermissionSet:
        """Return a :class:`PermissionSet` for convenient template / UI use.

        Note: This is a sync convenience wrapper. For async contexts,
        use the individual async methods directly.
        """
        if self._is_superuser:
            return PermissionSet(
                can_view=True,
                can_create=True,
                can_edit=True,
                can_delete=True,
            )
        return PermissionSet(
            can_view=self._cache.get((table_name, "view"), False),
            can_create=self._cache.get((table_name, "create"), False),
            can_edit=self._cache.get((table_name, "edit"), False),
            can_delete=self._cache.get((table_name, "delete"), False),
        )

    async def load_permissions(self, table_name: str) -> PermissionSet:
        """Async method to load and cache all permissions for a table.

        Call this before using ``permission_set()`` to ensure the cache is populated.
        """
        await self.has_permission(table_name, "view")
        await self.has_permission(table_name, "create")
        await self.has_permission(table_name, "edit")
        await self.has_permission(table_name, "delete")
        return self.permission_set(table_name)
