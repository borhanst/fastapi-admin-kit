"""Shared search helper for free-text and relation-picker queries.

Supports Django-style ``relation__field`` lookups so a model can be searched
by attributes of a related (FK or many-to-many) model, e.g.
``search_fields = ["name", "roles__name"]``.
"""

from __future__ import annotations

from typing import Any


def apply_search_filter(
    request: Any,
    query: Any,
    model: Any,
    search_fields: list[str] | None,
    q: str,
) -> Any:
    """Apply case-insensitive ``ilike`` search clauses to a query.

    Uses ``QueryBackend`` and ``IntrospectionBackend`` from ``app.state``
    when available, falling back to direct SQLAlchemy imports.

    Args:
        request: The FastAPI Request (used to access ``app.state`` backends).
        query: A query statement (SQLAlchemy ``select`` or backend query type).
        model: The root ORM model the query selects.
        search_fields: Field names to search. Plain names match direct columns;
            names containing ``__`` (e.g. ``roles__name``) match an attribute on
            a related model and trigger a join.
        q: The search term. Empty/None returns the query unchanged.

    Returns:
        The query with ``WHERE ... OR ...`` clauses applied. When any relation
        was joined, ``.distinct()`` is added to avoid duplicate parent rows
        produced by many-to-many joins.
    """
    if not q or not search_fields:
        return query

    query_adapter = getattr(request.app.state, "admin_query_adapter", None)
    introspection = getattr(request.app.state, "admin_introspection_adapter", None)

    if introspection is not None:
        rel_names = introspection.get_relationship_names(model)
    else:
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(model)
        rel_names = {r.key for r in mapper.relationships}

    clauses: list[Any] = []
    joined_rels: set[str] = set()

    for sf in search_fields:
        if "__" in sf:
            rel_name, attr = sf.split("__", 1)
            if rel_name not in rel_names:
                continue
            if introspection is not None:
                rel = introspection.get_relationship(model, rel_name)
            else:
                from sqlalchemy import inspect as sa_inspect

                mapper = sa_inspect(model)
                rel = mapper.relationships.get(rel_name)
            if rel is None:
                continue
            target = rel.mapper.class_
            if not hasattr(target, attr):
                continue
            col = getattr(target, attr)
            if not hasattr(col, "ilike"):
                continue
            if rel_name not in joined_rels:
                if query_adapter is not None:
                    query = query_adapter.join(query, getattr(model, rel_name))
                else:
                    query = query.join(getattr(model, rel_name))
                joined_rels.add(rel_name)
            if query_adapter is not None:
                clauses.append(query_adapter.ilike(col, f"%{q}%"))
            else:
                clauses.append(col.ilike(f"%{q}%"))
        else:
            if hasattr(model, sf):
                col = getattr(model, sf)
                if hasattr(col, "ilike"):
                    if query_adapter is not None:
                        clauses.append(query_adapter.ilike(col, f"%{q}%"))
                    else:
                        clauses.append(col.ilike(f"%{q}%"))

    if clauses:
        if query_adapter is not None:
            query = query_adapter.where(query, query_adapter.or_(*clauses))
        else:
            from sqlalchemy import or_

            query = query.where(or_(*clauses))
        if joined_rels:
            if query_adapter is not None:
                query = query_adapter.distinct(query)
            else:
                query = query.distinct()

    return query
