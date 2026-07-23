"""Concrete implementations of protocol interfaces.

SRP: Each class has a single responsibility.
DIP: View classes depend on these via protocol abstractions.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import Response

from fastapi_admin_kit.auth.dependencies import (
    resolve_permission_checker as _resolve_permission_checker,  # noqa: F401
)
from fastapi_admin_kit.db import get_db_session
from fastapi_admin_kit.registry import RegisteredModel
from fastapi_admin_kit.types import FieldMeta
from fastapi_admin_kit.validation import FormValidator
from fastapi_admin_kit.views.file_handler import (
    FILE_WIDGET_TYPES as _FILE_WIDGET_TYPES,
)
from fastapi_admin_kit.views.file_handler import (
    handle_file_field as _handle_file_field,
)

# ---------------------------------------------------------------------------
# HTML Renderers (SRP: only HTML template logic)
# ---------------------------------------------------------------------------


class ListHTMLRenderer:
    """SRP: Render list view as HTML template."""

    async def render(self, request: Request, context: dict[str, Any]) -> Response:
        templates = request.app.state.admin_jinja_env
        is_htmx = request.headers.get("HX-Request") == "true"
        template = "partials/list_table.html" if is_htmx else "pages/list.html"
        return templates.TemplateResponse(request, template, context)


class FormHTMLRenderer:
    """SRP: Render create/edit form as HTML template."""

    async def render(self, request: Request, context: dict[str, Any]) -> Response:
        templates = request.app.state.admin_jinja_env
        status = 422 if context.get("errors") else 200
        return templates.TemplateResponse(request, "pages/form.html", context, status_code=status)


# ---------------------------------------------------------------------------
# API Renderers (SRP: only JSON serialization logic)
# ---------------------------------------------------------------------------


class ListAPIRenderer:
    """SRP: Render list view as paginated JSON."""

    def __init__(self, registered: RegisteredModel | None = None):
        self.registered = registered

    async def render(self, request: Request, data: Any) -> Response:
        from fastapi_admin_kit.api.schemas import PaginatedResponse

        return PaginatedResponse(**data)


class ItemAPIRenderer:
    """SRP: Render single object as JSON dict."""

    def __init__(self, registered: RegisteredModel):
        self.registered = registered

    def serialize(self, obj: Any) -> dict[str, Any]:
        """Serialize an object to a dict using registered columns."""
        item_dict: dict[str, Any] = {"id": getattr(obj, "id", None)}
        for col in self.registered.columns:
            if col.name != "id":
                item_dict[col.name] = str(getattr(obj, col.name, ""))
        return item_dict

    async def render(self, request: Request, data: Any) -> Any:
        if isinstance(data, dict):
            return data
        return self.serialize(data)


class DeleteAPIRenderer:
    """SRP: Return 204 No Content."""

    async def render(self, request: Request, data: Any = None) -> Response:
        return Response(status_code=204)


class HTMLFormParser:
    """SRP: Parse multipart/form-data from HTML forms."""

    def __init__(self, registered: RegisteredModel):
        self.registered = registered
        self.validator = FormValidator()

    async def parse(
        self, request: Request, obj: Any | None = None
    ) -> tuple[dict[str, Any], dict[str, list[str]]]:
        form_data = await request.form()
        # Cache form data on request for reuse by inline objects
        request._cached_form_data = form_data
        parsed: dict[str, Any] = {}
        errors: dict[str, list[str]] = {}

        for field_meta in self.registered.form_fields:
            if field_meta.readonly:
                continue
            widget = self.registered.get_widget(field_meta.name)

            if isinstance(widget, _FILE_WIDGET_TYPES):
                action = form_data.get(f"_action_{field_meta.name}", "keep") if obj else None
                await _handle_file_field(
                    request,
                    widget,
                    field_meta,
                    form_data,
                    obj=obj,
                    action=action,
                    parsed=parsed,
                    errors=errors,
                )
                if obj is None and field_meta.name not in errors and field_meta.name not in parsed:
                    parsed[field_meta.name] = None
                continue

            raw = form_data.get(field_meta.name)
            value = widget.parse(raw)
            required_on_create = (field_meta.extra or {}).get("required_on_create")
            if obj is None and required_on_create is not None:
                effective_field = FieldMeta(
                    name=field_meta.name,
                    label=field_meta.label,
                    required=required_on_create,
                    readonly=field_meta.readonly,
                    extra=field_meta.extra,
                )
            else:
                effective_field = field_meta
            field_errors = widget.validate(value, effective_field)
            if field_errors:
                errors[field_meta.name] = field_errors
            else:
                parsed[field_meta.name] = value

        if not errors:
            errors = self.validator.run(self.registered, parsed, obj=obj)

        return parsed, errors


class JSONBodyParser:
    """SRP: Parse JSON body from API requests."""

    def __init__(self, registered: RegisteredModel):
        self.registered = registered

    async def parse(
        self, request: Request, obj: Any | None = None
    ) -> tuple[dict[str, Any], dict[str, list[str]]]:
        from sqlalchemy import inspect as sa_inspect

        body = await request.json()
        valid_fields = {col.name for col in self.registered.columns}
        # Relationship keys (FK / many-to-many) are handled separately by the
        # view (resolved to FK columns or applied as m2m collections), so they
        # must not be stripped from the parsed payload here.
        rel_fields = set()
        try:
            mapper = sa_inspect(self.registered.model)
            rel_fields = {r.key for r in mapper.relationships}
        except Exception:
            pass
        allowed = (valid_fields | rel_fields) - {"id"}
        filtered = {k: v for k, v in body.items() if k in allowed}
        return filtered, {}


# ---------------------------------------------------------------------------
# Query Providers (SRP: only database query logic)
# ---------------------------------------------------------------------------


class DefaultQueryProvider:
    """SRP: Build and execute queries with filtering, search, pagination.

    Filter logic is delegated to the Filter system — this class orchestrates.
    """

    def __init__(self, registered: RegisteredModel):
        self.registered = registered

    def _get_query_adapter(self, request: Request) -> Any:
        return getattr(request.app.state, "admin_query_adapter", None)

    def _get_introspection(self, request: Request) -> Any:
        return getattr(request.app.state, "admin_introspection_adapter", None)

    def _get_eager_loads(self, request: Request, model: Any, list_display: list[str]) -> list:
        from sqlalchemy.orm import joinedload

        introspection = self._get_introspection(request)
        if introspection is not None:
            rel_names = introspection.get_relationship_names(model)
        else:
            from sqlalchemy import inspect as sa_inspect

            mapper = sa_inspect(model)
            rel_names = {r.key for r in mapper.relationships}
        return [joinedload(getattr(model, c)) for c in list_display if c in rel_names]

    def _build_filter_clauses(
        self,
        request: Request,
        model: Any,
        registered: RegisteredModel,
    ) -> list:
        """Build filter clauses via Filter.apply()."""
        from fastapi_admin_kit.filters import Filter, FilterRegistry

        query_adapter = self._get_query_adapter(request)
        introspection = self._get_introspection(request)
        registry = FilterRegistry()
        auto = registry.auto_generate(model, registered.columns, introspection)

        filters: dict[str, Any] = {}
        for item in registered.admin.list_filter or []:
            if isinstance(item, str) and item in auto:
                filters[item] = auto[item]
            elif isinstance(item, Filter):
                filters[item.field_name] = item

        clauses: list = []
        for field_name, filter_obj in filters.items():
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

            has_value = (isinstance(value, dict) and any(value.values())) or (
                isinstance(value, str) and value
            )
            if not has_value:
                continue

            clause = filter_obj.apply(query_adapter, None, model, value)
            if clause is not None:
                clauses.append(clause)

        return clauses

    async def get_list(
        self, request: Request, q: str = "", page: int = 1
    ) -> tuple[list[Any], int, int, int]:
        """Execute list query with filtering, search, pagination.

        Returns (items, total, page, per_page).
        """
        from fastapi_admin_kit.search_utils import apply_search_filter

        session = get_db_session(request)
        registered = self.registered
        model = registered.model

        query_adapter = self._get_query_adapter(request)
        if query_adapter is not None:
            base = query_adapter.select(model)
        else:
            from sqlalchemy import select

            base = select(model)

        list_display = registered.admin.list_display or [
            c.name for c in registered.columns if c.name != "id"
        ]

        eager_loads = self._get_eager_loads(request, model, list_display)
        if query_adapter is not None:
            for opt in eager_loads:
                base = query_adapter.options(base, opt)
        else:
            for opt in eager_loads:
                base = base.options(opt)

        filter_clauses = self._build_filter_clauses(request, model, registered)
        if filter_clauses:
            if query_adapter is not None:
                base = query_adapter.where(base, *filter_clauses)
            else:
                from sqlalchemy import and_

                base = base.where(and_(*filter_clauses))

        if q and registered.admin.search_fields:
            base = apply_search_filter(request, base, model, registered.admin.search_fields, q)

        query_ordering = request.query_params.get("ordering", "")
        order = [query_ordering] if query_ordering else registered.admin.ordering or []
        if order:
            col_name = order[0].lstrip("-")
            col = getattr(model, col_name, None) if hasattr(model, col_name) else None
            if col is not None:
                if query_adapter is not None:
                    if order[0].startswith("-"):
                        base = query_adapter.order_by(base, f"-{col_name}")
                    else:
                        base = query_adapter.order_by(base, col_name)
                else:
                    from sqlalchemy import asc, desc

                    base = base.order_by(desc(col) if order[0].startswith("-") else asc(col))

        per_page = registered.admin.per_page

        from fastapi_admin_kit.pagination import (
            OffsetPagination,
            PaginationResult,
        )

        pagination = getattr(registered.admin, "pagination", None) or OffsetPagination()
        pk_col = getattr(model, self.registered.pk_field) if self.registered.pk_field else None
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

        return (
            pagination_result.items,
            pagination_result.total,
            pagination_result.page or page,
            per_page,
            pagination_result.next_cursor,
            pagination_result.has_next,
            pagination_result.mode,
        )

    async def get_object(self, request: Request, id: Any) -> Any | None:
        """Return a single object by primary key, eagerly loading M2M relationships."""
        from fastapi_admin_kit.inspection import cast_pk_value

        session = get_db_session(request)
        introspection = self._get_introspection(request)
        query_adapter = self._get_query_adapter(request)

        if introspection is not None:
            mapper_rel_names = introspection.get_relationship_names(self.registered.model)
        else:
            from sqlalchemy import inspect as sa_inspect

            mapper = sa_inspect(self.registered.model)
            mapper_rel_names = {r.key for r in mapper.relationships}

        m2m_rel_names = set()
        for rel_name in mapper_rel_names:
            if introspection is not None:
                rel = introspection.get_relationship(self.registered.model, rel_name)
            else:
                from sqlalchemy import inspect as sa_inspect

                mapper = sa_inspect(self.registered.model)
                rel = mapper.relationships.get(rel_name)
            if rel is not None and rel.direction.name == "MANYTOMANY":
                m2m_rel_names.add(rel_name)

        int_id = cast_pk_value(self.registered.model, id)

        if m2m_rel_names and query_adapter is not None:
            from sqlalchemy.orm import selectinload

            options = [selectinload(getattr(self.registered.model, rn)) for rn in m2m_rel_names]
            stmt = query_adapter.select(self.registered.model)
            for opt in options:
                stmt = query_adapter.options(stmt, opt)
            stmt = query_adapter.where(
                stmt,
                getattr(self.registered.model, self.registered.pk_field) == int_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
        elif m2m_rel_names:
            from sqlalchemy import inspect as sa_inspect
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            mapper = sa_inspect(self.registered.model)
            m2m_rels = [r for r in mapper.relationships if r.direction.name == "MANYTOMANY"]
            options = [selectinload(getattr(self.registered.model, r.key)) for r in m2m_rels]
            stmt = (
                select(self.registered.model)
                .options(*options)
                .where(getattr(self.registered.model, self.registered.pk_field) == int_id)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
        return await session.get(self.registered.model, int_id)
