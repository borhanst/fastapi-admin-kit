# FastAPI Admin Kit

A drop-in admin panel for FastAPI + SQLAlchemy apps.

---

## Features

- **Zero-Config Auto-Discovery** — Register a model, get full CRUD UI automatically
- **Built-in Auth & RBAC** — Session-based auth with role-based permissions per model
- **Audit Logging** — Every create, update, and delete is recorded with full diffs
- **Modern UI** — Tailwind CSS, HTMX, and Alpine.js for a fast, responsive experience
- **Fully Customizable** — Override widgets, templates, routes, and behavior via protocols
- **Global Search / Command Palette** — Press `⌘K` / `Ctrl+K` to instantly search models and fields
- **Inline Editing** — Edit records directly from the list view with a 3-dot action menu

## Quick Example

```python
from fastapi import FastAPI
from sqlalchemy import Column, Integer, String, Float
from sqlalchemy.orm import DeclarativeBase
from fastapi_admin_kit import Admin

class Base(DeclarativeBase):
    pass

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    price = Column(Float, nullable=False)

app = FastAPI()
admin = Admin(app, prefix="/admin")
admin.register(Product)
```

That's it — you now have a full admin panel at `/admin/products/` with list, create, edit, and delete views.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Web framework | FastAPI |
| ORM | SQLAlchemy 2.x |
| Templating | Jinja2 |
| CSS | Tailwind CSS |
| Interactivity | HTMX |
| Micro-interactions | Alpine.js |
| Icons | Google Icon |

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
