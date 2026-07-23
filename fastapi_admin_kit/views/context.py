"""ViewContextBuilder — builds template contexts for CRUD views."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import joinedload

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
                        q = sa_select(target_model).order_by(order_col).limit(100)
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

        .. deprecated::
            Use :class:`ListContextBuilder.build_list_context` instead.
            This method delegates to ListContextBuilder for backward compatibility.
        """
        from fastapi_admin_kit.views.list_context import ListContextBuilder

        builder = ListContextBuilder()
        return await builder.build_list_context(registered, request, q, page, permission_checker)

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
            "permissions": permission_checker.permission_set(registered.table_name)
            if permission_checker
            else PermissionSet(can_view=True, can_create=True, can_edit=True, can_delete=True),
            "detail_actions": registered.admin.get_detail_actions(),
            "submit_line_actions": registered.admin.get_submit_line_actions(),
            "conditional_fields": getattr(registered.admin, "conditional_fields", {}),
            "warn_unsaved_form": getattr(registered.admin, "warn_unsaved_form", True),
            "compressed_fields": getattr(registered.admin, "compressed_fields", True),
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
            "permissions": permission_checker.permission_set(registered.table_name)
            if permission_checker
            else PermissionSet(can_view=True, can_create=True, can_edit=True, can_delete=True),
        }
        await inject_sidebar_context(request, template_context)
        return template_context
