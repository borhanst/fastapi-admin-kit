# FastAPI Admin Kit

[![PyPI version](https://img.shields.io/pypi/v/fastapi-admin-kit.svg)](https://pypi.org/project/fastapi-admin-kit/)
[![Python versions](https://img.shields.io/pypi/pyversions/fastapi-admin-kit.svg)](https://pypi.org/project/fastapi-admin-kit/)
[![License](https://img.shields.io/pypi/l/fastapi-admin-kit.svg)](https://github.com/borhanst/fastapi-admin-kit/blob/main/LICENSE)

A drop-in admin panel for FastAPI + SQLAlchemy apps, inspired by Django Unfold.

📖 **[Documentation](https://borhanst.github.io/fastapi-admin-kit/)** | 🚀 **[Quick Start](#quick-start)** | 📦 **[PyPI](https://pypi.org/project/fastapi-admin-kit/)**

## Features

- Zero-config auto-discovery of SQLAlchemy models
- Built-in authentication, RBAC, and audit logging
- Modern UI with Tailwind CSS, HTMX, and Alpine.js
- Fully customizable widgets, themes, and templates
- CLI for user management (`fak-admin` / `fak` — create superusers, list users, change passwords)
- Async-first with support for PostgreSQL, MySQL, and SQLite

## Installation

```bash
pip install fastapi-admin-kit
```

For database-specific async drivers:

```bash
pip install fastapi-admin-kit[postgres]  # PostgreSQL via asyncpg
pip install fastapi-admin-kit[mysql]     # MySQL via aiomysql
```

## Quick Start

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import Column, Float, Integer, String
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from fastapi_admin_kit import Admin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    price = Column(Float, nullable=False)


DATABASE_URL = "sqlite+aiosqlite:///./app.db"
SECRET_KEY = "change-me-to-a-random-secret-key-in-production"

engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, class_=AsyncSession)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)
admin = Admin(
    app=app,
    engine=engine,
    base=Base,
    secret_key=SECRET_KEY,
    auth_backend=BuiltinAuthBackend(),
)
admin.register(Product)
```

## CLI Usage

Both the full name and the short alias work interchangeably:

```bash
# Create a superuser
fak-admin createsuperuser -e admin@example.com -p mypassword
fak createsuperuser -e admin@example.com -p mypassword       # short alias

# List all admin users
fak-admin users
fak users

# Change a user's password
fak-admin changepassword -e admin@example.com -p newpassword
fak changepassword -e admin@example.com -p newpassword
```

All commands accept `-d DATABASE_URL` or read the `DATABASE_URL` environment variable.

## Configuration

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | Async database connection string | `sqlite+aiosqlite:///./app.db` |
| `SECRET_KEY` | Signing key for sessions/CSRF/JWT (min 32 chars) | Required in production |

### Admin Options

```python
admin = Admin(
    app=app,
    engine=engine,
    base=Base,
    secret_key=SECRET_KEY,
    title="My Admin",           # Admin panel title
    admin_path="/admin",        # URL prefix
    dark_mode_default=False,    # Dark mode on by default
    # Theme
    theme=ThemeConfig(preset="modern", primary_color="#6366F1"),
    # Auth
    auth_backend=BuiltinAuthBackend(),
    # Environment badge
    environment_label="Production",
    environment_color="danger",
)
```

### Database Support

- **SQLite** (default, built-in via `aiosqlite`)
- **PostgreSQL**: `pip install fastapi-admin-kit[postgres]` + set `DATABASE_URL=postgresql+asyncpg://...`
- **MySQL**: `pip install fastapi-admin-kit[mysql]` + set `DATABASE_URL=mysql+aiomysql://...`

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check fastapi_admin_kit/

# Build distribution
pip install hatch
hatch build
```

## License

MIT
