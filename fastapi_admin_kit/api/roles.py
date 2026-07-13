"""API endpoints for role management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from fastapi_admin_kit.api.deps import require_api_superuser
from fastapi_admin_kit.auth.models import Role
from fastapi_admin_kit.db import get_db_session

router = APIRouter(prefix="/roles", tags=["api-roles"])


class RoleCreate(BaseModel):
    name: str
    description: str = ""


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class RoleResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    user_count: int = 0


@router.get("/", response_model=list[RoleResponse])
async def list_roles(
    request: Request,
    user: dict[str, Any] = Depends(require_api_superuser()),
) -> list[RoleResponse]:
    """GET /api/roles/ — list all roles (superuser only)."""
    db_session = get_db_session(request)
    result = await db_session.execute(select(Role))
    roles = result.scalars().all()
    return [
        RoleResponse(
            id=r.id,
            name=r.name,
            description=r.description,
            user_count=len(r.users),
        )
        for r in roles
    ]


@router.post("/", response_model=RoleResponse, status_code=201)
async def create_role(
    request: Request,
    body: RoleCreate,
    user: dict[str, Any] = Depends(require_api_superuser()),
) -> RoleResponse:
    """POST /api/roles/ — create a role (superuser only)."""
    db_session = get_db_session(request)

    existing = await db_session.execute(select(Role).where(Role.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Role name already exists.")

    role = Role(name=body.name, description=body.description)
    db_session.add(role)
    await db_session.flush()
    await db_session.refresh(role)

    return RoleResponse(id=role.id, name=role.name, description=role.description)


@router.put("/{role_id}", response_model=RoleResponse)
async def update_role(
    request: Request,
    role_id: int,
    body: RoleUpdate,
    user: dict[str, Any] = Depends(require_api_superuser()),
) -> RoleResponse:
    """PUT /api/roles/{id} — update a role (superuser only)."""
    db_session = get_db_session(request)
    role = await db_session.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found.")

    if body.name is not None:
        role.name = body.name
    if body.description is not None:
        role.description = body.description

    await db_session.flush()
    await db_session.refresh(role)

    return RoleResponse(
        id=role.id,
        name=role.name,
        description=role.description,
        user_count=len(role.users),
    )


@router.delete("/{role_id}", status_code=204, response_model=None)
async def delete_role(
    request: Request,
    role_id: int,
    user: dict[str, Any] = Depends(require_api_superuser()),
) -> None:
    """DELETE /api/roles/{id} — delete a role (superuser only)."""
    db_session = get_db_session(request)
    role = await db_session.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found.")

    if len(role.users) > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete role. {len(role.users)} user(s) are still assigned.",
        )

    await db_session.delete(role)
    await db_session.flush()
