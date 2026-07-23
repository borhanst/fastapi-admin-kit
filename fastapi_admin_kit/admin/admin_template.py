"""Admin template management and context building."""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AdminTemplate:
    """Manages Jinja2 template environment and sidebar context."""

    def __init__(
        self,
        title: str = "FastAPI Admin Kit",
        logo_url: str | None = None,
        favicon_url: str | None = None,
        primary_color: str = "#0ea5e9",
        primary_color_dark: str = "#0284c7",
        dark_mode_default: bool = False,
        dashboard_permission: str | None = None,
        settings_permission: str | None = None,
    ):
        self.title = title
        self.logo_url = logo_url
        self.favicon_url = favicon_url
        self.primary_color = primary_color
        self.primary_color_dark = primary_color_dark
        self.dark_mode_default = dark_mode_default
        self.dashboard_permission = dashboard_permission
        self.settings_permission = settings_permission
        self._nav_groups_built: list = []

    def _init_jinja(self, app: Any) -> None:
        """Initialise the Jinja2 template environment."""
        import re
        from pathlib import Path

        from starlette.templating import Jinja2Templates

        templates_dir = Path(__file__).parent.parent / "templates"
        jinja_env = Jinja2Templates(directory=str(templates_dir))

        def slugify(s: str) -> str:
            return re.sub(r"[^\w]", "-", s, flags=re.A).strip("-").lower()

        jinja_env.env.filters["slugify"] = slugify
        app.state.admin_jinja_env = jinja_env

    async def sidebar_template_kwargs(self, request: Any) -> dict[str, Any]:
        """Thin wrapper — returns sidebar kwargs for TemplateResponse contexts."""
        return await self.build_sidebar_context(request)

    async def build_sidebar_context(
        self,
        request: Any,
        user: Any = None,
        permissions_map: dict | None = None,
    ) -> dict:
        """Build per-request sidebar context (RBAC filter + permissions map).

        If *permissions_map* is provided (pre-loaded by the async caller),
        it is used directly instead of querying the database here.
        """
        if user is None:
            user = getattr(request.state, "admin_user", None)

        snapshot = getattr(request.state, "admin_user_snapshot", None)
        user_for_template = snapshot if snapshot else user
        is_superuser = (
            (
                bool(snapshot.get("is_superuser", False))
                if snapshot
                else bool(getattr(user, "is_superuser", False))
            )
            if user
            else False
        )

        from fastapi_admin_kit.types import PermissionSet

        nav_groups = self._nav_groups_built

        if permissions_map is None:
            permissions_map = {}

            if user and not is_superuser:
                user_id = snapshot.get("id") if snapshot else getattr(user, "id", None)
                role_ids = (
                    snapshot.get("role_ids", []) if snapshot else getattr(user, "role_ids", [])
                )
                if role_ids or user_id is not None:
                    try:
                        from sqlalchemy import select

                        from fastapi_admin_kit.auth.models import (
                            Permission,
                            UserPermission,
                            admin_role_permissions,
                        )
                        from fastapi_admin_kit.db import get_db_session

                        session = get_db_session(request)

                        # Load permissions from all roles, merge with OR logic
                        if role_ids:
                            result = await session.execute(
                                select(Permission)
                                .join(
                                    admin_role_permissions,
                                    Permission.id == admin_role_permissions.c.permission_id,
                                )
                                .where(admin_role_permissions.c.role_id.in_(role_ids))
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
                                select(UserPermission, Permission)
                                .join(Permission, UserPermission.permission_id == Permission.id)
                                .where(UserPermission.user_id == user_id)
                            )
                            for up, perm in result:
                                table = perm.table_name
                                if table in permissions_map:
                                    existing = permissions_map[table]
                                    permissions_map[table] = PermissionSet(
                                        can_view=existing.can_view or perm.can_view,
                                        can_create=existing.can_create or perm.can_create,
                                        can_edit=existing.can_edit or perm.can_edit,
                                        can_delete=existing.can_delete or perm.can_delete,
                                    )
                                else:
                                    permissions_map[table] = PermissionSet(
                                        can_view=perm.can_view,
                                        can_create=perm.can_create,
                                        can_edit=perm.can_edit,
                                        can_delete=perm.can_delete,
                                    )
                    except Exception as exc:
                        logger.warning(
                            "Permission query failed in sidebar fallback: %s", exc, exc_info=True
                        )

        def _item_visible(item: Any) -> bool:
            return (
                item.permission_table is None
                or is_superuser
                or (
                    permissions_map.get(item.permission_table)
                    and permissions_map[item.permission_table].can_view
                )
            )

        def _filter_items(items: list[Any]) -> list[Any]:
            from dataclasses import replace

            result = []
            for item in items:
                if not _item_visible(item):
                    continue
                filtered_children = _filter_items(item.children) if item.children else []
                result.append(replace(item, children=filtered_children))
            return result

        from dataclasses import replace

        dashboard_visible = (
            is_superuser
            or self.dashboard_permission is None
            or (
                permissions_map.get(self.dashboard_permission)
                and permissions_map[self.dashboard_permission].can_view
            )
        )
        settings_visible = (
            is_superuser
            or self.settings_permission is None
            or (
                permissions_map.get(self.settings_permission)
                and permissions_map[self.settings_permission].can_view
            )
        )

        filtered_groups: list[Any] = []
        for group in nav_groups:
            if not (
                group.permission_table is None
                or is_superuser
                or (
                    permissions_map.get(group.permission_table)
                    and permissions_map[group.permission_table].can_view
                )
            ):
                continue
            visible = _filter_items(group.items)
            if visible:
                filtered_groups.append(replace(group, items=visible))

        return {
            "nav_groups": filtered_groups,
            "permissions_map": permissions_map,
            "current_user": user_for_template,
            "dashboard_visible": dashboard_visible,
            "settings_visible": settings_visible,
        }

    async def apply_sidebar_context(self, request: Any, user: Any, context: dict) -> dict:
        """Inject nav_groups + permissions_map into a template context dict."""
        context.update(await self.build_sidebar_context(request, user=user))
        return context
