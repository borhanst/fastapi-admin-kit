"""Protocol interfaces for multi-ORM backend support.

These protocols define the contracts that all ORM backends (SQLAlchemy,
MongoDB/ODM, future) must implement. They are the seam that decouples
the rest of the codebase from any specific ORM.

Use structural subtyping — any class that satisfies the protocol's
method signatures is a valid implementation, no inheritance required.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, TypeVar, runtime_checkable

from fastapi_admin_kit.types import ColumnMeta, RelationMeta

ModelT = TypeVar("ModelT")
ObjT = TypeVar("ObjT")

# Type aliases — the rest of the codebase should reference these
# instead of SQLAlchemy-specific types.
QueryType = Any
SessionType = Any
ColumnMetaType = ColumnMeta
RelationMetaType = RelationMeta


@runtime_checkable
class IntrospectionBackend(Protocol):
    """Model introspection: reflect columns, relationships, PKs, and abstractness."""

    def inspect_model(self, model: type) -> tuple[list[ColumnMeta], list[RelationMeta]]:
        """Inspect a model and return its column and relationship metadata."""
        ...

    def get_pk_field(self, model: type) -> str | tuple[str, ...] | None:
        """Return the primary key field name(s) for a model."""
        ...

    def cast_pk_value(self, model: type, value: Any) -> Any:
        """Cast a string PK value to the correct Python type for the model."""
        ...

    def is_abstract(self, model: type) -> bool:
        """Return True if the model is abstract and should be skipped."""
        ...


@runtime_checkable
class SessionBackend(Protocol):
    """Data access: per-request session lifecycle."""

    def get(self, model: type[ModelT], pk: Any) -> ModelT | None:
        """Fetch a single object by primary key."""
        ...

    def add(self, obj: Any) -> None:
        """Stage an object for insertion."""
        ...

    def flush(self) -> None:
        """Flush pending changes to the DB without committing."""
        ...

    def delete(self, obj: Any) -> None:
        """Mark an object for deletion."""
        ...

    def refresh(self, obj: Any, attributes: Sequence[str] | None = None) -> None:
        """Re-read object attributes from the DB."""
        ...

    def execute(self, query: QueryType) -> Any:
        """Execute a query object and return the result."""
        ...

    def commit(self) -> None:
        """Persist all pending changes."""
        ...

    def rollback(self) -> None:
        """Discard all pending changes."""
        ...


@runtime_checkable
class QueryBackend(Protocol):
    """Chainable query building: select, filter, sort, join, paginate."""

    def select(self, model: type[ModelT]) -> QueryType:
        """Start a new query for the given model."""
        ...

    def where(self, query: QueryType, *conditions: Any) -> QueryType:
        """Add WHERE conditions to a query."""
        ...

    def order_by(self, query: QueryType, *columns: Any) -> QueryType:
        """Add ORDER BY clauses to a query."""
        ...

    def limit(self, query: QueryType, n: int) -> QueryType:
        """Limit the result set to *n* rows."""
        ...

    def offset(self, query: QueryType, n: int) -> QueryType:
        """Skip the first *n* rows of the result set."""
        ...

    def join(self, query: QueryType, related: type, on: Any | None = None) -> QueryType:
        """Join a related model onto the query."""
        ...

    def distinct(self, query: QueryType) -> QueryType:
        """Add DISTINCT to the query."""
        ...

    def count(self, query: QueryType) -> int:
        """Execute the query and return the total row count."""
        ...


@runtime_checkable
class AuditBackend(Protocol):
    """Change tracking: attach listeners, snapshot, and diff objects."""

    def attach_listeners(self, session_factory: Any, registry: dict[str, Any]) -> None:
        """Register change-tracking listeners on the session factory."""
        ...

    def snapshot(self, obj: Any) -> dict[str, Any]:
        """Capture a serialisable snapshot of the object's current state."""
        ...

    def compute_diff(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        """Return a dict of {field: (old_value, new_value)} for changed fields."""
        ...


@runtime_checkable
class DatabaseBackend(Protocol):
    """Connection lifecycle: create engine, run DDL, auto-migrate."""

    def create_connection(self) -> Any:
        """Create and return a new database connection or engine."""
        ...

    def create_tables(self, connection: Any, metadata: Any) -> None:
        """Issue DDL to create all tables defined in *metadata*."""
        ...

    def auto_migrate(self, connection: Any, metadata: Any) -> None:
        """Detect schema drift and apply migrations automatically."""
        ...
