"""Auto-route generation per registered model with RBAC."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from fastapi_admin_kit.auth.csrf import require_csrf_token
from fastapi_admin_kit.auth.dependencies import require_permission
from fastapi_admin_kit.db import get_db_session
from fastapi_admin_kit.registry import RegisteredModel
from fastapi_admin_kit.views.class_views import (
    BulkView,
    CreateView,
    DeleteView,
    EditView,
    ListView,
    SearchView,
    _resolve_view_class,
)


def build_model_router(registered: RegisteredModel) -> APIRouter:
    router = APIRouter(prefix=f"/{registered.table_name}")

    # DIP: view classes resolved from ModelAdmin config with defaults
    admin = registered.admin
    list_v = _resolve_view_class(admin, "list_view_class", ListView)(registered)
    create_v = _resolve_view_class(admin, "create_view_class", CreateView)(registered)
    edit_v = _resolve_view_class(admin, "edit_view_class", EditView)(registered)
    delete_v = _resolve_view_class(admin, "delete_view_class", DeleteView)(registered)
    bulk_v = _resolve_view_class(admin, "bulk_view_class", BulkView)(registered)
    search_v = _resolve_view_class(admin, "search_view_class", SearchView)(registered)

    router.add_api_route(
        "/",
        list_v.html_response,
        methods=["GET"],
        dependencies=[Depends(require_permission(registered.table_name, "view"))],
    )
    router.add_api_route(
        "/create",
        create_v.html_response,
        methods=["GET"],
        dependencies=[Depends(require_permission(registered.table_name, "create"))],
    )
    router.add_api_route(
        "/create",
        create_v.html_response,
        methods=["POST"],
        dependencies=[
            Depends(require_permission(registered.table_name, "create")),
            Depends(require_csrf_token),
        ],
    )
    router.add_api_route(
        "/search",
        search_v.html_response,
        methods=["GET"],
        dependencies=[Depends(require_permission(registered.table_name, "view"))],
    )
    router.add_api_route(
        "/bulk",
        bulk_v.html_response,
        methods=["POST"],
        dependencies=[
            Depends(require_permission(registered.table_name, "edit")),
            Depends(require_csrf_token),
        ],
    )

    @router.post("/validate-field")
    async def validate_field_endpoint(
        request: Request,
        _csrf: bool = Depends(require_csrf_token),
        _: None = Depends(require_permission(registered.table_name, "view")),
    ):
        templates = request.app.state.admin_jinja_env
        form = await request.form()
        field_name = form.get("field_name")
        raw_value = form.get(field_name)

        field_meta = next(
            (f for f in registered.form_fields if f.name == field_name), None
        )
        if field_meta is None:
            raise HTTPException(status_code=422, detail="Field not found")

        widget = registered.get_widget(field_name)
        parsed = widget.parse(raw_value)
        errors = widget.validate(parsed, field_meta)

        validator_fn = getattr(registered.admin, f"validate_{field_name}", None)
        if validator_fn and not errors:
            err = validator_fn(parsed, obj=None)
            if err:
                errors = [err]

        from fastapi_admin_kit.types import FieldRenderContext

        field_ctx = FieldRenderContext(
            meta=field_meta,
            widget_macro=widget.macro_name,
            widget_context=widget.render_context(field_meta, raw_value),
            errors=errors,
        )
        return templates.TemplateResponse(request, "partials/field_wrapper.html", {
            "field_ctx": field_ctx,
            "model_name": registered.table_name,
        })

    router.add_api_route(
        "/{id}",
        edit_v.html_response,
        methods=["GET"],
        dependencies=[Depends(require_permission(registered.table_name, "edit"))],
    )
    router.add_api_route(
        "/{id}",
        edit_v.html_response,
        methods=["POST"],
        dependencies=[
            Depends(require_permission(registered.table_name, "edit")),
            Depends(require_csrf_token),
        ],
    )
    router.add_api_route(
        "/{id}/delete",
        delete_v.html_response,
        methods=["POST"],
        dependencies=[
            Depends(require_permission(registered.table_name, "delete")),
            Depends(require_csrf_token),
        ],
    )

    # ── Custom Actions ─────────────────────────────────────────────

    @router.post("/action/{action_name}")
    async def execute_list_action(
        request: Request,
        action_name: str,
        _csrf: bool = Depends(require_csrf_token),
    ):
        """Execute a list-level action on selected objects."""
        session = get_db_session(request)
        form = await request.form()
        ids = form.getlist("ids[]")

        action_obj = None
        for a in registered.admin.get_list_actions():
            if a.name == action_name:
                action_obj = a
                break

        if not action_obj:
            raise HTTPException(status_code=404, detail=f"Unknown action: {action_name}")

        objects = []
        for pid in ids:
            obj = await session.get(registered.model, pid)
            if obj:
                objects.append(obj)

        if objects:
            await action_obj.execute(objects, request)
            await session.flush()

        from fastapi.responses import HTMLResponse
        return HTMLResponse(content="OK")

    @router.post("/action/{action_name}/{id}")
    async def execute_row_action(
        request: Request,
        action_name: str,
        id: str,
        _csrf: bool = Depends(require_csrf_token),
    ):
        """Execute a row-level action on a single object."""
        session = get_db_session(request)

        action_obj = None
        for a in registered.admin.get_row_actions():
            if a.name == action_name:
                action_obj = a
                break

        if not action_obj:
            raise HTTPException(status_code=404, detail=f"Unknown action: {action_name}")

        obj = await session.get(registered.model, int(id))
        if not obj:
            raise HTTPException(status_code=404, detail="Not found")

        await action_obj.execute([obj], request)
        await session.flush()

        from fastapi.responses import HTMLResponse
        return HTMLResponse(content="OK")

    # ── Sortable Endpoint ──────────────────────────────────────────

    @router.post("/sort")
    async def sort_items(
        request: Request,
        _csrf: bool = Depends(require_csrf_token),
    ):
        """Handle drag-drop sort updates."""
        body = await request.json()
        ordering_field = getattr(registered.admin, "ordering_field", None)
        if not ordering_field:
            raise HTTPException(status_code=400, detail="Sorting not configured")

        session = get_db_session(request)
        items = body.get("items", [])
        for idx, item_id in enumerate(items):
            obj = await session.get(registered.model, item_id)
            if obj:
                setattr(obj, ordering_field, idx)
        await session.flush()

        from fastapi.responses import HTMLResponse
        return HTMLResponse(content="OK")

    # ── Autocomplete Endpoint ──────────────────────────────────────

    @router.get("/autocomplete/")
    async def autocomplete(
        request: Request,
        q: str = "",
        _csrf: bool = Depends(require_permission(registered.table_name, "view")),
    ):
        """Search-as-you-type endpoint for relation pickers."""
        from fastapi.responses import JSONResponse

        session = get_db_session(request)
        model = registered.model
        results = []

        search_fields = getattr(registered.admin, "search_fields", None) or ["name", "title"]
        clauses = []
        for sf in search_fields:
            if hasattr(model, sf):
                col = getattr(model, sf)
                if hasattr(col, "ilike"):
                    clauses.append(col.ilike(f"%{q}%"))

        if clauses:
            from sqlalchemy import or_, select
            query = select(model).where(or_(*clauses)).limit(20)
            result = await session.execute(query)
            for obj in result.scalars():
                label = str(
                    getattr(obj, "name", None)
                    or getattr(obj, "title", None)
                    or f"#{getattr(obj, 'id', '?')}"
                )
                results.append({"id": str(obj.id), "label": label})

        return JSONResponse(content=results)

    # ── Inline Field Update (existing) ─────────────────────────────
    @router.patch("/{id}/field")
    async def update_field(
        request: Request,
        id: str,
        _csrf: bool = Depends(require_csrf_token),
    ):
        """Inline field update — used by toggle switches in list view."""
        from fastapi_admin_kit.auth.csrf import _get_secret_key, generate_csrf_token

        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            body = await request.json()
        else:
            form = await request.form()
            body = dict(form)

        field_name = body.get("field")
        new_value = body.get("value")

        if not field_name:
            raise HTTPException(status_code=400, detail="Missing field name")

        readonly = getattr(registered.admin, "readonly_fields", []) or []
        if field_name in readonly:
            raise HTTPException(status_code=403, detail="Field is read-only")

        col = next((c for c in registered.columns if c.name == field_name), None)
        if col is None:
            raise HTTPException(status_code=400, detail="Invalid field name")

        if col.type.__class__.__name__ == "Boolean":
            new_value = str(new_value).lower() in ("true", "1", "yes")

        session = get_db_session(request)
        try:
            obj = await session.get(registered.model, int(id))
            if obj is None:
                raise HTTPException(status_code=404, detail="Object not found")

            setattr(obj, field_name, new_value)
            await session.flush()
        except Exception:
            await session.rollback()
            raise

        val = getattr(obj, field_name)
        secret = _get_secret_key(request) or ""
        csrf_token = generate_csrf_token(secret)
        admin_path = request.app.state.admin_config["admin_path"]

        if val:
            toggle_html = (
                f'<button class="toggle-switch toggle-switch--on"'
                f' hx-patch="{admin_path}/{registered.table_name}/{obj.id}/field"'
                f' hx-vals=\'{{"field": "{field_name}", "value": "false"}}\''
                f' hx-target="this" hx-swap="outerHTML"'
                f' hx-headers=\'{{"X-CSRF-Token": "{csrf_token}"}}\''
                f' role="checkbox" aria-checked="true">'
                f'<span class="toggle-switch__thumb"></span></button>'
            )
        else:
            toggle_html = (
                f'<button class="toggle-switch"'
                f' hx-patch="{admin_path}/{registered.table_name}/{obj.id}/field"'
                f' hx-vals=\'{{"field": "{field_name}", "value": "true"}}\''
                f' hx-target="this" hx-swap="outerHTML"'
                f' hx-headers=\'{{"X-CSRF-Token": "{csrf_token}"}}\''
                f' role="checkbox" aria-checked="false">'
                f'<span class="toggle-switch__thumb"></span></button>'
            )
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=toggle_html)

    return router
