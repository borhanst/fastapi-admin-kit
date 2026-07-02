"""Example usage of FastAPI Console with SQLModel models.

SQLModel auto-generates __tablename__ from the class name:
  Hero → heroes, Category → categories, etc.

No need to explicitly set __tablename__ unless you want custom names.
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime

import bcrypt
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import Field, Relationship, SQLModel

from fastapi_admin_kit import Admin, ModelAdmin
from fastapi_admin_kit.actions import action

# Import audit models to register them with metadata
from fastapi_admin_kit.audit.models import AuditLog  # noqa: F401
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.models import AdminUser
from fastapi_admin_kit.config import ThemeConfig
from fastapi_admin_kit.models.base import Base as AdminBase

# ============================================================================
# SQLModel Models
# ============================================================================


class Hero(SQLModel, table=True):
    """Hero model — no __tablename__ needed, auto-generates 'heroes'."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    secret_name: str
    age: int | None = None

    def __str__(self) -> str:
        return self.name


class Team(SQLModel, table=True):
    """Team model — auto-generates 'team' table."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, unique=True)
    headquarters: str | None = None

    # One team has many heroes (FK is on Hero via team_id)
    heroes: list["HeroWithTeam"] = Relationship(back_populates="team")

    def __str__(self) -> str:
        return self.name


class HeroWithTeam(SQLModel, table=True):
    """Hero with team FK — auto-generates 'herowithteam' table."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    secret_name: str
    age: int | None = None
    team_id: int | None = Field(default=None, foreign_key="team.id")

    team: Team | None = Relationship(back_populates="heroes")

    def __str__(self) -> str:
        return self.name


class Category(SQLModel, table=True):
    """Product category — auto-generates 'category' table."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, unique=True)
    description: str | None = None
    created_at: datetime | None = Field(
        default=None, sa_column_kwargs={"server_default": "now()"}
    )

    products: list["Product"] = Relationship(back_populates="category")

    def __str__(self) -> str:
        return self.name


class Product(SQLModel, table=True):
    """Product with relations — auto-generates 'product' table."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    description: str | None = None
    price: float
    stock: int = Field(default=0)
    category_id: int | None = Field(default=None, foreign_key="category.id")
    is_active: bool = Field(default=True)
    sort_order: int = Field(default=0)
    created_at: datetime | None = Field(
        default=None, sa_column_kwargs={"server_default": "now()"}
    )
    updated_at: datetime | None = Field(
        default=None, sa_column_kwargs={"onupdate": "now()"}
    )

    category: Category | None = Relationship(back_populates="products")

    def __str__(self) -> str:
        return self.name


# ============================================================================
# ModelAdmin Customizations
# ============================================================================


class HeroAdmin(ModelAdmin):
    """Admin for Hero model."""

    list_display = ["id", "name", "secret_name", "age"]
    search_fields = ["name", "secret_name"]
    verbose_name = "Hero"
    verbose_name_plural = "Heroes"
    icon = "account_circle"
    tag = "heroes"


class TeamAdmin(ModelAdmin):
    """Admin for Team model."""

    list_display = ["id", "name", "headquarters"]
    search_fields = ["name"]
    verbose_name = "Team"
    verbose_name_plural = "Teams"
    icon = "users"
    tag = "heroes"


class CategoryAdmin(ModelAdmin):
    """Admin for Category model."""

    list_display = ["id", "name", "description", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["name"]
    ordering = ["-created_at"]
    verbose_name = "Category"
    verbose_name_plural = "Categories"
    icon = "folder"
    tag = "catalog"


class ProductAdmin(ModelAdmin):
    """Admin for Product model."""

    list_display = [
        "id",
        "name",
        "category",
        "price",
        "stock",
        "is_active",
        "created_at",
    ]
    list_filter = ["is_active", "category", "created_at"]
    search_fields = ["name", "description"]
    ordering = ["-created_at"]
    fields = [
        "name",
        "description",
        "category",
        "price",
        "stock",
        "is_active",
    ]
    readonly_fields = ["created_at", "updated_at"]
    verbose_name = "Product"
    verbose_name_plural = "Products"
    per_page = 20
    tag = "catalog"
    icon = "cube"

    @action(
        description="Export selected products",
        icon="arrow-down-tray",
        variant="primary",
    )
    async def export_products(self, objects, request):
        print(f"Exporting {len(objects)} products")


# ============================================================================
# Database Setup
# ============================================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL", "sqlite+aiosqlite:///./test_sqlmodel_debug.db"
)
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_maker = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


# ============================================================================
# FastAPI Application Setup
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    print("Starting FastAPI Console SQLModel Example...")

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await conn.run_sync(AdminBase.metadata.create_all)
    print("Database tables ready.")

    # Seed default admin user
    async with async_session_maker() as session:
        result = await session.execute(select(AdminUser).limit(1))
        if result.scalars().first() is None:
            hashed = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
            admin_user = AdminUser(
                email="admin@example.com",
                hashed_password=hashed,
                full_name="Admin",
                is_superuser=True,
                is_active=True,
            )
            session.add(admin_user)
            await session.commit()
            print("Created default admin user: admin@example.com / admin")

    # Initialize admin
    await admin.setup(app)
    print("FastAPI Console initialized successfully!")

    yield

    # Shutdown
    print("Shutting down...")
    await engine.dispose()


# Create FastAPI app
app = FastAPI(
    title="FastAPI Console SQLModel Example",
    description="Demonstration of FastAPI Console with SQLModel",
    version="2.0.0",
    lifespan=lifespan,
)

# Initialize admin
admin = Admin(
    app=app,
    engine=engine,
    title="SQLModel Admin Panel",
    logo_url=None,
    primary_color="#3b82f6",
    admin_path="/admin",
    dark_mode_default=False,
    per_page_default=25,
    secret_key=SECRET_KEY,
    auth_backend=BuiltinAuthBackend(),
    theme=ThemeConfig(
        preset="paper",
        primary_color="#6366F1",
        show_grain_texture=False,
        show_accent_line=True,
    ),
    sidebar_style="compact",
    table_style="striped",
    form_layout="two-column",
    show_history=True,
    environment_label="Development",
    environment_color="info",
)


# Register SQLModel models — no __tablename__ needed!
admin.register(Hero, HeroAdmin)
admin.register(Team, TeamAdmin)
admin.register(Category, CategoryAdmin)
admin.register(Product, ProductAdmin)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Welcome to FastAPI Console SQLModel Example!",
        "docs": "/docs",
        "admin": "/admin",
        "models": ["heroes", "team", "category", "product"],
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


# ============================================================================
# Run Instructions
# ============================================================================
# To run this example:
#   pip install -e ".[sqlmodel]"
#   python -m uvicorn example_sqlmodel:app --reload
#
# Then visit:
#   Admin Panel: http://localhost:8000/admin
#   API Docs:   http://localhost:8000/docs
#   Health:     http://localhost:8000/health
#
# Default admin login:
#   Email:    admin@example.com
#   Password: admin


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
