"""Admin user management views — list, create, edit, delete."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select

from fastapi_admin_kit.auth.dependencies import get_current_admin_user
from fastapi_admin_kit.auth.models import AdminRole
from fastapi_admin_kit.auth.protocol import AdminUserProtocol
from fastapi_admin_kit.db import get_db_session

router = APIRouter()


async def _require_superuser(
    user: AdminUserProtocol = Depends(get_current_admin_user),
) -> AdminUserProtocol:
    if not getattr(user, "is_superuser", False):
        raise HTTPException(
            status_code=403, detail="Superuser access required."
        )
    return user


@router.get("/users/roles/search")
async def roles_search(
    request: Request,
    q: str = Query("", description="Search query"),
    ids: str = Query("", description="Comma-separated role IDs to load"),
    _: AdminUserProtocol = Depends(_require_superuser),
):
    """Search roles for the multi-relation picker. Supports ?q= and ?ids=."""
    session = get_db_session(request)

    if ids:
        id_list = [
            int(i.strip()) for i in ids.split(",") if i.strip().isdigit()
        ]
        result = await session.execute(
            select(AdminRole).where(AdminRole.id.in_(id_list))
        )
    elif q:
        result = await session.execute(
            select(AdminRole)
            .where(
                or_(
                    AdminRole.name.ilike(f"%{q}%"),
                    AdminRole.description.ilike(f"%{q}%"),
                )
            )
            .limit(20)
        )
    else:
        result = await session.execute(
            select(AdminRole).order_by(AdminRole.name).limit(20)
        )

    roles = result.scalars().all()
    return JSONResponse(content=[{"id": r.id, "label": r.name} for r in roles])


# @router.get("/users", response_class=HTMLResponse)
# async def user_list_view(
#     request: Request,
#     _: AdminUserProtocol = Depends(_require_superuser),
# ):
#     """List admin users (superuser only)."""
#     templates = request.app.state.admin_jinja_env
#     session = get_db_session(request)

#     result = await session.execute(
#         select(AdminUser).options(selectinload(AdminUser.roles)).order_by(AdminUser.id)
#     )
#     users = list(result.scalars().all())

#     return templates.TemplateResponse(
#         request,
#         "pages/users/list.html",
#         await inject_sidebar_context(
#             request,
#             {
#                 "users": users,
#             },
#         ),
#     )


# @router.get("/users/create", response_class=HTMLResponse)
# async def user_create_view(
#     request: Request,
#     _: AdminUserProtocol = Depends(_require_superuser),
# ):
#     """Show user create form."""
#     templates = request.app.state.admin_jinja_env
#     session = get_db_session(request)

#     result = await session.execute(select(AdminRole).order_by(AdminRole.name))
#     roles = list(result.scalars().all())

#     return templates.TemplateResponse(
#         request,
#         "pages/users/form.html",
#         await inject_sidebar_context(
#             request,
#             {
#                 "user": None,
#                 "roles": roles,
#             },
#         ),
#     )


# @router.post("/users/create")
# async def user_create_post(
#     request: Request,
#     _: AdminUserProtocol = Depends(_require_superuser),
#     _csrf: bool = Depends(require_csrf_token),
# ):
#     """Handle user creation."""
#     from fastapi_admin_kit.auth.backend import pwd_context
#     from fastapi_admin_kit.auth.password import validate_password_strength

#     session = get_db_session(request)
#     form = await request.form()

#     email = form.get("email", "").strip()
#     password = form.get("password", "")
#     full_name = form.get("full_name", "").strip()
#     is_superuser = form.get("is_superuser") == "on"

#     if not email:
#         raise HTTPException(status_code=400, detail="Email is required.")

#     existing = await session.execute(
#         select(AdminUser).where(AdminUser.email == email)
#     )
#     if existing.scalar_one_or_none():
#         raise HTTPException(status_code=400, detail="Email already exists.")

#     password_errors = validate_password_strength(password)
#     if password_errors:
#         templates = request.app.state.admin_jinja_env
#         result = await session.execute(
#             select(AdminRole).order_by(AdminRole.name)
#         )
#         roles = list(result.scalars().all())
#         return templates.TemplateResponse(
#             request,
#             "pages/users/form.html",
#             await inject_sidebar_context(
#                 request,
#                 {
#                     "user": None,
#                     "roles": roles,
#                     "error": password_errors[0],
#                 },
#             ),
#         )

#     user = AdminUser(
#         email=email,
#         hashed_password=pwd_context.hash(password),
#         full_name=full_name,
#         is_superuser=is_superuser,
#     )
#     session.add(user)
#     await session.flush()

#     # Assign selected roles (from multiRelation JSON string or multi-select)
#     import json as _json

#     raw_role_ids = form.get("role_ids", "")
#     if isinstance(raw_role_ids, list):
#         raw_role_ids = raw_role_ids[0] if raw_role_ids else ""
#     if raw_role_ids:
#         try:
#             parsed = _json.loads(raw_role_ids)
#             if isinstance(parsed, list):
#                 role_id_strs = [str(v) for v in parsed]
#             else:
#                 role_id_strs = [str(parsed)]
#         except (ValueError, TypeError):
#             role_id_strs = [raw_role_ids]
#         for rid in role_id_strs:
#             try:
#                 role = await session.get(AdminRole, int(rid))
#                 if role:
#                     user.roles.append(role)
#             except (ValueError, TypeError):
#                 pass

#     await session.commit()

#     return RedirectResponse(url="/admin/users", status_code=302)


# @router.get("/users/{user_id}", response_class=HTMLResponse)
# async def user_edit_view(
#     request: Request,
#     user_id: int,
#     _: AdminUserProtocol = Depends(_require_superuser),
# ):
#     """Show user edit form."""
#     templates = request.app.state.admin_jinja_env
#     session = get_db_session(request)

#     result = await session.execute(
#         select(AdminUser)
#         .options(selectinload(AdminUser.roles))
#         .where(AdminUser.id == user_id)
#     )
#     user = result.scalar_one_or_none()
#     if user is None:
#         raise HTTPException(status_code=404, detail="User not found.")

#     result = await session.execute(select(AdminRole).order_by(AdminRole.name))
#     roles = list(result.scalars().all())

#     return templates.TemplateResponse(
#         request,
#         "pages/users/form.html",
#         await inject_sidebar_context(
#             request,
#             {
#                 "user": user,
#                 "roles": roles,
#             },
#         ),
#     )


# @router.post("/users/{user_id}")
# async def user_edit_post(
#     request: Request,
#     user_id: int,
#     current_user: AdminUserProtocol = Depends(_require_superuser),
#     _csrf: bool = Depends(require_csrf_token),
# ):
#     """Handle user edit."""
#     from fastapi_admin_kit.auth.backend import pwd_context
#     from fastapi_admin_kit.auth.password import validate_password_strength

#     session = get_db_session(request)
#     user = await session.get(AdminUser, user_id)
#     if user is None:
#         raise HTTPException(status_code=404, detail="User not found.")

#     form = await request.form()
#     email = form.get("email", "").strip()
#     password = form.get("password", "")
#     full_name = form.get("full_name", "").strip()
#     is_superuser = form.get("is_superuser") == "on"
#     is_active = form.get("is_active") != "off"

#     if email:
#         user.email = email
#     user.full_name = full_name

#     # Prevent superuser from deactivating themselves
#     if user.id == current_user.id and not is_active:
#         raise HTTPException(
#             status_code=400, detail="Cannot deactivate your own account."
#         )

#     if user.id == current_user.id and not is_superuser:
#         raise HTTPException(
#             status_code=400,
#             detail="Cannot remove superuser from your own account.",
#         )

#     user.is_superuser = is_superuser
#     user.is_active = is_active

#     if password:
#         password_errors = validate_password_strength(password)
#         if password_errors:
#             templates = request.app.state.admin_jinja_env
#             result = await session.execute(
#                 select(AdminRole).order_by(AdminRole.name)
#             )
#             roles = list(result.scalars().all())
#             return templates.TemplateResponse(
#                 request,
#                 "pages/users/form.html",
#                 await inject_sidebar_context(
#                     request,
#                     {
#                         "user": user,
#                         "roles": roles,
#                         "error": password_errors[0],
#                     },
#                 ),
#             )
#         user.hashed_password = pwd_context.hash(password)

#     # Update roles: clear existing, add selected
#     import json as _json

#     user.roles.clear()
#     raw_role_ids = form.get("role_ids", "")
#     if isinstance(raw_role_ids, list):
#         raw_role_ids = raw_role_ids[0] if raw_role_ids else ""
#     if raw_role_ids:
#         try:
#             parsed = _json.loads(raw_role_ids)
#             if isinstance(parsed, list):
#                 role_id_strs = [str(v) for v in parsed]
#             else:
#                 role_id_strs = [str(parsed)]
#         except (ValueError, TypeError):
#             role_id_strs = [raw_role_ids]
#         for rid in role_id_strs:
#             try:
#                 role = await session.get(AdminRole, int(rid))
#                 if role:
#                     user.roles.append(role)
#             except (ValueError, TypeError):
#                 pass

#     await session.commit()
#     return RedirectResponse(url="/admin/users", status_code=302)


# @router.post("/users/{user_id}/delete")
# async def user_delete_post(
#     request: Request,
#     user_id: int,
#     current_user: AdminUserProtocol = Depends(_require_superuser),
#     _csrf: bool = Depends(require_csrf_token),
# ):
#     """Soft-delete user (set is_active=False)."""
#     session = get_db_session(request)
#     user = await session.get(AdminUser, user_id)
#     if user is None:
#         raise HTTPException(status_code=404, detail="User not found.")

#     if user.id == current_user.id:
#         raise HTTPException(
#             status_code=400, detail="Cannot deactivate your own account."
#         )

#     user.is_active = False
#     await session.commit()

#     return RedirectResponse(url="/admin/users", status_code=302)
