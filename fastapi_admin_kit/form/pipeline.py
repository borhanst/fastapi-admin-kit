"""Build FormContext from a RegisteredModel + DB object + values + errors."""

from __future__ import annotations

from typing import Any

from fastapi_admin_kit.types import (
    FieldRenderContext,
    FieldsetContext,
    FormContext,
    InlineFormsetData,
    PermissionSet,
)


async def build_inline_formsets(
    registered: Any,
    obj: Any | None = None,
    inlines: list[Any] | None = None,
    request: Any = None,
    inline_values: dict[str, dict[str, list[str]]] | None = None,
    inline_errors: dict[str, dict[int, dict[str, list[str]]]] | None = None,
) -> list[InlineFormsetData]:
    """Build InlineFormsetData for each inline configuration.

    Args:
        registered: The parent model's RegisteredModel.
        obj: The parent object (None for create).
        inlines: List of InlineModelAdmin subclasses.
        request: The current request.
        inline_values: Parsed inline form data {prefix: {field: [val0, val1, ...]}}.
        inline_errors: Validation errors per inline {prefix: {row_idx: {field: [errs]}}}.
    """
    from fastapi_admin_kit.inspection import auto_label
    from fastapi_admin_kit.registry import AdminRegistry
    from fastapi_admin_kit.types import PermissionSet

    if not inlines:
        return []

    registry = AdminRegistry()
    inline_formsets: list[InlineFormsetData] = []
    inline_values = inline_values or {}
    inline_errors = inline_errors or {}

    # Resolve permission checker for inline models
    checker = None
    if request is not None:
        try:
            from fastapi_admin_kit.views.renderers import _resolve_permission_checker

            checker = await _resolve_permission_checker(request)
        except Exception:
            pass

    for inline_cls in inlines:
        inline_instance = inline_cls() if isinstance(inline_cls, type) else inline_cls
        related_model = inline_instance.model
        if related_model is None:
            continue

        # Build prefix from model name
        prefix = f"{related_model.__tablename__}_set"

        # Check permissions for the related model
        perms = PermissionSet(can_view=True, can_create=True, can_edit=True, can_delete=True)
        if checker is not None:
            try:
                await checker.load_permissions(related_model.__tablename__)
                perms = checker.permission_set(related_model.__tablename__)
            except Exception:
                pass

        # Skip inline if no view permission
        if not perms.can_view:
            continue

        # Find FK field pointing to parent
        fk_field = inline_instance.fk_name
        if not fk_field:
            # Auto-detect: look for FK pointing to parent model's table
            from sqlalchemy import inspect as sa_inspect

            mapper = sa_inspect(related_model)
            parent_table = registered.table_name
            for rel_key, rel_prop in mapper.relationships.items():
                if rel_prop.direction.name == "MANYTOONE":
                    target_table = rel_prop.mapper.class_.__tablename__
                    if target_table == parent_table:
                        local_cols = [c.key for c in rel_prop.local_columns]
                        if local_cols:
                            fk_field = local_cols[0]
                            break
            # Fallback: look for FK columns pointing to parent table
            if not fk_field:
                for col in registered.columns:
                    for fk in col.foreign_keys:
                        if fk.column.table.name == parent_table:
                            fk_field = col.name
                            break
                    if fk_field:
                        break

        # Get related model columns
        related_registered = registry.get(related_model.__tablename__)
        if related_registered is None:
            # Register the related model temporarily
            related_registered = registry.register(related_model)

        # Determine fields to display
        fields = inline_instance.get_form_fields(columns=related_registered.columns)

        # Build field labels
        field_labels = {f: auto_label(f) for f in fields}

        # Get initial data (existing related objects)
        initial: list[dict[str, Any]] = []
        initial_ids: list[str] = []

        # Build relationship map for the related model to detect FK fields
        from sqlalchemy import inspect as _sa_inspect

        try:
            _mapper = _sa_inspect(related_model)
            _rel_map = {r.key: r for r in _mapper.relationships}
        except Exception:
            _rel_map = {}

        if obj is not None and fk_field:
            # Load existing related objects
            from sqlalchemy import select
            from sqlalchemy.orm import joinedload

            session = None
            if request is not None:
                from fastapi_admin_kit.db import get_db_session

                session = get_db_session(request)

            if session is not None:
                try:
                    parent_pk = getattr(obj, "id", None)
                    if parent_pk is not None:
                        stmt = select(related_model).where(
                            getattr(related_model, fk_field) == parent_pk
                        )
                        # Eagerly load relationship fields to avoid lazy-load in async context
                        for _fn in fields:
                            _rel = _rel_map.get(_fn)
                            if _rel is not None and (
                                _rel.direction.name == "MANYTOONE" or not _rel.uselist
                            ):
                                stmt = stmt.options(joinedload(_rel))
                        if inline_instance.ordering:
                            for order in inline_instance.ordering:
                                if order.startswith("-"):
                                    col = getattr(related_model, order[1:], None)
                                    if col is not None:
                                        stmt = stmt.order_by(col.desc())
                                else:
                                    col = getattr(related_model, order, None)
                                    if col is not None:
                                        stmt = stmt.order_by(col)
                        result = session.execute(stmt)
                        if hasattr(result, "__await__"):
                            result = await result
                        related_objects = result.scalars().unique().all()

                        for rel_obj in related_objects:
                            row_data: dict[str, Any] = {"id": str(getattr(rel_obj, "id", ""))}
                            for field_name in fields:
                                rel = _rel_map.get(field_name)
                                if rel is not None and (
                                    rel.direction.name == "MANYTOONE" or not rel.uselist
                                ):
                                    local_cols = [c.key for c in rel.local_columns]
                                    val = getattr(rel_obj, local_cols[0], "") if local_cols else ""
                                    # Store the label for relation fields (already eagerly loaded)
                                    try:
                                        target_obj = getattr(rel_obj, field_name, None)
                                        if target_obj is not None and hasattr(target_obj, "id"):
                                            row_data[f"_{field_name}_label"] = str(target_obj)
                                    except Exception:
                                        pass
                                else:
                                    val = getattr(rel_obj, field_name, "")
                                # Convert boolean to "1"/"0" for checkbox compatibility
                                if isinstance(val, bool):
                                    val = "1" if val else "0"
                                else:
                                    val = str(val) if val is not None else ""
                                row_data[field_name] = val
                            initial.append(row_data)
                            initial_ids.append(str(getattr(rel_obj, "id", "")))
                except Exception:
                    pass

        # Use submitted values if available
        prefix_data = inline_values.get(prefix, {})
        if prefix_data:
            # Rebuild initial from submitted data
            total_forms = int(prefix_data.get(f"{prefix}-TOTAL_FORMS", "0"))
            initial = []
            initial_ids = []
            for i in range(total_forms):
                row: dict[str, Any] = {}
                row_id = prefix_data.get(f"{prefix}-{i}-id", "")
                if row_id:
                    row["id"] = row_id
                    initial_ids.append(row_id)
                for field_name in fields:
                    row[field_name] = prefix_data.get(f"{prefix}-{i}-{field_name}", "")
                initial.append(row)

        # Calculate total forms
        submitted_total = len(initial) if prefix_data else 0
        extra_count = inline_instance.extra
        total_forms = max(submitted_total, inline_instance.min_num) + extra_count
        if inline_instance.max_num is not None:
            total_forms = min(total_forms, inline_instance.max_num)

        # Build field metadata with type detection
        from sqlalchemy import Boolean, Date, DateTime, Float, Integer
        from sqlalchemy import inspect as sa_inspect

        boolean_fields: list[str] = []
        field_metas: list[Any] = []
        admin_path = "/admin"
        if request is not None:
            try:
                admin_config = getattr(request.app.state, "admin_config", None)
                if admin_config is not None:
                    admin_path = admin_config.get("admin_path", "/admin")
            except Exception:
                pass

        # Get relationships for the related model
        try:
            mapper = sa_inspect(related_model)
            rel_map = {r.key: r for r in mapper.relationships}
        except Exception:
            rel_map = {}

        for field_name in fields:
            col = next((c for c in related_registered.columns if c.name == field_name), None)
            rel = rel_map.get(field_name)
            field_type = "text"
            choices = None
            related_table = ""
            related_verbose = ""
            search_url = ""
            required = False

            if col is not None:
                col_type = type(col.type)
                required = not col.nullable

                if col_type in (Boolean,):
                    field_type = "boolean"
                    boolean_fields.append(field_name)
                elif col_type in (Integer,):
                    field_type = "number"
                elif col_type in (Float,):
                    field_type = "number"
                elif col_type in (Date,):
                    field_type = "date"
                elif col_type in (DateTime,):
                    field_type = "datetime"
                elif hasattr(col.type, "enums") and col.type.enums:
                    field_type = "select"
                    choices = [(e, e) for e in col.type.enums]
                else:
                    field_type = "text"
            elif rel is not None:
                # Relationship field
                target_model = rel.mapper.class_
                if rel.direction.name == "MANYTOONE" or not rel.uselist:
                    field_type = "relation"
                    related_table = target_model.__tablename__
                    related_verbose = auto_label(related_table)
                    search_url = f"{admin_path}/{related_table}/search"
                elif rel.direction.name == "MANYTOMANY":
                    field_type = "relation"
                    related_table = target_model.__tablename__
                    related_verbose = auto_label(related_table)
                    search_url = f"{admin_path}/{related_table}/search"

            from fastapi_admin_kit.types import InlineFormFieldMeta

            field_metas.append(
                InlineFormFieldMeta(
                    name=field_name,
                    label=field_labels.get(field_name, auto_label(field_name)),
                    field_type=field_type,
                    required=required,
                    readonly=field_name in inline_instance.get_readonly_fields(),
                    choices=choices,
                    related_table=related_table,
                    related_verbose=related_verbose,
                    search_url=search_url,
                    placeholder=f"Enter {auto_label(field_name).lower()}...",
                )
            )

        inline_formsets.append(
            InlineFormsetData(
                prefix=prefix,
                inline_type=inline_instance.inline_type,
                fields=fields,
                field_metas=field_metas,
                field_labels=field_labels,
                verbose_name=inline_instance.verbose_name or related_model.__name__,
                verbose_name_plural=inline_instance.verbose_name_plural
                or f"{related_model.__name__}s",
                can_delete=inline_instance.can_delete and perms.can_delete,
                can_add=perms.can_create,
                can_change=perms.can_edit,
                can_remove=perms.can_delete,
                initial=initial,
                initial_ids=initial_ids,
                extra_count=extra_count,
                max_num=inline_instance.max_num,
                min_num=inline_instance.min_num,
                errors=inline_errors.get(prefix, {}),
                readonly_fields=inline_instance.get_readonly_fields(),
                formfield_overrides=inline_instance.get_formfield_overrides(),
                fk_field=fk_field,
                boolean_fields=boolean_fields,
            )
        )

    return inline_formsets


def build_form_context(
    registered: Any,
    obj: Any | None = None,
    values: dict[str, Any] | None = None,
    errors: dict[str, list[str]] | None = None,
    request: Any = None,
    is_create: bool = False,
    rel_labels: dict[str, str] | None = None,
    inline_formsets: list[InlineFormsetData] | None = None,
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
        inline_formsets=inline_formsets or [],
    )
