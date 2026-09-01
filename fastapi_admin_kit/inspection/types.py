"""Model inspection types — ColumnMeta, RelationMeta."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {
        "password",
        "password_changed_at",
        "secret",
        "secret_key",
        "token",
        "refresh_token",
    }
)
"""Column names that must never appear in serialized API output."""

PRIVILEGED_ASSIGNMENT_FIELDS: frozenset[str] = frozenset(
    {
        "is_superuser",
        "is_active",
        "roles",
    }
)
"""User-model fields a non-superuser actor must never write (mass assignment).

Distinct from :data:`SENSITIVE_FIELDS`: sensitive fields are secret
*values* kept out of serialization; privileged fields are privilege-
granting columns kept out of unprivileged *writes*.
"""


@dataclass
class ColumnMeta:
    """Metadata for a single SQLAlchemy column."""

    name: str
    type: Any  # SQLAlchemy type instance
    nullable: bool = True
    primary_key: bool = False
    foreign_keys: list = field(default_factory=list)
    default: Any = None
    server_default: Any = None
    index: bool = False
    unique: bool = False

    @property
    def is_foreign_key(self) -> bool:
        return bool(self.foreign_keys)


@dataclass
class RelationMeta:
    """Metadata for a single SQLAlchemy relationship."""

    name: str
    direction: str  # MANYTOONE, ONETOMANY, MANYTOMANY
    target_model: type
    uselist: bool = True
    back_populates: str | None = None
    secondary: Any = None  # association table for many-to-many
