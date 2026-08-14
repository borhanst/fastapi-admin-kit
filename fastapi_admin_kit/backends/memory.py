"""Dependency-free reference backend — proves the multi-ORM seam is pluggable.

``InMemoryBackend`` implements all five backend protocols (introspection,
session, query, audit, database) against a plain ``dict`` store.  It imports
**no** external ORM, so any reader can verify that the rest of ``fastapi_admin_kit``
only depends on the protocol contracts and never on SQLAlchemy specifics.

The query language is intentionally tiny: conditions are built with the
model's own column descriptors (``model.name == "x"``, ``model.age > 3``,
``model.name.in_(...)``, ``model.name.ilike("%x%")``) and combined with
``backend.query.or_(...)``.  This is enough to exercise every seam method
end-to-end without a real database.
"""

from __future__ import annotations

import operator
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from fastapi_admin_kit.inspection.types import ColumnMeta, RelationMeta
from fastapi_admin_kit.schemas.schema import Schema

# ---------------------------------------------------------------------------
# Column descriptors + query expressions
# ---------------------------------------------------------------------------


class MemColumn:
    """Lightweight column descriptor usable on materialized model classes.

    At the class level it behaves like a column (so ``model.col == value``
    builds an expression); on instances it stores/loads the value.
    """

    def __init__(self, name: str, type_name: str = "string", primary_key: bool = False):
        self.name = name
        self.type_name = type_name
        self.primary_key = primary_key

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, owner: type | None = None) -> Any:
        if obj is None:
            return self
        return obj.__dict__.get(self.name)

    def __set__(self, obj: Any, value: Any) -> None:
        obj.__dict__[self.name] = value

    def __eq__(self, other: Any) -> MemExpr:  # type: ignore[override]
        return MemExpr(self.name, operator.eq, other)

    def __ne__(self, other: Any) -> MemExpr:  # type: ignore[override]
        return MemExpr(self.name, operator.ne, other)

    def __gt__(self, other: Any) -> MemExpr:
        return MemExpr(self.name, operator.gt, other)

    def __lt__(self, other: Any) -> MemExpr:
        return MemExpr(self.name, operator.lt, other)

    def __ge__(self, other: Any) -> MemExpr:
        return MemExpr(self.name, operator.ge, other)

    def __le__(self, other: Any) -> MemExpr:
        return MemExpr(self.name, operator.le, other)

    def in_(self, values: Any) -> MemExpr:
        return MemExpr(self.name, "in", list(values))

    def ilike(self, pattern: str) -> MemExpr:
        return MemExpr(self.name, "ilike", pattern)

    def desc(self) -> MemOrder:
        return MemOrder(self.name, True)


@dataclass
class MemExpr:
    """A single boolean condition: ``column op value``."""

    name: str
    op: Any
    value: Any


@dataclass
class MemBool:
    """A boolean combination (AND/OR) of :class:`MemExpr` nodes."""

    kind: str  # "and" | "or"
    exprs: list[Any]


@dataclass
class MemOrder:
    name: str
    desc: bool = False


@dataclass
class MemQuery:
    """A backend-agnostic query representation evaluated against the store."""

    model: type
    predicates: list[Any] = field(default_factory=list)
    orders: list[MemOrder] = field(default_factory=list)
    limit: int | None = None
    offset: int | None = None
    is_count: bool = False


def _matches(record: dict, expr: Any) -> bool:
    if isinstance(expr, MemExpr):
        left = record.get(expr.name)
        if expr.op is operator.eq:
            return left == expr.value
        if expr.op is operator.ne:
            return left != expr.value
        if expr.op is operator.gt:
            return left is not None and left > expr.value
        if expr.op is operator.lt:
            return left is not None and left < expr.value
        if expr.op is operator.ge:
            return left is not None and left >= expr.value
        if expr.op is operator.le:
            return left is not None and left <= expr.value
        if expr.op == "in":
            return left in expr.value
        if expr.op == "ilike":
            if left is None:
                return False
            pat = expr.value.lower().strip("%")
            return pat in str(left).lower()
        return False
    if isinstance(expr, MemBool):
        results = [_matches(record, e) for e in expr.exprs]
        return any(results) if expr.kind == "or" else all(results)
    return True


# ---------------------------------------------------------------------------
# Session backend
# ---------------------------------------------------------------------------


class MemorySessionBackend:
    """A ``SessionBackend`` backed by an in-memory dict store."""

    def __init__(self, store: dict, connection: Any = None) -> None:
        self._store = store
        self._connection = connection

    # -- lifecycle ----------------------------------------------------------
    def _table(self, model: type) -> list[dict]:
        name = getattr(model, "__tablename__", None)
        if name is None:
            raise ValueError("Model has no __tablename__")
        return self._store.setdefault(name, [])

    def _reconstruct(self, model: type, record: dict) -> Any:
        obj = model()
        for key, value in record.items():
            setattr(obj, key, value)
        return obj

    def add(self, obj: Any) -> None:
        model = type(obj)
        table = self._table(model)
        record = dict(getattr(obj, "__dict__", {}))
        pk_field = _pk_field_name(model)
        if pk_field and record.get(pk_field) is None:
            record[pk_field] = _next_id(self._store, model.__tablename__)
            # Write the auto-assigned pk back onto the object so callers observe
            # the same post-``add`` id semantics SQLAlchemy exposes after flush.
            setattr(obj, pk_field, record[pk_field])
        # overwrite if pk exists
        if pk_field and record.get(pk_field) is not None:
            existing = next((r for r in table if r.get(pk_field) == record[pk_field]), None)
            if existing is not None:
                existing.clear()
                existing.update(record)
                return
        table.append(record)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None

    def delete(self, obj: Any) -> None:
        model = type(obj)
        table = self._table(model)
        pk_field = _pk_field_name(model)
        pk = getattr(obj, pk_field, None) if pk_field else None
        for i, r in enumerate(list(table)):
            if pk is None or r.get(pk_field) == pk:
                table.pop(i)
                return

    def refresh(self, obj: Any, attributes: Sequence[str] | None = None) -> None:
        return None

    def get(self, model: type, pk: Any) -> Any | None:
        table = self._table(model)
        pk_field = _pk_field_name(model)
        for r in table:
            if r.get(pk_field) == pk:
                return self._reconstruct(model, r)
        return None

    # -- query execution ----------------------------------------------------
    def _rows(self, query: MemQuery) -> list[dict]:
        table = self._table(query.model)
        rows = [r for r in table if all(_matches(r, p) for p in query.predicates)]
        for order in query.orders:
            rows.sort(key=lambda r: _sort_key(r.get(order.name)), reverse=order.desc)
        return rows

    def execute(self, query: MemQuery) -> MemResult:
        return MemResult(self._rows(query), query)

    def all(self, query: MemQuery, unique: bool = False) -> list[Any]:
        rows = self._rows(query)
        if query.offset:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return [self._reconstruct(query.model, r) for r in rows]

    def rows(self, query: MemQuery) -> list[Any]:
        return self.all(query)

    def first(self, query: MemQuery, unique: bool = False) -> Any | None:
        rows = self.all(query)
        return rows[0] if rows else None

    def scalar(self, query: MemQuery) -> Any | None:
        if query.is_count:
            return len(self._rows(query))
        rows = self._rows(query)
        return self._reconstruct(query.model, rows[0]) if rows else None

    def scalar_one(self, query: MemQuery) -> Any:
        rows = self._rows(query)
        if not rows:
            raise ValueError("scalar_one() returned no rows")
        return self._reconstruct(query.model, rows[0])

    def scalar_one_or_none(self, query: MemQuery) -> Any | None:
        rows = self._rows(query)
        return self._reconstruct(query.model, rows[0]) if rows else None

    def count(self, query: MemQuery) -> int:
        return len(self._rows(query))


class MemResult:
    """Minimal result wrapper retained for call sites that still call execute."""

    def __init__(self, rows: list[dict], query: MemQuery) -> None:
        self._rows = rows
        self._query = query

    def scalars(self) -> MemResult:
        return self

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def scalar(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        if not self._rows:
            raise ValueError("scalar_one() returned no rows")
        return self._rows[0]

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None


# ---------------------------------------------------------------------------
# Query backend
# ---------------------------------------------------------------------------


class MemoryQueryAdapter:
    """Builds :class:`MemQuery` objects with a chainable API."""

    def select(self, model: type) -> MemQuery:
        return MemQuery(model=model)

    def where(self, query: MemQuery, *conditions: Any) -> MemQuery:
        query.predicates.extend(conditions)
        return query

    def order_by(self, query: MemQuery, *columns: Any) -> MemQuery:
        for col in columns:
            if isinstance(col, MemOrder):
                query.orders.append(col)
            elif isinstance(col, MemColumn):
                query.orders.append(MemOrder(col.name, False))
            elif isinstance(col, str):
                query.orders.append(MemOrder(col, False))
        return query

    def limit(self, query: MemQuery, n: int) -> MemQuery:
        query.limit = n
        return query

    def offset(self, query: MemQuery, n: int) -> MemQuery:
        query.offset = n
        return query

    def join(self, query: MemQuery, related: type, on: Any | None = None) -> MemQuery:
        return query

    def distinct(self, query: MemQuery) -> MemQuery:
        return query

    def count(self, query: MemQuery) -> MemQuery:
        query.is_count = True
        return query

    def options(self, query: MemQuery, *opts: Any) -> MemQuery:
        return query

    def ilike(self, column: MemColumn, pattern: str) -> MemExpr:
        return column.ilike(pattern)

    def or_(self, *clauses: Any) -> MemBool:
        return MemBool("or", list(clauses))

    def and_(self, *clauses: Any) -> MemBool:
        return MemBool("and", list(clauses))


# ---------------------------------------------------------------------------
# Introspection backend
# ---------------------------------------------------------------------------


class MemoryIntrospectionAdapter:
    """Reflects a materialized model's schema."""

    def inspect_model(self, model: type) -> tuple[list[ColumnMeta], list[RelationMeta]]:
        schema: Schema = getattr(model, "__schema__", None)
        if schema is None:
            return [], []
        columns = [
            ColumnMeta(
                name=f.name,
                type=f.type,
                nullable=f.nullable,
                primary_key=f.primary_key,
                unique=f.unique,
                index=f.index,
                default=f.default,
            )
            for f in schema.fields
        ]
        relations = [
            RelationMeta(
                name=r.name,
                direction=r.type.upper(),
                target_model=None,
                back_populates=r.back_populates,
                secondary=r.through,
            )
            for r in schema.relations
        ]
        return columns, relations

    def get_pk_field(self, model: type) -> str | None:
        return _pk_field_name(model)

    def cast_pk_value(self, model: type, value: Any) -> Any:
        schema: Schema = getattr(model, "__schema__", None)
        if schema is None:
            return value
        pk = schema.get_pk_field()
        if pk is not None and pk.type in ("integer", "int", "bigint"):
            try:
                return int(value)
            except (TypeError, ValueError):
                return value
        return value

    def is_abstract(self, model: type) -> bool:
        return False

    def get_relationship_names(self, model: type) -> set[str]:
        schema: Schema = getattr(model, "__schema__", None)
        if schema is None:
            return set()
        return {r.name for r in schema.relations}

    def get_relationship(self, model: type, name: str) -> Any:
        schema: Schema = getattr(model, "__schema__", None)
        if schema is None:
            return None
        return schema.get_relation(name)

    def get_relationship_local_columns(self, model: type, name: str) -> list[str]:
        return []

    def get_column_type_name(self, model: type, field_name: str) -> str | None:
        schema: Schema = getattr(model, "__schema__", None)
        if schema is None:
            return None
        f = schema.get_field(field_name)
        return f.type if f is not None else None

    def get_column_attr(self, model: type, field_name: str) -> Any:
        return getattr(model, field_name, None)

    def get_pk_columns(self, model: type) -> list[Any]:
        pk = _pk_field_name(model)
        return [pk] if pk else []


# ---------------------------------------------------------------------------
# Audit backend
# ---------------------------------------------------------------------------


class MemoryAuditBackend:
    """No-op change tracking for the in-memory backend."""

    def attach_listeners(self, session_factory: Any, registry: dict[str, Any]) -> None:
        return None

    def snapshot(self, obj: Any) -> dict[str, Any]:
        return dict(getattr(obj, "__dict__", {}))

    def compute_diff(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        diff: dict[str, Any] = {}
        keys = set(before) | set(after)
        for k in keys:
            if before.get(k) != after.get(k):
                diff[k] = (before.get(k), after.get(k))
        return diff


# ---------------------------------------------------------------------------
# Database backend
# ---------------------------------------------------------------------------


_ROLE_TABLE = "admin_roles"
_PERM_TABLE = "admin_permissions"
_JUNCTION_TABLE = "admin_role_permissions"


class MemoryDatabaseBackend:
    """Creates connections, sessions, tables, and seeds roles in-memory."""

    def __init__(self, admin_database: Any = None) -> None:
        self._admin_database = admin_database
        self._store: dict[str, list[dict]] = {}

    def create_connection(self) -> dict:
        for t in (_ROLE_TABLE, _PERM_TABLE, _JUNCTION_TABLE):
            self._store.setdefault(t, [])
        return self._store

    def create_session_factory(self, connection: dict) -> Any:
        def factory() -> MemorySessionBackend:
            return MemorySessionBackend(connection)

        return factory

    def create_tables(self, connection: dict, metadata: Any, tables: Any = None) -> None:
        return None

    def auto_migrate(self, connection: dict, metadata: Any) -> None:
        return None

    def has_tables(self, connection: dict, names: list[str]) -> set[str]:
        existing = set(connection.keys())
        return {n for n in names if n not in existing}

    def seed_roles(
        self,
        session_factory: Any,
        seed_roles: list[Any],
        overwrite: bool = False,
    ) -> None:
        store = self._store
        if store[_ROLE_TABLE] and not overwrite:
            return
        if overwrite:
            store[_ROLE_TABLE].clear()
            store[_PERM_TABLE].clear()
            store[_JUNCTION_TABLE].clear()

        session = session_factory()
        for role_spec in seed_roles:
            role = {
                "id": _next_id(store, _ROLE_TABLE),
                "name": role_spec.name,
                "description": getattr(role_spec, "description", None),
            }
            store[_ROLE_TABLE].append(role)
            perms = getattr(role_spec, "permissions", None) or {}
            for table_name, actions in perms.items():
                perm = {
                    "id": _next_id(store, _PERM_TABLE),
                    "name": table_name,
                    "table_name": table_name,
                    "can_view": bool(actions.get("view", False)),
                    "can_create": bool(actions.get("create", False)),
                    "can_edit": bool(actions.get("edit", False)),
                    "can_delete": bool(actions.get("delete", False)),
                }
                store[_PERM_TABLE].append(perm)
                store[_JUNCTION_TABLE].append({"role_id": role["id"], "permission_id": perm["id"]})
        session.commit()

    def materialize(self, schema: Schema, base: Any | None = None) -> type:
        cols = {f.name: MemColumn(f.name, f.type, f.primary_key) for f in schema.fields}

        def _init(self: Any, **kwargs: Any) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

        cls = type(
            schema.verbose_name or schema.table_name,
            (),
            {
                "__tablename__": schema.table_name,
                "__schema__": schema,
                "__init__": _init,
            },
        )
        for name, col in cols.items():
            setattr(cls, name, col)
        return cls

    @property
    def session_adapter_class(self) -> type:
        return MemorySessionBackend


# ---------------------------------------------------------------------------
# Composite backend
# ---------------------------------------------------------------------------


class InMemoryBackend:
    """Reference multi-ORM backend with zero external dependencies.

    Implements the same five-protocol seam as :class:`SqlAlchemyBackend` so the
    admin wiring can be exercised without SQLAlchemy.
    """

    def __init__(self, admin_database: Any = None) -> None:
        self.database = MemoryDatabaseBackend(admin_database=admin_database)
        self.query = MemoryQueryAdapter()
        self.introspection = MemoryIntrospectionAdapter()
        self.audit = MemoryAuditBackend()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pk_field_name(model: type) -> str | None:
    schema: Schema = getattr(model, "__schema__", None)
    if schema is not None:
        pk = schema.get_pk_field()
        return pk.name if pk is not None else None
    for name in ("id", "pk"):
        if hasattr(model, name):
            return name
    return None


def _sort_key(value: Any) -> Any:
    return (value is None, value)


def _next_id(store: dict, table: str) -> int:
    rows = store.get(table, [])
    return max([r.get("id", 0) for r in rows], default=0) + 1
