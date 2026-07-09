"""Role management views — list, create, edit, delete."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select

from fastapi_admin_kit.auth.csrf import require_csrf_token
from fastapi_admin_kit.auth.dependencies import get_current_admin_user
from fastapi_admin_kit.auth.models import AdminPermission, AdminRole
from fastapi_admin_kit.auth.protocol import AdminUserProtocol
from fastapi_admin_kit.db import get_db_session
from fastapi_admin_kit.views.sidebar import inject_sidebar_context

router = APIRouter()


async def _require_superuser(
    user: AdminUserProtocol = Depends(get_current_admin_user),
) -> AdminUserProtocol:
    if not getattr(user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Superuser access required.")
    return user


@router.get("/tables/search")
async def tables_search(
    request: Request,
    q: str = Query("", description="Search query"),
    _: AdminUserProtocol = Depends(_require_superuser),
):
    """Search registered models for permission table picker."""
    registry = request.app.state.admin_registry
    models = registry.all()

    results = [
        {"id": m.table_name, "label": m.verbose_name}
        for m in models
    ]

    if q:
        q_lower = q.lower()
        results = [
            r for r in results
            if q_lower in r["label"].lower() or q_lower in r["id"].lower()
        ]

    return JSONResponse(content=results)


@router.get("/roles", response_class=HTMLResponse)
async def role_list_view(
    request: Request,
    _: AdminUserProtocol = Depends(_require_superuser),
):
    """List roles with user counts."""
    templates = request.app.state.admin_jinja_env
    session = get_db_session(request)

    result = await session.execute(select(AdminRole))
    roles = list(result.scalars().all())

    role_data = []
    for role in roles:
        user_count = len(role.users)
        role_data.append({
            "role": role,
            "user_count": user_count,
        })

    return templates.TemplateResponse(
        request,
        "pages/roles.html",
        await inject_sidebar_context(request, {
            "roles": role_data,
        }),
    )


@router.get("/roles/create", response_class=HTMLResponse)
async def role_create_view(
    request: Request,
    _: AdminUserProtocol = Depends(_require_superuser),
):
    """Show empty role create form."""
    templates = request.app.state.admin_jinja_env

    return templates.TemplateResponse(
        request,
        "pages/role_form.html",
        await inject_sidebar_context(request, {
            "role": None,
            "perm_data": {},
            "search_url": f"{request.app.state.admin_config['admin_path']}/tables/search",
        }),
    )


@router.get("/roles/{role_id}", response_class=HTMLResponse)
async def role_edit_view(
    request: Request,
    role_id: int,
    _: AdminUserProtocol = Depends(_require_superuser),
):
    """Show edit form with permission matrix."""
    templates = request.app.state.admin_jinja_env
    session = get_db_session(request)
    registry = request.app.state.admin_registry

    role = await session.get(AdminRole, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")

    models = registry.all()
    model_map = {m.table_name: m.verbose_name for m in models}

    perms = (
        await session.execute(
            select(AdminPermission).where(AdminPermission.role_id == role_id)
        )
    ).scalars().all()

    perm_data = {}
    for p in perms:
        perm_data[p.table_name] = {
            "_label": model_map.get(p.table_name, p.table_name),
            "view": p.can_view,
            "create": p.can_create,
            "edit": p.can_edit,
            "delete": p.can_delete,
        }

    return templates.TemplateResponse(
        request,
        "pages/role_form.html",
        await inject_sidebar_context(request, {
            "role": role,
            "perm_data": perm_data,
            "search_url": f"{request.app.state.admin_config['admin_path']}/tables/search",
        }),
    )


@router.post("/roles/{role_id}", response_class=HTMLResponse)
async def role_save_view(
    request: Request,
    role_id: int,
    _: AdminUserProtocol = Depends(_require_superuser),
    _csrf: bool = Depends(require_csrf_token),
):
    """Save role permissions from form submission."""
    session = get_db_session(request)

    role = await session.get(AdminRole, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")

    form = await request.form()
    perm_data_raw = form.get("perm_data", "{}")

    try:
        perm_data = json.loads(perm_data_raw)
    except (json.JSONDecodeError, TypeError):
        perm_data = {}

    existing_perms = (
        await session.execute(
            select(AdminPermission).where(AdminPermission.role_id == role_id)
        )
    ).scalars().all()
    existing_perm_map = {p.table_name: p for p in existing_perms}

    for table, data in perm_data.items():
        if not any(data.get(a) for a in ["view", "create", "edit", "delete"]):
            continue
        if table in existing_perm_map:
            perm = existing_perm_map[table]
            perm.can_view = data.get("view", False)
            perm.can_create = data.get("create", False)
            perm.can_edit = data.get("edit", False)
            perm.can_delete = data.get("delete", False)
        else:
            perm = AdminPermission(
                role_id=role_id,
                table_name=table,
                can_view=data.get("view", False),
                can_create=data.get("create", False),
                can_edit=data.get("edit", False),
                can_delete=data.get("delete", False),
            )
            session.add(perm)

    tables_in_form = set(perm_data.keys())
    for table, perm in existing_perm_map.items():
        if table not in tables_in_form:
            await session.delete(perm)

    await session.flush()

    return RedirectResponse(url=f"{request.app.state.admin_config['admin_path']}/roles", status_code=302)


@router.post("/roles/{role_id}/delete", response_class=RedirectResponse)
async def role_delete_view(
    request: Request,
    role_id: int,
    _: AdminUserProtocol = Depends(_require_superuser),
    _csrf: bool = Depends(require_csrf_token),
):
    """Delete role (refuse if users assigned)."""
    session = get_db_session(request)

    role = await session.get(AdminRole, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")

    user_count = len(role.users)
    if user_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete role. {user_count} user(s) are still assigned.",
        )

    await session.delete(role)
    await session.flush()

    return RedirectResponse(url=f"{request.app.state.admin_config['admin_path']}/roles", status_code=302)
