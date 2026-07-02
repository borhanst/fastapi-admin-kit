"""ViewContextBuilder — builds template contexts for CRUD views."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy import and_, asc, desc, or_, select
from sqlalchemy.orm import joinedload

from fastapi_admin_kit.db import get_db_session
from fastapi_admin_kit.registry import RegisteredModel
from fastapi_admin_kit.types import PermissionSet
from fastapi_admin_kit.views.sidebar import inject_sidebar_context


class DisplayColumn:
    """Helper to render a column in the list view."""

    def __init__(
        self,
        name: str,
        label: str,
        is_relation: bool = False,
        display_fn: Any = None,
        options: Any = None,
    ):
        self.name = name
        self.label = label
        self.is_relation = is_relation
        self.display_fn = display_fn
        self.options = options
        self.boolean = options.boolean if options else False
        self.css_class = options.css_class if options else ""
        self.width = options.width if options else None
        self.icon = options.icon if options else ""

    def value(self, obj: Any) -> Any:
        if self.display_fn:
            result = self.display_fn(obj)
            if result is None:
                return self.options.empty_value if self.options else "-"
            if self.options and self.options.format and result is not None:
                try:
                    return self.options.format.format(result)
                except (ValueError, IndexError):
                    return str(result)
            return result

        val = getattr(obj, self.name, "")

        if self.is_relation and val is not None:
            from fastapi_admin_kit.inspection import model_display_name

            return model_display_name(val)

        return val


class ViewContextBuilder:
    """Builds template contexts for list, form, and delete views.

    Centralizes context construction logic that was previously duplicated
    across multiple factory functions.
    """

    def __init__(
        self,
        registry: Any = None,
        permission_checker: Any = None,
        widget_resolver: Any = None,
    ):
        self.registry = registry
        self.permission_checker = permission_checker
        self.widget_resolver = widget_resolver

    def _get_eager_loads(self, model: Any, list_display: list[str]) -> list:
        """Build eager load options for relationship columns."""
        from sqlalchemy import inspect as sa_inspect

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
        from sqlalchemy import select as sa_select

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
                                        if (
                                            fk.column.table
                                            == rel.mapper.persist_selectable
                                        ):
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
                        q = (
                            sa_select(target_model)
                            .order_by(order_col)
                            .limit(100)
                        )
                    else:
                        pk = sa_inspect(target_model).primary_key[0]
                        q = sa_select(target_model).order_by(pk).limit(100)
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
                        return {"field_type": "enum", "choices": choices}

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

    async def build_list_context(
        self,
        registered: RegisteredModel,
        request: Request,
        q: str = "",
        page: int = 1,
        permission_checker: Any = None,
    ) -> dict[str, Any]:
        """Build the template context for a list view.

        Returns a dict suitable for passing to TemplateResponse.
        """
        session = get_db_session(request)
        model = registered.model
        base = select(model)

        list_display = registered.admin.list_display or [
            c.name for c in registered.columns if c.name != "id"
        ]

        eager_loads = self._get_eager_loads(model, list_display)
        for opt in eager_loads:
            base = base.options(opt)

        active_filters: dict[str, str] = {}
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

                if filter_value:
                    active_filters[filter_field] = filter_value

            # Support range filters: filter_field__gte, filter_field__lte, etc.
            for filter_field in registered.admin.list_filter:
                gte_val = request.query_params.get(
                    f"filter_{filter_field}__gte", ""
                )
                lte_val = request.query_params.get(
                    f"filter_{filter_field}__lte", ""
                )
                from_val = request.query_params.get(
                    f"filter_{filter_field}__from", ""
                )
                to_val = request.query_params.get(
                    f"filter_{filter_field}__to", ""
                )

                if (gte_val or lte_val) and hasattr(model, filter_field):
                    col = getattr(model, filter_field)
                    if gte_val:
                        try:
                            col_type = type(col.property.columns[0].type)
                            filter_clauses.append(
                                col >= col_type().coerce(gte_val)
                            )
                        except Exception:
                            pass
                    if lte_val:
                        try:
                            col_type = type(col.property.columns[0].type)
                            filter_clauses.append(
                                col <= col_type().coerce(lte_val)
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

                if gte_val:
                    active_filters[f"{filter_field}__gte"] = gte_val
                if lte_val:
                    active_filters[f"{filter_field}__lte"] = lte_val
                if from_val:
                    active_filters[f"{filter_field}__from"] = from_val
                if to_val:
                    active_filters[f"{filter_field}__to"] = to_val

            if filter_clauses:
                base = base.where(and_(*filter_clauses))

        if q and registered.admin.search_fields:
            clauses = []
            for sf in registered.admin.search_fields:
                if hasattr(model, sf):
                    col = getattr(model, sf)
                    if hasattr(col, "ilike"):
                        clauses.append(col.ilike(f"%{q}%"))
            if clauses:
                base = base.where(or_(*clauses))

        query_ordering = request.query_params.get("ordering", "")
        if query_ordering:
            order = [query_ordering]
        else:
            order = registered.admin.ordering or []
        if order:
            col_name = order[0].lstrip("-")
            col = (
                getattr(model, col_name, None)
                if hasattr(model, col_name)
                else None
            )
            if col is not None:
                base = base.order_by(
                    desc(col) if order[0].startswith("-") else asc(col)
                )

        per_page = registered.admin.per_page

        from fastapi_admin_kit.pagination import OffsetPagination, PaginationResult

        pagination = getattr(registered.admin, "pagination", None) or OffsetPagination()
        pk_col = getattr(model, registered.pk_field) if registered.pk_field else None
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
        items = pagination_result.items
        total = pagination_result.total
        page = pagination_result.page or 1
        total_pages = pagination_result.total_pages or 1

        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(model)
        rel_names = {r.key for r in mapper.relationships}

        # Collect @column decorated methods (check _column_options attribute)
        decorated_columns: dict[str, Any] = {}
        for col_name in list_display:
            method = getattr(registered.admin, col_name, None)
            if method and hasattr(method, "_column_options"):
                decorated_columns[col_name] = method._column_options

        display_columns = []
        for col_name in list_display:
            label = col_name.replace("_", " ").title()
            display_fn = None
            options = None

            # Check @column decorator first
            if col_name in decorated_columns:
                options = decorated_columns[col_name]
                display_fn = getattr(registered.admin, col_name)
                label = options.header or label
            # Check display_functions dict fallback
            elif (
                registered.admin.display_functions
                and col_name in registered.admin.display_functions
            ):
                display_fn = registered.admin.display_functions[col_name]

            display_columns.append(
                DisplayColumn(col_name, label, col_name in rel_names, display_fn, options)
            )

        filter_fields: dict[str, dict[str, Any]] = {}
        if registered.admin.list_filter:
            for filter_field in registered.admin.list_filter:
                filter_fields[filter_field] = await self._get_filter_choices(
                    model, filter_field, session
                )

        ordering = request.query_params.get("ordering", "")
        if not ordering and registered.admin.ordering:
            ordering = registered.admin.ordering[0]

        template_context = {
            "model": registered,
            "registered": registered,
            "display_columns": display_columns,
            "items": items,
            "search_query": q,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "per_page": per_page,
            "next_cursor": pagination_result.next_cursor,
            "has_next": pagination_result.has_next,
            "pagination_mode": pagination_result.mode,
            "filter_fields": filter_fields,
            "active_filters": active_filters,
            "ordering": ordering,
            "permissions": permission_checker.permission_set(
                registered.table_name
            )
            if permission_checker
            else PermissionSet(
                can_view=True, can_create=True, can_edit=True, can_delete=True
            ),
            "list_actions": registered.admin.get_list_actions(),
            "row_actions": registered.admin.get_row_actions(),
            "list_tabs": getattr(registered.admin, "list_tabs", []),
            "list_sections": getattr(registered.admin, "list_sections", []),
            "ordering_field": getattr(registered.admin, "ordering_field", None),
            "hide_ordering_field": getattr(
                registered.admin, "hide_ordering_field", False
            ),
            "list_filter_options": getattr(
                registered.admin, "list_filter_options", {}
            ),
            "list_filter_horizontal": getattr(
                registered.admin, "list_filter_horizontal", False
            ),
        }
        await inject_sidebar_context(request, template_context)
        return template_context

    async def build_form_context(
        self,
        registered: RegisteredModel,
        request: Request,
        obj: Any | None = None,
        values: dict[str, Any] | None = None,
        errors: dict[str, list[str]] | None = None,
        is_create: bool = False,
        permission_checker: Any = None,
        rel_labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Build the template context for a form view.

        Returns a dict suitable for passing to TemplateResponse.
        """
        from fastapi_admin_kit.form.pipeline import (
            build_form_context as _build_form_ctx,
        )

        ctx = _build_form_ctx(
            registered,
            obj=obj,
            values=values,
            errors=errors,
            request=request,
            is_create=is_create,
            rel_labels=rel_labels,
        )
        template_context = {
            "form_context": ctx,
            "registered": registered,
            "obj": ctx.obj,
            "form_fields": ctx.fieldsets[0].fields if ctx.fieldsets else [],
            "fieldsets": ctx.fieldsets,
            "errors": ctx.errors,
            "is_create": is_create,
            "permissions": permission_checker.permission_set(
                registered.table_name
            )
            if permission_checker
            else PermissionSet(
                can_view=True, can_create=True, can_edit=True, can_delete=True
            ),
            "detail_actions": registered.admin.get_detail_actions(),
            "submit_line_actions": registered.admin.get_submit_line_actions(),
            "conditional_fields": getattr(
                registered.admin, "conditional_fields", {}
            ),
            "warn_unsaved_form": getattr(
                registered.admin, "warn_unsaved_form", True
            ),
            "compressed_fields": getattr(
                registered.admin, "compressed_fields", True
            ),
            "change_form_show_cancel_button": getattr(
                registered.admin, "change_form_show_cancel_button", True
            ),
        }
        await inject_sidebar_context(request, template_context)
        return template_context

    async def build_delete_context(
        self,
        registered: RegisteredModel,
        request: Request,
        permission_checker: Any = None,
    ) -> dict[str, Any]:
        """Build the template context for a delete confirmation view.

        Returns a dict suitable for passing to TemplateResponse.
        """
        template_context = {
            "model": registered,
            "registered": registered,
            "permissions": permission_checker.permission_set(
                registered.table_name
            )
            if permission_checker
            else PermissionSet(
                can_view=True, can_create=True, can_edit=True, can_delete=True
            ),
        }
        await inject_sidebar_context(request, template_context)
        return template_context
