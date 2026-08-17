# Alembic Setup

FastAPI Admin Kit provides built-in models for authentication (users, roles, permissions) and audit logging. This guide shows how to set up Alembic to manage database migrations for both admin tables and your application models.

## Quick Start with `fak init-alembic`

The easiest way to get started is using the built-in CLI command:

```bash
# For a new project
fak init-alembic --app myapp:app --auto-migrate

# For an existing database (baseline migration)
fak init-alembic --app myapp:app --baseline
```

This command:
1. Creates `alembic.ini` with proper configuration
2. Creates `alembic/env.py` that imports admin models from `fastapi_admin_kit.migrations.models`
3. Creates `alembic/script.py.mako` template
4. Optionally auto-generates the initial migration (`--auto-migrate`)
5. Optionally creates a baseline migration for existing databases (`--baseline`)

### What `init-alembic` Does

```
myproject/
├── alembic.ini          # Alembic configuration
├── alembic/
│   ├── env.py           # Migration environment (imports admin models)
│   ├── script.py.mako   # Migration template
│   └── versions/        # Migration scripts
```

The generated `alembic/env.py` includes:

```python
# Import admin models (materialized from schemas)
from fastapi_admin_kit.migrations.models import Base as AdminBase

# Import your app models
# from myapp.models import Base as AppBase

# Combine metadata for autogenerate
target_metadata = [AdminBase.metadata]
# target_metadata.append(AppBase.metadata)  # Add your models
```

## Manual Alembic Setup

If you prefer manual setup or have an existing Alembic configuration:

### 1. Install Alembic

```bash
pip install alembic
```

### 2. Initialize Alembic

```bash
alembic init alembic
```

### 3. Configure `alembic/env.py`

Replace the contents of `alembic/env.py`:

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

# Import admin models (materialized from schemas)
from fastapi_admin_kit.migrations.models import Base as AdminBase

# Import your application models
# from myapp.models import Base as AppBase

# Combine metadata for autogenerate
target_metadata = [AdminBase.metadata]
# target_metadata.append(AppBase.metadata)  # Add your models

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

### 4. Configure Database URL

Edit `alembic.ini`:

```ini
[alembic]
script_location = alembic
sqlalchemy.url = sqlite+aiosqlite:///./your_database.db
# For PostgreSQL:
# sqlalchemy.url = postgresql+asyncpg://user:pass@localhost:5432/dbname
```

### 5. Generate Initial Migration

```bash
alembic revision --autogenerate -m "init admin models"
```

### 6. Apply Migrations

```bash
alembic upgrade head
```

## Production vs Development Mode

FastAPI Admin Kit supports two modes:

| Mode | Setting | Behavior |
|------|---------|----------|
| **Development** (default) | `use_alembic=False` | Uses `create_all()` + auto-migration (adds missing columns) |
| **Production** | `use_alembic=True` | Expects Alembic to manage schema; skips `create_all()` |

### In Your Application

```python
from fastapi_admin_kit import Admin
from fastapi_admin_kit.config import BehaviorConfig

admin = Admin(
    app=app,
    engine=engine,
    # ... other config ...
    behavior=BehaviorConfig(use_alembic=True),  # Production mode
)
```

### In Lifespan (Production)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run alembic upgrade head on startup
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")

    await admin.setup(app)
    yield
```

## CLI Commands

### Initialize Alembic

```bash
# New project with auto-generated initial migration
fak init-alembic --app myapp:app --auto-migrate

# Existing project with database (creates baseline)
fak init-alembic --app myapp:app --baseline

# Force overwrite existing alembic config
fak init-alembic --app myapp:app --force
```

### Run Migrations (Production)

```bash
# Run all pending migrations (equivalent to alembic upgrade head)
fak migrate-alembic

# Run to specific revision
fak migrate-alembic <revision>

# Use custom app path to find alembic.ini
fak migrate-alembic --app myapp:app
```

### Dev Mode Migrations (Legacy)

```bash
# Add missing columns / recreate tables (dev only)
fak migrate User Product

# Convert old permissions format
fak migrate-permissions
```

## Existing Database Migration (Baseline)

If you have an existing database created with `create_all()`:

```bash
# Create baseline migration and stamp as applied
fak init-alembic --app myapp:app --baseline

# Or manually:
alembic revision -m "baseline_existing_schema"
# Edit the migration to match your current schema
alembic stamp head
```

## Adding Your Models to Migrations

In `alembic/env.py`, add your application's metadata:

```python
from fastapi_admin_kit.migrations.models import Base as AdminBase
from myapp.models import Base as AppBase  # Your models

target_metadata = [AdminBase.metadata, AppBase.metadata]
```

Then autogenerate will include both admin and app tables:

```bash
alembic revision --autogenerate -m "add product table"
```

## Junction Tables

The admin models include two junction tables for many-to-many relationships:
- `admin_user_roles` — User ↔ Role
- `admin_role_permissions` — Role ↔ Permission

These are automatically created via SQLAlchemy relationships and included in migrations.

## AI tables and migrations

`AdminBase.metadata` **always** includes the four `admin_ai_*` tables
(`admin_ai_usage_log`, `admin_ai_conversations`, `admin_ai_messages`,
`admin_ai_attachments`), regardless of the `ai_enabled` flag. The AI schemas
are materialized unconditionally in `migrations/models.py` and
`get_admin_metadata()` is never filtered.

This means managing the AI schema is **independent of the `ai_enabled`
flag**: if your initial Alembic revision was autogenerated (e.g. via
`fak init-alembic --auto-migrate`), the `admin_ai_*` `CREATE TABLE`
statements are already present, so enabling or disabling AI later never
requires a new migration. If your database somehow lacks them (e.g. an older
database used with `--baseline`), the next
`alembic revision --autogenerate && alembic upgrade head` adds four plain
`CREATE TABLE` statements.

In development mode (`use_alembic=False`), `Admin.setup()` also creates the
AI tables automatically whenever `ai_enabled=True`, so no migration is needed
there either.

## Troubleshooting

### "Table already exists" on initial migration

If tables were created via `create_all()` before Alembic:

```bash
# Option 1: Baseline (recommended)
fak init-alembic --baseline

# Option 2: Stamp head manually
alembic stamp head
```

### Import errors in `env.py`

Ensure your project root is in `sys.path`:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

### Async engine issues

The generated `env.py` uses `async_engine_from_config` for async migrations. For sync engines, use the sync variant in the template.

## Next Steps

- [Model Registration](../guide/model-registration.md) — Register your models with the admin
- [Authentication & RBAC](../guide/auth-rbac.md) — Set up roles and permissions
- [Existing Alembic Integration](./existing-alembic-integration.md) — Integrate with existing Alembic setup
