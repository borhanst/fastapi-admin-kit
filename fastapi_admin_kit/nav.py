"""Navigation tag & group system for the admin sidebar.

Implements the full tag system from TAG_SPEC.md:
- NavGroupConfig / NavItemConfig — developer-provided config
- BuiltNavGroup / BuiltNavItem — resolved output of SidebarBuilder
- DefaultSidebarBuilder / SidebarBuilderProtocol
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from fastapi_admin_kit.registry import RegisteredModel


# ---------------------------------------------------------------------------
# Public config types (passed by the developer)
# ---------------------------------------------------------------------------


@dataclass
class NavItemConfig:
    """A custom nav item placed inside a tag group (independent of models)."""

    label: str
    url: str
    icon: str | None = None
    order: int = 999
    permission: str | None = None


@dataclass
class NavGroupConfig:
    """Developer-provided configuration for one sidebar tag group."""

    tag: str
    label: str | None = None
    icon: str | None = None
    order: int = 999
    collapsed_by_default: bool = False
    permission: str | None = None
    extra_items: list[NavItemConfig] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Built types (produced by SidebarBuilder at startup — read-only in templates)
# ---------------------------------------------------------------------------


@dataclass
class BuiltNavItem:
    label: str
    url: str
    icon: str | None = None
    order: int = 999
    badge_fn: Callable | None = None
    permission_table: str | None = None
    children: list[BuiltNavItem] = field(default_factory=list)


@dataclass
class BuiltNavGroup:
    tag: str
    label: str
    icon: str | None = None
    order: int = 999
    collapsed_by_default: bool = False
    permission_table: str | None = None
    items: list[BuiltNavItem] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SidebarBuilder protocol + default implementation
# ---------------------------------------------------------------------------


@runtime_checkable
class SidebarBuilder(Protocol):
    """Protocol that all sidebar builders must satisfy."""

    def build(
        self,
        registry: list[RegisteredModel],
        nav_group_configs: list[NavGroupConfig],
        admin_path: str = "/admin",
    ) -> list[BuiltNavGroup]: ...


class DefaultSidebarBuilder:
    """Default implementation: bucket registered models by tag, honour configs."""

    def build(
        self,
        registry: list[RegisteredModel],
        nav_group_configs: list[NavGroupConfig],
        admin_path: str = "/admin",
    ) -> list[BuiltNavGroup]:
        buckets: dict[str, list[BuiltNavItem]] = {}
        for registered in registry:
            tags = self._get_tags(registered)
            for tag in tags:
                buckets.setdefault(tag, []).append(
                    BuiltNavItem(
                        label=registered.verbose_name_plural,
                        url=f"{admin_path}/{registered.table_name}/",
                        icon=getattr(registered.admin, "icon", None),
                        order=getattr(registered.admin, "nav_order", 999),
                        badge_fn=getattr(
                            registered.admin, "get_nav_badge", None
                        ),
                        permission_table=registered.table_name,
                        children=self._build_children(registered),
                    )
                )

        groups: list[BuiltNavGroup] = []
        seen: set[str] = set()

        # Process configured tags in order first
        configured_lower = {cfg.tag.lower(): cfg for cfg in nav_group_configs}
        for cfg in sorted(nav_group_configs, key=lambda c: c.order):
            tag = cfg.tag
            if tag in seen:
                continue
            seen.add(tag)
            items = sorted(
                buckets.get(tag, []),
                key=lambda i: (i.order, i.label),
            )
            extra_items = self._build_extra_items(cfg.extra_items)
            all_items = sorted(items + extra_items, key=lambda i: i.order)
            groups.append(
                BuiltNavGroup(
                    tag=tag,
                    label=cfg.label or tag.title(),
                    icon=cfg.icon,
                    order=cfg.order,
                    collapsed_by_default=cfg.collapsed_by_default,
                    permission_table=cfg.permission,
                    items=all_items,
                )
            )

        # Process any remaining buckets (no explicit config)
        for tag, items in buckets.items():
            if tag in seen:
                continue
            seen.add(tag)
            cfg = configured_lower.get(tag.lower())
            groups.append(
                BuiltNavGroup(
                    tag=tag,
                    label=cfg.label if cfg else tag.title(),
                    icon=cfg.icon if cfg else None,
                    order=cfg.order if cfg else 999,
                    collapsed_by_default=cfg.collapsed_by_default
                    if cfg
                    else False,
                    permission_table=cfg.permission if cfg else None,
                    items=sorted(items, key=lambda i: (i.order, i.label)),
                )
            )

        groups.sort(key=lambda g: (g.order, g.label))
        return groups

    def _get_tags(self, registered: RegisteredModel) -> list[str]:
        admin = registered.admin
        tags = getattr(admin, "tags", None)
        if tags:
            return list(tags)
        tag = getattr(admin, "tag", None)
        if tag:
            return [tag]
        return ["Other"]

    def _build_children(
        self, registered: RegisteredModel
    ) -> list[BuiltNavItem]:
        children_configs = getattr(registered.admin, "nav_children", None) or []
        result: list[BuiltNavItem] = []
        for child_cfg in children_configs:
            result.append(
                BuiltNavItem(
                    label=child_cfg.label,
                    url=child_cfg.url,
                    icon=getattr(child_cfg, "icon", None),
                    permission_table=getattr(child_cfg, "permission", None),
                )
            )
        return result

    def _build_extra_items(
        self, extras: list[NavItemConfig]
    ) -> list[BuiltNavItem]:
        return [
            BuiltNavItem(
                label=e.label,
                url=e.url,
                icon=e.icon,
                order=e.order,
                permission_table=e.permission,
            )
            for e in extras
        ]
