"""Build FormContext from a RegisteredModel + DB object + values + errors."""

from __future__ import annotations

from typing import Any

from fastapi_admin_kit.types import (
    FieldRenderContext,
    FieldsetContext,
    FormContext,
    PermissionSet,
)


def build_form_context(
    registered: Any,
    obj: Any | None = None,
    values: dict[str, Any] | None = None,
    errors: dict[str, list[str]] | None = None,
    request: Any = None,
    is_create: bool = False,
    rel_labels: dict[str, str] | None = None,
) -> FormContext:
    values = values or {}
    errors = errors or {}
    rendered: list[FieldRenderContext] = []
    fieldsets: list[FieldsetContext] = [FieldsetContext(fields=[])]

    for field_meta in registered.form_fields:
        col = next((c for c in registered.columns if c.name == field_meta.name), None)
        rel = next(
            (r for r in registered.relationships if r.name == field_meta.name),
            None,
        )
        widget = registered.get_widget(field_meta.name)

        value = values.get(field_meta.name)
        if value is None and obj is not None:
            if hasattr(obj, "__dict__"):
                value = obj.__dict__.get(field_meta.name)
            # For M2M relationships, extract IDs from loaded collection
            if value is None and rel is not None:
                try:
                    from sqlalchemy import inspect as sa_inspect

                    mapper = sa_inspect(type(obj))
                    rel_prop = mapper.relationships.get(rel.name)
                    if rel_prop is not None:
                        if rel_prop.direction.name == "MANYTOMANY":
                            collection = getattr(obj, rel_prop.key, None)
                            if collection is not None:
                                value = [str(item.id) for item in collection]
                        else:
                            local_cols = [c.key for c in rel_prop.local_columns]
                            if local_cols:
                                value = getattr(obj, local_cols[0], None)
                except Exception:
                    pass
            # Handle case where __dict__ returned loaded M2M collection objects
            if (
                value is not None
                and rel is not None
                and isinstance(value, list)
                and value
                and hasattr(value[0], "id")
            ):
                try:
                    from sqlalchemy import inspect as sa_inspect

                    mapper = sa_inspect(type(obj))
                    rel_prop = mapper.relationships.get(rel.name)
                    if rel_prop is not None and rel_prop.direction.name == "MANYTOMANY":
                        value = [str(item.id) for item in value]
                except Exception:
                    pass
            elif value is None and col is not None:
                value = getattr(obj, field_meta.name, None)

        widget_macro = widget.macro_name
        widget_ctx = widget.render_context(field_meta, value)
        widget_ctx["is_create"] = is_create
        if request is not None:
            admin_path = request.app.state.admin_config["admin_path"]
            widget_ctx["admin_path"] = admin_path
            if "search_url" in widget_ctx:
                widget_ctx["search_url"] = widget_ctx["search_url"].replace(
                    "/admin/", f"{admin_path}/"
                )
        if obj is not None:
            widget_ctx["obj_id"] = getattr(obj, "id", "")
        if rel is not None and rel_labels:
            widget_ctx["label_text"] = rel_labels.get(rel.name, "")
        field_errors = errors.get(field_meta.name, [])
        rendered.append(
            FieldRenderContext(
                meta=field_meta,
                widget_macro=widget_macro,
                widget_context=widget_ctx,
                errors=field_errors,
            )
        )

    fieldsets[0].fields = rendered

    return FormContext(
        model_name=registered.table_name,
        verbose_name=registered.verbose_name,
        is_create=is_create,
        obj=obj,
        fieldsets=fieldsets,
        errors=errors,
        values=values,
        action_url="",
        list_url="",
        can_delete=not is_create,
        permissions=PermissionSet(),
        readonly=False,
    )
