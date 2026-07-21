"""Example usage of FastAPI Admin Kit with AI Agent Integration.

Demonstrates:
  - Enabling the AI agent system with AIConfig
  - Configuring multiple AI agents (default + specialist)
  - Creating custom tools with the @tool decorator
  - Using built-in tools (query_database, create_record, etc.)
  - Accessing the AI chat UI and dashboard

Run:
  pip install -e ".[ai]"
  python example_ai.py

Then visit:
  Admin Panel:  http://localhost:8000/admin
  AI Chat:      http://localhost:8000/admin/ai/chat
  AI Dashboard: http://localhost:8000/admin/ai/dashboard
  API Docs:     http://localhost:8000/docs

Default admin login:
  Email:    admin@example.com
  Password: admin
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import bcrypt
from fastapi import FastAPI
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.sql import func

from fastapi_admin_kit import Admin, ModelAdmin
from fastapi_admin_kit.ai import AIAgentConfig, AIConfig, tool
from fastapi_admin_kit.ai.usage import AIUsageLog  # noqa: F401
from fastapi_admin_kit.audit.models import AuditLog  # noqa: F401
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.models import User  # noqa: F401
from fastapi_admin_kit.config import ThemeConfig
from fastapi_admin_kit.models import Base as AdminBase
from fastapi_admin_kit.nav import NavGroupConfig
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# SQLAlchemy Models
# ============================================================================


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __str__(self) -> str:
        return self.name


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    tier = Column(String(20), default="standard")
    total_spent = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __str__(self) -> str:
        return self.name


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True)
    subject = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    status = Column(String(20), default="open")
    priority = Column(String(10), default="medium")
    customer_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __str__(self) -> str:
        return f"#{self.id} {self.subject}"


# ============================================================================
# ModelAdmin
# ============================================================================


class ProductAdmin(ModelAdmin):
    list_display = ["id", "name", "price", "stock", "is_active"]
    search_fields = ["name"]
    list_filter = ["is_active", "created_at"]
    ordering = ["-created_at"]
    verbose_name = "Product"
    verbose_name_plural = "Products"
    tag = "catalog"
    icon = "cube"


class CustomerAdmin(ModelAdmin):
    list_display = [
        "id", "name", "email", "tier", "total_spent", "is_active",
    ]
    search_fields = ["name", "email"]
    list_filter = ["tier", "is_active"]
    ordering = ["-created_at"]
    verbose_name = "Customer"
    verbose_name_plural = "Customers"
    tag = "crm"
    icon = "group"


class TicketAdmin(ModelAdmin):
    list_display = ["id", "subject", "status", "priority", "created_at"]
    search_fields = ["subject"]
    list_filter = ["status", "priority"]
    ordering = ["-created_at"]
    verbose_name = "Ticket"
    verbose_name_plural = "Tickets"
    tag = "support"
    icon = "support_agent"


# ============================================================================
# Custom AI Tools
# ============================================================================


@tool(
    name="search_products",
    description="Search products by name or description.",
    category="ecommerce",
)
async def search_products(
    ctx: Any, query: str, limit: int = 10
) -> dict:
    """Search products across name and description fields."""
    session = ctx.deps.session
    stmt = (
        select(Product)
        .where(
            Product.name.ilike(f"%{query}%")
            | Product.description.ilike(f"%{query}%")
        )
        .limit(limit)
    )

    result = await session.execute(stmt)
    products = result.scalars().all()

    return {
        "count": len(products),
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "price": p.price,
                "stock": p.stock,
                "is_active": p.is_active,
            }
            for p in products
        ],
    }


@tool(
    name="get_customer_summary",
    description="Get customer data summary.",
    category="crm",
)
async def get_customer_summary(
    ctx: Any, customer_id: int | None = None
) -> dict:
    """Get customer summary or aggregate stats."""
    session = ctx.deps.session

    if customer_id:
        result = await session.execute(
            select(Customer).where(Customer.id == customer_id)
        )
        customer = result.scalars().first()
        if not customer:
            return {"error": f"Customer {customer_id} not found"}
        return {
            "id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "tier": customer.tier,
            "total_spent": customer.total_spent,
        }

    result = await session.execute(select(Customer))
    customers = result.scalars().all()

    tiers: dict[str, int] = {}
    for c in customers:
        tiers.setdefault(c.tier, 0)
        tiers[c.tier] += 1

    return {
        "total_customers": len(customers),
        "by_tier": tiers,
        "total_revenue": sum(c.total_spent for c in customers),
    }


@tool(
    name="get_support_stats",
    description="Get support ticket statistics.",
    category="support",
)
async def get_support_stats(ctx: Any) -> dict:
    """Aggregate support ticket statistics."""
    session = ctx.deps.session
    result = await session.execute(select(Ticket))
    tickets = result.scalars().all()

    by_status: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    for t in tickets:
        by_status.setdefault(t.status, 0)
        by_status[t.status] += 1
        by_priority.setdefault(t.priority, 0)
        by_priority[t.priority] += 1

    total = len(tickets)
    resolved = by_status.get("resolved", 0)
    rate = f"{(resolved / total * 100):.1f}%" if total else "N/A"

    return {
        "total_tickets": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "resolution_rate": rate,
    }


@tool(
    name="update_ticket_status",
    description="Update a support ticket status.",
    category="support",
)
async def update_ticket_status(
    ctx: Any, ticket_id: int, status: str
) -> dict:
    """Update a ticket's status field."""
    valid = {"open", "in_progress", "resolved"}
    if status not in valid:
        return {"error": f"Invalid status. Must be one of: {valid}"}

    session = ctx.deps.session
    result = await session.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = result.scalars().first()
    if not ticket:
        return {"error": f"Ticket {ticket_id} not found"}

    old_status = ticket.status
    ticket.status = status
    await session.flush()

    return {
        "ticket_id": ticket_id,
        "old_status": old_status,
        "new_status": status,
    }


# ============================================================================
# AI Configuration
#
# Supported model strings:
#   Groq:      "groq:llama-3.3-70b-versatile", "groq:llama-3.1-8b-instant"
#   Google:    "google:gemini-2.0-flash", "google:gemini-1.5-pro"
#   OpenAI:    "openai:gpt-4o-mini", "openai:gpt-4o"
#   Anthropic: "anthropic:claude-3-5-sonnet-latest"
# ============================================================================

ai_config = AIConfig(
    agents=[
        AIAgentConfig(
            name="default",
            model="groq:llama-3.3-70b-versatile",
            api_key=os.environ.get("GROQ_API_KEY"),
            system_prompt=(
                "You are a helpful admin assistant. You can query the "
                "database, search products, manage customers, and handle "
                "support tickets. Always be concise and accurate."
            ),
            cost_per_1k_input_tokens=0.00059,
            cost_per_1k_output_tokens=0.00079,
        ),
    ],
    default_agent="default",
    dashboard_enabled=True,
    log_retention_days=30,
)


# ============================================================================
# Database Setup
# ============================================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL", "sqlite+aiosqlite:///./example_ai.db"
)
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production-at-least-32chars")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_maker = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def seed_data(session: AsyncSession) -> None:
    """Insert sample data if tables are empty."""
    result = await session.execute(select(Product).limit(1))
    if result.scalars().first() is not None:
        return

    products = [
        Product(
            name="Laptop Pro 16",
            description="High-performance laptop",
            price=1999.99, stock=25, is_active=True,
        ),
        Product(
            name="Wireless Mouse",
            description="Ergonomic wireless mouse",
            price=49.99, stock=200, is_active=True,
        ),
        Product(
            name="USB-C Hub",
            description="7-in-1 USB-C hub",
            price=79.99, stock=150, is_active=True,
        ),
        Product(
            name='Monitor 27"',
            description="4K IPS monitor",
            price=599.99, stock=30, is_active=True,
        ),
        Product(
            name="Keyboard Mech",
            description="Mechanical keyboard RGB",
            price=129.99, stock=0, is_active=False,
        ),
    ]
    session.add_all(products)

    customers = [
        Customer(
            name="Alice Johnson",
            email="alice@example.com",
            tier="vip",
            total_spent=4500.00,
        ),
        Customer(
            name="Bob Smith",
            email="bob@example.com",
            tier="premium",
            total_spent=1200.00,
        ),
        Customer(
            name="Carol White",
            email="carol@example.com",
            tier="standard",
            total_spent=350.00,
        ),
        Customer(
            name="Dave Brown",
            email="dave@example.com",
            tier="premium",
            total_spent=2100.00,
        ),
    ]
    session.add_all(customers)

    tickets = [
        Ticket(
            subject="Order not received",
            body="Order #1234 hasn't arrived",
            status="open", priority="high", customer_id=1,
        ),
        Ticket(
            subject="Defective product",
            body="Mouse scroll not working",
            status="in_progress", priority="medium", customer_id=2,
        ),
        Ticket(
            subject="Billing question",
            body="Charged twice for order",
            status="open", priority="urgent", customer_id=3,
        ),
        Ticket(
            subject="Feature request",
            body="Dark mode support",
            status="resolved", priority="low", customer_id=4,
        ),
    ]
    session.add_all(tickets)

    await session.commit()
    print("Seeded AI example data.")


async def seed_admin(session: AsyncSession) -> None:
    """Create default admin user."""
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
    print("Created admin: admin@example.com / admin")


# ============================================================================
# FastAPI App
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting AI Example...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(AdminBase.metadata.create_all)

    async with async_session_maker() as session:
        await seed_data(session)
        await seed_admin(session)

    await admin.setup(app)
    print("Ready! Visit http://localhost:8000/admin")
    print("AI Chat: http://localhost:8000/admin/ai/chat")

    yield

    await engine.dispose()


app = FastAPI(
    title="FastAPI Admin Kit - AI Example",
    description="AI agent integration with custom tools",
    version="1.0.0",
    lifespan=lifespan,
)

admin = Admin(
    app=app,
    engine=engine,
    base=Base,
    title="AI Admin Panel",
    admin_path="/admin",
    secret_key=SECRET_KEY,
    auth_backend=BuiltinAuthBackend(),
    # AI
    ai_enabled=True,
    ai=ai_config,
    # Theme
    theme=ThemeConfig(preset="paper", primary_color="#6366F1"),
    # Navigation
    nav_groups=[
        NavGroupConfig(
            tag="catalog", label="CATALOG",
            icon="inventory_2", order=1,
        ),
        NavGroupConfig(
            tag="crm", label="CRM",
            icon="group", order=2,
        ),
        NavGroupConfig(
            tag="support", label="SUPPORT",
            icon="support_agent", order=3,
        ),
    ],
)

admin.register(Product, ProductAdmin)
admin.register(Customer, CustomerAdmin)
admin.register(Ticket, TicketAdmin)


@app.get("/")
async def root():
    return {
        "message": "AI Example - visit /admin",
        "ai_chat": "/admin/ai/chat",
        "ai_dashboard": "/admin/ai/dashboard",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
