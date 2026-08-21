"""Concrete implementations of protocol interfaces.

SRP: Each class has a single responsibility.
DIP: View classes depend on these via protocol abstractions.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import Response

from fastapi_admin_kit.audit.diff import serialize_value
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

MAX_PER_PAGE = 100
"""Upper bound for client-supplied ``?per_page=`` (DoS guard)."""

# ---------------------------------------------------------------------------
# HTML Renderers (SRP: only HTML template logic)
# ---------------------------------------------------------------------------


def _template_exists(request: Request, name: str) -> bool:
    """Return True if a template can be found in the Jinja environment."""
    try:
        env = request.app.state.admin_jinja_env.env
        env.loader.get_source(env, name)
        return True
    except Exception:
        return False


def resolve_template(request: Request, candidates: list[str]) -> str:
    """Return the first existing candidate template, falling back to the last.

    Order of precedence:
      1. Explicit template from ModelAdmin (e.g. "admin/users/list.html")
      2. Auto-discovery: "admin/<table_name>/<view>.html"
      3. Global override: "admin/<view>.html"
      4. Built-in default (always present)
    """
    for name in candidates:
        if _template_exists(request, name):
            return name
    return candidates[-1]


class ListHTMLRenderer:
    """SRP: Render list view as HTML template.

    ``list_template`` is the raw ModelAdmin override (may be None); when set it
    takes precedence. Otherwise auto-discovery checks ``admin/<table>/list.html``
    then the global ``admin/list.html`` before the built-in default.
    """

    def __init__(
        self,
        list_template: str | None = None,
        table_name: str | None = None,
        partial_template: str = "partials/list_table.html",
        **kwargs: Any,
    ):
        self.list_template = list_template
        self.table_name = table_name
        self.partial_template = partial_template

    async def render(self, request: Request, context: dict[str, Any]) -> Response:
        templates = request.app.state.admin_jinja_env
        is_htmx = request.headers.get("HX-Request") == "true"
        if is_htmx:
            template = self.partial_template
        else:
            candidates = []
            if self.list_template:
                candidates.append(self.list_template)
            if self.table_name:
                candidates.append(f"admin/{self.table_name}/list.html")
            candidates += ["admin/list.html", "pages/list.html"]
            template = resolve_template(request, candidates)
        return templates.TemplateResponse(request, template, context)


class FormHTMLRenderer:
    """SRP: Render create/edit form as HTML template.

    ``create_template`` / ``edit_template`` are raw ModelAdmin overrides (may be
    None); when set they take precedence. Otherwise auto-discovery checks
    ``admin/<table>/form.html`` then the global ``admin/form.html`` before the
    built-in default.
    """

    def __init__(
        self,
        create_template: str | None = None,
        edit_template: str | None = None,
        table_name: str | None = None,
        **kwargs: Any,
    ):
        self.create_template = create_template
        self.edit_template = edit_template
        self.table_name = table_name

    async def render(
        self, request: Request, context: dict[str, Any], is_create: bool = True
    ) -> Response:
        templates = request.app.state.admin_jinja_env
        status = 422 if context.get("errors") else 200
        explicit = self.create_template if is_create else self.edit_template
        candidates = []
        if explicit:
            candidates.append(explicit)
        if self.table_name:
            candidates.append(f"admin/{self.table_name}/form.html")
        candidates += ["admin/form.html", "pages/form.html"]
        template = resolve_template(request, candidates)
        return templates.TemplateResponse(request, template, context, status_code=status)


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
        from fastapi_admin_kit.inspection.types import SENSITIVE_FIELDS

        item_dict: dict[str, Any] = {"id": getattr(obj, "id", None)}
        for col in self.registered.columns:
            if col.name != "id" and col.name not in SENSITIVE_FIELDS:
                item_dict[col.name] = serialize_value(getattr(obj, col.name, None))
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
    """SRP: Parse JSON body from API requests.

    Security parity with :class:`HTMLFormParser`: the parsed payload runs
    through the same shared validation pipeline (widget validation via
    ``FormValidator.run``, ``admin.validate_create/update`` and
    ``admin.process_form_data``), so business rules cannot be bypassed by
    speaking JSON instead of submitting the HTML form. Sensitive fields
    (``hashed_password`` etc.) are rejected from the allowed field set.
    """

    def __init__(self, registered: RegisteredModel):
        self.registered = registered
        self.admin = registered.admin
        self.validator = FormValidator()

    async def parse(
        self, request: Request, obj: Any | None = None
    ) -> tuple[dict[str, Any], dict[str, list[str]]]:
        from sqlalchemy import inspect as sa_inspect

        from fastapi_admin_kit.form.types import FieldError
        from fastapi_admin_kit.inspection.types import SENSITIVE_FIELDS

        # Pre-parsed body supplied by the API wrapper handler (so FastAPI can
        # document the request body schema in Swagger/OpenAPI).
        body = getattr(request.state, "_api_payload", None)
        if body is None:
            body = await request.json()
        if not isinstance(body, dict):
            return {}, {"__all__": ["Request body must be a JSON object."]}

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
        allowed = (valid_fields | rel_fields) - {"id"} - set(SENSITIVE_FIELDS)
        # Admin-declared extra fields (e.g. the virtual "password" input on
        # UserAdmin) are intentional write-only inputs — they are not secret
        # columns and must survive the sensitive-field filter so the JSON
        # path can carry them exactly like the HTML form does.
        extra_names = {f.name for f in getattr(self.admin, "extra_fields", None) or []}
        allowed |= extra_names
        filtered = {k: v for k, v in body.items() if k in allowed}

        # Coerce raw JSON values (ISO date strings etc.) through the same
        # widgets the HTML path uses, so widget validators see typed values.
        for name, value in list(filtered.items()):
            if value is None:
                continue
            try:
                widget = self.registered.get_widget(name)
                parsed_value = widget.parse(value)
            except Exception:
                continue
            if parsed_value is not None:
                filtered[name] = parsed_value

        # Shared validation identical to the HTML path. Creates validate the
        # full field set; updates only the fields present in the payload so
        # partial PATCH bodies keep working.
        errors = self.validator.run(
            self.registered,
            filtered,
            obj=obj,
            only_fields=None if obj is None else set(filtered),
        )

        if not errors:
            try:
                if obj is None:
                    result = self.admin.validate_create(filtered, request)
                else:
                    result = self.admin.validate_update(obj, filtered, request)
                filtered = self.admin.process_form_data(result, request)
            except FieldError as exc:
                errors = exc.field_errors
            except ValueError as exc:
                errors = {"__all__": [str(exc)]}

        return filtered, errors


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
        from fastapi_admin_kit.filters.lookups import parse_filter_params

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
            value, _active = parse_filter_params(request.query_params, field_name)

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
        self, request: Request, q: str = "", page: int = 1, order: str = ""
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
            base = registered.admin.get_queryset(session, request)

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

        if registered.admin.list_filter:
            filter_clauses = self._build_filter_clauses(request, model, registered)
            if filter_clauses:
                if query_adapter is not None:
                    base = query_adapter.where(base, *filter_clauses)
                else:
                    from sqlalchemy import and_

                    base = base.where(and_(*filter_clauses))

        if q and registered.admin.search_fields:
            base = apply_search_filter(request, base, model, registered.admin.search_fields, q)

        query_ordering = request.query_params.get("ordering", "") or order
        order = registered.admin.get_ordering(
            {"ordering": query_ordering}, registered.admin.ordering
        )
        if order:
            col_name = order[0].lstrip("-")
            col = getattr(model, col_name, None) if hasattr(model, col_name) else None
            if col is not None:
                from sqlalchemy.orm import ColumnProperty

                if isinstance(getattr(col, "property", None), ColumnProperty):
                    if query_adapter is not None:
                        from sqlalchemy import desc

                        if order[0].startswith("-"):
                            base = query_adapter.order_by(base, desc(col))
                        else:
                            base = query_adapter.order_by(base, col)
                    else:
                        from sqlalchemy import asc, desc

                        base = base.order_by(desc(col) if order[0].startswith("-") else asc(col))

        try:
            requested_per_page = int(
                request.query_params.get("per_page", registered.admin.per_page)
            )
        except (TypeError, ValueError):
            requested_per_page = registered.admin.per_page
        # DoS guard: client-supplied per_page is capped at MAX_PER_PAGE.
        # An explicitly larger admin configuration still wins.
        cap = max(MAX_PER_PAGE, int(registered.admin.per_page or 0))
        per_page = max(1, min(requested_per_page, cap))

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
            return await session.scalar_one_or_none(stmt)
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
            return await session.scalar_one_or_none(stmt)
        return await session.get(self.registered.model, int_id)
