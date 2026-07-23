"""ListContextBuilder — deep module for building list view template context.

Uses IntrospectionBackend and QueryBackend protocols for ORM-agnosticism.
Filter logic is delegated to the Filter system (filters/base.py, filters/registry.py).
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from fastapi_admin_kit.registry import RegisteredModel


class ListContextBuilder:
    """Builds the complete template context for list views.

    Filter clause building and type detection are handled by the
    Filter system — this class orchestrates, it does not duplicate.
    """

    def _get_introspection(self, request: Request) -> Any:
        return getattr(request.app.state, "admin_introspection_adapter", None)

    def _get_query_adapter(self, request: Request) -> Any:
        return getattr(request.app.state, "admin_query_adapter", None)

    def _get_or_build_filters(
        self,
        request: Request,
        model: Any,
        registered: RegisteredModel,
    ) -> dict[str, Any]:
        """Return {field_name: Filter} for this model.

        If ``list_filter`` contains Filter instances they are used directly;
        strings are auto-resolved via FilterRegistry.
        """
        from fastapi_admin_kit.filters import Filter, FilterRegistry

        introspection = self._get_introspection(request)
        registry = FilterRegistry()

        auto = registry.auto_generate(model, registered.columns, introspection)

        result: dict[str, Any] = {}
        if not registered.admin.list_filter:
            return result

        for item in registered.admin.list_filter:
            if isinstance(item, str):
                if item in auto:
                    result[item] = auto[item]
            elif isinstance(item, Filter):
                result[item.field_name] = item
        return result

    def _collect_filter_value(
        self,
        request: Request,
        field_name: str,
    ) -> tuple[Any, dict[str, str]]:
        """Read query params for *field_name* and return (value, active_pairs).

        ``value`` is a plain string for equality filters or a dict with
        ``gte/lte/from/to`` keys for range filters.
        ``active_pairs`` are the non-empty params to record in active_filters.
        """
        eq = request.query_params.get(f"filter_{field_name}", "")
        gte = request.query_params.get(f"filter_{field_name}__gte", "")
        lte = request.query_params.get(f"filter_{field_name}__lte", "")
        from_ = request.query_params.get(f"filter_{field_name}__from", "")
        to_ = request.query_params.get(f"filter_{field_name}__to", "")

        has_range = bool(gte or lte or from_ or to_)
        if has_range:
            value: Any = {}
            if gte:
                value["gte"] = gte
            if lte:
                value["lte"] = lte
            if from_:
                value["from"] = from_
            if to_:
                value["to"] = to_
        else:
            value = eq

        active: dict[str, str] = {}
        if eq:
            active[field_name] = eq
        if gte:
            active[f"{field_name}__gte"] = gte
        if lte:
            active[f"{field_name}__lte"] = lte
        if from_:
            active[f"{field_name}__from"] = from_
        if to_:
            active[f"{field_name}__to"] = to_

        return value, active

    def _build_filter_clauses(
        self,
        request: Request,
        model: Any,
        registered: RegisteredModel,
    ) -> tuple[list, dict[str, str]]:
        """Build filter clauses and collect active filters via Filter.apply()."""
        query_adapter = self._get_query_adapter(request)
        filters = self._get_or_build_filters(request, model, registered)
        clauses: list = []
        active_filters: dict[str, str] = {}

        for field_name, filter_obj in filters.items():
            value, active = self._collect_filter_value(request, field_name)
            active_filters.update(active)

            has_value = (isinstance(value, dict) and any(value.values())) or (
                isinstance(value, str) and value
            )
            if not has_value:
                continue

            clause = filter_obj.apply(query_adapter, None, model, value)
            if clause is not None:
                clauses.append(clause)

        return clauses, active_filters

    async def _build_filter_fields(
        self,
        request: Request,
        model: Any,
        registered: RegisteredModel,
        session: Any,
    ) -> dict[str, dict[str, Any]]:
        """Build filter field metadata for template rendering."""
        filters = self._get_or_build_filters(request, model, registered)
        introspection = self._get_introspection(request)
        query_adapter = self._get_query_adapter(request)
        result: dict[str, dict[str, Any]] = {}

        for field_name, filter_obj in filters.items():
            ft = filter_obj.field_type
            choices = filter_obj.get_choices(session)

            if ft == "relation" and len(choices) <= 1:
                choices = await self._build_relation_choices(
                    model, field_name, session, introspection, query_adapter
                )
            elif ft == "text" and len(choices) <= 1:
                choices = await self._build_text_choices(model, field_name, session, introspection)

            result[field_name] = {"field_type": ft, "choices": choices}

        return result

    # ------------------------------------------------------------------
    # Dynamic choices helpers (require DB access)
    # ------------------------------------------------------------------

    async def _build_relation_choices(
        self,
        model: Any,
        field_name: str,
        session: Any,
        introspection: Any,
        query_adapter: Any,
    ) -> list[tuple[str, str]]:
        target = self._resolve_relation_target(model, field_name, introspection)
        choices: list[tuple[str, str]] = [("", "All")]
        if target is None or session is None:
            return choices
        try:
            order_col = getattr(target, "name", None) or getattr(target, "title", None)
            if query_adapter is not None:
                q = query_adapter.select(target)
                if order_col is not None:
                    q = query_adapter.order_by(q, order_col)
                else:
                    pk_cols = (
                        introspection.get_pk_columns(target) if introspection is not None else None
                    )
                    if pk_cols:
                        q = query_adapter.order_by(q, pk_cols[0])
                    else:
                        from sqlalchemy import inspect as sa_inspect

                        q = query_adapter.order_by(q, sa_inspect(target).primary_key[0])
                q = query_adapter.limit(q, 100)
            else:
                from sqlalchemy import inspect as sa_inspect
                from sqlalchemy import select

                pk = (
                    introspection.get_pk_columns(target)[0]
                    if introspection is not None
                    else sa_inspect(target).primary_key[0]
                )
                q = select(target).order_by(order_col or pk).limit(100)
            result = await session.execute(q)
            for obj in result.scalars():
                label = str(
                    getattr(obj, "name", None)
                    or getattr(obj, "title", None)
                    or f"#{getattr(obj, 'id', '?')}"
                )
                choices.append((str(obj.id), label))
        except Exception:
            pass
        return choices

    def _resolve_relation_target(
        self,
        model: Any,
        field_name: str,
        introspection: Any,
    ) -> Any:
        if introspection is not None:
            rel = introspection.get_relationship(model, field_name)
            if rel is not None:
                return rel.mapper.class_
            for rname in introspection.get_relationship_names(model):
                r = introspection.get_relationship(model, rname)
                if r is not None and r.direction.name == "MANYTOONE":
                    col = introspection.get_column_attr(model, field_name)
                    if col is not None:
                        for fk in col.foreign_keys:
                            if fk.column.table == r.mapper.persist_selectable:
                                return r.mapper.class_
        else:
            from sqlalchemy import inspect as sa_inspect

            mapper = sa_inspect(model)
            rel = mapper.relationships.get(field_name)
            if rel is not None:
                return rel.mapper.class_
            for rel in mapper.relationships:
                if rel.direction.name == "MANYTOONE":
                    for prop in mapper.column_attrs:
                        if prop.key == field_name:
                            col = prop.columns[0] if prop.columns else None
                            if col is not None:
                                for fk in col.foreign_keys:
                                    if fk.column.table == rel.mapper.persist_selectable:
                                        return rel.mapper.class_
        return None

    async def _build_text_choices(
        self,
        model: Any,
        field_name: str,
        session: Any,
        introspection: Any,
    ) -> list[tuple[str, str]]:
        choices: list[tuple[str, str]] = [("", "All")]
        col = None
        if introspection is not None:
            col = introspection.get_column_attr(model, field_name)
        else:
            from sqlalchemy import inspect as sa_inspect

            mapper = sa_inspect(model)
            for prop in mapper.column_attrs:
                if prop.key == field_name:
                    col = prop.columns[0] if prop.columns else None
                    break
        if col is None or session is None:
            return choices
        try:
            from sqlalchemy import select

            q = select(col).where(col.isnot(None)).group_by(col).order_by(col).limit(100)
            result = await session.execute(q)
            for (val,) in result:
                label = str(val).replace("_", " ").title()
                choices.append((str(val), label))
        except Exception:
            pass
        return choices

    # ------------------------------------------------------------------
    # Eager loads + display columns (unchanged — not filter-related)
    # ------------------------------------------------------------------

    def _get_eager_loads(self, request: Request, model: Any, list_display: list[str]) -> list:
        introspection = self._get_introspection(request)
        if introspection is not None:
            rel_names = introspection.get_relationship_names(model)
        else:
            from sqlalchemy import inspect as sa_inspect

            mapper = sa_inspect(model)
            rel_names = {r.key for r in mapper.relationships}

        from sqlalchemy.orm import joinedload

        return [joinedload(getattr(model, c)) for c in list_display if c in rel_names]

    def _build_display_columns(self, registered: RegisteredModel, request: Request) -> list:
        from fastapi_admin_kit.views.context import DisplayColumn

        introspection = self._get_introspection(request)
        if introspection is not None:
            rel_names = introspection.get_relationship_names(registered.model)
        else:
            from sqlalchemy import inspect as sa_inspect

            mapper = sa_inspect(registered.model)
            rel_names = {r.key for r in mapper.relationships}

        list_display = registered.admin.list_display or [
            c.name for c in registered.columns if c.name != "id"
        ]

        decorated: dict[str, Any] = {}
        for cn in list_display:
            method = getattr(registered.admin, cn, None)
            if method and hasattr(method, "_column_options"):
                decorated[cn] = method._column_options

        columns = []
        for cn in list_display:
            label = cn.replace("_", " ").title()
            fn = None
            opts = None
            if cn in decorated:
                opts = decorated[cn]
                fn = getattr(registered.admin, cn)
                label = opts.header or label
            elif registered.admin.display_functions and cn in registered.admin.display_functions:
                fn = registered.admin.display_functions[cn]
            columns.append(DisplayColumn(cn, label, cn in rel_names, fn, opts))
        return columns

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def build_list_context(
        self,
        registered: RegisteredModel,
        request: Request,
        q: str = "",
        page: int = 1,
        permission_checker: Any = None,
    ) -> dict[str, Any]:
        from fastapi_admin_kit.db import get_db_session
        from fastapi_admin_kit.search_utils import apply_search_filter
        from fastapi_admin_kit.types import PermissionSet
        from fastapi_admin_kit.views.sidebar import inject_sidebar_context

        session = get_db_session(request)
        model = registered.model
        from sqlalchemy import and_, desc

        base = registered.admin.get_queryset(session, request)

        list_display = registered.admin.list_display or [
            c.name for c in registered.columns if c.name != "id"
        ]

        for opt in self._get_eager_loads(request, model, list_display):
            base = base.options(opt)

        filter_clauses, active_filters = self._build_filter_clauses(request, model, registered)
        if filter_clauses:
            base = base.where(and_(*filter_clauses))

        if q and registered.admin.search_fields:
            base = apply_search_filter(request, base, model, registered.admin.search_fields, q)

        query_ordering = request.query_params.get("ordering", "")
        order = [query_ordering] if query_ordering else registered.admin.ordering or []
        if order:
            col_name = order[0].lstrip("-")
            col = getattr(model, col_name, None) if hasattr(model, col_name) else None
            if col is not None:
                base = base.order_by(desc(col) if order[0].startswith("-") else asc(col))

        per_page = registered.admin.per_page

        from fastapi_admin_kit.pagination import (
            OffsetPagination,
            PaginationResult,
        )

        pagination = getattr(registered.admin, "pagination", None) or OffsetPagination()
        pk_col = getattr(model, registered.pk_field) if registered.pk_field else None
        query_adapter = getattr(request.app.state, "admin_query_adapter", None)
        pagination_result: PaginationResult = await pagination.paginate(
            base,
            session,
            per_page=per_page,
            page=page,
            after=request.query_params.get("after"),
            before=request.query_params.get("before"),
            pk_col=pk_col,
            model=model,
            query_adapter=query_adapter,
        )

        display_columns = self._build_display_columns(registered, request)
        filter_fields = await self._build_filter_fields(request, model, registered, session)

        ordering = request.query_params.get("ordering", "")
        if not ordering and registered.admin.ordering:
            ordering = registered.admin.ordering[0]

        template_context = {
            "model": registered,
            "registered": registered,
            "display_columns": display_columns,
            "items": pagination_result.items,
            "search_query": q,
            "page": pagination_result.page or 1,
            "total_pages": pagination_result.total_pages or 1,
            "total": pagination_result.total,
            "per_page": per_page,
            "next_cursor": pagination_result.next_cursor,
            "has_next": pagination_result.has_next,
            "pagination_mode": pagination_result.mode,
            "filter_fields": filter_fields,
            "active_filters": active_filters,
            "ordering": ordering,
            "permissions": permission_checker.permission_set(registered.table_name)
            if permission_checker
            else PermissionSet(can_view=True, can_create=True, can_edit=True, can_delete=True),
            "list_actions": registered.admin.get_list_actions(),
            "row_actions": registered.admin.get_row_actions(),
            "list_tabs": getattr(registered.admin, "list_tabs", []),
            "list_sections": getattr(registered.admin, "list_sections", []),
            "ordering_field": getattr(registered.admin, "ordering_field", None),
            "hide_ordering_field": getattr(registered.admin, "hide_ordering_field", False),
            "list_filter_options": getattr(registered.admin, "list_filter_options", {}),
            "list_filter_horizontal": getattr(registered.admin, "list_filter_horizontal", False),
        }

        template_context.update(self._get_extra_context(request, registered))
        await inject_sidebar_context(request, template_context)
        return template_context

    def _get_extra_context(self, request: Request, registered: RegisteredModel) -> dict[str, Any]:
        extra = getattr(registered.admin, "extra", None)
        if extra is None:
            return {}
        admin_path = request.app.state.admin_config.get("admin_path", "/admin")
        return extra.to_context(admin_path)


def asc(col: Any) -> Any:
    from sqlalchemy import asc as sa_asc

    return sa_asc(col)
