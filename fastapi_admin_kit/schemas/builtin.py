"""Built-in model schemas for admin auth, roles, permissions, and audit.

These schemas define the default admin models. Backends convert them to
native ORM models via ``materialize(schema)``. Custom user models can
override the user schema by passing ``auth_model=`` to ``Admin()``.
"""

from __future__ import annotations

from fastapi_admin_kit.schemas.schema import Field, Relation, Schema

# ---------------------------------------------------------------------------
# User schema
# ---------------------------------------------------------------------------

USER_SCHEMA = Schema(
    table_name="admin_users",
    verbose_name="Admin User",
    verbose_name_plural="Admin Users",
    fields=[
        Field("id", type="integer", primary_key=True, auto_increment=True),
        Field("email", type="string", max_length=255, unique=True, nullable=False),
        Field("hashed_password", type="string", max_length=255, nullable=False),
        Field("full_name", type="string", max_length=255, nullable=True),
        Field("is_active", type="boolean", default=True),
        Field("is_superuser", type="boolean", default=False),
        Field("last_login", type="datetime", nullable=True),
        Field("password_changed_at", type="datetime", nullable=True),
        Field("created_at", type="datetime", server_default="now()"),
    ],
    relations=[
        Relation(
            name="roles",
            target="admin_roles",
            type="many_to_many",
            through="admin_user_roles",
            back_populates="users",
        ),
        Relation(
            name="direct_permissions",
            target="admin_user_permissions",
            type="one_to_many",
            back_populates="user",
        ),
        Relation(
            name="refresh_tokens",
            target="admin_refresh_tokens",
            type="one_to_many",
            back_populates="user",
        ),
        Relation(
            name="totp",
            target="admin_user_totp",
            type="one_to_many",
            back_populates="user",
        ),
    ],
)

# ---------------------------------------------------------------------------
# Role schema
# ---------------------------------------------------------------------------

ROLE_SCHEMA = Schema(
    table_name="admin_roles",
    verbose_name="Role",
    verbose_name_plural="Roles",
    fields=[
        Field("id", type="integer", primary_key=True),
        Field("name", type="string", max_length=100, unique=True, nullable=False),
        Field("description", type="text", nullable=True),
        Field("created_at", type="datetime", server_default="now()"),
    ],
    relations=[
        Relation(
            name="users",
            target="admin_users",
            type="many_to_many",
            through="admin_user_roles",
            back_populates="roles",
        ),
        Relation(
            name="permissions",
            target="admin_permissions",
            type="many_to_many",
            through="admin_role_permissions",
            back_populates="roles",
        ),
    ],
)

# ---------------------------------------------------------------------------
# Permission schema
# ---------------------------------------------------------------------------

PERMISSION_SCHEMA = Schema(
    table_name="admin_permissions",
    verbose_name="Permission",
    verbose_name_plural="Permissions",
    fields=[
        Field("id", type="integer", primary_key=True),
        Field("name", type="string", max_length=255, nullable=False, unique=True),
        Field("table_name", type="string", max_length=255, nullable=False),
        Field("can_view", type="boolean", default=False),
        Field("can_create", type="boolean", default=False),
        Field("can_edit", type="boolean", default=False),
        Field("can_delete", type="boolean", default=False),
    ],
    relations=[
        Relation(
            name="roles",
            target="admin_roles",
            type="many_to_many",
            through="admin_role_permissions",
            back_populates="permissions",
        ),
    ],
)

# ---------------------------------------------------------------------------
# Audit Log schema
# ---------------------------------------------------------------------------

AUDIT_LOG_SCHEMA = Schema(
    table_name="admin_audit_log",
    verbose_name="Audit Log",
    verbose_name_plural="Audit Logs",
    fields=[
        Field("id", type="integer", primary_key=True, auto_increment=True),
        Field("user_id", type="integer", nullable=True, index=True),
        Field("user_email", type="string", max_length=255, nullable=True),
        Field("action", type="string", max_length=10, nullable=False),
        Field("model_name", type="string", max_length=255, nullable=False),
        Field("table_name", type="string", max_length=255, nullable=False),
        Field("object_id", type="string", max_length=255, nullable=False),
        Field("object_repr", type="string", max_length=500, nullable=True),
        Field("changes", type="json", nullable=True),
        Field("full_snapshot", type="json", nullable=True),
        Field("ip_address", type="string", max_length=45, nullable=True),
        Field("user_agent", type="text", nullable=True),
        Field("timestamp", type="datetime", server_default="now()"),
    ],
    relations=[],
)

# ---------------------------------------------------------------------------
# Login Attempt schema
# ---------------------------------------------------------------------------

LOGIN_ATTEMPT_SCHEMA = Schema(
    table_name="admin_login_attempts",
    verbose_name="Login Attempt",
    verbose_name_plural="Login Attempts",
    fields=[
        Field("id", type="integer", primary_key=True),
        Field("email", type="string", max_length=255, nullable=False, index=True),
        Field("ip_address", type="string", max_length=45, nullable=False),
        Field("user_agent", type="string", max_length=512, nullable=True),
        Field("success", type="boolean", default=False),
        Field("note", type="text", nullable=True),
        Field("timestamp", type="datetime", server_default="now()"),
    ],
    relations=[],
)
