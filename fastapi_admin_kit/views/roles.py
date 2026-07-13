"""Role management views — list, create, edit, delete."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select

from fastapi_admin_kit.auth.csrf import require_csrf_token
from fastapi_admin_kit.auth.dependencies import get_current_admin_user
from fastapi_admin_kit.auth.models import Permission, Role
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

    results = [{"id": m.table_name, "label": m.verbose_name} for m in models]

    if q:
        q_lower = q.lower()
        results = [
            r for r in results if q_lower in r["label"].lower() or q_lower in r["id"].lower()
        ]

    return JSONResponse(content=results)


@router.get("/permissions/search")
async def permissions_search(
    request: Request,
    q: str = Query("", description="Search query"),
    ids: str = Query("", description="Comma-separated permission IDs to load"),
    _: AdminUserProtocol = Depends(_require_superuser),
):
    """Search existing permissions for the multi-select picker."""
    session = get_db_session(request)

    if ids:
        id_list = [int(i.strip()) for i in ids.split(",") if i.strip().isdigit()]
        if id_list:
            result = await session.execute(select(Permission).where(Permission.id.in_(id_list)))
            perms = result.scalars().all()
            return JSONResponse(
                content=[{"id": p.id, "label": p.name, "table_name": p.table_name} for p in perms]
            )

    query = select(Permission)
    if q:
        query = query.where(Permission.name.ilike(f"%{q}%"))
    query = query.order_by(Permission.name).limit(50)

    result = await session.execute(query)
    perms = result.scalars().all()

    return JSONResponse(
        content=[{"id": p.id, "label": p.name, "table_name": p.table_name} for p in perms]
    )


@router.get("/roles", response_class=HTMLResponse)
async def role_list_view(
    request: Request,
    _: AdminUserProtocol = Depends(_require_superuser),
):
    """List roles with user counts."""
    templates = request.app.state.admin_jinja_env
    session = get_db_session(request)

    result = await session.execute(select(Role))
    roles = list(result.scalars().all())

    role_data = []
    for role in roles:
        user_count = len(role.users)
        role_data.append(
            {
                "role": role,
                "user_count": user_count,
            }
        )

    return templates.TemplateResponse(
        request,
        "pages/roles.html",
        await inject_sidebar_context(
            request,
            {
                "roles": role_data,
            },
        ),
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
        await inject_sidebar_context(
            request,
            {
                "role": None,
                "perm_ids": [],
                "perm_search_url": (
                    f"{request.app.state.admin_config['admin_path']}" "/permissions/search"
                ),
            },
        ),
    )


@router.post("/roles", response_class=RedirectResponse)
async def role_create_save_view(
    request: Request,
    _: AdminUserProtocol = Depends(_require_superuser),
    _csrf: bool = Depends(require_csrf_token),
):
    """Create a new role with permissions from form submission."""
    session = get_db_session(request)

    form = await request.form()
    name = form.get("name", "").strip()
    description = form.get("description", "").strip()
    perm_ids_raw = form.get("perm_ids", "[]")

    if not name:
        raise HTTPException(status_code=400, detail="Role name is required.")

    existing = await session.execute(select(Role).where(Role.name == name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Role name already exists.")

    role = Role(name=name, description=description)
    session.add(role)
    await session.flush()

    try:
        perm_ids = json.loads(perm_ids_raw)
    except (json.JSONDecodeError, TypeError):
        perm_ids = []

    if perm_ids:
        result = await session.execute(select(Permission).where(Permission.id.in_(perm_ids)))
        perms = result.scalars().all()
        for perm in perms:
            role.permissions.append(perm)

    await session.flush()

    return RedirectResponse(
        url=f"{request.app.state.admin_config['admin_path']}/roles",
        status_code=302,
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

    role = await session.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")

    perm_ids = [p.id for p in role.permissions]

    return templates.TemplateResponse(
        request,
        "pages/role_form.html",
        await inject_sidebar_context(
            request,
            {
                "role": role,
                "perm_ids": perm_ids,
                "perm_search_url": (
                    f"{request.app.state.admin_config['admin_path']}" "/permissions/search"
                ),
            },
        ),
    )


@router.post("/roles/{role_id}", response_class=RedirectResponse)
async def role_save_view(
    request: Request,
    role_id: int,
    _: AdminUserProtocol = Depends(_require_superuser),
    _csrf: bool = Depends(require_csrf_token),
):
    """Save role permissions from form submission."""
    session = get_db_session(request)

    role = await session.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")

    form = await request.form()
    perm_ids_raw = form.get("perm_ids", "[]")

    try:
        perm_ids = json.loads(perm_ids_raw)
    except (json.JSONDecodeError, TypeError):
        perm_ids = []

    role.permissions.clear()

    if perm_ids:
        result = await session.execute(select(Permission).where(Permission.id.in_(perm_ids)))
        perms = result.scalars().all()
        for perm in perms:
            role.permissions.append(perm)

    await session.flush()

    return RedirectResponse(
        url=f"{request.app.state.admin_config['admin_path']}/roles",
        status_code=302,
    )


@router.post("/roles/{role_id}/delete", response_class=RedirectResponse)
async def role_delete_view(
    request: Request,
    role_id: int,
    _: AdminUserProtocol = Depends(_require_superuser),
    _csrf: bool = Depends(require_csrf_token),
):
    """Delete role (refuse if users assigned)."""
    session = get_db_session(request)

    role = await session.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")

    user_count = len(role.users)
    if user_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete role. {user_count} user(s) are still assigned.",
        )

    role.permissions.clear()

    await session.delete(role)
    await session.flush()

    return RedirectResponse(
        url=f"{request.app.state.admin_config['admin_path']}/roles",
        status_code=302,
    )
