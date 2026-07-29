"""Model inspection types — ColumnMeta, RelationMeta."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
