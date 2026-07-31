# Integrating with Existing Alembic Setup

If your project already uses Alembic for migrations, you don't need to run `fak init-alembic`. Instead, add the admin models to your existing Alembic configuration.

## Quick Integration

In your existing `alembic/env.py`, add the admin models' metadata:

```python
# Your existing imports
from myapp.models import Base as AppBase

# Add this import
from fastapi_admin_kit.migrations.models import Base as AdminBase

# Combine metadata for autogenerate
target_metadata = [AppBase.metadata, AdminBase.metadata]
```

That's it! Now run:

```bash
alembic revision --autogenerate -m "add admin models"
alembic upgrade head
```

## What Gets Added

The admin models include:

| Table | Purpose |
|-------|---------|
| `admin_users` | Admin user accounts |
| `admin_roles` | Role definitions |
| `admin_permissions` | Per-model permissions |
| `admin_user_roles` | User ↔ Role junction |
| `admin_role_permissions` | Role ↔ Permission junction |
| `admin_user_permissions` | Direct user permission overrides |
| `admin_refresh_tokens` | JWT refresh tokens |
| `admin_user_totp` | 2FA TOTP secrets |
| `admin_login_attempts` | Login audit trail |
| `admin_audit_log` | Full change audit log |

Plus two junction tables (`admin_user_roles`, `admin_role_permissions`) created automatically via relationships.

## Custom User Model

If you use a custom `auth_model` with `Admin()`:

```python
admin = Admin(
    app=app,
    auth_model=MyCustomUser,  # Your custom user model
    # ...
)
```

Your custom user model's table will be managed by **your** migrations (not admin migrations). Ensure your `AppBase.metadata` includes it.

The admin models reference `admin_users` table via foreign keys. If your custom user model uses a different table name, you'll need to adjust the foreign key references or use the built-in `User` model.

## Example: Complete `alembic/env.py`

```python
import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Your application models
from myapp.models import Base as AppBase

# FastAPI Admin Kit models
from fastapi_admin_kit.migrations.models import Base as AdminBase

# Combine metadata for autogenerate
target_metadata = [AppBase.metadata, AdminBase.metadata]

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

## Migration History

Your migration history will now include admin tables alongside your app tables. Each revision can contain changes to both.

```bash
# After integration, first admin migration
alembic revision --autogenerate -m "add admin models"

# Later, your app changes
alembic revision --autogenerate -m "add product table"

# Both in history:
alembic history --verbose
```

## Backward Compatibility

The old `fastapi_admin_kit.auth.models` and `fastapi_admin_kit.audit.models` modules still exist but emit deprecation warnings. They re-export the same model classes from `migrations.models`.

You can migrate imports gradually:

```python
# Old (deprecated, still works)
from fastapi_admin_kit.auth.models import User, Role

# New (recommended)
from fastapi_admin_kit.migrations.models import User, Role
```

## Next Steps

- [Alembic Setup](alembic-setup.md) — Full setup guide for new projects
- [CLI Reference](cli.md) — `init-alembic` and `migrate-alembic` commands
- [Model Registration](../guide/model-registration.md) — Register your models with the admin
