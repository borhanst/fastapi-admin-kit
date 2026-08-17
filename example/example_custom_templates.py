"""Example usage of FastAPI Admin Kit with custom Jinja2 template dirs.

Custom template dirs let you override any of the admin's built-in templates
with your own files. The directory is *prepended* to the template loader, so
your templates take priority over the built-ins.

Configuration:
    admin = Admin(
        app=app,
        engine=engine,
        secret_key=SECRET_KEY,
        config=AdminConfig(template_dirs=["custom_templates"]),
    )

Template resolution order (first match wins):
    1. Explicit per-model template (e.g. admin.list_template)
    2. Per-model override:  admin/<table>/list.html
    3. Global override:     admin/list.html
    4. Built-in default:    pages/list.html

The directory in this example (example/custom_templates/) provides:
    - admin/list.html            -> global list-view header override
    - admin/products/list.html   -> per-model override for the Product admin

Create your files, run the app, then visit the admin list pages to see the
custom headers rendered in place of the built-ins.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import bcrypt
from fastapi import FastAPI
from sqlalchemy import Column, Float, ForeignKey, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

from fastapi_admin_kit import Admin, ModelAdmin
from fastapi_admin_kit.admin.admin_config import AdminConfig
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.models import User
from fastapi_admin_kit.models import Base as AdminBase

# ============================================================================
# SQLAlchemy Models
# ============================================================================


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Category(Base):
    """Product category model."""

    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)

    products = relationship("Product", back_populates="category")

    def __str__(self) -> str:
        return self.name


class Product(Base):
    """Product model."""

    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)

    category = relationship("Category", back_populates="products")

    def __str__(self) -> str:
        return self.name


# ============================================================================
# ModelAdmin Classes
# ============================================================================


class CategoryAdmin(ModelAdmin):
    """Admin for Category — uses the global admin/list.html override."""

    list_display = ["id", "name"]
    search_fields = ["name"]
    verbose_name = "Category"
    verbose_name_plural = "Categories"
    icon = "folder"
    tag = "catalog"


class ProductAdmin(ModelAdmin):
    """Admin for Product — uses the per-model admin/products/list.html override."""

    list_display = ["id", "name", "category", "price", "stock"]
    search_fields = ["name"]
    list_filter = ["category"]
    verbose_name = "Product"
    verbose_name_plural = "Products"
    icon = "cube"
    tag = "catalog"


# ============================================================================
# Database Setup
# ============================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./test_custom_templates.db")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def seed_demo_data(session: AsyncSession) -> None:
    """Insert demo data if tables are empty."""
    result = await session.execute(select(Category).limit(1))
    if result.scalars().first() is not None:
        return

    electronics = Category(name="Electronics")
    session.add(electronics)
    await session.flush()

    session.add_all(
        [
            Product(name="Laptop", price=999.99, stock=50, category=electronics),
            Product(name="Headphones", price=199.99, stock=200, category=electronics),
        ]
    )
    await session.commit()
    print("Seeded demo data.")


# ============================================================================
# FastAPI Application Setup
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    print("Starting FastAPI Admin Kit Custom Templates Example...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(AdminBase.metadata.create_all)

    async with async_session_maker() as session:
        await seed_demo_data(session)
        result = await session.execute(select(User).limit(1))
        if result.scalars().first() is None:
            hashed = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
            session.add(
                User(
                    email="admin@example.com",
                    hashed_password=hashed,
                    full_name="Admin",
                    is_superuser=True,
                    is_active=True,
                )
            )
            await session.commit()
            print("Created default admin user: admin@example.com / admin")

    await admin.setup(app)
    print("FastAPI Admin Kit initialized successfully!")

    yield

    await engine.dispose()


app = FastAPI(
    title="FastAPI Admin Kit Custom Templates Example",
    description="Demonstration of overriding admin templates via custom template dirs",
    version="1.0.0",
    lifespan=lifespan,
)

# A bare folder name like "custom_templates" is resolved relative to the
# process CWD and will NOT be found unless the server is started from the
# folder's parent directory. Always pass the ACTUAL path — derive an absolute
# one from this file's location so it works regardless of the launch directory:
TEMPLATE_DIR = str(Path(__file__).resolve().parent / "custom_templates")

admin = Admin(
    app=app,
    engine=engine,
    base=Base,
    secret_key=SECRET_KEY,
    auth_backend=BuiltinAuthBackend(),
    config=AdminConfig(template_dirs=[TEMPLATE_DIR]),
)

admin.register(Category, CategoryAdmin)
admin.register(Product, ProductAdmin)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Welcome to FastAPI Admin Kit Custom Templates Example!",
        "admin": "/admin",
        "models": ["categories", "products"],
    }


# ============================================================================
# Run Instructions
# ============================================================================
# To run this example:
#   pip install -e ..
#   python -m uvicorn example_custom_templates:app --reload
#
# (The custom template dir uses an absolute path based on this file, so it
# works no matter which directory you launch uvicorn from.)
#
# Then visit:
#   Admin Panel: http://localhost:8000/admin
#
#   Categories list: http://localhost:8000/admin/categories/
#     -> uses example/custom_templates/admin/list.html (global override)
#
#   Products list:   http://localhost:8000/admin/products/
#     -> uses example/custom_templates/admin/products/list.html (per-model)
#
# Default admin login:
#   Email:    admin@example.com
#   Password: admin
#
# To add more overrides, mirror the built-in template structure under
# example/custom_templates/ (e.g. admin/form.html, admin/detail.html, ...).


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
