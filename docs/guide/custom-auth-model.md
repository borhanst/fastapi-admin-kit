# Custom Auth Model

Use your own user model instead of the built-in `admin_users` table. This is
the recommended pattern when your project already has a `User` model
(SQLAlchemy, SQLModel, or anything that satisfies
`AdminUserProtocol`).

## Why use a custom auth model

- You already have a `User` model with your schema, password hashing, and
  email-verification flow. Reusing it avoids two parallel user tables.
- Your `User.id` may be a `UUID`, ULID, or `String(36)` — the admin tables
  adapt their `user_id` columns to match.
- Roles, permissions, and audit log records reference your real user IDs.

## Minimal example

```python
import uuid
from typing import Optional

from fastapi import FastAPI
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.types import Uuid

from fastapi_admin_kit import Admin, DatabaseConfig, DatabaseType
from fastapi_admin_kit.auth.mixins import AuthModelMixin


class Base(DeclarativeBase):
    pass


class User(AuthModelMixin, Base):
    __tablename__ = "users"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    name = Column(String(255), nullable=True)

    # AuthModelMixin provides the rest of the protocol surface
    # (is_active, is_superuser, role_ids, verify_password, etc.).


app = FastAPI()
admin = Admin(
    app=app,
    base=Base,
    database_config=DatabaseConfig(
        db_type=DatabaseType.POSTGRESQL,
        url="postgresql+asyncpg://user:pass@localhost/app",
    ),
    secret_key="change-me-to-32-chars-or-more-please",
    auth_model=User,
)
```

When `auth_model=` is supplied:

1. The built-in `admin_users` and `admin_user_roles` tables are **not**
   created. Your `User` table is the single source of truth.
2. The built-in log-pattern `user_id` columns (`admin_audit_log.user_id`,
   `admin_user_permissions.user_id`, `admin_refresh_tokens.user_id`,
   etc.) are retyped to match your `User.id` type — e.g. `Uuid` if your
   `User.id` is a `Uuid`.
3. The built-in `UserAdmin` CRUD view is **not** registered. Register
   your own `UserAdmin` subclass against your model if you want it in
   the sidebar.

## Lifespan setup

The recommended pattern is to call `admin.create_tables()` from your
`lifespan` instead of touching `AdminBase.metadata` directly. The
package will skip the built-in user tables and let your project's
metadata own them.

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlmodel import SQLModel  # or your ORM of choice

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Create your project's tables first
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # 2. Create the admin tables (built-in user tables are skipped
    #    because auth_model=User is configured)
    await admin.create_tables()

    # 3. Wire up routes, middleware, templates
    await admin.setup(app)

    yield
```

> **Do not** call `AdminBase.metadata.create_all` directly. It bypasses
> the custom-auth_model logic and will create the default
> `admin_users` / `admin_user_roles` tables even when you supplied your
> own user model. Always go through `admin.create_tables()` or
> `admin.setup()`.

## What you keep

Even with a custom `auth_model`, the admin still manages these tables:

- `admin_roles` and `admin_permissions` (RBAC)
- `admin_user_permissions` (per-user permission overrides)
- `admin_refresh_tokens` (session storage)
- `admin_user_totp` (2FA secrets)
- `admin_audit_log` (change history with `user_id` and `user_email`)
- `admin_notifications` and friends (when notifications are enabled)
- `admin_ai_*` (when AI is enabled)

## What you bring

Your `auth_model` must satisfy `AdminUserProtocol` (validated at
`Admin()` construction time):

| Attribute | Type | Notes |
|-----------|------|-------|
| `id` | any | The PK type — `int`, `UUID`, etc. |
| `email` | `str` | Used as the login identifier |
| `is_active` | `bool` | Inactive users cannot log in |
| `is_superuser` | `bool` | Bypasses all RBAC checks |
| `hashed_password` | `str` | bcrypt / argon2 hash |
| `role_ids` | `list[int]` | Property that returns role IDs |
| `roles` | relationship | M2M to `Role` model |
| `verify_password(plain)` | method | Returns `bool` |

`fastapi_admin_kit.auth.mixins.AuthModelMixin` provides all of the
above for SQLAlchemy declarative models — inherit from it to get
`is_active`, `is_superuser`, `role_ids`, and password helpers for free.

## Troubleshooting

### `'NoneType' object has no attribute '_run_ddl_visitor'`

You called `AdminBase.metadata.create_all` directly, or you constructed
`Admin()` without an engine and without a `database_config`. Pass one
of:

```python
admin = Admin(
    engine=engine,                  # explicit engine
    # or
    database_config=DatabaseConfig(...),  # lazy engine from URL
)
```

If you want the admin to skip table creation entirely (e.g. you manage
schema with Alembic), pass `use_alembic=True`.

### `admin_users` table keeps being created

Make sure you're using `admin.create_tables()` or `admin.setup()`, **not**
`AdminBase.metadata.create_all`. The package never mutates the shared
`AdminBase.metadata` (its `FacadeDict` is immutable); it filters the
excluded tables only at `create_all` time, and only via the public
`Admin` API.

### `TypeError: Object of type UUID is not JSON serializable` on login

The session cookie is signed via `itsdangerous`, whose default JSON
encoder doesn't know about `UUID`. The admin's `SignedCookieSessionBackend`
registers a `default=` handler that converts `UUID` → `str`, `datetime`
→ ISO string, `Decimal` → `str`, and `set`/`frozenset` → `list`. This
covers every payload type a typical `auth_model` exposes (`user.id`,
`iat`, optional `exp`), so a UUID PK works out of the box.

If you replace the session backend with a custom one, make sure your
encoder handles the same set of types — or coerce `user.id` to `str`
before stuffing it into the payload.
