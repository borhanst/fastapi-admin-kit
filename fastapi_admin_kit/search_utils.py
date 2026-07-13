"""Shared search helper for free-text and relation-picker queries.

Supports Django-style ``relation__field`` lookups so a model can be searched
by attributes of a related (FK or many-to-many) model, e.g.
``search_fields = ["name", "roles__name"]``.
"""

from __future__ import annotations

from typing import Any


def apply_search_filter(
    query: Any,
    model: Any,
    search_fields: list[str] | None,
    q: str,
) -> Any:
    """Apply case-insensitive ``ilike`` search clauses to a SQLAlchemy query.

    Args:
        query: A SQLAlchemy ``select`` statement (or query object).
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

    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import or_

    mapper = sa_inspect(model)
    clauses: list[Any] = []
    joined_rels: set[str] = set()

    for sf in search_fields:
        if "__" in sf:
            rel_name, attr = sf.split("__", 1)
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
                query = query.join(getattr(model, rel_name))
                joined_rels.add(rel_name)
            clauses.append(col.ilike(f"%{q}%"))
        else:
            if hasattr(model, sf):
                col = getattr(model, sf)
                if hasattr(col, "ilike"):
                    clauses.append(col.ilike(f"%{q}%"))

    if clauses:
        query = query.where(or_(*clauses))
        if joined_rels:
            query = query.distinct()

    return query
