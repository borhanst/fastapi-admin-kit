# Alembic Setup

FastAPI Admin Kit does not bundle Alembic. This guide shows how to set up Alembic in your project to manage database migrations for both your models and the admin tables.

## Install Alembic

```bash
pip install alembic
```

## Initialize Alembic

```bash
alembic init alembic
```

## Configure `alembic.ini`

Set the database URL:

```ini
[alembic]
script_location = alembic
sqlalchemy.url = sqlite+aiosqlite:///./your_database.db
```

For PostgreSQL:

```ini
sqlalchemy.url = postgresql+asyncpg://user:password@localhost:5432/your_database
```

## Configure `alembic/env.py`

Replace the contents of `alembic/env.py`:

```python
import asyncio
import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import Base as UserBase
from fastapi_admin_kit.models.base import Base as AdminBase

target_metadata = UserBase.metadata
for table in AdminBase.metadata.tables.values():
    if table.name not in target_metadata.tables:
        target_metadata._add_table(table.name, table.schema, table)

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

Adjust the import to match your project:

```python
# If models are in app/models.py
from app.models import Base as UserBase

# If models are in src/models/__init__.py
from src.models import Base as UserBase
```

## Generate Initial Migration

```bash
alembic revision --autogenerate -m "initial schema"
```

## Apply Migration

```bash
alembic upgrade head
```

## Sync Engine

For synchronous engines, replace `run_migrations_online`:

```python
from sqlalchemy import engine_from_config

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
```

## Existing Tables

If tables were created with `create_all()` before Alembic:

```bash
alembic stamp head
```

## Verify Admin Tables

```python
from fastapi_admin_kit.models.base import Base as AdminBase
print(list(AdminBase.metadata.tables.keys()))
```

## Next Steps

- [Model Registration](model-registration.md)
- [Authentication & RBAC](auth-rbac.md)
