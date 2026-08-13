"""Example usage of FastAPI Admin Kit with Notification System.

This example demonstrates:
- Setting up NotificationService with SMS (Twilio), Email (SMTP), In-App channels
- Registering custom SMS providers
- Using notification templates
- Mounting notification API endpoints
- Sending notifications from custom routes
- Preference management
- Admin panel integration with real-time in-app notifications

Run:
    pip install "fastapi-admin-kit[notifications]"
    python -m uvicorn example_notifications:app --reload

Then visit:
    Admin Panel: http://localhost:8000/admin
    API Docs:    http://localhost:8000/docs
    Notifications API: http://localhost:8000/api/notifications
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import bcrypt
from fastapi import FastAPI, Request
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_admin_kit import Admin, ModelAdmin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.migrations.models import User
from fastapi_admin_kit.models import Base
from fastapi_admin_kit.models import Base as AdminBase
from fastapi_admin_kit.notifications import (
    NotificationService,
    NotificationTemplate,
    SMTPEmailProvider,
    TemplateRegistry,
    TwilioSMSProvider,
    configure_notifications,
)
from fastapi_admin_kit.notifications.sms import SMSDeliveryError, SMSProvider, SMSResult, SMSStatus

# ============================================================================
# Custom SMS Provider Example (Vonage, AWS SNS, custom gateway, ...)
# ============================================================================

class MyCustomSMSProvider(SMSProvider):
    """Example custom SMS provider for any SMS gateway.

    Replace the HTTP call with your gateway's API (Vonage, AWS SNS, Plivo, etc.)
    """

    name = "custom"

    def __init__(self, api_key: str, endpoint: str = "https://api.sms-gateway.com/v1/send") -> None:
        self.api_key = api_key
        self.endpoint = endpoint

    async def send(self, to: str, message: str) -> SMSResult:
        import httpx

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"to": to, "message": message},
                )
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:
            raise SMSDeliveryError(f"Custom SMS provider failed: {exc}") from exc

        message_id = str(payload.get("id", ""))
        return SMSResult(message_id=message_id, status=SMSStatus.QUEUED, to=to, raw=payload)

    async def check_status(self, message_id: str) -> SMSStatus:
        import httpx

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    self.endpoint.replace("/send", f"/status/{message_id}"),
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                status = resp.json().get("status", "queued")
        except Exception as exc:
            raise SMSDeliveryError(f"Custom SMS status check failed: {exc}") from exc

        return SMSStatus(status) if status in SMSStatus._value2member_map_ else SMSStatus.QUEUED


# ============================================================================
# SQLAlchemy Models
# ============================================================================


class Product(Base):
    """Simple product model for demo."""

    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __str__(self) -> str:
        return self.name


# ============================================================================
# Notification Setup
# ============================================================================

def create_notification_service(session_factory) -> NotificationService:
    """Create and configure the NotificationService."""

    service = NotificationService(session_factory=session_factory)

    # --- Email Provider (SMTP) ---
    # Configure with your SMTP credentials
    email_provider = SMTPEmailProvider(
        host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
        port=int(os.getenv("SMTP_PORT", "587")),
        username=os.getenv("SMTP_USERNAME"),
        password=os.getenv("SMTP_PASSWORD"),
        from_address=os.getenv("SMTP_FROM", "notifications@example.com"),
        from_name="FastAPI Admin Kit",
        use_tls=True,
    )
    service.register_email_provider("smtp", email_provider)

    # --- SMS Provider: Twilio (built-in) ---
    # Requires `pip install "fastapi-admin-kit[notifications]"` and Twilio credentials
    twilio_provider = TwilioSMSProvider(
        account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        from_number=os.getenv("TWILIO_FROM_NUMBER", "+15017122661"),
    )
    service.register_sms_provider("twilio", twilio_provider)

    # --- SMS Provider: Custom (Vonage, AWS SNS, custom gateway, ...) ---
    # Uncomment and configure for custom provider
    # custom_provider = MyCustomSMSProvider(
    #     api_key=os.getenv("CUSTOM_SMS_API_KEY", ""),
    #     endpoint=os.getenv("CUSTOM_SMS_ENDPOINT", "https://api.sms-gateway.com/v1/send"),
    # )
    # service.register_sms_provider("custom", custom_provider)
    # service.set_default_sms_provider("custom")

    # --- Templates ---
    registry = TemplateRegistry()
    registry.register(
        NotificationTemplate(
            name="order_shipped",
            title="Order {order_id} shipped",
            body="Your order {order_id} is on the way. Track it here: {tracking_url}",
            sms_body="Order {order_id} shipped. Track: {tracking_url}",
            email_subject="Your order {order_id} has shipped!",
        )
    )
    registry.register(
        NotificationTemplate(
            name="welcome",
            title="Welcome to {app_name}!",
            body="Hi {name}, thanks for joining {app_name}. We're excited to have you!",
            email_subject="Welcome to {app_name}!",
        )
    )
    service.config.templates = registry

    return service


# ============================================================================
# Database Configuration
# ============================================================================

EXAMPLE_DIR = Path(__file__).resolve().parent
_DB_PATH = EXAMPLE_DIR / "notifications_demo.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{_DB_PATH}")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ============================================================================
# Admin Setup
# ============================================================================

class ProductAdmin(ModelAdmin):
    list_display = ["id", "name", "price", "stock", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name"]
    ordering = ["-created_at"]
    inline_edit = True
    inline_edit_fields = ["name", "price", "stock", "is_active"]
    tag = "catalog"
    icon = "cube"


async def seed_demo_data(session: AsyncSession) -> None:
    """Insert demo data if tables are empty."""
    result = await session.execute(select(Product).limit(1))
    if result.scalars().first() is not None:
        return

    products = [
        Product(name="Laptop", price=999.99, stock=50, is_active=True),
        Product(name="Headphones", price=199.99, stock=200, is_active=True),
        Product(name="T-Shirt", price=29.99, stock=500, is_active=True),
        Product(name="Jeans", price=79.99, stock=150, is_active=False),
    ]
    session.add_all(products)
    await session.commit()
    print("Seeded demo products.")


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    print("Starting FastAPI Admin Kit with Notifications...")

    # Create all tables (user models + admin internals + notification models)
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
    title="FastAPI Admin Kit — Notifications Example",
    description="Demonstration of the notification system (SMS, Email, In-App)",
    version="1.0.0",
    lifespan=lifespan,
)

# Initialize admin
admin = Admin(
    app=app,
    engine=engine,
    base=Base,
    title="Admin Panel with Notifications",
    admin_path="/admin",
    dark_mode_default=False,
    per_page_default=25,
    secret_key=SECRET_KEY,
    auth_backend=BuiltinAuthBackend(),
    show_history=True,
    show_view_on_site=True,
    environment_label="Development",
    environment_color="info",
    mobile_sidebar="overlay",
)

# --- Register notification service and mount API ---
service = create_notification_service(async_session_maker)
configure_notifications(app, service, prefix="/api/notifications")

# Register models
admin.register(Product, ProductAdmin)


# ============================================================================
# Custom API Routes using NotificationService
# ============================================================================

@app.get("/")
async def root():
    return {
        "message": "FastAPI Admin Kit with Notifications!",
        "admin": "/admin",
        "docs": "/docs",
        "notifications_api": "/api/notifications",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


# Example: Send a notification from a custom route
@app.post("/api/send-test-notification")
async def send_test_notification(request: Request, user_id: str = "1"):
    """Demo endpoint: send a test notification via multiple channels."""
    session = async_session_maker()

    # Send using template
    result = await service.notify(
        user_id=user_id,
        message="",  # body comes from template
        channels=["email", "sms", "in_app"],
        template="order_shipped",
        context={"order_id": "ORD-12345", "tracking_url": "https://track.example.com/ORD-12345"},
        email="user@example.com",  # recipient email
        phone="+15551234567",      # recipient phone (E.164)
        session=session,
    )

    return {
        "user_id": result.user_id,
        "notification_id": result.notification_id,
        "channels": [
            {
                "channel": c.channel,
                "provider": c.provider,
                "success": c.success,
                "message_id": c.message_id,
                "error": c.error,
            }
            for c in result.channels
        ],
    }


# Example: Batch send
@app.post("/api/send-batch")
async def send_batch_notification():
    """Demo endpoint: batch send to multiple recipients."""
    session = async_session_maker()

    recipients = [
        {"user_id": "1", "email": "alice@example.com", "phone": "+15550000001"},
        {"user_id": "2", "email": "bob@example.com", "phone": "+15550000002"},
        {"user_id": "3", "email": "carol@example.com", "phone": "+15550000003"},
    ]

    results = await service.notify_many(
        recipients,
        "System maintenance scheduled for midnight UTC.",
        channels=["email", "in_app"],
        session=session,
    )

    return [
        {
            "user_id": r.user_id,
            "notification_id": r.notification_id,
            "channels": [
                {
                    "channel": c.channel,
                    "success": c.success,
                    "error": c.error,
                }
                for c in r.channels
            ],
        }
        for r in results
    ]


# Example: Update user preferences
@app.put("/api/user-preferences")
async def update_user_preferences(user_id: str, channel: str, enabled: bool):
    """Opt a user in/out of a notification channel."""
    session = async_session_maker()
    await service.set_preference(user_id, channel, enabled, session=session)
    return {"channel": channel, "enabled": enabled}


# ============================================================================
# Run Instructions
# ============================================================================
# To run this example:
#   pip install -e ".[notifications]"
#   python -m uvicorn example_notifications:app --reload
#
# Then visit:
#   Admin Panel:     http://localhost:8000/admin
#   API Docs:        http://localhost:8000/docs
#   Notifications:   http://localhost:8000/api/notifications
#   Health:          http://localhost:8000/health
#
# Default admin login:
#   Email:    admin@example.com
#   Password: admin
#
# Notification API endpoints:
#   POST   /api/notifications/send           — Send notification
#   POST   /api/notifications/send/batch     — Batch send
#   GET    /api/notifications/               — List in-app notifications (auth)
#   GET    /api/notifications/unread-count   — Unread badge count (auth)
#   PUT    /api/notifications/{id}/read      — Mark as read (auth)
#   PUT    /api/notifications/preferences    — Update channel preferences (auth)
#   GET    /api/notifications/preferences    — Read preferences (auth)
#   WS     /api/notifications/ws             — Realtime WebSocket stream
#   GET    /api/notifications/stream         — SSE fallback stream (auth)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
