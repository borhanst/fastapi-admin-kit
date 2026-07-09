"""Sidebar context helper for template views."""

from __future__ import annotations

from typing import Any

from fastapi import Request


async def inject_sidebar_context(request: Request, context: dict[str, Any]) -> dict[str, Any]:
    """Inject nav_groups + permissions_map into a template context dict."""
    admin_instance: Any = request.app.state.admin
    if hasattr(admin_instance, "build_sidebar_context"):
        user = getattr(request.state, "admin_user", None)

        snapshot = getattr(request.state, "admin_user_snapshot", None)
        is_superuser = (
            bool(snapshot.get("is_superuser", False))
            if snapshot
            else bool(getattr(user, "is_superuser", False))
        ) if user else False

        permissions_map: dict = {}
        if user and not is_superuser:
            try:
                from sqlalchemy import select

                from fastapi_admin_kit.auth.models import Permission, UserPermission
                from fastapi_admin_kit.db import get_db_session
                from fastapi_admin_kit.types import PermissionSet

                snapshot = getattr(request.state, "admin_user_snapshot", None)
                user_id = (
                    snapshot.get("id")
                    if snapshot
                    else getattr(user, "id", None)
                )
                role_ids = (
                    snapshot.get("role_ids", [])
                    if snapshot
                    else getattr(user, "role_ids", [])
                )

                session = get_db_session(request)

                # Load permissions from all roles, merge with OR logic
                if role_ids:
                    result = await session.execute(
                        select(Permission).where(
                            Permission.role_id.in_(role_ids)
                        )
                    )
                    for perm in result.scalars():
                        if perm.table_name in permissions_map:
                            existing = permissions_map[perm.table_name]
                            permissions_map[perm.table_name] = PermissionSet(
                                can_view=existing.can_view or perm.can_view,
                                can_create=existing.can_create or perm.can_create,
                                can_edit=existing.can_edit or perm.can_edit,
                                can_delete=existing.can_delete or perm.can_delete,
                            )
                        else:
                            permissions_map[perm.table_name] = PermissionSet(
                                can_view=perm.can_view,
                                can_create=perm.can_create,
                                can_edit=perm.can_edit,
                                can_delete=perm.can_delete,
                            )

                # Load direct user permission overrides, merge on top
                if user_id is not None:
                    result = await session.execute(
                        select(UserPermission).where(
                            UserPermission.user_id == user_id
                        )
                    )
                    for perm in result.scalars():
                        if perm.table_name in permissions_map:
                            existing = permissions_map[perm.table_name]
                            permissions_map[perm.table_name] = PermissionSet(
                                can_view=existing.can_view or perm.can_view,
                                can_create=existing.can_create or perm.can_create,
                                can_edit=existing.can_edit or perm.can_edit,
                                can_delete=existing.can_delete or perm.can_delete,
                            )
                        else:
                            permissions_map[perm.table_name] = PermissionSet(
                                can_view=perm.can_view,
                                can_create=perm.can_create,
                                can_edit=perm.can_edit,
                                can_delete=perm.can_delete,
                            )
            except Exception:
                pass

        context.update(
            admin_instance.build_sidebar_context(
                request, user=user, permissions_map=permissions_map
            )
        )
    return context
