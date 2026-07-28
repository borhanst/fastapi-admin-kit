# FastAPI Admin Kit

A drop-in admin panel for FastAPI + SQLAlchemy + SQLModel apps.

![FastAPI Admin Kit Dashboard](assets/images/admin-dashboard.png)

---

## Features

- **Zero-Config Auto-Discovery** — Register a model, get full CRUD UI automatically
- **Built-in Auth & RBAC** — Session-based auth with role-based permissions per model
- **Audit Logging** — Every create, update, and delete is recorded with full diffs
- **Modern UI** — Tailwind CSS, HTMX, and Alpine.js for a fast, responsive experience
- **Fully Customizable** — Override widgets, templates, routes, and behavior via protocols
- **Global Search / Command Palette** — Press `⌘K` / `Ctrl+K` to instantly search models and fields
- **Inline Editing** — Edit records directly from the list view with a 3-dot action menu
- **CLI Tools** — Create superusers, manage users, run migrations
- **Async-First** — Built for async FastAPI with support for PostgreSQL, MySQL, and SQLite
- **SQLModel Support** — Works with both SQLAlchemy and SQLModel models

## Quick Example

```python
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Column, Integer, String, Float
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from fastapi_admin_kit import Admin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.mixins import AuthModelMixin


class Base(DeclarativeBase):
    pass


class User(AuthModelMixin, Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    price = Column(Float, nullable=False)


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./app.db")
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))

engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, class_=AsyncSession)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await admin.setup()
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)
admin = Admin(
    app=app,
    engine=engine,
    base=Base,
    secret_key=SECRET_KEY,
    auth_model=User,
    auth_backend=BuiltinAuthBackend(),
)
admin.register(Product)
```

That's it — you now have a full admin panel at `/admin/products/` with list, create, edit, and delete views.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Web framework | FastAPI |
| ORM | SQLAlchemy 2.x / SQLModel |
| Templating | Jinja2 |
| CSS | Tailwind CSS |
| Interactivity | HTMX |
| Micro-interactions | Alpine.js |
| Icons | Google Material Symbols |
| Auth | Session-based with bcrypt |
| Database | PostgreSQL, MySQL, SQLite (async) |

## Getting Started

| | | |
|---|---|---|
| **Installation** | **Quick Start** | **Configuration** |
| Install fastapi-admin-kit with pip | Get up and running in 5 minutes | Customize the admin to fit your needs |
| [Installation :material-arrow-right:](getting-started/installation.md) | [Quick Start :material-arrow-right:](getting-started/quickstart.md) | [Configuration :material-arrow-right:](getting-started/configuration.md) |

## How It Works

```
Developer registers a model
        │
        ▼
┌─────────────────┐
│ AUTO-DISCOVERY   │ → Inspects columns, maps types to widgets
└────────┬────────┘
         ▼
┌─────────────────┐
│ RBAC CHECK       │ → Validates permissions per request
└────────┬────────┘
         ▼
┌─────────────────┐
│ MODERN UI        │ → Renders with Tailwind + HTMX
└────────┬────────┘
         ▼
┌─────────────────┐
│ AUDIT LOG        │ → Records all changes automatically
└─────────────────┘
```
