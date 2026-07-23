"""Class-based view orchestrators for CRUD operations.

SRP: Each view class coordinates a single workflow.
OCP: Extend by subclassing, never modify the base.
DIP: Compose via protocol abstractions (renderer, parser, query provider).
"""

from __future__ import annotations

import math
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from fastapi_admin_kit.admin.builtin_models import flush_pending_perm_ops
from fastapi_admin_kit.db import get_db_session
from fastapi_admin_kit.flash import add_flash
from fastapi_admin_kit.form.types import FieldError
from fastapi_admin_kit.registry import RegisteredModel
from fastapi_admin_kit.views.context import DisplayColumn
from fastapi_admin_kit.views.list_context import ListContextBuilder
from fastapi_admin_kit.views.model_saver import ModelSaver
from fastapi_admin_kit.views.renderers import (
    DefaultQueryProvider,
    FormHTMLRenderer,
    HTMLFormParser,
    ItemAPIRenderer,
    JSONBodyParser,
    ListAPIRenderer,
    ListHTMLRenderer,
    _resolve_permission_checker,
)


def _resolve_view_class(admin: Any, attr: str, default: type) -> type:
    """Resolve a view class from ModelAdmin, falling back to default."""
    cls = getattr(admin, attr, None)
    return cls if cls is not None else default


class BaseView:
    """Base class — holds registered model, provides dependency injection.

    Subclass and override class attributes to swap implementations (DIP).
    """

    # Class-level defaults — override per-model or subclass (OCP)
    query_provider_class: type = DefaultQueryProvider
    form_parser_class: type = HTMLFormParser
    html_renderer_class: type | None = None
    api_renderer_class: type | None = None
    model_saver_class: type = ModelSaver
    list_context_builder_class: type = ListContextBuilder

    def __init__(self, registered: RegisteredModel):
        self.registered = registered
        self.admin = registered.admin
        # Instantiate dependencies — DIP: inject via class attributes
        self.query_provider = self.query_provider_class(registered)
        self.form_parser = self.form_parser_class(registered)
        self.html_renderer = self.html_renderer_class() if self.html_renderer_class else None
        self.api_renderer = self.api_renderer_class(registered) if self.api_renderer_class else None
        self.model_saver = self.model_saver_class(registered)
        self.list_context_builder = self.list_context_builder_class()

    def _get_extra_context(self, request: Request) -> dict[str, Any]:
        """Inject AdminExtra CSS/JS into template context.

        SRP: Only collects extra assets from model admin config.
        """
        extra = getattr(self.admin, "extra", None)
        if extra is None:
            return {}
        admin_path = request.app.state.admin_config.get("admin_path", "/admin")
        return extra.to_context(admin_path)

    def _serialize(self, obj: Any) -> dict[str, Any]:
        """Serialize an object to a dict using registered columns."""
        if self.api_renderer and hasattr(self.api_renderer, "serialize"):
            return self.api_renderer.serialize(obj)
        item_dict: dict[str, Any] = {"id": getattr(obj, "id", None)}
        for col in self.registered.columns:
            if col.name != "id":
                item_dict[col.name] = str(getattr(obj, col.name, ""))
        return item_dict

    async def html_response(self, request: Request) -> Response:
        raise NotImplementedError

    async def api_response(self, request: Request) -> Response:
        raise NotImplementedError

    def _resolve_rel_keys(self, parsed: dict[str, Any]) -> dict[str, Any]:
        """Convert relationship keys in parsed data to their FK column names."""
        from sqlalchemy import inspect as sa_inspect

        col_names = {c.name for c in self.registered.columns}
        rel_fk_map: dict[str, str] = {}
        try:
            mapper = sa_inspect(self.registered.model)
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

    def _pop_manytomany_keys(self, obj: Any, parsed: dict[str, Any]) -> dict[str, Any]:
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

    async def _apply_m2m_from_data(self, obj: Any, m2m_data: dict[str, Any], session: Any) -> None:
        """Apply MANYTOMANY data extracted by _pop_manytomany_keys."""
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
            pk_list = list(raw) if isinstance(raw, list) else [raw]
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
            # Pre-load the collection inside the async greenlet so the
            # subsequent setattr does not trigger a lazy load (MissingGreenlet).
            await session.refresh(obj, [rel_key])
            setattr(obj, rel_key, objs)


class ListView(BaseView):
    """Orchestrates list view: query -> render HTML or API."""

    html_renderer_class = ListHTMLRenderer
    api_renderer_class = ListAPIRenderer

    def _build_display_columns(self) -> list[DisplayColumn]:
        """Build display column metadata."""
        from sqlalchemy import inspect as sa_inspect

        model = self.registered.model
        mapper = sa_inspect(model)
        rel_names = {r.key for r in mapper.relationships}

        list_display = self.admin.list_display or [
            c.name for c in self.registered.columns if c.name != "id"
        ]

        # Collect @column decorated methods (check _column_options attribute)
        decorated_columns: dict[str, Any] = {}
        for attr_name in list_display:
            method = getattr(self.admin, attr_name, None)
            if method and hasattr(method, "_column_options"):
                decorated_columns[attr_name] = method._column_options

        display_columns = []
        for col_name in list_display:
            label = col_name.replace("_", " ").title()
            display_fn = None
            options = None

            # Check @column decorator first
            if col_name in decorated_columns:
                options = decorated_columns[col_name]
                display_fn = getattr(self.admin, col_name)
                label = options.header or label
            # Check display_functions dict fallback
            elif self.admin.display_functions and col_name in self.admin.display_functions:
                display_fn = self.admin.display_functions[col_name]

            display_columns.append(
                DisplayColumn(col_name, label, col_name in rel_names, display_fn, options)
            )
        return display_columns

    async def _build_filter_fields(self, request: Request) -> dict[str, dict[str, Any]]:
        """Build filter field metadata."""
        if not self.admin.list_filter:
            return {}
        session = get_db_session(request)
        model = self.registered.model
        filter_fields: dict[str, dict[str, Any]] = {}
        for filter_field in self.admin.list_filter:
            filter_fields[filter_field] = await self.query_provider._get_filter_choices(
                request, model, filter_field, session
            )
        return filter_fields

    async def get_context(
        self, request: Request, q: str, page: int, checker: Any
    ) -> dict[str, Any]:
        """Build template context — delegates to ListContextBuilder."""
        return await self.list_context_builder.build_list_context(
            self.registered, request, q, page, checker
        )

    async def html_response(self, request: Request, q: str = "", page: int = 1) -> Response:
        checker = await _resolve_permission_checker(request)
        if checker:
            await checker.load_permissions(self.registered.table_name)
        ctx = await self.get_context(request, q, page, checker)
        return await self.html_renderer.render(request, ctx)

    async def api_response(
        self,
        request: Request,
        page: int = 1,
        per_page: int = 25,
        q: str = "",
        order: str = "",
        after: str | None = None,
        before: str | None = None,
    ) -> Any:
        (
            items,
            total,
            page,
            per_page,
            next_cursor,
            has_next,
            pagination_mode,
        ) = await self.query_provider.get_list(request, q, page)
        item_list = [self._serialize(item) for item in items]
        return await self.api_renderer.render(
            request,
            {
                "items": item_list,
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": math.ceil(total / per_page) if per_page else 1,
                "next_cursor": next_cursor,
                "has_next": has_next,
            },
        )


class CreateView(BaseView):
    """Orchestrates create: parse -> validate -> save -> respond."""

    html_renderer_class = FormHTMLRenderer
    form_parser_class = HTMLFormParser
    api_renderer_class = ItemAPIRenderer

    async def _build_form_context(
        self,
        request: Request,
        obj: Any | None = None,
        values: dict[str, Any] | None = None,
        errors: dict[str, list[str]] | None = None,
        is_create: bool = True,
        checker: Any = None,
        inline_values: dict[str, dict[str, list[str]]] | None = None,
        inline_errors: dict[str, dict[int, dict[str, list[str]]]] | None = None,
    ) -> dict[str, Any]:
        """Build form template context."""
        from fastapi_admin_kit.auth.types import PermissionSet
        from fastapi_admin_kit.form.pipeline import (
            build_form_context as _build_form_ctx,
        )
        from fastapi_admin_kit.form.pipeline import (
            build_inline_formsets,
        )
        from fastapi_admin_kit.views.sidebar import inject_sidebar_context

        # Build inline formsets
        inlines = getattr(self.admin, "inlines", [])
        inline_formsets = await build_inline_formsets(
            self.registered,
            obj=obj,
            inlines=inlines,
            request=request,
            inline_values=inline_values,
            inline_errors=inline_errors,
        )

        ctx = _build_form_ctx(
            self.registered,
            obj=obj,
            values=values,
            errors=errors,
            request=request,
            is_create=is_create,
            inline_formsets=inline_formsets,
        )
        template_context = {
            "form_context": ctx,
            "registered": self.registered,
            "obj": ctx.obj,
            "form_fields": ctx.fieldsets[0].fields if ctx.fieldsets else [],
            "fieldsets": ctx.fieldsets,
            "errors": ctx.errors,
            "is_create": is_create,
            "permissions": checker.permission_set(self.registered.table_name)
            if checker
            else PermissionSet(can_view=True, can_create=True, can_edit=True, can_delete=True),
            "detail_actions": self.admin.get_detail_actions(),
            "submit_line_actions": self.admin.get_submit_line_actions(),
            "conditional_fields": getattr(self.admin, "conditional_fields", {}),
            "warn_unsaved_form": getattr(self.admin, "warn_unsaved_form", True),
            "compressed_fields": getattr(self.admin, "compressed_fields", True),
            "change_form_show_cancel_button": getattr(
                self.admin, "change_form_show_cancel_button", True
            ),
            "inline_formsets": ctx.inline_formsets,
        }
        template_context.update(self._get_extra_context(request))
        await inject_sidebar_context(request, template_context)

        template_context = await self.admin.get_form_context(template_context, obj, request)

        return template_context

    async def _create_object(self, request: Request, parsed: dict[str, Any]) -> RedirectResponse:
        """Create object in database."""
        try:
            session = get_db_session(request)
            m2m_data = self.model_saver.extract_m2m(self.registered.model, parsed, request)
            resolved = self.model_saver.resolve_rel_keys(parsed, request)
            resolved = self.admin.prepare_create_data(resolved, request)
            obj = self.registered.model(**resolved)
            self.admin.on_create(obj, request)
            session.add(obj)
            await session.flush()
            await self.model_saver.apply_m2m(obj, m2m_data, request)

            # Save inline objects
            await self.model_saver.save_inline_objects(request, obj)

            self.admin.after_create(obj, request)
            await flush_pending_perm_ops(request)
            await add_flash(request, "success", f"{self.registered.verbose_name} created.")
        except Exception:
            session = get_db_session(request)
            await session.rollback()
            raise
        url = f"{request.app.state.admin_config['admin_path']}/{self.registered.table_name}/"
        return RedirectResponse(url=url, status_code=303)

    async def _save_inline_objects(self, request: Request, parent_obj: Any) -> None:
        """Parse and save inline formset objects."""
        from fastapi_admin_kit.inspection import cast_pk_value

        inlines = getattr(self.admin, "inlines", [])
        if not inlines:
            return

        # Use cached form data from form_parser.parse()
        form_data = getattr(request, "_cached_form_data", None)
        if form_data is None:
            form_data = await request.form()
        session = get_db_session(request)

        for inline_cls in inlines:
            inline_instance = inline_cls() if isinstance(inline_cls, type) else inline_cls
            related_model = inline_instance.model
            if related_model is None:
                continue

            prefix = f"{related_model.__tablename__}_set"

            # Get FK field
            fk_field = inline_instance.fk_name
            if not fk_field:
                from sqlalchemy import inspect as sa_inspect

                mapper = sa_inspect(related_model)
                parent_table = self.registered.table_name
                for rel_key, rel_prop in mapper.relationships.items():
                    if rel_prop.direction.name == "MANYTOONE":
                        target_table = rel_prop.mapper.class_.__tablename__
                        if target_table == parent_table:
                            local_cols = [c.key for c in rel_prop.local_columns]
                            if local_cols:
                                fk_field = local_cols[0]
                                break

            if not fk_field:
                continue

            # Parse formset data
            total_forms = int(form_data.get(f"{prefix}-TOTAL_FORMS", "0"))
            initial_forms = int(form_data.get(f"{prefix}-INITIAL_FORMS", "0"))
            deleted_ids: list[str] = []

            # Collect deleted IDs
            for i in range(initial_forms):
                delete_key = f"{prefix}-{i}-DELETE"
                if form_data.get(delete_key) in ("on", "1"):
                    obj_id = form_data.get(f"{prefix}-{i}-id", "")
                    if obj_id:
                        deleted_ids.append(obj_id)

            # Delete marked objects
            for obj_id in deleted_ids:
                try:
                    pk_val = cast_pk_value(related_model, obj_id)
                    existing = await session.get(related_model, pk_val)
                    if existing:
                        await session.delete(existing)
                except Exception:
                    pass

            # Get fields to save — use registered columns if inline has no explicit fields
            from fastapi_admin_kit.registry import AdminRegistry

            related_registry = AdminRegistry()
            related_registered = related_registry.get(related_model.__tablename__)
            related_columns = related_registered.columns if related_registered else None
            fields = inline_instance.get_form_fields(columns=related_columns)
            if not fields:
                continue

            # Create/update objects
            for i in range(total_forms):
                obj_id = form_data.get(f"{prefix}-{i}-id", "")
                delete_key = f"{prefix}-{i}-DELETE"
                if form_data.get(delete_key) in ("on", "1"):
                    continue

                # Build data dict
                data: dict[str, Any] = {}
                for field_name in fields:
                    val = form_data.get(f"{prefix}-{i}-{field_name}")
                    if val is not None:
                        from sqlalchemy import inspect as sa_inspect

                        try:
                            mapper = sa_inspect(related_model)
                            rel = mapper.relationships.get(field_name)
                        except Exception:
                            rel = None

                        if rel is not None:
                            local_cols = [c.key for c in rel.local_columns]
                            fk_col = local_cols[0] if local_cols else None
                            if val and fk_col:
                                casted_val = val
                                try:
                                    casted_val = cast_pk_value(related_model, val)
                                except Exception:
                                    pass
                                data[fk_col] = casted_val
                            elif not val and fk_col:
                                data[fk_col] = None
                        else:
                            related_col = None
                            if related_registered:
                                related_col = next(
                                    (c for c in related_registered.columns if c.name == field_name),
                                    None,
                                )
                            if related_col is not None:
                                from fastapi_admin_kit.inspection import (
                                    cast_value,
                                )

                                val = cast_value(related_col, val)
                            data[field_name] = val

                if obj_id:
                    try:
                        pk_val = cast_pk_value(related_model, obj_id)
                        existing = await session.get(related_model, pk_val)
                        if existing:
                            for k, v in data.items():
                                setattr(existing, k, v)
                    except Exception:
                        pass
                else:
                    parent_pk_field = self.registered.pk_field or "id"
                    data[fk_field] = getattr(parent_obj, parent_pk_field, None)
                    new_obj = related_model(**data)
                    session.add(new_obj)

            await session.flush()

    async def html_response(self, request: Request) -> Response:
        checker = await _resolve_permission_checker(request)
        if checker:
            await checker.load_permissions(self.registered.table_name)

        if request.method == "GET":
            ctx = await self._build_form_context(request, is_create=True, checker=checker)
            return await self.html_renderer.render(request, ctx)

        # POST
        parsed, errors = await self.form_parser.parse(request)

        # Extract perm_data for User model direct permissions
        if self.registered.table_name == "admin_users":
            import json

            form = await request.form()
            perm_data_raw = form.get("perm_data")
            if perm_data_raw:
                try:
                    perm_data = (
                        json.loads(perm_data_raw)
                        if isinstance(perm_data_raw, str)
                        else perm_data_raw
                    )
                    request.state._admin_perm_data = perm_data
                except (json.JSONDecodeError, TypeError):
                    pass

        if errors:
            session = get_db_session(request)
            await session.rollback()
            user = getattr(request.state, "admin_user", None)
            if user is not None:
                await session.refresh(user)
            ctx = await self._build_form_context(
                request,
                values=parsed,
                errors=errors,
                is_create=True,
                checker=checker,
            )
            return await self.html_renderer.render(request, ctx)

        try:
            result = self.admin.validate_create(parsed, request)
        except FieldError as e:
            session = get_db_session(request)
            await session.rollback()
            ctx = await self._build_form_context(
                request,
                values=parsed,
                errors=e.field_errors,
                is_create=True,
                checker=checker,
            )
            return await self.html_renderer.render(request, ctx)
        except ValueError as e:
            session = get_db_session(request)
            await session.rollback()
            ctx = await self._build_form_context(
                request,
                values=parsed,
                errors={"__all__": [str(e)]},
                is_create=True,
                checker=checker,
            )
            return await self.html_renderer.render(request, ctx)

        parsed = result

        parsed = self.admin.process_form_data(parsed, request)

        return await self._create_object(request, parsed)

    async def api_response(self, request: Request) -> Any:
        parser = JSONBodyParser(self.registered)
        parsed, errors = await parser.parse(request)
        if errors:
            raise HTTPException(status_code=422, detail=errors)
        session = get_db_session(request)
        m2m_data = self.model_saver.extract_m2m(self.registered.model, parsed, request)
        resolved = self.model_saver.resolve_rel_keys(parsed, request)
        resolved = self.admin.prepare_create_data(resolved, request)
        obj = self.registered.model(**resolved)
        self.admin.on_create(obj, request)
        session.add(obj)
        await session.flush()
        await self.model_saver.apply_m2m(obj, m2m_data, request)
        self.admin.after_create(obj, request)
        await flush_pending_perm_ops(request)
        return await self.api_renderer.render(request, self._serialize(obj))


class EditView(BaseView):
    """Orchestrates edit: fetch -> parse -> validate -> update -> respond."""

    html_renderer_class = FormHTMLRenderer
    form_parser_class = HTMLFormParser
    api_renderer_class = ItemAPIRenderer

    async def _resolve_rel_labels(self, obj: Any, request: Request) -> dict[str, str]:
        """Resolve display labels for relationship fields from FK values."""
        from sqlalchemy import inspect as sa_inspect

        from fastapi_admin_kit.inspection import model_display_name

        labels: dict[str, str] = {}
        if obj is None:
            return labels
        try:
            mapper = sa_inspect(type(obj))
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

    async def _build_form_context(
        self,
        request: Request,
        obj: Any | None = None,
        values: dict[str, Any] | None = None,
        errors: dict[str, list[str]] | None = None,
        is_create: bool = False,
        checker: Any = None,
        rel_labels: dict[str, str] | None = None,
        inline_values: dict[str, dict[str, list[str]]] | None = None,
        inline_errors: dict[str, dict[int, dict[str, list[str]]]] | None = None,
    ) -> dict[str, Any]:
        """Build form template context."""
        from fastapi_admin_kit.auth.types import PermissionSet
        from fastapi_admin_kit.form.pipeline import (
            build_form_context as _build_form_ctx,
        )
        from fastapi_admin_kit.form.pipeline import (
            build_inline_formsets,
        )
        from fastapi_admin_kit.views.sidebar import inject_sidebar_context

        # Build inline formsets
        inlines = getattr(self.admin, "inlines", [])
        inline_formsets = await build_inline_formsets(
            self.registered,
            obj=obj,
            inlines=inlines,
            request=request,
            inline_values=inline_values,
            inline_errors=inline_errors,
        )

        ctx = _build_form_ctx(
            self.registered,
            obj=obj,
            values=values,
            errors=errors,
            request=request,
            is_create=is_create,
            rel_labels=rel_labels,
            inline_formsets=inline_formsets,
        )
        template_context = {
            "form_context": ctx,
            "registered": self.registered,
            "obj": ctx.obj,
            "form_fields": ctx.fieldsets[0].fields if ctx.fieldsets else [],
            "fieldsets": ctx.fieldsets,
            "errors": ctx.errors,
            "is_create": is_create,
            "permissions": checker.permission_set(self.registered.table_name)
            if checker
            else PermissionSet(can_view=True, can_create=True, can_edit=True, can_delete=True),
            "detail_actions": self.admin.get_detail_actions(),
            "submit_line_actions": self.admin.get_submit_line_actions(),
            "conditional_fields": getattr(self.admin, "conditional_fields", {}),
            "warn_unsaved_form": getattr(self.admin, "warn_unsaved_form", True),
            "compressed_fields": getattr(self.admin, "compressed_fields", True),
            "change_form_show_cancel_button": getattr(
                self.admin, "change_form_show_cancel_button", True
            ),
            "inline_formsets": ctx.inline_formsets,
        }
        template_context.update(self._get_extra_context(request))
        await inject_sidebar_context(request, template_context)

        template_context = await self.admin.get_form_context(template_context, obj, request)

        return template_context

    def _apply_parsed(self, obj: Any, parsed: dict[str, Any]) -> None:
        """Apply parsed form/JSON data to an ORM object.

        Relationship fields (e.g. ``"user"``) are resolved to their
        local foreign-key column (e.g. ``"user_id"``) so that the
        correct column is persisted by SQLAlchemy.
        """
        from sqlalchemy import inspect as sa_inspect

        col_names = {c.name for c in self.registered.columns}

        # Build mapping: relationship key -> local FK column key
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

    async def _update_object(
        self, request: Request, obj: Any, parsed: dict[str, Any]
    ) -> RedirectResponse:
        """Update object in database."""
        try:
            parsed = self.admin.prepare_update_data(parsed, request)
            m2m_data = self.model_saver.extract_m2m(obj, parsed, request)
            self.model_saver.apply_parsed(obj, parsed, request)
            session = get_db_session(request)
            await self.model_saver.apply_m2m(obj, m2m_data, request)
            self.admin.on_update(obj, parsed, request)
            await session.flush()

            # Save inline objects
            await self.model_saver.save_inline_objects(request, obj)

            self.admin.after_update(obj, request)
            await flush_pending_perm_ops(request)
            await add_flash(request, "success", f"{self.registered.verbose_name} updated.")
        except Exception:
            session = get_db_session(request)
            await session.rollback()
            raise
        url = f"{request.app.state.admin_config['admin_path']}/{self.registered.table_name}/"
        return RedirectResponse(url=url, status_code=303)

    async def _save_inline_objects(self, request: Request, parent_obj: Any) -> None:
        """Parse and save inline formset objects."""
        from fastapi_admin_kit.inspection import cast_pk_value

        inlines = getattr(self.admin, "inlines", [])
        if not inlines:
            return

        # Use cached form data from form_parser.parse()
        form_data = getattr(request, "_cached_form_data", None)
        if form_data is None:
            form_data = await request.form()
        session = get_db_session(request)

        for inline_cls in inlines:
            inline_instance = inline_cls() if isinstance(inline_cls, type) else inline_cls
            related_model = inline_instance.model
            if related_model is None:
                continue

            prefix = f"{related_model.__tablename__}_set"

            # Get FK field
            fk_field = inline_instance.fk_name
            if not fk_field:
                from sqlalchemy import inspect as sa_inspect

                mapper = sa_inspect(related_model)
                parent_table = self.registered.table_name
                for rel_key, rel_prop in mapper.relationships.items():
                    if rel_prop.direction.name == "MANYTOONE":
                        target_table = rel_prop.mapper.class_.__tablename__
                        if target_table == parent_table:
                            local_cols = [c.key for c in rel_prop.local_columns]
                            if local_cols:
                                fk_field = local_cols[0]
                                break

            if not fk_field:
                continue

            # Parse formset data
            total_forms = int(form_data.get(f"{prefix}-TOTAL_FORMS", "0"))
            initial_forms = int(form_data.get(f"{prefix}-INITIAL_FORMS", "0"))
            deleted_ids: list[str] = []

            # Collect deleted IDs
            for i in range(initial_forms):
                delete_key = f"{prefix}-{i}-DELETE"
                if form_data.get(delete_key) in ("on", "1"):
                    obj_id = form_data.get(f"{prefix}-{i}-id", "")
                    if obj_id:
                        deleted_ids.append(obj_id)

            # Delete marked objects
            for obj_id in deleted_ids:
                try:
                    pk_val = cast_pk_value(related_model, obj_id)
                    existing = await session.get(related_model, pk_val)
                    if existing:
                        await session.delete(existing)
                except Exception:
                    pass

            # Get fields to save — use registered columns if inline has no explicit fields
            from fastapi_admin_kit.registry import AdminRegistry

            related_registry = AdminRegistry()
            related_registered = related_registry.get(related_model.__tablename__)
            related_columns = related_registered.columns if related_registered else None
            fields = inline_instance.get_form_fields(columns=related_columns)
            if not fields:
                continue

            # Create/update objects
            for i in range(total_forms):
                obj_id = form_data.get(f"{prefix}-{i}-id", "")
                delete_key = f"{prefix}-{i}-DELETE"
                if form_data.get(delete_key) in ("on", "1"):
                    continue

                # Build data dict
                data: dict[str, Any] = {}
                for field_name in fields:
                    val = form_data.get(f"{prefix}-{i}-{field_name}")
                    if val is not None:
                        from sqlalchemy import inspect as sa_inspect

                        try:
                            mapper = sa_inspect(related_model)
                            rel = mapper.relationships.get(field_name)
                        except Exception:
                            rel = None

                        if rel is not None:
                            local_cols = [c.key for c in rel.local_columns]
                            fk_col = local_cols[0] if local_cols else None
                            if val and fk_col:
                                casted_val = val
                                try:
                                    casted_val = cast_pk_value(related_model, val)
                                except Exception:
                                    pass
                                data[fk_col] = casted_val
                            elif not val and fk_col:
                                data[fk_col] = None
                        else:
                            related_col = None
                            if related_registered:
                                related_col = next(
                                    (c for c in related_registered.columns if c.name == field_name),
                                    None,
                                )
                            if related_col is not None:
                                from fastapi_admin_kit.inspection import (
                                    cast_value,
                                )

                                val = cast_value(related_col, val)
                            data[field_name] = val

                if obj_id:
                    try:
                        pk_val = cast_pk_value(related_model, obj_id)
                        existing = await session.get(related_model, pk_val)
                        if existing:
                            for k, v in data.items():
                                setattr(existing, k, v)
                    except Exception:
                        pass
                else:
                    parent_pk_field = self.registered.pk_field or "id"
                    data[fk_field] = getattr(parent_obj, parent_pk_field, None)
                    new_obj = related_model(**data)
                    session.add(new_obj)

            await session.flush()

    async def _build_detail_context(
        self,
        request: Request,
        obj: Any,
        checker: Any = None,
    ) -> dict[str, Any]:
        """Build read-only detail view context with all fields."""
        from fastapi_admin_kit.auth.types import PermissionSet
        from fastapi_admin_kit.form.pipeline import (
            build_form_context as _build_form_ctx,
        )
        from fastapi_admin_kit.views.sidebar import inject_sidebar_context

        rel_labels = await self._resolve_rel_labels(obj, request)
        ctx = _build_form_ctx(
            self.registered,
            obj=obj,
            request=request,
            is_create=False,
            rel_labels=rel_labels,
        )
        template_context = {
            "form_context": ctx,
            "registered": self.registered,
            "obj": obj,
            "form_fields": ctx.fieldsets[0].fields if ctx.fieldsets else [],
            "fieldsets": ctx.fieldsets,
            "is_create": False,
            "permissions": checker.permission_set(self.registered.table_name)
            if checker
            else PermissionSet(can_view=True, can_create=True, can_edit=True, can_delete=True),
        }
        template_context.update(self._get_extra_context(request))
        await inject_sidebar_context(request, template_context)
        return template_context

    async def html_response(self, request: Request, id: Any = None) -> Response:
        obj = await self.query_provider.get_object(request, id)
        if not obj:
            raise HTTPException(status_code=404, detail="Not found")

        checker = await _resolve_permission_checker(request)
        if checker:
            await checker.load_permissions(self.registered.table_name)

        perms = checker.permission_set(self.registered.table_name) if checker else None

        if request.method == "GET":
            if perms and not perms.can_edit and perms.can_view:
                ctx = await self._build_detail_context(request, obj, checker)
                return request.app.state.admin_jinja_env.TemplateResponse(
                    request, "pages/detail.html", ctx
                )
            rel_labels = await self._resolve_rel_labels(obj, request)
            ctx = await self._build_form_context(
                request,
                obj=obj,
                is_create=False,
                checker=checker,
                rel_labels=rel_labels,
            )
            return await self.html_renderer.render(request, ctx)

        # POST
        parsed, errors = await self.form_parser.parse(request, obj=obj)

        # Extract perm_data for User model direct permissions
        if self.registered.table_name == "admin_users":
            import json

            form = await request.form()
            perm_data_raw = form.get("perm_data")
            if perm_data_raw:
                try:
                    perm_data = (
                        json.loads(perm_data_raw)
                        if isinstance(perm_data_raw, str)
                        else perm_data_raw
                    )
                    request.state._admin_perm_data = perm_data
                except (json.JSONDecodeError, TypeError):
                    pass

        if errors:
            session = get_db_session(request)
            await session.rollback()
            await session.refresh(obj)
            user = getattr(request.state, "admin_user", None)
            if user is not None:
                await session.refresh(user)
            rel_labels = await self._resolve_rel_labels(obj, request)
            ctx = await self._build_form_context(
                request,
                obj=obj,
                values=parsed,
                errors=errors,
                checker=checker,
                rel_labels=rel_labels,
            )
            return await self.html_renderer.render(request, ctx)

        try:
            result = self.admin.validate_update(obj, parsed, request)
        except FieldError as e:
            session = get_db_session(request)
            await session.rollback()
            await session.refresh(obj)
            rel_labels = await self._resolve_rel_labels(obj, request)
            ctx = await self._build_form_context(
                request,
                obj=obj,
                values=parsed,
                errors=e.field_errors,
                checker=checker,
                rel_labels=rel_labels,
            )
            return await self.html_renderer.render(request, ctx)
        except ValueError as e:
            session = get_db_session(request)
            await session.rollback()
            await session.refresh(obj)
            rel_labels = await self._resolve_rel_labels(obj, request)
            ctx = await self._build_form_context(
                request,
                obj=obj,
                values=parsed,
                errors={"__all__": [str(e)]},
                checker=checker,
                rel_labels=rel_labels,
            )
            return await self.html_renderer.render(request, ctx)

        parsed = result

        parsed = self.admin.process_form_data(parsed, request)

        return await self._update_object(request, obj, parsed)

    async def api_response(
        self,
        request: Request,
        id: Any = None,
        item_id: Any = None,
    ) -> Any:
        pk = id or item_id
        obj = await self.query_provider.get_object(request, pk)
        if not obj:
            raise HTTPException(status_code=404, detail="Not found")

        if request.method == "GET":
            return self._serialize(obj)

        # PUT
        parser = JSONBodyParser(self.registered)
        parsed, _ = await parser.parse(request, obj)
        try:
            m2m_data = self.model_saver.extract_m2m(obj, parsed, request)
            self.model_saver.apply_parsed(obj, parsed, request)
            session = get_db_session(request)
            await self.model_saver.apply_m2m(obj, m2m_data, request)
            self.admin.on_update(obj, parsed, request)
            await session.flush()
            self.admin.after_update(obj, request)
            await flush_pending_perm_ops(request)
        except Exception:
            session = get_db_session(request)
            await session.rollback()
            raise
        return self._serialize(obj)


class DeleteView(BaseView):
    """Orchestrates delete: fetch -> delete -> respond."""

    async def html_response(self, request: Request, id: Any = None) -> Response:
        obj = await self.query_provider.get_object(request, id)
        if not obj:
            raise HTTPException(status_code=404, detail="Not found")
        try:
            self.admin.on_delete(obj, request)
            session = get_db_session(request)
            await session.delete(obj)
            await session.flush()
            self.admin.after_delete(obj, request)
            await add_flash(request, "success", f"{self.registered.verbose_name} deleted.")
        except Exception:
            session = get_db_session(request)
            await session.rollback()
            raise
        url = f"{request.app.state.admin_config['admin_path']}/{self.registered.table_name}/"
        return RedirectResponse(url=url, status_code=303)

    async def api_response(
        self,
        request: Request,
        id: Any = None,
        item_id: Any = None,
    ) -> Response:
        pk = id or item_id
        obj = await self.query_provider.get_object(request, pk)
        if not obj:
            raise HTTPException(status_code=404, detail="Not found")
        self.admin.on_delete(obj, request)
        session = get_db_session(request)
        await session.delete(obj)
        await session.flush()
        self.admin.after_delete(obj, request)
        return Response(status_code=204)


class BulkView(BaseView):
    """Orchestrates bulk actions on multiple objects."""

    html_renderer_class = ListHTMLRenderer

    async def html_response(self, request: Request) -> Response:
        session = get_db_session(request)
        form = await request.form()
        action = form.get("action", "")
        ids = form.getlist("ids[]")

        is_htmx = request.headers.get("HX-Request") == "true"

        if not ids:
            if is_htmx:
                list_view = ListView(self.registered)
                checker = await _resolve_permission_checker(request)
                ctx = await list_view.get_context(request, "", 1, checker)
                return await self.html_renderer.render(request, ctx)
            url = f"{request.app.state.admin_config['admin_path']}/{self.registered.table_name}/"
            return RedirectResponse(url=url, status_code=303)

        if action == "delete_selected":
            for pid in ids:
                obj = await session.get(self.registered.model, pid)
                if obj:
                    self.admin.on_delete(obj, request)
                    await session.delete(obj)
            await session.flush()
        else:
            action_obj = None
            for a in self.admin.get_list_actions():
                if a.name == action:
                    action_obj = a
                    break

            if action_obj:
                objects = []
                for pid in ids:
                    obj = await session.get(self.registered.model, pid)
                    if obj:
                        objects.append(obj)
                if objects:
                    await action_obj.execute(objects, request)
                await session.flush()
            else:
                action_fn = getattr(self.admin, f"action_{action}", None)
                if not action_fn:
                    raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
                for pid in ids:
                    obj = await session.get(self.registered.model, pid)
                    if obj:
                        action_fn(obj)
                await session.flush()

        if is_htmx:
            list_view = ListView(self.registered)
            checker = await _resolve_permission_checker(request)
            ctx = await list_view.get_context(request, "", 1, checker)
            return await self.html_renderer.render(request, ctx)

        url = f"{request.app.state.admin_config['admin_path']}/{self.registered.table_name}/"
        return RedirectResponse(url=url, status_code=303)

    async def api_response(self, request: Request) -> Any:
        from fastapi.responses import JSONResponse

        session = get_db_session(request)
        content_type = request.headers.get("content-type", "")
        is_json = content_type.startswith("application/json")
        body = await request.json() if is_json else {}
        action = body.get("action", "")
        ids = body.get("ids", [])

        if action == "delete_selected":
            deleted = 0
            for pid in ids:
                obj = await session.get(self.registered.model, pid)
                if obj:
                    self.admin.on_delete(obj, request)
                    await session.delete(obj)
                    deleted += 1
            await session.flush()
            return JSONResponse({"deleted": deleted})

        action_obj = None
        for a in self.admin.get_list_actions():
            if a.name == action:
                action_obj = a
                break

        if action_obj:
            objects = []
            for pid in ids:
                obj = await session.get(self.registered.model, pid)
                if obj:
                    objects.append(obj)
            if objects:
                await action_obj.execute(objects, request)
            await session.flush()
            return JSONResponse({"executed": len(objects)})

        action_fn = getattr(self.admin, f"action_{action}", None)
        if not action_fn:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

        executed = 0
        for pid in ids:
            obj = await session.get(self.registered.model, pid)
            if obj:
                action_fn(obj)
                executed += 1
        await session.flush()
        return JSONResponse({"executed": executed})


class SearchView(BaseView):
    """Orchestrates search/autocomplete for relation pickers."""

    async def html_response(
        self,
        request: Request,
        q: str = "",
        limit: int = 20,
        exclude_id: str = "",
    ) -> Any:
        return await self._search(request, q, limit, exclude_id)

    async def api_response(
        self,
        request: Request,
        q: str = "",
        limit: int = 20,
        exclude_id: str = "",
    ) -> Any:
        return await self._search(request, q, limit, exclude_id)

    def _is_browser_request(self, request: Request) -> bool:
        accept = request.headers.get("accept", "")
        return "text/html" in accept or "text/xhtml" in accept

    def _render_search_page(
        self,
        request: Request,
        q: str,
        error: str | None = None,
        results: list | None = None,
    ) -> Any:
        templates = request.app.state.admin_jinja_env
        admin_path = request.app.state.admin_config["admin_path"]
        search_fields = getattr(self.admin, "search_fields", None) or [
            "name",
            "title",
        ]
        return templates.TemplateResponse(
            request,
            "pages/search.html",
            {
                "registered": self.registered,
                "admin_path": admin_path,
                "q": q,
                "error": error,
                "results": results,
                "search_fields": search_fields,
            },
            status_code=422 if error else 200,
        )

    async def _search(self, request: Request, q: str, limit: int = 20, exclude_id: str = "") -> Any:
        from fastapi.responses import JSONResponse
        from sqlalchemy import select

        is_browser = self._is_browser_request(request)

        try:
            session = get_db_session(request)
            model = self.registered.model

            from fastapi_admin_kit.search_utils import apply_search_filter

            search_fields = getattr(self.admin, "search_fields", None) or [
                "name",
                "title",
            ]
            base = apply_search_filter(request, select(model), model, search_fields, q)

            if exclude_id:
                pk_col = getattr(model, self.registered.pk_field, None)
                if pk_col is not None:
                    from fastapi_admin_kit.inspection import cast_pk_value

                    base = base.where(pk_col != cast_pk_value(model, exclude_id))

            base = base.limit(limit)
            result = session.execute(base)
            if hasattr(result, "__await__"):
                result = await result
            rows = result.scalars().all()

            results = []
            for row in rows:
                pk = getattr(row, self.registered.pk_field)
                from fastapi_admin_kit.inspection import model_display_name

                label = model_display_name(row)
                results.append({"id": str(pk), "label": label})

            if is_browser:
                return self._render_search_page(request, q, results=results)
            return JSONResponse(results)

        except Exception as exc:
            error_msg = str(exc) or "An unexpected error occurred while searching."
            if is_browser:
                return self._render_search_page(request, q, error=error_msg)
            from fastapi.responses import JSONResponse as _JSONResponse

            return _JSONResponse(status_code=500, content={"error": error_msg})
