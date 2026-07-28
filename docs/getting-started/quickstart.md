# Quick Start

Get a fully functional admin panel running in 5 minutes.

## Step 1: Create Your FastAPI App

```python
# main.py
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Column, Integer, String, Float, Boolean
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from fastapi_admin_kit import Admin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.mixins import AuthModelMixin
from fastapi_admin_kit.auth.models import Role, admin_user_roles
from sqlalchemy.orm import relationship

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./app.db")
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))

engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


# User model (required for built-in auth)
class User(AuthModelMixin, Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    full_name = Column(String(255))

    roles = relationship(
        "Role", secondary=admin_user_roles, back_populates="users"
    )


# Your models
class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)


# Create tables and initialize admin
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

## Step 2: Run the Server

```bash
pip install fastapi-admin-kit[full]
uvicorn main:app --reload
```

## Step 3: Access the Admin

Open your browser and go to:

```
http://localhost:8000/admin/
```

You'll see the admin login page. On first run, a default superuser is created:

- **Email:** admin@example.com
- **Password:** admin

!!! warning
    Change the default password immediately in production!

## Step 4: Register More Models

```python
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    products = relationship("Product", back_populates="category")

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    price = Column(Float, nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"))
    category = relationship("Category", back_populates="products")

# Register all models
admin.register(Category)
admin.register(Product)
```

Now you have:

- `/admin/categories/` — CRUD for categories
- `/admin/products/` — CRUD for products with FK dropdowns

## Step 5: Customize with ModelAdmin

```python
from fastapi_admin_kit import ModelAdmin

@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = ["name", "price", "stock", "is_active"]
    search_fields = ["name"]
    list_filter = ["is_active", "category"]
    ordering = ["-id"]
    per_page = 25
```

## What You Get

| Feature | Description |
|---------|-------------|
| List view | Paginated table with search and filters |
| Create form | Auto-generated form from model columns |
| Edit form | Pre-populated form with validation |
| Delete | Confirmation dialog before deletion |
| Audit log | All changes tracked automatically |
| RBAC | Role-based permissions per model |
| Command palette | `Cmd+K` / `Ctrl+K` global search |
| Inline editing | Edit records from the list view |

## Next Steps

- [Configuration](configuration.md) — Customize the admin panel
- [Model Registration](../guide/model-registration.md) — Advanced registration options
- [Authentication & RBAC](../guide/auth-rbac.md) — Set up roles and permissions
