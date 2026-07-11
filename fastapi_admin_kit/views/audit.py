"""Audit log views — list and detail."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, select

from fastapi_admin_kit.audit.models import AuditLog
from fastapi_admin_kit.auth.dependencies import get_current_admin_user
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


@router.get("/audit")
async def audit_list_view(
    request: Request,
    model: str | None = Query(None, description="Filter by model name"),
    user_id: int | None = Query(None),
    action: str | None = Query(None, pattern="^(CREATE|UPDATE|DELETE)$"),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    object_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    _: AdminUserProtocol = Depends(_require_superuser),
):
    """List audit log entries with filters."""
    templates = request.app.state.admin_jinja_env
    session = get_db_session(request)

    query = select(AuditLog)

    if model:
        query = query.where(AuditLog.table_name == model)
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    if action:
        query = query.where(AuditLog.action == action)
    if from_date:
        query = query.where(AuditLog.timestamp >= datetime.combine(from_date, datetime.min.time()))
    if to_date:
        query = query.where(AuditLog.timestamp <= datetime.combine(to_date, datetime.max.time()))
    if object_id:
        query = query.where(AuditLog.object_id == object_id)

    query = query.order_by(desc(AuditLog.timestamp))
    per_page = 25
    offset = (page - 1) * per_page
    total_query = select(AuditLog)
    if model:
        total_query = total_query.where(AuditLog.table_name == model)
    if user_id:
        total_query = total_query.where(AuditLog.user_id == user_id)
    if action:
        total_query = total_query.where(AuditLog.action == action)
    if from_date:
        total_query = total_query.where(
            AuditLog.timestamp >= datetime.combine(from_date, datetime.min.time())
        )
    if to_date:
        total_query = total_query.where(
            AuditLog.timestamp <= datetime.combine(to_date, datetime.max.time())
        )
    if object_id:
        total_query = total_query.where(AuditLog.object_id == object_id)

    total_result = await session.execute(total_query)
    total = len(total_result.scalars().all())
    entries = (await session.execute(query.offset(offset).limit(per_page))).scalars().all()

    admin_path = request.app.state.admin_config["admin_path"]

    return templates.TemplateResponse(
        request,
        "pages/audit_log.html",
        await inject_sidebar_context(request, {
            "entries": entries,
            "page": page,
            "per_page": per_page,
            "total_items": total,
            "total_pages": max(1, (total + per_page - 1) // per_page),
            "admin_path": admin_path,
            "search": "",
            "action_filter": action or "",
            "model_filter": model or "",
            "model_names": [m.table_name for m in request.app.state.admin_registry.all()],
            "filters": {
                "model": model or "",
                "user_id": user_id or "",
                "action": action or "",
                "from_date": from_date or "",
                "to_date": to_date or "",
                "object_id": object_id or "",
            },
        }),
    )


@router.get("/audit/{entry_id}")
async def audit_detail_view(
    request: Request,
    entry_id: int,
    _: AdminUserProtocol = Depends(_require_superuser),
):
    """Show detailed audit entry with diff snapshot."""
    templates = request.app.state.admin_jinja_env
    session = get_db_session(request)

    entry = await session.get(AuditLog, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Audit entry not found")

    admin_path = request.app.state.admin_config["admin_path"]

    return templates.TemplateResponse(
        request,
        "pages/audit_detail.html",
        await inject_sidebar_context(request, {
            "entry": entry,
            "admin_path": admin_path,
        }),
    )
