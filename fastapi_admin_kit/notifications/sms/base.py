"""Abstract base class for SMS providers.

A provider is any object implementing :class:`SMSProvider`.  The notification
service treats providers as pluggable — Twilio ships out of the box, but users
can implement custom providers (Vonage, AWS SNS, a bespoke gateway, ...) by
subclassing this class and registering them::

    service.register_sms_provider("custom", MyCustomSMSProvider(...))
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SMSStatus(StrEnum):
    """Delivery status of an SMS message."""

    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass
class SMSResult:
    """Outcome of a :meth:`SMSProvider.send` call.

    Attributes:
        message_id: Provider-side message identifier (for status checks).
        status: Provider-reported status (defaults to ``SMSStatus.QUEUED``).
        to: Recipient phone number the message was addressed to.
        cost: Optional per-message cost reported by the provider.
        raw: Provider-specific raw response payload.
    """

    message_id: str
    status: SMSStatus = SMSStatus.QUEUED
    to: str = ""
    cost: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class SMSProvider(ABC):
    """Abstract interface every SMS provider must implement."""

    name: str = "base"

    @abstractmethod
    async def send(self, to: str, message: str) -> SMSResult:
        """Send an SMS to *to* (an E.164 phone number).

        Raises:
            SMSDeliveryError: If the provider rejects the send.
        """

    @abstractmethod
    async def check_status(self, message_id: str) -> SMSStatus:
        """Check delivery status of a previously sent message."""


class SMSDeliveryError(Exception):
    """Raised when an SMS provider fails to send or report a message."""
