# Quick Start

Get a fully functional admin panel running in 5 minutes.

## Step 1: Create Your FastAPI App

```python
# main.py
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from fastapi_admin_kit import Admin

# Database setup
engine = create_engine("sqlite:///example.db")

class Base(DeclarativeBase):
    pass

# Your models
from sqlalchemy import Column, Integer, String, Float, Boolean

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)

# Create tables
Base.metadata.create_all(engine)

# FastAPI app
app = FastAPI()

# Initialize admin
admin = Admin(
    app=app,
    engine=engine,
    secret_key="your-secret-key-change-in-production",
)
admin.register(Product)
```

## Step 2: Run the Server

```bash
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

## Next Steps

- [Configuration](configuration.md) — Customize the admin panel
- [Model Registration](../guide/model-registration.md) — Advanced registration options
- [Authentication & RBAC](../guide/auth-rbac.md) — Set up roles and permissions
