"""SQLAlchemy backend adapters implementing the multi-ORM protocol interfaces.

Contains:
- ``SqlAlchemyIntrospectionAdapter`` — model introspection (#23)
- ``SqlAlchemySessionAdapter`` — per-request session lifecycle (#24)
- ``SqlAlchemyQueryAdapter`` — chainable query building (#25)
- ``SqlAlchemyAuditBackend`` — change tracking: listeners, snapshot, diff (#29)
- ``SqlAlchemyDatabaseBackend`` — connection lifecycle & DDL (#30)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import inspect as sa_inspect

from fastapi_admin_kit.types import ColumnMeta, RelationMeta


def _is_async_session(session: Any) -> bool:
    """Return True if *session* is an SQLAlchemy async session."""
    from sqlalchemy.ext.asyncio import AsyncSession

    return isinstance(session, AsyncSession)


# ---------------------------------------------------------------------------
# #23 — Introspection Adapter
# ---------------------------------------------------------------------------


class SqlAlchemyIntrospectionAdapter:
    """Reflects SQLAlchemy model metadata into ColumnMeta / RelationMeta.

    Implements :class:`IntrospectionBackend` via structural subtyping.
    """

    def inspect_model(self, model: type) -> tuple[list[ColumnMeta], list[RelationMeta]]:
        """Inspect a SQLAlchemy model and return column + relationship metadata."""
        mapper = sa_inspect(model)
        columns: list[ColumnMeta] = []
        relationships: list[RelationMeta] = []

        is_sqlmodel = self._is_sqlmodel(model)

        for col in mapper.columns:
            col_type = col.type
            if is_sqlmodel:
                col_type = self._resolve_sqlmodel_type(model, col.key, col.type)
            columns.append(
                ColumnMeta(
                    name=col.key,
                    type=col_type,
                    nullable=col.nullable,
                    primary_key=col.primary_key,
                    foreign_keys=list(col.foreign_keys),
                    default=col.default,
                    server_default=col.server_default,
                    index=col.index,
                    unique=col.unique,
                )
            )

        for rel in mapper.relationships:
            try:
                relationships.append(
                    RelationMeta(
                        name=rel.key,
                        direction=rel.direction.name,
                        target_model=rel.mapper.class_,
                        uselist=rel.uselist,
                        back_populates=rel.back_populates,
                        secondary=rel.secondary,
                    )
                )
            except Exception:
                pass

        return columns, relationships

    def get_pk_field(self, model: type) -> str | tuple[str, ...] | None:
        """Return the primary key field name(s) for a model."""
        mapper = sa_inspect(model)
        pk_cols = mapper.primary_key
        if not pk_cols:
            return None
        if len(pk_cols) == 1:
            return pk_cols[0].key
        return tuple(col.key for col in pk_cols)

    def cast_pk_value(self, model: type, value: Any) -> Any:
        """Cast a string PK value to the correct Python type for the model."""
        if value is None:
            return None
        mapper = sa_inspect(model)
        pk_cols = mapper.primary_key
        if not pk_cols or len(pk_cols) != 1:
            return value
        pk_col = pk_cols[0]
        from sqlalchemy import BigInteger, Integer
        from sqlalchemy.dialects.postgresql import UUID as PG_UUID
        from sqlalchemy.types import Uuid

        col_type = type(pk_col.type)
        if col_type in (Integer, BigInteger):
            return int(value)
        if col_type in (PG_UUID, Uuid):
            from uuid import UUID

            return UUID(str(value))
        return value

    def is_abstract(self, model: type) -> bool:
        """Return True if the model is abstract and should be skipped."""
        return getattr(model, "__abstract__", False)

    def get_relationship_names(self, model: type) -> set[str]:
        """Return the set of relationship key names on a model."""
        mapper = sa_inspect(model)
        return {r.key for r in mapper.relationships}

    def get_relationship(self, model: type, name: str) -> Any:
        """Return a single relationship descriptor by name, or None."""
        mapper = sa_inspect(model)
        return mapper.relationships.get(name)

    def get_column_type_name(self, model: type, field_name: str) -> str | None:
        """Return the SQLAlchemy type class name for a column, or None."""
        mapper = sa_inspect(model)
        for prop in mapper.column_attrs:
            if prop.key == field_name:
                col = prop.columns[0] if prop.columns else None
                if col is not None:
                    return col.type.__class__.__name__
        return None

    def get_column_attr(self, model: type, field_name: str) -> Any:
        """Return the column attribute for a field name, or None."""
        mapper = sa_inspect(model)
        for prop in mapper.column_attrs:
            if prop.key == field_name:
                col = prop.columns[0] if prop.columns else None
                return col
        return None

    def get_pk_columns(self, model: type) -> list[Any]:
        """Return the primary key column(s) for a model."""
        mapper = sa_inspect(model)
        return list(mapper.primary_key)

    # -- internal helpers ---------------------------------------------------

    def _is_sqlmodel(self, model: type) -> bool:
        try:
            from sqlmodel import SQLModel

            return isinstance(model, type) and issubclass(model, SQLModel)
        except ImportError:
            return False

    def _resolve_sqlmodel_type(self, model: type, field_name: str, default_type: Any) -> Any:
        try:
            from sqlmodel import SQLModel

            if not (isinstance(model, type) and issubclass(model, SQLModel)):
                return default_type

            sqlmodel_fields = getattr(model, "__sqlmodel_fields__", {})
            if field_name not in sqlmodel_fields:
                return default_type

            field_info = sqlmodel_fields[field_name]
            annotation = getattr(field_info, "annotation", None)
            if annotation is None:
                return default_type

            import sqlalchemy as sa

            type_map = {
                int: sa.Integer,
                str: sa.String,
                float: sa.Float,
                bool: sa.Boolean,
            }

            origin = getattr(annotation, "__origin__", None)
            if origin is not None:
                args = getattr(annotation, "__args__", ())
                if args:
                    inner = args[0]
                    if inner in type_map:
                        return type_map[inner]

            if annotation in type_map:
                return type_map[annotation]
            return default_type
        except Exception:
            return default_type


# ---------------------------------------------------------------------------
# #24 — Session Adapter
# ---------------------------------------------------------------------------


class SqlAlchemySessionAdapter:
    """Wraps an ``AsyncSession`` (or sync ``Session``) to implement
    :class:`SessionBackend`.

    When wrapping an ``AsyncSession``, all methods that talk to the DB
    return awaitable coroutines so that existing ``await session.flush()``
    call-sites continue to work.
    """

    def __init__(self, session: Any) -> None:
        self._session = session
        self._is_async = hasattr(session, "__await__") or _is_async_session(session)

    @property
    def session(self) -> Any:
        return self._session

    def _maybe_async(self, coro: Any) -> Any:
        """If the underlying session is async and we're in an async context,
        return the coroutine so the caller can ``await`` it.
        Otherwise run it synchronously and return the result."""
        if self._is_async and hasattr(coro, "__await__"):
            return coro
        if hasattr(coro, "__await__"):
            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                return coro
            return loop.run_until_complete(coro) if loop else coro
        return coro

    def get(self, model: type, pk: Any) -> Any | None:
        """Fetch a single object by primary key."""
        coro = self._session.get(model, pk)
        if self._is_async:
            return coro
        return coro

    def add(self, obj: Any) -> None:
        """Stage an object for insertion."""
        self._session.add(obj)

    def flush(self) -> Any:
        """Flush pending changes to the DB without committing."""
        result = self._session.flush()
        if hasattr(result, "__await__"):
            return self._maybe_async(result)
        return result

    def delete(self, obj: Any) -> Any:
        """Mark an object for deletion."""
        result = self._session.delete(obj)
        if hasattr(result, "__await__"):
            return self._maybe_async(result)
        return result

    def refresh(self, obj: Any, attributes: Sequence[str] | None = None) -> Any:
        """Re-read object attributes from the DB."""
        kwargs = {}
        if attributes:
            kwargs["attribute_names"] = list(attributes)
        result = self._session.refresh(obj, **kwargs)
        if hasattr(result, "__await__"):
            return self._maybe_async(result)
        return result

    def execute(self, query: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute a query object and return the result."""
        result = self._session.execute(query, *args, **kwargs)
        if hasattr(result, "__await__"):
            return self._maybe_async(result)
        return result

    def commit(self) -> Any:
        """Persist all pending changes."""
        result = self._session.commit()
        if hasattr(result, "__await__"):
            return self._maybe_async(result)
        return result

    def rollback(self) -> Any:
        """Discard all pending changes."""
        result = self._session.rollback()
        if hasattr(result, "__await__"):
            return self._maybe_async(result)
        return result

    def close(self) -> Any:
        """Close the underlying session."""
        result = self._session.close()
        if hasattr(result, "__await__"):
            return self._maybe_async(result)
        return result


# ---------------------------------------------------------------------------
# #25 — Query Adapter
# ---------------------------------------------------------------------------


class SqlAlchemyQueryAdapter:
    """Chainable wrapper around SQLAlchemy ``select()`` statements.

    Implements :class:`QueryBackend` via structural subtyping.
    """

    def select(self, model: type) -> Any:
        """Start a new query for the given model."""
        from sqlalchemy import select as sa_select

        return sa_select(model)

    def where(self, query: Any, *conditions: Any) -> Any:
        """Add WHERE conditions (AND composition)."""
        return query.where(*conditions)

    def order_by(self, query: Any, *columns: Any) -> Any:
        """Add ORDER BY clauses.  Prefix ``-`` for descending."""
        from sqlalchemy import asc, desc

        resolved: list[Any] = []
        for col in columns:
            if isinstance(col, str) and col.startswith("-"):
                resolved.append(desc(col[1:]))
            else:
                resolved.append(asc(col) if isinstance(col, str) else col)
        return query.order_by(*resolved)

    def limit(self, query: Any, n: int) -> Any:
        """Limit the result set to *n* rows."""
        return query.limit(n)

    def offset(self, query: Any, n: int) -> Any:
        """Skip the first *n* rows of the result set."""
        return query.offset(n)

    def join(self, query: Any, related: type, on: Any | None = None) -> Any:
        """Join a related model onto the query."""
        if on is not None:
            return query.join(related, on)
        return query.join(related)

    def distinct(self, query: Any) -> Any:
        """Add DISTINCT to the query."""
        return query.distinct()

    def count(self, query: Any) -> int:
        """Execute the query and return the total row count.

        Wraps the query in a subquery and counts all rows.
        """
        from sqlalchemy import func
        from sqlalchemy import select as sa_select

        # Extract the selectable from the query
        subq = query.subquery()
        count_q = sa_select(func.count()).select_from(subq)
        # The caller must execute this; return the compiled query
        # so the caller can pass it to session.execute()
        return count_q

    def options(self, query: Any, *opts: Any) -> Any:
        """Add eager-load options (joinedload, selectinload, etc.)."""
        return query.options(*opts)

    def ilike(self, column: Any, pattern: str) -> Any:
        """Apply case-insensitive LIKE to a column, returning a boolean clause."""
        return column.ilike(pattern)

    def or_(self, *clauses: Any) -> Any:
        """Compose multiple boolean clauses with OR."""
        from sqlalchemy import or_

        return or_(*clauses)


# ---------------------------------------------------------------------------
# #29 — Audit Backend
# ---------------------------------------------------------------------------


class SqlAlchemyAuditBackend:
    """Implements :class:`AuditBackend` via structural subtyping.

    Wraps the SQLAlchemy-specific audit listener, snapshot, and diff logic
    so the rest of the codebase can use the protocol interface.
    """

    def attach_listeners(self, session_factory: Any, registry: Any) -> None:
        """Wire up SQLAlchemy ``before_flush`` and ``after_flush_postexec`` listeners."""
        from fastapi_admin_kit.audit.listener import attach_audit_listener

        attach_audit_listener(session_factory, registry)

    def snapshot(self, obj: Any) -> dict[str, Any]:
        """Snapshot all mapped columns of a SQLAlchemy model instance."""
        from sqlalchemy.inspection import inspect as sa_inspect

        from fastapi_admin_kit.audit.diff import serialize_value

        if not hasattr(obj, "__table__"):
            raise ValueError("Object is not a SQLAlchemy model instance")
        mapper = sa_inspect(obj.__class__)
        data: dict[str, Any] = {}
        for column in mapper.columns:
            data[column.key] = serialize_value(getattr(obj, column.key))
        return data

    def compute_diff(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        """Compute changed fields between two snapshots."""
        diff: dict[str, Any] = {}
        all_keys = set(before.keys()) | set(after.keys())
        for key in all_keys:
            old_val = before.get(key)
            new_val = after.get(key)
            if old_val != new_val:
                diff[key] = {"old": old_val, "new": new_val}
        return diff


# ---------------------------------------------------------------------------
# #30 — Database Backend
# ---------------------------------------------------------------------------


class SqlAlchemyDatabaseBackend:
    """Wraps ``AdminDatabase``'s engine/table/migration logic to implement
    :class:`DatabaseBackend`.
    """

    def __init__(
        self,
        admin_database: Any | None = None,
        database_config: Any | None = None,
    ) -> None:
        self._admin_database = admin_database
        self._database_config = database_config

    def create_connection(self) -> Any:
        """Create and return a new SQLAlchemy async engine."""
        if self._admin_database is not None:
            self._admin_database._ensure_engine()
            return self._admin_database.engine
        if self._database_config is not None:
            return self._database_config.create_engine()
        raise ValueError("No admin_database or database_config provided")

    def create_tables(self, connection: Any, metadata: Any) -> None:
        """Issue DDL to create all tables defined in *metadata*.

        For async engines, ``connection`` should be the engine itself;
        tables are created via ``run_sync``.
        """
        from sqlalchemy.ext.asyncio import AsyncEngine

        if isinstance(connection, AsyncEngine):
            import asyncio

            async def _create() -> None:
                async with connection.begin() as conn:
                    await conn.run_sync(metadata.create_all)

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                # We're inside an async context — caller should use run_sync
                return _create()
            asyncio.run(_create())
        else:
            metadata.create_all(bind=connection)

    def auto_migrate(self, connection: Any, metadata: Any) -> None:
        """Detect schema drift and add missing columns automatically."""
        from sqlalchemy.ext.asyncio import AsyncEngine

        if isinstance(connection, AsyncEngine):
            if self._admin_database is not None:
                import asyncio

                async def _migrate() -> None:
                    async with connection.begin() as conn:
                        await conn.run_sync(self._admin_database._auto_migrate, metadata)

                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop and loop.is_running():
                    return _migrate()
                asyncio.run(_migrate())
        elif self._admin_database is not None:
            self._admin_database._auto_migrate_sync(metadata)

    def create_session_factory(self, connection: Any) -> Any:
        """Create an ``async_sessionmaker`` bound to *connection*."""
        from fastapi_admin_kit.db import create_session_factory

        return create_session_factory(connection)

    def materialize(
        self,
        schema: Any,
        base: Any | None = None,
    ) -> type:
        """Convert a :class:`Schema` into a SQLAlchemy model class.

        This is the materialization layer of the three-layer architecture:

        1. **Protocol** — contract definition (``auth/protocol.py``)
        2. **Schema** — declarative model definitions (``schemas/builtin.py``)
        3. **Materialization** — this method converts schemas to native models

        Args:
            schema: A :class:`~fastapi_admin_kit.schemas.schema.Schema` instance
                describing the model structure.
            base: The SQLAlchemy declarative base class. If ``None``, falls back
                to the configured ``AdminDatabase.base`` or ``Base``.

        Returns:
            A new SQLAlchemy model class with ``__tablename__`` and mapped columns.

        Example::

            from fastapi_admin_kit.schemas.builtin import USER_SCHEMA

            backend = SqlAlchemyDatabaseBackend(admin_database=db)
            UserModel = backend.materialize(USER_SCHEMA, base=Base)
            # UserModel is a class usable with SQLAlchemy
        """
        from sqlalchemy import (
            Boolean,
            Column,
            DateTime,
            Float,
            Integer,
            String,
            Text,
        )
        from sqlalchemy.dialects.postgresql import JSON as PG_JSON
        from sqlalchemy.sql import func

        from fastapi_admin_kit.schemas.schema import Schema as SchemaType

        if not isinstance(schema, SchemaType):
            raise TypeError(f"Expected Schema instance, got {type(schema).__name__}")

        if base is None and self._admin_database is not None:
            base = getattr(self._admin_database, "base", None)
        if base is None:
            from fastapi_admin_kit.models.base import Base

            base = Base

        type_map: dict[str, type] = {
            "integer": Integer,
            "string": String,
            "text": Text,
            "boolean": Boolean,
            "datetime": DateTime(timezone=True),
            "float": Float,
            "json": PG_JSON,
        }

        columns: list[Column] = []
        for f in schema.fields:
            sa_type = type_map.get(f.type, String)

            kwargs: dict[str, Any] = {}
            if f.primary_key:
                kwargs["primary_key"] = True
            if f.auto_increment and f.primary_key:
                kwargs["autoincrement"] = True
            if f.nullable and not f.primary_key:
                kwargs["nullable"] = True
            elif not f.nullable:
                kwargs["nullable"] = False
            if f.unique:
                kwargs["unique"] = True
            if f.max_length and sa_type is String:
                sa_type = String(f.max_length)
            if f.default is not None:
                kwargs["default"] = f.default
            if f.server_default is not None:
                if f.server_default == "now()":
                    kwargs["server_default"] = func.now()
                else:
                    kwargs["server_default"] = f.server_default
            if f.index and not f.primary_key:
                kwargs["index"] = True

            columns.append(Column(f.name, sa_type, **kwargs))

        # Build the model class dynamically
        table_name = schema.table_name
        model_attrs: dict[str, Any] = {
            "__tablename__": table_name,
            "__table_args__": {"extend_existing": True},
        }
        for col in columns:
            model_attrs[col.key] = col

        model_class = type(table_name, (base,), model_attrs)
        return model_class
