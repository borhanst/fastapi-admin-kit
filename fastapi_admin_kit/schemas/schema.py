"""Schema, Field, and Relation dataclasses for declarative model definitions.

These dataclasses describe the structure of admin models in a
backend-agnostic way. Each backend (SQLAlchemy, Beanie, Django) implements
``materialize(schema)`` to convert these into native ORM models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Field:
    """A single field definition in a schema.

    Attributes:
        name: Column/field name.
        type: Field type string (``"integer"``, ``"string"``, ``"boolean"``,
              ``"datetime"``, ``"text"``, ``"json"``, ``"float"``).
        primary_key: Whether this is the primary key.
        auto_increment: Whether the DB auto-generates the value.
        nullable: Whether the field allows NULL.
        unique: Whether a unique constraint applies.
        max_length: Maximum length for string fields.
        default: Python default value (used by ORM).
        server_default: Server-side default expression (e.g., ``"now()"``).
        index: Whether to create a DB index.
        choices: Optional list of ``(value, label)`` tuples for select fields.
        description: Human-readable description.
    """

    name: str
    type: str = "string"
    primary_key: bool = False
    auto_increment: bool = False
    nullable: bool = True
    unique: bool = False
    max_length: int | None = None
    default: Any = None
    server_default: str | None = None
    index: bool = False
    choices: list[tuple[str, str]] | None = None
    description: str | None = None


@dataclass
class Relation:
    """A relationship definition in a schema.

    Attributes:
        name: Relationship attribute name.
        target: Target table name (``"admin_roles"``, etc.).
        type: Relationship type (``"many_to_many"``, ``"one_to_many"``,
              ``"many_to_one"``).
        through: Junction table name (for ``many_to_many``).
        back_populates: Back-reference attribute name on the target.
    """

    name: str
    target: str
    type: str = "many_to_many"  # many_to_many | one_to_many | many_to_one
    through: str | None = None
    back_populates: str | None = None


@dataclass
class Schema:
    """Declarative model definition — backend-agnostic.

    A schema defines the table name, fields, and relationships for an
    admin model. Backends convert schemas to native ORM models via
    ``materialize()``.

    Attributes:
        table_name: Database table name.
        fields: List of field definitions.
        relations: List of relationship definitions.
        description: Human-readable model description.
        verbose_name: Display name for the model.
        verbose_name_plural: Plural display name.
    """

    table_name: str
    fields: list[Field] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    description: str | None = None
    verbose_name: str | None = None
    verbose_name_plural: str | None = None

    def get_field(self, name: str) -> Field | None:
        """Return a field by name, or None if not found."""
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def get_pk_field(self) -> Field | None:
        """Return the primary key field, or None."""
        for f in self.fields:
            if f.primary_key:
                return f
        return None

    def get_relation(self, name: str) -> Relation | None:
        """Return a relation by name, or None if not found."""
        for r in self.relations:
            if r.name == name:
                return r
        return None

    def field_names(self) -> list[str]:
        """Return all field names."""
        return [f.name for f in self.fields]

    def relation_names(self) -> list[str]:
        """Return all relation names."""
        return [r.name for r in self.relations]
