# Notifications (SMS, Email, In-App Realtime)

The notification system is a **standalone module** — import it in any FastAPI
route or service, no admin panel required.

It supports three channels:

- **SMS** — Twilio built-in, plus an extensible provider interface
- **Email** — SMTP built-in (stdlib `smtplib`)
- **In-App Realtime** — notifications stored in the DB and pushed to connected
  clients over WebSocket (with an SSE fallback)

## Installation

```bash
pip install "fastapi-admin-kit[notifications]"   # adds Twilio
```

The module itself has no hard third-party dependencies — Twilio is optional and
imported lazily.

## Quick start

```python
from fastapi_admin_kit.notifications import (
    NotificationService,
    SMTPEmailProvider,
    TwilioSMSProvider,
    configure_notifications,
)

service = NotificationService()

# SMS — Twilio out of the box
service.register_sms_provider(
    "twilio",
    TwilioSMSProvider(
        account_sid="AC...",
        auth_token="...",
        from_number="+15017122661",
    ),
)

# Email — SMTP out of the box
service.register_email_provider(
    "smtp",
    SMTPEmailProvider(
        host="smtp.gmail.com",
        port=587,
        username="you@example.com",
        password="app-password",
        from_address="you@example.com",
    ),
)

# Mount the API endpoints
configure_notifications(app, service, prefix="/api/notifications")
```

Then send a notification:

```python
await service.notify(
    user_id="1234",
    message="Your order has shipped!",
    channels=["sms", "email"],
    email="user@example.com",
    phone="+15551234567",
)
```

`notify()` sends on all requested channels simultaneously and applies a
**fallback** to the configured `fallback_channels` when a channel fails.

## Custom SMS providers

Extend `SMSProvider` and register it:

```python
from fastapi_admin_kit.notifications import SMSProvider, SMSResult, SMSStatus


class MyCustomSMSProvider(SMSProvider):
    name = "custom"

    async def send(self, to: str, message: str) -> SMSResult:
        # Call any SMS API (Vonage, AWS SNS, custom gateway, ...)
        return SMSResult(message_id="msg-1", status=SMSStatus.QUEUED, to=to)

    async def check_status(self, message_id: str) -> SMSStatus:
        return SMSStatus.DELIVERED


service.register_sms_provider("custom", MyCustomSMSProvider())
service.set_default_sms_provider("custom")
```

A ready-to-copy example lives in
`fastapi_admin_kit/notifications/sms/custom/example.py`.

## In-App realtime

Include the `"in_app"` channel to store the notification in the DB and push it
to connected clients instantly.

```python
await service.notify(
    user_id="1234",
    message="Someone commented on your post.",
    channels=["in_app"],
    title="New comment",
    data={"post_id": 42},
)
```

Clients connect via:

- **WebSocket**: `WS /api/notifications/ws?user_id=1234` (or with a JWT
  `?token=...`)
- **SSE fallback**: `GET /api/notifications/stream` (authenticated)

The hub handles connection drops during publish and supports heartbeat /
stale-connection pruning. Fallback to polling: `GET /api/notifications` lists
in-app history; `GET /api/notifications/unread-count` returns the badge count.
Pushed messages are JSON with a `type` field: `{"type": "notification", ...}`
for new notifications and `{"type": "read", "notification_id": ...}` when a
notification is marked read (so all open tabs stay in sync).

## Templates

Named templates render `{placeholder}` values from context:

```python
from fastapi_admin_kit.notifications import NotificationTemplate, TemplateRegistry

registry = TemplateRegistry()
registry.register(
    NotificationTemplate(
        name="order_shipped",
        title="Order {order_id} shipped",
        body="Your order {order_id} is on the way.",
    )
)
service.config.templates = registry

await service.notify(
    user_id="1234",
    message="",                       # body comes from the template
    channels=["email"],
    template="order_shipped",
    context={"order_id": "ABC-123"},
    email="user@example.com",
)
```

## Preferences (opt-in / opt-out)

Per-user channel preferences are stored in the DB. Opting out blocks delivery:

```python
await service.set_preference(user_id="1234", channel="sms", enabled=False, session=session)
prefs = await service.get_preferences(user_id="1234", session=session)
```

The API exposes `PUT /notifications/preferences` and
`GET /notifications/preferences` for the authenticated user.

## Batch sending

```python
await service.notify_many(
    [
        {"user_id": "1", "email": "a@example.com", "phone": "+15550000001"},
        {"user_id": "2", "email": "b@example.com", "phone": "+15550000002"},
    ],
    "System maintenance at midnight.",
    channels=["email"],
)
```

## API endpoints

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/notifications/send` | Send a notification |
| `POST` | `/notifications/send/batch` | Batch send |
| `GET` | `/notifications/` | List in-app notifications (auth) |
| `GET` | `/notifications/unread-count` | Unread badge count (auth) |
| `PUT` | `/notifications/{id}/read` | Mark as read (auth) |
| `PUT` | `/notifications/preferences` | Update channel preferences (auth) |
| `GET` | `/notifications/preferences` | Read channel preferences (auth) |
| `WS` | `/notifications/ws` | Realtime WebSocket stream |
| `GET` | `/notifications/stream` | SSE fallback stream (auth) |

## History / logs

Every per-channel delivery attempt is written to
`admin_notification_logs`. In-app notifications (title, body, channels, data,
read/unread) are persisted in `admin_notifications`, so the module doubles as
a notification history store.

## Configuration

`NotificationConfig` controls defaults:

```python
from fastapi_admin_kit.notifications import NotificationConfig, NotificationService

service = NotificationService(
    config=NotificationConfig(
        default_channels=["sms", "email"],
        fallback_channels=["sms", "email"],
        default_sms_provider="twilio",
        default_email_provider="smtp",
    )
)
```
