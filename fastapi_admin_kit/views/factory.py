"""ViewFactory — unified factory for CRUD view handlers."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.datastructures import UploadFile

from fastapi_admin_kit.db import get_db_session
from fastapi_admin_kit.flash import add_flash
from fastapi_admin_kit.registry import RegisteredModel
from fastapi_admin_kit.validation import FormValidator
from fastapi_admin_kit.views.context import ViewContextBuilder
from fastapi_admin_kit.widgets.inputs import FileUploadWidget, ImageUploadWidget

_FILE_WIDGET_TYPES = (FileUploadWidget, ImageUploadWidget)


def _apply_parsed_to_obj(
    obj: Any, parsed: dict[str, Any], registered: RegisteredModel
) -> None:
    """Apply parsed data to an ORM object, mapping relationship names to FK columns."""
    from sqlalchemy import inspect as sa_inspect

    col_names = {c.name for c in registered.columns}
    rel_fk_map: dict[str, str] = {}
    try:
        mapper = sa_inspect(type(obj))
    except Exception:
        mapper = None
    if mapper is not None:
        for rel_key, rel_prop in mapper.relationships.items():
            if rel_prop.direction.name == "MANYTOMANY":
                continue
            local_cols = [c.key for c in rel_prop.local_columns]
            if local_cols:
                rel_fk_map[rel_key] = local_cols[0]

    for key, value in parsed.items():
        if key in col_names:
            setattr(obj, key, value)
        elif key in rel_fk_map:
            setattr(obj, rel_fk_map[key], value)


def _pop_manytomany_keys(
    obj: Any, parsed: dict[str, Any], registered: RegisteredModel
) -> dict[str, dict[str, Any]]:
    """Remove MANYTOMANY relationship keys from parsed dict in-place.

    Returns a dict mapping rel_key -> raw parsed value for M2M fields.
    """
    from sqlalchemy import inspect as sa_inspect

    m2m_data: dict[str, Any] = {}
    try:
        model_class = type(obj) if not isinstance(obj, type) else obj
        mapper = sa_inspect(model_class)
    except Exception:
        return m2m_data
    for rel_key, rel_prop in mapper.relationships.items():
        if rel_prop.direction.name == "MANYTOMANY" and rel_key in parsed:
            m2m_data[rel_key] = parsed.pop(rel_key)
    return m2m_data


async def _apply_m2m_from_data(
    obj: Any, m2m_data: dict[str, Any], registered: RegisteredModel, session: Any
) -> None:
    """Apply MANYTOMANY data extracted by _pop_manytomany_keys."""
    import json as _json

    from sqlalchemy import inspect as sa_inspect

    if not m2m_data:
        return
    try:
        mapper = sa_inspect(type(obj))
    except Exception:
        return
    for rel_key, rel_prop in mapper.relationships.items():
        if rel_prop.direction.name != "MANYTOMANY":
            continue
        if rel_key not in m2m_data:
            continue
        raw = m2m_data[rel_key]
        pk_list = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item.startswith("["):
                    try:
                        pk_list.extend(_json.loads(item))
                    except (ValueError, TypeError):
                        pk_list.append(item)
                else:
                    pk_list.append(item)
        else:
            pk_list = [raw]
        target_model = rel_prop.mapper.class_
        objs = []
        for pk in pk_list:
            if not pk:
                continue
            try:
                from fastapi_admin_kit.inspection import cast_pk_value
                loaded = await session.get(target_model, cast_pk_value(target_model, pk))
                if loaded:
                    objs.append(loaded)
            except (ValueError, TypeError):
                pass
        await session.refresh(obj, [rel_key])
        setattr(obj, rel_key, objs)


def _resolve_rel_keys(
    parsed: dict[str, Any], registered: RegisteredModel
) -> dict[str, Any]:
    """Convert relationship keys in parsed data to their FK column names."""
    from sqlalchemy import inspect as sa_inspect

    col_names = {c.name for c in registered.columns}
    rel_fk_map: dict[str, str] = {}
    try:
        model = registered.model
        mapper = sa_inspect(model)
    except Exception:
        mapper = None
    if mapper is not None:
        for rel_key, rel_prop in mapper.relationships.items():
            if rel_prop.direction.name == "MANYTOMANY":
                continue
            local_cols = [c.key for c in rel_prop.local_columns]
            if local_cols:
                rel_fk_map[rel_key] = local_cols[0]

    resolved: dict[str, Any] = {}
    for key, value in parsed.items():
        if key in rel_fk_map and key not in col_names:
            resolved[rel_fk_map[key]] = value
        else:
            resolved[key] = value
    return resolved


async def _resolve_rel_labels(
    obj: Any, registered: RegisteredModel, request: Any
) -> dict[str, str]:
    """Resolve display labels for relationship fields from FK values."""
    from sqlalchemy import inspect as sa_inspect

    from fastapi_admin_kit.inspection import model_display_name

    labels: dict[str, str] = {}
    if obj is None:
        return labels
    try:
        mapper = sa_inspect(registered.model)
    except Exception:
        return labels
    session = get_db_session(request)
    for rel_key, rel_prop in mapper.relationships.items():
        local_cols = [c.key for c in rel_prop.local_columns]
        if not local_cols:
            continue
        fk_val = getattr(obj, local_cols[0], None)
        if fk_val is None:
            continue
        target_cls = rel_prop.mapper.class_
        try:
            target = await session.get(target_cls, fk_val)
            if target is not None:
                labels[rel_key] = model_display_name(target)
        except Exception:
            labels[rel_key] = str(fk_val)
    return labels


def _get_storage(request: Request):
    """Get the storage backend from app.state, or None."""
    return getattr(request.app.state, "admin_storage", None)


async def _resolve_permission_checker(request: Request) -> Any:
    """Resolve a PermissionChecker for the current request.

    Returns None if the user is not authenticated or the checker cannot be built.
    Delegates current-user resolution to :mod:`fastapi_admin_kit.auth.identity`, the
    single request-authentication seam — so the user is loaded per request on
    ``request.state.admin_user`` and never cached on ``app.state`` (which
    previously leaked identity across concurrent requests).
    """
    from fastapi_admin_kit.auth.identity import get_current_user_from_cookie
    from fastapi_admin_kit.auth.permissions import PermissionChecker

    user = await get_current_user_from_cookie(request)
    if user is None:
        return None

    async_session = get_db_session(request)
    if async_session is None:
        return None

    snapshot = getattr(request.state, "admin_user_snapshot", None)
    return PermissionChecker(session=async_session, user=user, user_snapshot=snapshot)


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


class ViewFactory:
    """Unified factory for creating CRUD view handlers.

    Centralizes view creation logic that was previously duplicated across
    multiple standalone factory functions.
    """

    def __init__(
        self,
        context_builder: ViewContextBuilder | None = None,
        form_pipeline: Any = None,
        validation_engine: Any = None,
    ):
        self.context_builder = context_builder or ViewContextBuilder()
        self.form_pipeline = form_pipeline
        self.validation_engine = validation_engine or FormValidator()

    async def _parse_form_fields(
        self,
        registered: RegisteredModel,
        form_data: Any,
        request: Request,
        obj: Any | None = None,
    ) -> tuple[dict[str, Any], dict[str, list[str]]]:
        """Parse and validate form fields from request data.

        Returns (parsed_values, errors).
        """
        parsed: dict[str, Any] = {}
        errors: dict[str, list[str]] = {}

        for field_meta in registered.form_fields:
            if field_meta.readonly:
                continue
            widget = registered.get_widget(field_meta.name)

            if isinstance(widget, _FILE_WIDGET_TYPES):
                action = (
                    form_data.get(f"_action_{field_meta.name}", "keep")
                    if obj
                    else None
                )
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
                if (
                    obj is None
                    and field_meta.name not in errors
                    and field_meta.name not in parsed
                ):
                    parsed[field_meta.name] = None
                continue

            raw = form_data.get(field_meta.name)
            value = widget.parse(raw)
            required_on_create = (field_meta.extra or {}).get("required_on_create")
            if obj is None and required_on_create is not None:
                from fastapi_admin_kit.types import FieldMeta
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
            errors = self.validation_engine.run(registered, parsed, obj=obj)

        return parsed, errors

    def create_list_view(self, registered: RegisteredModel):
        """Create a list view handler for the given model."""

        async def list_view(
            request: Request, q: str = "", page: int = 1, _: Any = None
        ):
            templates = request.app.state.admin_jinja_env
            checker = await _resolve_permission_checker(request)
            if checker:
                await checker.load_permissions(registered.table_name)
            ctx = await self.context_builder.build_list_context(
                registered, request, q=q, page=page, permission_checker=checker
            )
            is_htmx = request.headers.get("HX-Request") == "true"
            if is_htmx:
                return templates.TemplateResponse(
                    request, "partials/list_table.html", ctx
                )
            return templates.TemplateResponse(request, "pages/list.html", ctx)

        list_view.__name__ = f"list_{registered.table_name}"
        return list_view

    def create_create_form_view(self, registered: RegisteredModel):
        """Create a form display handler for creating new objects."""

        async def create_form(request: Request, _: Any = None):
            templates = request.app.state.admin_jinja_env
            checker = await _resolve_permission_checker(request)
            if checker:
                await checker.load_permissions(registered.table_name)
            ctx = await self.context_builder.build_form_context(
                registered, request, is_create=True, permission_checker=checker
            )
            return templates.TemplateResponse(request, "pages/form.html", ctx)

        create_form.__name__ = f"create_form_{registered.table_name}"
        return create_form

    def create_create_submit_view(self, registered: RegisteredModel):
        """Create a form submission handler for creating new objects."""

        async def create_submit(request: Request, _: Any = None):
            templates = request.app.state.admin_jinja_env
            session = get_db_session(request)
            form_data = await request.form()
            checker = await _resolve_permission_checker(request)
            if checker:
                await checker.load_permissions(registered.table_name)

            parsed, errors = await self._parse_form_fields(
                registered, form_data, request, obj=None
            )

            if errors:
                await session.rollback()
                ctx = await self.context_builder.build_form_context(
                    registered,
                    request,
                    values=parsed,
                    errors=errors,
                    is_create=True,
                    permission_checker=checker,
                )
                return templates.TemplateResponse(
                    request, "pages/form.html", ctx, status_code=422
                )

            try:
                parsed = registered.admin.validate_create(parsed, request)
            except ValueError as e:
                await session.rollback()
                ctx = await self.context_builder.build_form_context(
                    registered,
                    request,
                    values=parsed,
                    errors={"__all__": [str(e)]},
                    is_create=True,
                    permission_checker=checker,
                )
                return templates.TemplateResponse(
                    request, "pages/form.html", ctx, status_code=422
                )

            parsed = registered.admin.process_form_data(parsed, request)

            m2m_data = _pop_manytomany_keys(registered.model, parsed, registered)
            parsed = _resolve_rel_keys(parsed, registered)
            obj = registered.model(**parsed)
            registered.admin.on_create(obj, request)
            session.add(obj)
            await _apply_m2m_from_data(obj, m2m_data, registered, session)
            await session.flush()
            registered.admin.after_create(obj, request)
            await add_flash(request, "success", f"{registered.verbose_name} created.")
            url = f"{request.app.state.admin_config['admin_path']}/{registered.table_name}/"
            return RedirectResponse(url=url, status_code=303)

        create_submit.__name__ = f"create_submit_{registered.table_name}"
        return create_submit

    def create_edit_form_view(self, registered: RegisteredModel):
        """Create a form display handler for editing existing objects."""

        async def edit_form(request: Request, id: str, _: Any = None):
            templates = request.app.state.admin_jinja_env
            session = get_db_session(request)
            from fastapi_admin_kit.inspection import cast_pk_value
            obj = await session.get(registered.model, cast_pk_value(registered.model, id))
            if not obj:
                raise HTTPException(status_code=404, detail="Not found")
            checker = await _resolve_permission_checker(request)
            if checker:
                await checker.load_permissions(registered.table_name)
            rel_labels = await _resolve_rel_labels(obj, registered, request)
            ctx = await self.context_builder.build_form_context(
                registered,
                request,
                obj=obj,
                is_create=False,
                permission_checker=checker,
                rel_labels=rel_labels,
            )
            return templates.TemplateResponse(request, "pages/form.html", ctx)

        edit_form.__name__ = f"edit_form_{registered.table_name}"
        return edit_form

    def create_edit_submit_view(self, registered: RegisteredModel):
        """Create a form submission handler for editing existing objects."""

        async def edit_submit(request: Request, id: str, _: Any = None):
            templates = request.app.state.admin_jinja_env
            session = get_db_session(request)
            from fastapi_admin_kit.inspection import cast_pk_value
            obj = await session.get(registered.model, cast_pk_value(registered.model, id))
            if not obj:
                raise HTTPException(status_code=404, detail="Not found")
            form_data = await request.form()
            checker = await _resolve_permission_checker(request)
            if checker:
                await checker.load_permissions(registered.table_name)

            parsed, errors = await self._parse_form_fields(
                registered, form_data, request, obj=obj
            )

            if errors:
                await session.rollback()
                rel_labels = await _resolve_rel_labels(obj, registered, request)
                ctx = await self.context_builder.build_form_context(
                    registered,
                    request,
                    obj=obj,
                    values=parsed,
                    errors=errors,
                    is_create=False,
                    permission_checker=checker,
                    rel_labels=rel_labels,
                )
                return templates.TemplateResponse(
                    request, "pages/form.html", ctx, status_code=422
                )

            try:
                parsed = registered.admin.validate_update(obj, parsed, request)
            except ValueError as e:
                await session.rollback()
                rel_labels = await _resolve_rel_labels(obj, registered, request)
                ctx = await self.context_builder.build_form_context(
                    registered,
                    request,
                    obj=obj,
                    values=parsed,
                    errors={"__all__": [str(e)]},
                    is_create=False,
                    permission_checker=checker,
                    rel_labels=rel_labels,
                )
                return templates.TemplateResponse(
                    request, "pages/form.html", ctx, status_code=422
                )

            parsed = registered.admin.process_form_data(parsed, request)

            registered.admin.on_update(obj, parsed, request)
            m2m_data = _pop_manytomany_keys(obj, parsed, registered)
            _apply_parsed_to_obj(obj, parsed, registered)
            await _apply_m2m_from_data(obj, m2m_data, registered, session)
            await session.flush()
            registered.admin.after_update(obj, request)
            await add_flash(request, "success", f"{registered.verbose_name} updated.")
            url = f"{request.app.state.admin_config['admin_path']}/{registered.table_name}/"
            return RedirectResponse(url=url, status_code=303)

        edit_submit.__name__ = f"edit_submit_{registered.table_name}"
        return edit_submit

    def create_delete_view(self, registered: RegisteredModel):
        """Create a delete handler for removing objects."""

        async def delete_submit(request: Request, id: str, _: Any = None):
            session = get_db_session(request)
            try:
                await session.rollback()
            except Exception:
                pass
            from fastapi_admin_kit.inspection import cast_pk_value
            obj = await session.get(registered.model, cast_pk_value(registered.model, id))
            if not obj:
                raise HTTPException(status_code=404, detail="Not found")
            try:
                registered.admin.on_delete(obj, request)
                await session.delete(obj)
                await session.flush()
                registered.admin.after_delete(obj, request)
                await add_flash(
                    request, "success", f"{registered.verbose_name} deleted."
                )
            except Exception as e:
                await session.rollback()
                await add_flash(request, "error", f"Cannot delete: {str(e)}")
            url = f"{request.app.state.admin_config['admin_path']}/{registered.table_name}/"
            return RedirectResponse(url=url, status_code=303)

        delete_submit.__name__ = f"delete_{registered.table_name}"
        return delete_submit

    def create_bulk_view(self, registered: RegisteredModel):
        """Create a bulk action handler for multiple objects."""

        async def bulk_action(request: Request, _: Any = None):
            templates = request.app.state.admin_jinja_env
            session = get_db_session(request)
            try:
                await session.rollback()
            except Exception:
                pass
            form = await request.form()
            action = form.get("action", "")
            ids = form.getlist("ids[]")

            is_htmx = request.headers.get("HX-Request") == "true"

            if not ids:
                if is_htmx:
                    ctx = await self.context_builder.build_list_context(
                        registered, request, permission_checker=None
                    )
                    return templates.TemplateResponse(
                        request, "partials/list_table.html", ctx
                    )
                url = f"{request.app.state.admin_config['admin_path']}/{registered.table_name}/"
                return RedirectResponse(url=url, status_code=303)

            try:
                if action == "delete_selected":
                    for pid in ids:
                        obj = await session.get(registered.model, int(pid))
                        if obj:
                            registered.admin.on_delete(obj, request)
                            await session.delete(obj)
                    await session.flush()
                    await add_flash(
                        request,
                        "success",
                        f"{len(ids)} {registered.verbose_name}(s) deleted.",
                    )
                else:
                    action_fn = getattr(
                        registered.admin, f"action_{action}", None
                    )
                    if not action_fn:
                        raise HTTPException(
                            status_code=400, detail=f"Unknown action: {action}"
                        )
                    for pid in ids:
                        obj = await session.get(registered.model, int(pid))
                        if obj:
                            action_fn(obj)
                    await session.flush()
                    await add_flash(
                        request,
                        "success",
                        f"Action '{action}' applied to {len(ids)} item(s).",
                    )
            except Exception as e:
                await session.rollback()
                await add_flash(request, "error", f"Action failed: {str(e)}")

            if is_htmx:
                ctx = await self.context_builder.build_list_context(
                    registered, request, permission_checker=None
                )
                return templates.TemplateResponse(
                    request, "partials/list_table.html", ctx
                )

            url = f"{request.app.state.admin_config['admin_path']}/{registered.table_name}/"
            return RedirectResponse(url=url, status_code=303)

        bulk_action.__name__ = f"bulk_{registered.table_name}"
        return bulk_action

    def create_all_views(self, registered: RegisteredModel) -> dict[str, Any]:
        """Create all standard CRUD views for a registered model.

        Returns a dict mapping view names to handler functions.
        """
        return {
            "list": self.create_list_view(registered),
            "create_form": self.create_create_form_view(registered),
            "create_submit": self.create_create_submit_view(registered),
            "edit_form": self.create_edit_form_view(registered),
            "edit_submit": self.create_edit_submit_view(registered),
            "delete": self.create_delete_view(registered),
            "bulk": self.create_bulk_view(registered),
        }
