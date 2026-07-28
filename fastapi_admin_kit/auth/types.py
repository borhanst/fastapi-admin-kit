"""Auth types — permissions and role seeding configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PermissionSet:
    """Set of boolean permissions for a single model."""

    can_view: bool = False
    can_create: bool = False
    can_edit: bool = False
    can_delete: bool = False


@dataclass
class SeedRole:
    """Defines a role to be seeded on first startup."""

    name: str
    description: str = ""
    permissions: dict[str, dict[str, bool]] = field(default_factory=dict)
