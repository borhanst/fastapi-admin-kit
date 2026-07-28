"""Protocol for user models that can be used as the admin auth model.

Defines the contract that any user model must satisfy to work with the
admin RBAC system. The protocol layer is the first of three layers:

1. **Protocol** — contract definition (this file)
2. **Schema** — built-in model definitions (``schemas/builtin.py``)
3. **Materialization** — backend converts schemas to native models

Custom user models only need to satisfy the protocol. Built-in models
are defined as schemas and materialized by the backend.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AdminPermissionProtocol(Protocol):
    """Contract for a permission object.

    Each permission grants CRUD booleans on a specific model table.
    The admin reads this to enforce access control.
    """

    id: Any
    name: str
    table_name: str
    can_view: bool
    can_create: bool
    can_edit: bool
    can_delete: bool


@runtime_checkable
class AdminRoleProtocol(Protocol):
    """Contract for a role object.

    Roles group permissions and are assigned to users via M2M.
    The admin reads ``role.permissions`` to check access.
    """

    id: Any
    name: str
    permissions: list  # list of AdminPermissionProtocol-compatible objects


@runtime_checkable
class AdminUserProtocol(Protocol):
    """Contract for a user model that works with admin RBAC.

    Any user model passed as ``auth_model=`` must satisfy this interface.
    The admin framework only reads these attributes from the user object.
    """

    id: Any  # primary key (int, str, UUID, etc.)
    email: str  # used for audit log denormalization
    is_active: bool  # inactive users are refused login
    is_superuser: bool  # bypasses all permission checks if True

    # Many-to-many roles — the admin reads this to look up permissions.
    # Must be an iterable of role objects, each with an `id` attribute
    # and a `.permissions` iterable.
    roles: list  # list of AdminRoleProtocol-compatible objects

    def verify_password(self, password: str) -> bool: ...

    def hash_password(self, password: str) -> str: ...

    @property
    def role_ids(self) -> list: ...
