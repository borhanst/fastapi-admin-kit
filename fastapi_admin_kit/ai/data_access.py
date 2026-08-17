"""Single data-access seam (Candidate 3).

Every data tool used to re-implement the same
``if qb is not None: … else: direct SQLAlchemy`` branch — a copy of the query
builder, not a shared default.  That fallback now lives in exactly one place:
:class:`SqlAlchemyDataAccess`.  Tools call ``deps.data_access.query /
get_by_pk / create_record``; a non-SQLAlchemy backend is just another adapter
behind the same interface.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from fastapi_admin_kit.backends import as_session_backend


@runtime_checkable
class DataAccess(Protocol):
    """What the AI data tools need from a persistence backend."""

    async def query(
        self, model: Any, filters: dict[str, object] | None, limit: int
    ) -> list[Any]: ...

    async def get_by_pk(self, model: Any, pk: object) -> Any | None: ...

    async def create_record(self, model: Any, data: dict[str, object]) -> Any: ...


class SqlAlchemyDataAccess:
    """The single home of the SQLAlchemy read/write path.

    Used directly when no ORM-agnostic ``query_backend`` is configured, and as
    the fallback the adapter resolves to.  Either way the SQL lives here once.
    """

    def __init__(
        self,
        session: Any,
        query_backend: Any | None = None,
        introspection_backend: Any | None = None,
        session_backend: Any | None = None,
    ) -> None:
        self.session = session
        self.query_backend = query_backend
        self.introspection_backend = introspection_backend
        # Session-scoped adapter (e.g. SqlAlchemySessionAdapter).  When present
        # every execute/add/flush goes through it; otherwise we fall back to the
        # raw session.  Either way the SQL lives only in this class.
        self.session_backend = session_backend or as_session_backend(session)

    async def _all(self, stmt: Any) -> list[Any]:
        """Execute *stmt* and return all rows as ORM objects."""
        if self.session_backend is not None:
            return await self.session_backend.all(stmt)
        return list((await self.session.execute(stmt)).scalars().all())

    async def _first(self, stmt: Any) -> Any | None:
        """Execute *stmt* and return the first ORM object, or None."""
        if self.session_backend is not None:
            return await self.session_backend.first(stmt)
        return (await self.session.execute(stmt)).scalars().first()

    async def _scalar_one_or_none(self, stmt: Any) -> Any | None:
        """Execute *stmt* and return the first column or None."""
        if self.session_backend is not None:
            return await self.session_backend.scalar_one_or_none(stmt)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def _add(self, obj: Any) -> None:
        if self.session_backend is not None:
            self.session_backend.add(obj)
        else:
            self.session.add(obj)

    async def _flush(self) -> None:
        if self.session_backend is not None:
            await self.session_backend.flush()
        else:
            await self.session.flush()

    async def query(self, model: Any, filters: dict[str, object] | None, limit: int) -> list[Any]:
        if self.query_backend is not None:
            # ORM-agnostic path — use the registered QueryBackend adapter.
            stmt = self.query_backend.select(model)
            for field_name, value in (filters or {}).items():
                col_attr = getattr(model, field_name, None)
                if col_attr is None:
                    continue
                if isinstance(value, dict | list):
                    continue
                try:
                    if value is None:
                        stmt = self.query_backend.where(stmt, col_attr.is_(None))
                    else:
                        stmt = self.query_backend.where(stmt, col_attr == value)
                except Exception:  # noqa: BLE001
                    continue
            stmt = self.query_backend.limit(stmt, limit)
        else:
            # Fallback: direct SQLAlchemy (existing behaviour).
            from sqlalchemy import select

            stmt = select(model)
            for field_name, value in (filters or {}).items():
                if not hasattr(model, field_name):
                    continue
                if isinstance(value, dict | list):
                    continue
                col = getattr(model, field_name)
                try:
                    if value is None:
                        stmt = stmt.where(col.is_(None))
                    else:
                        stmt = stmt.where(col == value)
                except Exception:  # noqa: BLE001
                    continue
            stmt = stmt.limit(limit)

        return await self._all(stmt)

    async def get_by_pk(self, model: Any, pk: object) -> Any | None:
        pk_col = getattr(model, "id", None)
        if self.query_backend is not None:
            stmt = self.query_backend.select(model)
            if pk_col is not None:
                stmt = self.query_backend.where(stmt, pk_col == pk)
            stmt = self.query_backend.limit(stmt, 1)
            return await self._first(stmt)

        from sqlalchemy import select

        return await self._scalar_one_or_none(
            select(model).where(pk_col == pk) if pk_col is not None else select(model)
        )

    async def create_record(self, model: Any, data: dict[str, object]) -> Any:
        obj = model(**data)
        self._add(obj)
        await self._flush()
        return obj
