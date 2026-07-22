"""Concrete implementations of protocol interfaces.

SRP: Each class has a single responsibility.
DIP: View classes depend on these via protocol abstractions.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import Response
from starlette.datastructures import UploadFile

from fastapi_admin_kit.db import get_db_session
from fastapi_admin_kit.registry import RegisteredModel
from fastapi_admin_kit.types import FieldMeta
from fastapi_admin_kit.validation import FormValidator
from fastapi_admin_kit.widgets.inputs import FileUploadWidget, ImageUploadWidget

_FILE_WIDGET_TYPES = (FileUploadWidget, ImageUploadWidget)


def _get_storage(request: Request):
    """Get the storage backend from app.state, or None."""
    return getattr(request.app.state, "admin_storage", None)


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


# ---------------------------------------------------------------------------
# Form Parsers (SRP: only form data parsing + validation)
# ---------------------------------------------------------------------------


async def _handle_file_field(
    request: Request,
    widget: Any,
    field_meta: Any,
    form_data: Any,
    obj: Any | None,
    action: str | None,
    parsed: dict[str, Any],
    errors: dict[str, list[str]],
) -> None:
    """Handle a file upload field during form submission."""
    storage = _get_storage(request)
    field_name = field_meta.name
    raw = form_data.get(field_name)

    if isinstance(raw, UploadFile) and raw.filename:
        if widget.max_size_mb is not None:
            content = await raw.read()
            max_bytes = int(widget.max_size_mb * 1024 * 1024)
            if len(content) > max_bytes:
                errors[field_name] = [
                    f"File size exceeds maximum allowed size ({widget.max_size_mb} MB)."
                ]
                await raw.seek(0)
                return
            await raw.seek(0)

        if storage is None:
            errors[field_name] = ["No storage backend configured."]
            return

        try:
            path = await storage.save(raw, directory=field_meta.name)
        except ValueError as exc:
            errors[field_name] = [str(exc)]
            return

        if action == "replace" and obj is not None:
            old_path = getattr(obj, field_name, None)
            if old_path:
                await storage.delete(old_path)

        parsed[field_name] = path

    elif action == "clear":
        if storage is not None and obj is not None:
            old_path = getattr(obj, field_name, None)
            if old_path:
                await storage.delete(old_path)
        parsed[field_name] = None

    elif action == "keep" or action is None:
        if obj is not None:
            parsed[field_name] = getattr(obj, field_name, None)

    else:
        if obj is not None:
            parsed[field_name] = getattr(obj, field_name, None)


class HTMLFormParser:
    """SRP: Parse multipart/form-data from HTML forms."""

    def __init__(self, registered: RegisteredModel):
        self.registered = registered
        self.validator = FormValidator()

    async def parse(
        self, request: Request, obj: Any | None = None
    ) -> tuple[dict[str, Any], dict[str, list[str]]]:
        form_data = await request.form()
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
    """SRP: Build and execute SQLAlchemy queries with filtering, search, pagination."""

    def __init__(self, registered: RegisteredModel):
        self.registered = registered

    def _get_eager_loads(self, model: Any, list_display: list[str]) -> list:
        """Build eager load options for relationship columns."""
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy.orm import joinedload

        mapper = sa_inspect(model)
        rel_names = {r.key for r in mapper.relationships}
        options = []
        for col_name in list_display:
            if col_name in rel_names:
                options.append(joinedload(getattr(model, col_name)))
        return options

    def _get_field_type(self, model: Any, field_name: str) -> str:
        """Detect the abstract field type for a model field."""
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(model)
        rel_names = {r.key for r in mapper.relationships}

        if field_name in rel_names:
            return "relation"

        for prop in mapper.column_attrs:
            if prop.key == field_name:
                col = prop.columns[0] if prop.columns else None
                if col is None:
                    break
                type_name = col.type.__class__.__name__
                if type_name == "Boolean":
                    return "boolean"
                if type_name == "DateTime":
                    return "datetime"
                if type_name == "Date":
                    return "date"
                if type_name == "Time":
                    return "time"
                if hasattr(col.type, "enums") and col.type.enums:
                    return "enum"
                if col.foreign_keys:
                    return "relation"
                return "text"
        return "text"

    async def _get_filter_choices(
        self, model: Any, field_name: str, session: Any = None
    ) -> dict[str, Any]:
        """Get filter field type and available choices for a field."""
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy import select

        mapper = sa_inspect(model)
        field_type = self._get_field_type(model, field_name)

        if field_type == "relation":
            rel_map = {r.key: r for r in mapper.relationships}
            target_model = None
            if field_name in rel_map:
                target_model = rel_map[field_name].mapper.class_
            else:
                for rel in mapper.relationships:
                    if rel.direction.name == "MANYTOONE":
                        for prop in mapper.column_attrs:
                            if prop.key == field_name:
                                col = prop.columns[0] if prop.columns else None
                                if col is not None:
                                    for fk in col.foreign_keys:
                                        if fk.column.table == rel.mapper.persist_selectable:
                                            target_model = rel.mapper.class_
                                            break
                        if target_model is not None:
                            break

            choices: list[tuple[str, str]] = [("", "All")]
            if target_model is not None and session is not None:
                try:
                    order_col = getattr(target_model, "name", None) or getattr(
                        target_model, "title", None
                    )
                    if order_col is not None:
                        q = select(target_model).order_by(order_col).limit(100)
                    else:
                        pk = sa_inspect(target_model).primary_key[0]
                        q = select(target_model).order_by(pk).limit(100)
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
            return {"field_type": field_type, "choices": choices}

        if field_type == "boolean":
            return {
                "field_type": "boolean",
                "choices": [("", "All"), ("1", "Yes"), ("0", "No")],
            }

        if field_type == "enum":
            for prop in mapper.column_attrs:
                if prop.key == field_name:
                    col = prop.columns[0] if prop.columns else None
                    if col is not None and hasattr(col.type, "enums"):
                        choices = [("", "All")]
                        for val in col.type.enums:
                            choices.append((val, val.replace("_", " ").title()))
                        return {"field_type": field_type, "choices": choices}

        if field_type in ("date", "datetime", "time"):
            return {"field_type": field_type, "choices": [("", "All")]}

        choices = [("", "All")]
        for prop in mapper.column_attrs:
            if prop.key == field_name:
                col = prop.columns[0] if prop.columns else None
                if col is not None and session is not None:
                    try:
                        q = (
                            select(col)
                            .where(col.isnot(None))
                            .group_by(col)
                            .order_by(col)
                            .limit(100)
                        )
                        result = session.execute(q)
                        for (val,) in result:
                            label = str(val).replace("_", " ").title()
                            choices.append((str(val), label))
                    except Exception:
                        pass
        return {"field_type": "text", "choices": choices}

    async def get_list(
        self, request: Request, q: str = "", page: int = 1
    ) -> tuple[list[Any], int, int, int]:
        """Execute list query with filtering, search, pagination.

        Returns (items, total, page, per_page).
        """
        from sqlalchemy import and_, asc, desc, select

        from fastapi_admin_kit.search_utils import apply_search_filter

        session = get_db_session(request)
        registered = self.registered
        model = registered.model
        base = select(model)

        list_display = registered.admin.list_display or [
            c.name for c in registered.columns if c.name != "id"
        ]

        eager_loads = self._get_eager_loads(model, list_display)
        for opt in eager_loads:
            base = base.options(opt)

        if registered.admin.list_filter:
            filter_clauses = []
            for filter_field in registered.admin.list_filter:
                param_key = f"filter_{filter_field}"
                filter_value = request.query_params.get(param_key, "")
                if filter_value and hasattr(model, filter_field):
                    field_type = self._get_field_type(model, filter_field)
                    col = getattr(model, filter_field)

                    if field_type == "boolean":
                        bool_val = filter_value == "1"
                        filter_clauses.append(col == bool_val)
                    elif field_type == "datetime":
                        from datetime import datetime as _dt

                        try:
                            parsed = _dt.fromisoformat(filter_value)
                        except (ValueError, TypeError):
                            parsed = None
                        if parsed is not None:
                            filter_clauses.append(col == parsed)
                    elif field_type == "date":
                        from datetime import date as _date

                        try:
                            parsed = _date.fromisoformat(filter_value)
                        except (ValueError, TypeError):
                            parsed = None
                        if parsed is not None:
                            filter_clauses.append(col == parsed)
                    elif field_type == "time":
                        from datetime import time as _time

                        try:
                            parsed = _time.fromisoformat(filter_value)
                        except (ValueError, TypeError):
                            parsed = None
                        if parsed is not None:
                            filter_clauses.append(col == parsed)
                    else:
                        filter_clauses.append(col == filter_value)

            # Range filters
            for filter_field in registered.admin.list_filter:
                gte_val = request.query_params.get(f"filter_{filter_field}__gte", "")
                lte_val = request.query_params.get(f"filter_{filter_field}__lte", "")
                from_val = request.query_params.get(f"filter_{filter_field}__from", "")
                to_val = request.query_params.get(f"filter_{filter_field}__to", "")

                if (gte_val or lte_val) and hasattr(model, filter_field):
                    col = getattr(model, filter_field)
                    if gte_val:
                        try:
                            filter_clauses.append(
                                col >= type(col.property.columns[0].type)().coerce(gte_val)
                            )
                        except Exception:
                            pass
                    if lte_val:
                        try:
                            filter_clauses.append(
                                col <= type(col.property.columns[0].type)().coerce(lte_val)
                            )
                        except Exception:
                            pass

                if (from_val or to_val) and hasattr(model, filter_field):
                    col = getattr(model, filter_field)
                    field_type = self._get_field_type(model, filter_field)
                    if field_type == "date" and from_val:
                        try:
                            from datetime import date as _date

                            d = _date.fromisoformat(from_val)
                            filter_clauses.append(col >= d)
                        except (ValueError, TypeError):
                            pass
                    if field_type == "date" and to_val:
                        try:
                            from datetime import date as _date

                            d = _date.fromisoformat(to_val)
                            filter_clauses.append(col <= d)
                        except (ValueError, TypeError):
                            pass
                    if field_type == "datetime" and from_val:
                        try:
                            from datetime import datetime as _dt

                            dt = _dt.fromisoformat(from_val)
                            filter_clauses.append(col >= dt)
                        except (ValueError, TypeError):
                            pass
                    if field_type == "datetime" and to_val:
                        try:
                            from datetime import datetime as _dt

                            dt = _dt.fromisoformat(to_val)
                            filter_clauses.append(col <= dt)
                        except (ValueError, TypeError):
                            pass

            if filter_clauses:
                base = base.where(and_(*filter_clauses))

        if q and registered.admin.search_fields:
            base = apply_search_filter(base, model, registered.admin.search_fields, q)

        query_ordering = request.query_params.get("ordering", "")
        if query_ordering:
            order = [query_ordering]
        else:
            order = registered.admin.ordering or []
        if order:
            col_name = order[0].lstrip("-")
            col = getattr(model, col_name, None) if hasattr(model, col_name) else None
            if col is not None:
                base = base.order_by(desc(col) if order[0].startswith("-") else asc(col))

        per_page = registered.admin.per_page

        from fastapi_admin_kit.pagination import OffsetPagination, PaginationResult

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
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy.orm import selectinload

        session = get_db_session(request)
        mapper = sa_inspect(self.registered.model)
        options = []
        for rel in mapper.relationships:
            if rel.direction.name == "MANYTOMANY":
                options.append(selectinload(getattr(self.registered.model, rel.key)))
        from fastapi_admin_kit.inspection import cast_pk_value

        int_id = cast_pk_value(self.registered.model, id)
        if options:
            from sqlalchemy import select

            stmt = (
                select(self.registered.model)
                .options(*options)
                .where(getattr(self.registered.model, self.registered.pk_field) == int_id)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
        return await session.get(self.registered.model, int_id)
