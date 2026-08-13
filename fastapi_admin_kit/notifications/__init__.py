"""Notification system — SMS, Email, and In-App Realtime channels.

Standalone module: can be imported and used independently of the admin panel.

Public API::

    from fastapi_admin_kit.notifications import (
        NotificationService,
        NotificationConfig,
        TemplateRegistry,
        NotificationTemplate,
        RealtimeNotificationHub,
    )
"""

from fastapi_admin_kit.notifications.config import (
    NotificationConfig,
    NotificationTemplate,
    TemplateRegistry,
)
from fastapi_admin_kit.notifications.email import (
    EmailDeliveryError,
    EmailProvider,
    EmailResult,
    SMTPEmailProvider,
)
from fastapi_admin_kit.notifications.models import (
    Notification,
    NotificationLog,
    NotificationPreference,
)
from fastapi_admin_kit.notifications.plugin import configure_notifications
from fastapi_admin_kit.notifications.realtime import RealtimeNotificationHub
from fastapi_admin_kit.notifications.router import router as notifications_router
from fastapi_admin_kit.notifications.service import (
    ChannelResult,
    NotificationResult,
    NotificationService,
)
from fastapi_admin_kit.notifications.sms import (
    SMSDeliveryError,
    SMSProvider,
    SMSResult,
    SMSStatus,
    TwilioSMSProvider,
)

__all__ = [
    "ChannelResult",
    "EmailDeliveryError",
    "EmailProvider",
    "EmailResult",
    "Notification",
    "NotificationConfig",
    "NotificationLog",
    "NotificationPreference",
    "NotificationResult",
    "NotificationService",
    "NotificationTemplate",
    "RealtimeNotificationHub",
    "SMTPEmailProvider",
    "SMSDeliveryError",
    "SMSProvider",
    "SMSResult",
    "SMSStatus",
    "TemplateRegistry",
    "TwilioSMSProvider",
    "configure_notifications",
    "notifications_router",
]
