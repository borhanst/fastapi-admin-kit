"""Example usage of FastAPI Admin Kit with UnfoldAdmin features."""

import os
from contextlib import asynccontextmanager

import bcrypt
from fastapi import FastAPI
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker
from sqlalchemy.sql import func

from fastapi_admin_kit import Admin, ModelAdmin, column
from fastapi_admin_kit.actions import action
from fastapi_admin_kit.audit.models import (
    AuditLog,  # noqa: F401 — ensure table is created
)
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.models import User
from fastapi_admin_kit.config import ThemeConfig
from fastapi_admin_kit.dashboard import (
    CardComponent,
    LinkComponent,
    ProgressComponent,
    TableComponent,
)
from fastapi_admin_kit.models import Base as AdminBase
from fastapi_admin_kit.types import TabConfig, TableSection
from fastapi_admin_kit.widgets.inputs import ArrayWidget, WysiwygWidget

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
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    products = relationship("Product", back_populates="category")

    def __str__(self) -> str:
        return self.name


class Product(Base):
    """Product model with relations."""

    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    category = relationship("Category", back_populates="products")
    orders = relationship("OrderItem", back_populates="product", cascade="all, delete-orphan")

    def __str__(self) -> str:
        return self.name


class User(Base):
    """User model."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False, unique=True)
    full_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    orders = relationship("Order", back_populates="user")

    # def __str__(self) -> str:
    #     return self.email


class Order(Base):
    """Order model."""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    order_date = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(
        Enum(
            "pending",
            "processing",
            "completed",
            "cancelled",
            name="order_status",
        ),
        default="pending",
    )
    total_amount = Column(Float, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    def __str__(self) -> str:
        return f"Order #{self.id}"


class OrderItem(Base):
    """Order line items."""

    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)

    # Relationships
    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="orders")

    def __str__(self) -> str:
        return f"Item in Order #{self.order_id}"


# ============================================================================
# ModelAdmin Customizations — showcasing all UnfoldAdmin features
# ============================================================================


class CategoryAdmin(ModelAdmin):
    """Admin configuration for Category model."""

    list_display = ["id", "name", "description", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["name"]
    ordering = ["-created_at"]
    verbose_name = "Category"
    verbose_name_plural = "Categories"
    icon = "folder"
    tag = "catalog"

    # Actions
    actions_list = ["export_categories"]

    # Tabs
    list_tabs = [
        TabConfig(title="All", url="/admin/categories/"),
        TabConfig(
            title="Active",
            url="/admin/categories/?filter_created_at__gte=2025-01-01",
        ),
    ]

    @action(
        description="Export selected categories to CSV",
        icon="arrow-down-tray",
        variant="primary",
    )
    async def export_categories(self, objects, request):
        print(f"Exporting {len(objects)} categories")


class ProductAdmin(ModelAdmin):
    """Admin configuration for Product model — full UnfoldAdmin feature demo."""

    list_display = [
        "id",
        "name",
        "category",
        "formatted_price",
        "stock",
        "status",
        "created_at",
    ]
    list_filter = ["is_active", "category", "created_at", "updated_at"]
    search_fields = ["name", "description"]
    ordering = ["-created_at"]
    inline_edit = True
    inline_edit_fields = ["name", "price", "stock", "is_active", "status"]
    fields = [
        "name",
        "description",
        "category",
        "price",
        "stock",
        "is_active",
        "tags",
    ]
    readonly_fields = ["created_at", "updated_at"]
    verbose_name = "Product"
    verbose_name_plural = "Products"
    per_page = 20
    tag = "catalog"
    icon = "cube"

    # Per-model UI overrides
    list_style = "bordered"
    card_color = "#6366F1"

    # Actions — list-level, row-level, detail-level, submit-line
    actions_list = ["export_products", "deactivate_selected"]
    actions_row = ["toggle_active"]
    actions_detail = ["export_products"]
    actions_submit_line = ["save_and_continue"]

    # Tabs
    list_tabs = [
        TabConfig(title="All Products", url="/admin/products/"),
        TabConfig(title="Active", url="/admin/products/?filter_is_active=1"),
        TabConfig(title="Out of Stock", url="/admin/products/?filter_stock__lte=0"),
    ]

    # Sortable
    ordering_field = "sort_order"

    # Conditional fields — show tags only when is_active is true
    conditional_fields = {
        "tags": {"show_when": "is_active", "values": ["1", "on", "true"]},
    }

    # Form UX
    warn_unsaved_form = True
    compressed_fields = True
    change_form_show_cancel_button = True

    @column(header="Price", format="$ {:,.2f}", order="price", icon="attach_money")
    def formatted_price(self, obj):
        return obj.price

    @column(header="Status", boolean=True, icon="check_circle")
    def status(self, obj):
        return obj.is_active

    # Custom widgets
    formfield_overrides = {
        "description": WysiwygWidget(),
        "tags": ArrayWidget(),
    }

    @action(
        description="Export selected products",
        icon="arrow-down-tray",
        variant="primary",
    )
    async def export_products(self, objects, request):
        print(f"Exporting {len(objects)} products")

    @action(
        description="Deactivate selected",
        icon="x-circle",
        variant="danger",
    )
    async def deactivate_selected(self, objects, request):
        for obj in objects:
            obj.is_active = False

    @action(
        description="Toggle active status",
        icon="arrow-path",
        variant="warning",
        location="row",
    )
    async def toggle_active(self, objects, request):
        for obj in objects:
            obj.is_active = not obj.is_active

    @action(
        description="Save and continue editing",
        icon="check",
        variant="success",
        location="submit_line",
    )
    async def save_and_continue(self, objects, request):
        pass


class UserAdmin(ModelAdmin):
    """Admin configuration for User model."""

    list_display = ["id", "email", "full_name", "is_active", "created_at"]
    search_fields = ["email", "full_name"]
    list_filter = ["is_active", "created_at"]
    ordering = ["-created_at"]
    fields = ["email", "full_name", "is_active"]
    readonly_fields = ["created_at"]
    verbose_name = "User"
    verbose_name_plural = "Users"
    tag = "user"
    icon = "users"

    # Actions
    actions_list = ["deactivate_users"]
    actions_row = ["toggle_user_active"]

    # Tabs
    list_tabs = [
        TabConfig(title="All Users", url="/admin/users/"),
        TabConfig(title="Active", url="/admin/users/?filter_is_active=1"),
    ]

    # Form UX
    warn_unsaved_form = True

    @action(
        description="Deactivate selected users",
        icon="x-circle",
        variant="danger",
    )
    async def deactivate_users(self, objects, request):
        for obj in objects:
            obj.is_active = False

    @action(
        description="Toggle active",
        icon="arrow-path",
        variant="warning",
        location="row",
    )
    async def toggle_user_active(self, objects, request):
        for obj in objects:
            obj.is_active = not obj.is_active


class OrderAdmin(ModelAdmin):
    """Admin configuration for Order model."""

    list_display = ["id", "user", "order_date", "status", "total_amount"]
    list_filter = ["status", "order_date"]
    search_fields = ["user__email"]
    ordering = ["-order_date"]
    fields = ["user", "order_date", "status", "total_amount", "notes"]
    readonly_fields = ["created_at"]
    verbose_name = "Order"
    verbose_name_plural = "Orders"
    tag = "order"
    icon = "shopping-cart"

    # Per-model UI overrides
    list_style = "compact"
    form_layout = "one-column"

    # Actions
    actions_list = ["export_orders", "mark_completed"]
    actions_row = ["mark_completed_row"]
    actions_submit_line = ["save_and_email"]

    # Tabs
    list_tabs = [
        TabConfig(title="All Orders", url="/admin/orders/"),
        TabConfig(title="Pending", url="/admin/orders/?filter_status=pending"),
        TabConfig(title="Completed", url="/admin/orders/?filter_status=completed"),
    ]

    # Expandable sections
    list_sections = [
        TableSection(
            title="Order Items",
            related_model="OrderItem",
            related_field="items",
            list_display=["product", "quantity", "price"],
        ),
    ]

    # Conditional fields — show notes only for non-pending orders
    conditional_fields = {
        "notes": {"show_when": "status", "values": ["processing", "completed"]},
    }

    # Custom widgets
    formfield_overrides = {
        "notes": WysiwygWidget(),
    }

    @action(
        description="Export selected orders",
        icon="arrow-down-tray",
        variant="primary",
    )
    async def export_orders(self, objects, request):
        print(f"Exporting {len(objects)} orders")

    @action(
        description="Mark as completed",
        icon="check-circle",
        variant="success",
    )
    async def mark_completed(self, objects, request):
        for obj in objects:
            obj.status = "completed"

    @action(
        description="Mark completed",
        icon="check-circle",
        variant="success",
        location="row",
    )
    async def mark_completed_row(self, objects, request):
        for obj in objects:
            obj.status = "completed"

    @action(
        description="Save and send email",
        icon="paper-airplane",
        variant="primary",
        location="submit_line",
    )
    async def save_and_email(self, objects, request):
        pass


# ============================================================================
# Dashboard Callback — custom data injection
# ============================================================================


async def custom_dashboard_data(request, session):
    """Custom dashboard callback to inject additional data."""
    # Example: calculate total revenue
    result = await session.execute(select(func.sum(Order.total_amount)))
    total_revenue = result.scalar() or 0.0
    return {
        "total_revenue": total_revenue,
        "components": [
            CardComponent(
                title="Total Revenue",
                value=f"${total_revenue:,.2f}",
                description="All-time revenue",
            ),
            ProgressComponent(
                title="Order Completion Rate",
                value=75,
                description="75% of orders completed",
            ),
            TableComponent(
                title="Recent Orders",
                headers=["Order", "User", "Amount", "Status"],
                rows=[
                    ["#1", "alice@example.com", "$1,199.98", "Completed"],
                    ["#2", "bob@example.com", "$29.99", "Pending"],
                ],
            ),
            LinkComponent(
                title="View All Orders",
                description="Browse the full order list",
                url="/admin/orders/",
                icon="shopping-cart",
            ),
        ],
    }


# ============================================================================
# FastAPI Application Setup
# ============================================================================

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./test_debug.db")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

# Option A: Create engine manually (traditional approach)
engine = create_async_engine(DATABASE_URL, echo=False)
async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Option B: Use DatabaseConfig — pass url= (auto-normalizes to async driver)
#   from fastapi_admin_kit import DatabaseConfig
#   db_config = DatabaseConfig(url="sqlite:///./test_debug.db")  # → sqlite+aiosqlite:///...
#   engine = db_config.create_engine()
#
# Option C: Use DatabaseConfig with structured fields + DatabaseType enum
#   from fastapi_admin_kit import DatabaseConfig, DatabaseType
#   db_config = DatabaseConfig(
#       db_type=DatabaseType.POSTGRESQL,
#       host="localhost",
#       port=5432,
#       database="mydb",
#       username="user",
#       password="pass",
#   )
#   engine = db_config.create_engine()
#
# Option D: Pass database_config directly to Admin (engine created automatically)
#   admin = Admin(app=app, database_config=db_config, ...)


async def seed_demo_data(session: AsyncSession) -> None:
    """Insert demo data if tables are empty."""
    result = await session.execute(select(Category).limit(1))
    if result.scalars().first() is not None:
        return

    electronics = Category(name="Electronics", description="Gadgets and devices")
    clothing = Category(name="Clothing", description="Apparel and accessories")
    session.add_all([electronics, clothing])
    await session.flush()

    products = [
        Product(
            name="Laptop",
            description="<p>15-inch laptop with <strong>high performance</strong></p>",
            price=999.99,
            stock=50,
            category=electronics,
            is_active=True,
            sort_order=1,
        ),
        Product(
            name="Headphones",
            description="<p>Noise-cancelling wireless headphones</p>",
            price=199.99,
            stock=200,
            category=electronics,
            is_active=True,
            sort_order=2,
        ),
        Product(
            name="T-Shirt",
            description="<p>100% cotton comfortable tee</p>",
            price=29.99,
            stock=500,
            category=clothing,
            is_active=True,
            sort_order=3,
        ),
        Product(
            name="Jeans",
            description="<p>Slim fit denim jeans</p>",
            price=79.99,
            stock=150,
            category=clothing,
            is_active=False,
            sort_order=4,
        ),
    ]
    session.add_all(products)
    await session.flush()

    user1 = User(email="alice@example.com", full_name="Alice Johnson", is_active=True)
    user2 = User(email="bob@example.com", full_name="Bob Smith", is_active=True)
    session.add_all([user1, user2])
    await session.flush()

    order1 = Order(
        user=user1,
        status="completed",
        total_amount=1199.98,
        notes="<p>Gift wrap requested</p>",
    )
    order2 = Order(user=user2, status="pending", total_amount=29.99, notes="")
    session.add_all([order1, order2])
    await session.flush()

    session.add_all(
        [
            OrderItem(order=order1, product=products[0], quantity=1, price=999.99),
            OrderItem(order=order1, product=products[1], quantity=1, price=199.99),
            OrderItem(order=order2, product=products[2], quantity=1, price=29.99),
        ]
    )
    await session.commit()
    print("Seeded demo data.")


async def seed_admin_user(session: AsyncSession) -> None:
    """Create a default superadmin if none exists."""
    result = await session.execute(select(User).limit(1))
    if result.scalars().first() is not None:
        return

    hashed = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
    admin_user = User(
        email="admin@example.com",
        hashed_password=hashed,
        full_name="Admin",
        is_superuser=True,
        is_active=True,
    )
    session.add(admin_user)
    await session.commit()
    print("Created default admin user: admin@example.com / admin")


# Lifespan context manager for FastAPI startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    print("Starting FastAPI Admin Kit Example...")

    # Create all tables (user models + admin internals)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(AdminBase.metadata.create_all)
    print("Database tables ready.")

    # Seed demo data
    async with async_session_maker() as session:
        await seed_demo_data(session)
        await seed_admin_user(session)

    # Initialize admin
    await admin.setup(app)
    print("FastAPI Admin Kit initialized successfully!")

    yield

    # Shutdown
    print("Shutting down...")
    await engine.dispose()


# Create FastAPI app
app = FastAPI(
    title="FastAPI Admin Kit Example",
    description="Demonstration of FastAPI Admin Kit with UnfoldAdmin features",
    version="2.0.0",
    lifespan=lifespan,
)


from fastapi_admin_kit.nav import NavGroupConfig

# Initialize admin with full UnfoldAdmin configuration
#   Use database_config= instead of engine= to let Admin create the async engine:
#   admin = Admin(app=app, database_config=db_config, base=Base, ...)
admin = Admin(
    app=app,
    engine=engine,
    base=Base,
    title="My Admin Panel",
    logo_url=None,
    primary_color="#3b82f6",
    admin_path="/admin",
    dark_mode_default=False,
    per_page_default=25,
    secret_key=SECRET_KEY,
    auth_backend=BuiltinAuthBackend(),
    # Theme configuration
    theme=ThemeConfig(
        preset="paper",
        primary_color="#6366F1",
        show_grain_texture=False,
        show_accent_line=True,
    ),
    # UI component configuration
    sidebar_style="compact",
    table_style="striped",
    form_layout="two-column",
    form_spacing="normal",
    dashboard_grid="auto",
    dashboard_card_style="default",
    dashboard_stat_size="normal",
    topbar_style="default",
    content_width="default",
    sidebar_position="left",
    # Feature toggles
    show_history=True,
    show_view_on_site=True,
    environment_label="Development",
    environment_color="info",
    # Custom CSS injection
    custom_css="",
    # Mobile
    mobile_sidebar="overlay",
    # Navigation groups
    nav_groups=[
        NavGroupConfig(tag="order", label="ORDER MANAGEMENT", icon="shopping-cart", order=1),
        NavGroupConfig(tag="catalog", label="CATALOG", icon="folder", order=2),
        NavGroupConfig(tag="user", label="USER MANAGEMENT", icon="users", order=3),
        NavGroupConfig(tag="admin", label="ADMIN AREA", icon="shield-check", order=4),
    ],
)


# Register models with their admin classes
admin.register(Category, CategoryAdmin)
admin.register(Product, ProductAdmin)
admin.register(User, UserAdmin)
admin.register(Order, OrderAdmin)


# ============================================================================
# API Routes
# ============================================================================


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Welcome to FastAPI Admin Kit Example!",
        "docs": "/docs",
        "admin": "/admin",
        "models": ["categories", "products", "users", "orders"],
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


# ============================================================================
# Run Instructions
# ============================================================================
# To run this example:
#   pip install -e .
#   python -m uvicorn example:app --reload
#
# Then visit:
#   Admin Panel: http://localhost:8000/admin
#   Theme Settings: http://localhost:8000/admin/settings/theme
#   API Docs:   http://localhost:8000/docs
#   Health:     http://localhost:8000/health
#
# Default admin login:
#   Email:    admin@example.com
#   Password: admin
#
# UnfoldAdmin features to try:
#   - Custom actions: select products and click "Export" or "Deactivate"
#   - Row actions: click action buttons on each row
#   - Tabs: switch between All/Active/Out of Stock views
#   - Sortable: drag products by the handle icon
#   - Range filters: use From/To date pickers
#   - Conditional fields: toggle is_active to show/hide tags
#   - Wysiwyg editor: rich text editing on description fields
#   - Array widget: add/remove items on product tags
#   - Dashboard components: cards, progress bars, tables
#   - Topbar: environment badge, history link, view on site
#   - Sidebar: collapsible nav groups with icons
#   - Unsaved changes warning: try navigating away from a dirty form


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
