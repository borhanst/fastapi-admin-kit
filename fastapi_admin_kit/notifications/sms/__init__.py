"""SMS provider architecture for the notification system.

Providers implement the abstract :class:`SMSProvider` interface and are
registered with the :class:`NotificationService` via
``service.register_sms_provider(name, provider)``.
"""

from fastapi_admin_kit.notifications.sms.base import (
    SMSDeliveryError,
    SMSProvider,
    SMSResult,
    SMSStatus,
)
from fastapi_admin_kit.notifications.sms.twilio import TwilioSMSProvider

__all__ = [
    "SMSDeliveryError",
    "SMSProvider",
    "SMSResult",
    "SMSStatus",
    "TwilioSMSProvider",
]
