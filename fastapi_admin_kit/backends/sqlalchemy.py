"""SQLAlchemy backend adapters implementing the multi-ORM protocol interfaces.

Contains:
- ``SqlAlchemyIntrospectionAdapter`` — model introspection (#23)
- ``SqlAlchemySessionAdapter`` — per-request session lifecycle (#24)
- ``SqlAlchemyQueryAdapter`` — chainable query building (#25)
- ``SqlAlchemyAuditBackend`` — change tracking: listeners, snapshot, diff (#29)
- ``SqlAlchemyDatabaseBackend`` — connection lifecycle & DDL (#30)
- ``SqlAlchemyBackend`` — composite backend wiring all adapters together
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy import inspect as sa_inspect

from fastapi_admin_kit.inspection.types import ColumnMeta, RelationMeta

if TYPE_CHECKING:
    from fastapi_admin_kit.admin.admin_database import AdminDatabase


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

    def get_relationship_local_columns(self, model: type, name: str) -> list[str]:
        """Return the local column key(s) for a relationship.

        For MANYTOONE relationships, these are the foreign key columns.
        For ONETOMANY/MANYTOMANY, returns the local columns that participate
        in the relationship (may be empty for purely reverse relationships).
        """
        mapper = sa_inspect(model)
        rel = mapper.relationships.get(name)
        if rel is None:
            return []
        return [c.key for c in rel.local_columns]

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

    def all(self, query: Any, unique: bool = False) -> Any:
        """Execute *query* and return all rows as ORM objects."""
        result = self.execute(query)
        if hasattr(result, "__await__"):

            async def _run() -> list[Any]:
                r = await result
                scalars = r.scalars()
                if unique:
                    scalars = scalars.unique()
                return scalars.all()

            return _run()
        scalars = result.scalars()
        if unique:
            scalars = scalars.unique()
        return scalars.all()

    def first(self, query: Any, unique: bool = False) -> Any | None:
        """Execute *query* and return the first row as an ORM object, or None."""
        result = self.execute(query)
        if hasattr(result, "__await__"):

            async def _run() -> Any | None:
                r = await result
                scalars = r.scalars()
                if unique:
                    scalars = scalars.unique()
                return scalars.first()

            return _run()
        scalars = result.scalars()
        if unique:
            scalars = scalars.unique()
        return scalars.first()

    def rows(self, query: Any) -> Any:
        """Execute *query* and return all rows as tuples/Rows (no scalar unwrap)."""
        result = self.execute(query)
        if hasattr(result, "__await__"):

            async def _run() -> list[Any]:
                return (await result).all()

            return _run()
        return result.all()

    def scalar(self, query: Any) -> Any | None:
        """Execute *query* and return the first column of the first row, or None."""
        result = self.execute(query)
        if hasattr(result, "__await__"):

            async def _run() -> Any | None:
                return (await result).scalar()

            return _run()
        return result.scalar()

    def scalar_one(self, query: Any) -> Any:
        """Execute *query* and return the first column of the first (only) row."""
        result = self.execute(query)
        if hasattr(result, "__await__"):

            async def _run() -> Any:
                return (await result).scalar_one()

            return _run()
        return result.scalar_one()

    def scalar_one_or_none(self, query: Any) -> Any | None:
        """Execute *query* and return the first column or None (no/one row)."""
        result = self.execute(query)
        if hasattr(result, "__await__"):

            async def _run() -> Any | None:
                return (await result).scalar_one_or_none()

            return _run()
        return result.scalar_one_or_none()

    def count(self, query: Any) -> int:
        """Execute a count *query* and return the integer total."""
        result = self.execute(query)
        if hasattr(result, "__await__"):

            async def _run() -> int:
                return (await result).scalar() or 0

            return _run()
        return result.scalar() or 0

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

    def and_(self, *clauses: Any) -> Any:
        """Compose multiple boolean clauses with AND."""
        from sqlalchemy import and_

        return and_(*clauses)


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

    def create_tables(self, connection: Any, metadata: Any, tables: Any = None) -> Any:
        """Issue DDL to create the given *tables* (or all of *metadata*).

        For async engines, ``connection`` should be the engine itself;
        tables are created via ``run_sync``.
        """
        from sqlalchemy.ext.asyncio import AsyncEngine

        if connection is None:
            raise RuntimeError(
                "create_tables called with connection=None — the Admin "
                "instance has no engine. Pass `engine=` or `database_config=` "
                "to Admin(), or set `use_alembic=True` to skip create_all."
            )

        if isinstance(connection, AsyncEngine):

            async def _create() -> None:
                async with connection.begin() as conn:
                    await conn.run_sync(metadata.create_all, tables)

            return self._run_async(_create)
        metadata.create_all(bind=connection, tables=tables)

    def auto_migrate(self, connection: Any, metadata: Any) -> Any:
        """Detect schema drift and add missing columns automatically."""
        from sqlalchemy.ext.asyncio import AsyncEngine

        if isinstance(connection, AsyncEngine):

            async def _migrate() -> None:
                async with connection.begin() as conn:
                    await conn.run_sync(self._auto_migrate, metadata)

            return self._run_async(_migrate)
        self._auto_migrate_sync(connection, metadata)

    @staticmethod
    def _run_async(coro_factory: Any) -> Any:
        """Run *coro_factory* within the current loop or via ``asyncio.run``."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            return coro_factory()
        return asyncio.run(coro_factory())

    def _auto_migrate_sync(self, connection: Any, metadata: Any) -> None:
        """Sync version of auto-migrate (called with a sync connection)."""
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy import text

        from fastapi_admin_kit.admin.admin_database import _validate_identifier

        inspector = sa_inspect(connection)
        for table_name, table in metadata.tables.items():
            if not inspector.has_table(table_name):
                continue
            safe_table = _validate_identifier(table_name)
            existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name not in existing_cols:
                    safe_col = _validate_identifier(col.name, "column")
                    col_type = col.type.compile(connection.dialect)
                    nullable = "NULL" if col.nullable else "NOT NULL"
                    default = ""
                    if col.server_default is not None:
                        default_sql = col.server_default.arg
                        if hasattr(default_sql, "text"):
                            default_sql = default_sql.text
                        default = f" DEFAULT {default_sql}"
                    elif col.default is not None and col.default.is_seq:
                        pass
                    sql = text(
                        f"""ALTER TABLE {safe_table}
                        ADD COLUMN {safe_col} {col_type}
                        {nullable}{default}"""
                    )
                    with connection.begin() as conn:
                        conn.execute(sql)

    def _auto_migrate(self, sync_conn: Any, metadata: Any) -> None:
        """Add missing columns to existing tables (sync, called via run_sync)."""
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy import text

        from fastapi_admin_kit.admin.admin_database import _validate_identifier

        dialect = sync_conn.dialect if hasattr(sync_conn, "dialect") else None
        if dialect is None:
            return

        inspector = sa_inspect(sync_conn)
        for table_name, table in metadata.tables.items():
            if not inspector.has_table(table_name):
                continue
            safe_table = _validate_identifier(table_name)
            existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name not in existing_cols:
                    safe_col = _validate_identifier(col.name, "column")
                    col_type = col.type.compile(dialect)
                    nullable = "NULL" if col.nullable else "NOT NULL"
                    default = ""
                    if col.server_default is not None:
                        default_sql = col.server_default.arg
                        if hasattr(default_sql, "text"):
                            default_sql = default_sql.text
                        default = f" DEFAULT {default_sql}"
                    elif not col.nullable:
                        # SQLite requires a default for NOT NULL columns being added
                        type_defaults = {
                            "VARCHAR": "''",
                            "TEXT": "''",
                            "INTEGER": "0",
                            "FLOAT": "0.0",
                            "BOOLEAN": "0",
                            "DATETIME": "''",
                        }
                        sql_type = col_type.upper().split("(")[0]
                        temp_val = type_defaults.get(sql_type, "''")
                        default = f" DEFAULT {temp_val}"
                    sql = text(
                        f"""ALTER TABLE {safe_table}
                        ADD COLUMN
                        {safe_col} {col_type} {nullable}{default}
                        """
                    )
                    sync_conn.execute(sql)

    def create_session_factory(self, connection: Any) -> Any:
        """Return a zero-arg callable yielding a :class:`SessionBackend`."""
        from sqlalchemy.ext.asyncio import AsyncEngine

        if isinstance(connection, AsyncEngine):
            from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

            sm = async_sessionmaker(
                bind=connection,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            def factory() -> SqlAlchemySessionAdapter:
                return SqlAlchemySessionAdapter(sm())

            return factory

        from sqlalchemy.orm import sessionmaker

        sm = sessionmaker(bind=connection, expire_on_commit=False)

        def factory() -> SqlAlchemySessionAdapter:
            return SqlAlchemySessionAdapter(sm())

        return factory

    def has_tables(self, connection: Any, names: list[str]) -> set[str]:
        """Return the subset of *names* whose tables do not yet exist."""
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy.ext.asyncio import AsyncEngine

        if isinstance(connection, AsyncEngine):

            def _check(sync_conn: Any) -> set[str]:
                inspector = sa_inspect(sync_conn)
                return {n for n in names if not inspector.has_table(n)}

            async def _run() -> set[str]:
                async with connection.connect() as conn:
                    return await conn.run_sync(_check)

            return _run()
        inspector = sa_inspect(connection)
        return {n for n in names if not inspector.has_table(n)}

    def seed_roles(
        self,
        session_factory: Any,
        seed_roles: list[Any],
        overwrite: bool = False,
    ) -> Any:
        """Seed default roles/permissions using *session_factory*.

        Mirrors the previous ``AdminDatabase._seed_roles`` logic but consumes a
        backend-agnostic session factory (returns ``SessionBackend`` objects).
        """
        from sqlalchemy import delete as sa_delete
        from sqlalchemy import select as sa_select
        from sqlalchemy.ext.asyncio import AsyncSession

        from fastapi_admin_kit.migrations.models import (
            Permission,
            Role,
            admin_role_permissions,
        )

        session = session_factory()
        is_async = isinstance(getattr(session, "_session", session), AsyncSession)

        if is_async:

            async def _run_async() -> None:
                existing = await session.all(sa_select(Role))
                if existing and not overwrite:
                    return
                if overwrite:
                    await session.execute(sa_delete(admin_role_permissions))
                    await session.execute(sa_delete(Role))
                for role_spec in seed_roles:
                    role = Role(name=role_spec.name, description=role_spec.description)
                    session.add(role)
                    await session.flush()
                    await session.refresh(role, ["permissions"])
                    if role_spec.permissions:
                        for table_name, perms in role_spec.permissions.items():
                            existing_perm = await session.scalar_one_or_none(
                                sa_select(Permission).filter_by(table_name=table_name)
                            )
                            if existing_perm is None:
                                perm = Permission(
                                    name=table_name,
                                    table_name=table_name,
                                    can_view=perms.get("view", False),
                                    can_create=perms.get("create", False),
                                    can_edit=perms.get("edit", False),
                                    can_delete=perms.get("delete", False),
                                )
                                session.add(perm)
                                await session.flush()
                            else:
                                perm = existing_perm
                            role.permissions.append(perm)
                await session.commit()

            return _run_async()

        existing = session.all(sa_select(Role))
        if existing and not overwrite:
            return None
        if overwrite:
            session.execute(sa_delete(admin_role_permissions))
            session.execute(sa_delete(Role))
        for role_spec in seed_roles:
            role = Role(name=role_spec.name, description=role_spec.description)
            session.add(role)
            session.flush()
            if role_spec.permissions:
                for table_name, perms in role_spec.permissions.items():
                    existing_perm = session.scalar_one_or_none(
                        sa_select(Permission).filter_by(table_name=table_name)
                    )
                    if existing_perm is None:
                        perm = Permission(
                            name=table_name,
                            table_name=table_name,
                            can_view=perms.get("view", False),
                            can_create=perms.get("create", False),
                            can_edit=perms.get("edit", False),
                            can_delete=perms.get("delete", False),
                        )
                        session.add(perm)
                        session.flush()
                    else:
                        perm = existing_perm
                    role.permissions.append(perm)
        session.commit()
        return None

    @property
    def session_adapter_class(self) -> type:
        """Class wrapping a raw connection into a :class:`SessionBackend`."""
        return SqlAlchemySessionAdapter

    def materialize(
        self,
        schema: Any,
        base: Any | None = None,
        schemas: Any | None = None,
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
            schemas: Optional mapping of ``table_name -> Schema`` for every model
                being materialized. Used to derive the type of a foreign-key column
                from the referenced model's primary-key type (e.g. a ``user_id``
                column pointing at a User whose ``id`` is a UUID becomes a UUID
                instead of an integer/string).

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
            ForeignKey,
            Index,
            Integer,
            Numeric,
            String,
            Text,
        )
        from sqlalchemy.orm import relationship
        from sqlalchemy.sql import func
        from sqlalchemy.types import Uuid

        from fastapi_admin_kit.schemas.schema import Schema as SchemaType

        if not isinstance(schema, SchemaType):
            raise TypeError(f"Expected Schema instance, got {type(schema).__name__}")

        if base is None and self._admin_database is not None:
            base = getattr(self._admin_database, "base", None)
        if base is None:
            from fastapi_admin_kit.models.base import Base

            base = Base

        # Reuse an already-materialized class for this table instead of creating
        # a duplicate mapper. Duplicate mappers for the same table share a
        # declarative registry entry, so lazy relationship/back_populates
        # resolution can point at a stale copy and fail mapper configuration.
        for mapper in list(base.registry.mappers):
            table = mapper.local_table
            if table is not None and table.name == schema.table_name:
                return mapper.class_

        # Cross-dialect JSON type: native JSON where supported (PostgreSQL,
        # MySQL), TEXT with json.dumps/loads elsewhere (SQLite).
        from sqlalchemy import types

        class JSON(types.TypeDecorator):
            impl = Text
            cache_ok = True

            def load_dialect_impl(self, dialect):
                if dialect.name in ("postgresql", "mysql"):
                    return dialect.type_descriptor(types.JSON())
                return dialect.type_descriptor(Text())

            def _uses_native_json(self, dialect) -> bool:
                return dialect.name in ("postgresql", "mysql")

            def process_bind_param(self, value, dialect):
                import json

                if value is None or isinstance(value, str):
                    return value
                if self._uses_native_json(dialect):
                    return value
                return json.dumps(value)

            def process_result_value(self, value, dialect):
                import json

                if value is None:
                    return None
                if self._uses_native_json(dialect):
                    return value
                if isinstance(value, str):
                    return json.loads(value)
                return value

        type_map: dict[str, type] = {
            "integer": Integer,
            "string": String,
            "text": Text,
            "boolean": Boolean,
            "datetime": DateTime(timezone=True),
            "float": Float,
            "numeric": Numeric,
            "json": JSON,
            "uuid": Uuid,
        }

        # Map a schema field to its SQLAlchemy type instance. Used both for the
        # model columns and for deriving foreign-key column types from the
        # referenced model's primary key.
        def _schema_field_sa_type(fld: Any) -> Any:
            if fld.type == "string" and fld.max_length:
                return String(fld.max_length)
            return type_map.get(fld.type, String)

        # Resolve the SQLAlchemy type of a relation target's primary key so a
        # foreign-key column can mirror it (uuid vs int, etc.). *target* may be
        # a table-name string or a materialized model class.
        def _resolve_target_pk_type(target: Any) -> Any | None:
            if not isinstance(target, str):
                table = getattr(target, "__table__", None)
            else:
                table = None
                has_meta = base is not None and hasattr(base, "metadata")
                md = base.metadata.tables if has_meta else None
                if md is not None and target in md:
                    table = md[target]
                if table is None:
                    if schemas is None:
                        from fastapi_admin_kit.schemas.builtin import BUILTIN_SCHEMAS
                    reg = schemas if schemas is not None else BUILTIN_SCHEMAS
                    if reg and target in reg:
                        pk = reg[target].get_pk_field()
                        if pk is not None:
                            return _schema_field_sa_type(pk)
                    return None
            if table is None:
                return None
            pk_cols = list(table.primary_key.columns)
            if not pk_cols:
                return None
            return pk_cols[0].type

        columns: list[Column] = []
        existing_cols: dict[str, Any] = {}
        if base is not None and hasattr(base, "metadata"):
            existing_table = base.metadata.tables.get(schema.table_name)
            if existing_table is not None:
                existing_cols = {c.name: c for c in existing_table.columns}

        # Collect many_to_one target tables to know which columns need ForeignKey
        many_to_one_targets = {
            rel.target: rel.name for rel in schema.relations if rel.type == "many_to_one"
        }

        # Mirror a custom auth_model's primary-key type onto ``user_id`` columns
        # even when the field is NOT declared as a many_to_one FK relation. The
        # built-in schemas hardcode ``user_id`` as ``string``/``integer`` (the
        # legacy default) so a custom User with a UUID PK would otherwise be
        # materialized as the wrong SQL type. We only retype columns that
        # reference the user table (or any of the well-known user-id columns);
        # other FK columns are left to the many_to_one branch below.
        user_pk_type: Any | None = None
        if base is not None and hasattr(base, "metadata"):
            users_table = base.metadata.tables.get("admin_users")
            if users_table is not None:
                pk_cols_real = list(users_table.primary_key.columns)
                if pk_cols_real:
                    user_pk_type = pk_cols_real[0].type

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
            if f.name == "user_id" and user_pk_type is not None:
                sa_type = user_pk_type
            if f.default is not None:
                kwargs["default"] = f.default
            if f.server_default is not None:
                if f.server_default == "now()":
                    kwargs["server_default"] = func.now()
                else:
                    kwargs["server_default"] = f.server_default
            if f.index and not f.primary_key:
                existing_col = existing_cols.get(f.name)
                if existing_col is None or not existing_col.index:
                    kwargs["index"] = True

            # Add ForeignKey for many_to_one relationship columns
            # The FK column is typically named {target}_id where target is the table name
            # But we need to handle cases like admin_users -> user_id (not admin_user_id)
            fk_target = None
            for target_table, rel_name in many_to_one_targets.items():
                # Try common naming patterns for the FK column
                # Strip common prefixes like "admin_" from table name
                base_name = target_table
                if base_name.startswith("admin_"):
                    base_name = base_name[6:]  # Remove "admin_"

                possible_names = [
                    f"{base_name.rstrip('s')}_id",  # e.g., admin_users -> user_id
                    f"{base_name}_id",  # e.g., admin_users -> users_id
                    f"{target_table.rstrip('s')}_id",  # e.g., admin_users -> admin_user_id
                    f"{target_table}_id",  # e.g., admin_users -> admin_users_id
                ]
                for possible_name in possible_names:
                    if f.name == possible_name:
                        fk_target = target_table
                        break
                if fk_target:
                    break

            # Build column with ForeignKey if needed
            if fk_target:
                from sqlalchemy import ForeignKey

                # Mirror the referenced model's primary-key type (uuid vs int,
                # etc.) instead of blindly using the field's declared type.
                resolved_pk_type = _resolve_target_pk_type(fk_target)
                if resolved_pk_type is not None:
                    sa_type = resolved_pk_type

                # Use string-based FK to allow target table to not exist yet
                columns.append(
                    Column(f.name, sa_type, ForeignKey(f"{fk_target}.id", use_alter=True), **kwargs)
                )
            else:
                columns.append(Column(f.name, sa_type, **kwargs))

        # Build table args with indexes from schema
        # SQLAlchemy expects __table_args__ as tuple where last element is dict for options
        table_args_list: list[Any] = []

        # Check if table already exists in metadata (to avoid recreating indexes)
        existing_table = None
        if base is not None and hasattr(base, "metadata"):
            existing_table = base.metadata.tables.get(schema.table_name)

        if hasattr(schema, "indexes") and schema.indexes and existing_table is None:
            for idx_def in schema.indexes:
                if isinstance(idx_def, dict):
                    columns_list = idx_def.get("columns", [])
                    name = idx_def.get("name")
                    unique = idx_def.get("unique", False)
                    if columns_list:
                        table_args_list.append(Index(name, *columns_list, unique=unique))
        table_args_list.append({"extend_existing": True})
        table_args = tuple(table_args_list)

        # Build the model class dynamically
        table_name = schema.table_name
        model_attrs: dict[str, Any] = {
            "__tablename__": table_name,
            "__table_args__": table_args,
        }
        for col in columns:
            model_attrs[col.key] = col

        # Process relationships from schema (after model_attrs is defined)
        for rel in schema.relations:
            if rel.type == "many_to_many" and rel.through:
                # Many-to-many relationship using a junction table
                # Resolve the through table from metadata if it's a string and available
                secondary = rel.through
                if isinstance(secondary, str) and base is not None and hasattr(base, "metadata"):
                    table = base.metadata.tables.get(secondary)
                    if table is not None:
                        secondary = table
                # Pass the table (or string name) - SQLAlchemy will resolve it at mapper config time
                model_attrs[rel.name] = relationship(
                    rel.target,
                    secondary=secondary,
                    back_populates=rel.back_populates,
                )
            elif rel.type == "one_to_many":
                # One-to-many: foreign key is on the target table
                # Use same naming convention as many_to_one: strip "admin_" prefix and singularize
                base_name = table_name
                if base_name.startswith("admin_"):
                    base_name = base_name[6:]  # Remove "admin_"
                # Singularize: users -> user, roles -> role, etc.
                if base_name.endswith("s"):
                    base_name = base_name[:-1]
                fk_col_name = f"{base_name}_id"
                model_attrs[rel.name] = relationship(
                    rel.target,
                    back_populates=rel.back_populates,
                    foreign_keys=f"[{rel.target}.{fk_col_name}]",
                )
            elif rel.type == "many_to_one":
                # Many-to-one: foreign key is on this table
                # Use smarter FK column naming that handles prefixes like "admin_"
                target_table = rel.target
                base_name = target_table
                if base_name.startswith("admin_"):
                    base_name = base_name[6:]  # Remove "admin_"

                possible_names = [
                    f"{base_name.rstrip('s')}_id",  # e.g., admin_users -> user_id
                    f"{base_name}_id",  # e.g., admin_users -> users_id
                    f"{target_table.rstrip('s')}_id",  # e.g., admin_users -> admin_user_id
                    f"{target_table}_id",  # e.g., admin_users -> admin_users_id
                ]
                fk_col_name = None
                for possible_name in possible_names:
                    if possible_name in model_attrs:
                        fk_col_name = possible_name
                        break

                if fk_col_name:
                    model_attrs[rel.name] = relationship(
                        rel.target,
                        back_populates=rel.back_populates,
                        foreign_keys=model_attrs[fk_col_name],
                    )

        model_class = type(table_name, (base,), model_attrs)

        # Expose the schema's display names so the admin registry can derive
        # verbose_name / verbose_name_plural without a hand-written ModelAdmin.
        if schema.verbose_name:
            model_class.verbose_name = schema.verbose_name
        if schema.verbose_name_plural:
            model_class.verbose_name_plural = schema.verbose_name_plural

        # Add AuthModelMixin methods to User model if this is the User schema
        if schema.table_name == "admin_users":
            from fastapi_admin_kit.auth.password import password_manager

            # Add role_ids property
            @property
            def role_ids(self) -> list[int]:
                roles = getattr(self, "roles", None)
                if roles is None:
                    return []
                return [r.id for r in roles]

            model_class.role_ids = role_ids

            # Add verify_password method
            def verify_password(self, password: str) -> bool:
                return password_manager.verify(password, self.hashed_password)

            model_class.verify_password = verify_password

            # Add hash_password classmethod
            @classmethod
            def hash_password(cls, password: str) -> str:
                return password_manager.hash(password)

            model_class.hash_password = hash_password

            # Add set_hasher classmethod
            @classmethod
            def set_hasher(cls, hasher: type) -> None:
                cls._hasher = hasher

            model_class.set_hasher = set_hasher

            # Initialize _hasher attribute
            model_class._hasher = None

            # Add has_perm method
            async def has_perm(self, perm_name: str, session) -> bool:
                if self.is_superuser:
                    return True

                from sqlalchemy import select

                from fastapi_admin_kit.migrations.models import (
                    Permission,
                    UserPermission,
                    admin_role_permissions,
                )

                # Parse perm_name -> (table_name, action)
                if ":" in perm_name:
                    table_name, action = perm_name.rsplit(":", 1)
                else:
                    parts = perm_name.rsplit("_", 1)
                    if len(parts) != 2:
                        return False
                    table_name, action = parts

                attr = f"can_{action}"
                if attr not in ("can_view", "can_create", "can_edit", "can_delete"):
                    return False

                role_ids = self.role_ids
                if not role_ids and not self.id:
                    return False

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
                        if perm.table_name == table_name and getattr(perm, attr, False):
                            return True

                result = await session.execute(
                    select(Permission)
                    .join(UserPermission, UserPermission.permission_id == Permission.id)
                    .where(UserPermission.user_id == self.id)
                )
                for perm in result.scalars():
                    if perm.table_name == table_name and getattr(perm, attr, False):
                        return True

                return False

            model_class.has_perm = has_perm

        return model_class


# ---------------------------------------------------------------------------
# Composite Backend — wires all SQLAlchemy adapters together
# ---------------------------------------------------------------------------


class SqlAlchemyBackend:
    """Composite backend that composes all SQLAlchemy adapters into one object.

    This is the default backend for Admin when no custom backend is provided.
    Users can pass a custom backend (e.g. ``MongoDBBackend``) to ``Admin()``
    to switch ORM strategies without changing the rest of the admin wiring.

    Example::

        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyBackend

        admin = Admin(backend=SqlAlchemyBackend())
    """

    def __init__(
        self,
        admin_database: AdminDatabase | None = None,
        *,
        introspection: SqlAlchemyIntrospectionAdapter | None = None,
        query: SqlAlchemyQueryAdapter | None = None,
        audit: SqlAlchemyAuditBackend | None = None,
        database: SqlAlchemyDatabaseBackend | None = None,
    ) -> None:
        self.introspection = introspection or SqlAlchemyIntrospectionAdapter()
        self.query = query or SqlAlchemyQueryAdapter()
        self.audit = audit or SqlAlchemyAuditBackend()
        self.database = database or SqlAlchemyDatabaseBackend(admin_database=admin_database)

    @classmethod
    def from_admin_database(cls, admin_database: AdminDatabase) -> SqlAlchemyBackend:
        """Create a backend from an existing ``AdminDatabase`` instance."""
        return cls(admin_database=admin_database)
