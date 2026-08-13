"""Twilio SMS provider — first built-in implementation of :class:`SMSProvider`.

The ``twilio`` package is imported lazily so the module can be imported even
when the optional dependency is not installed.  Install it with::

    pip install "fastapi-admin-kit[notifications]"
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi_admin_kit.notifications.sms.base import (
    SMSDeliveryError,
    SMSProvider,
    SMSResult,
    SMSStatus,
)

if TYPE_CHECKING:
    from twilio.rest import Client


def _map_status(twilio_status: str) -> SMSStatus:
    """Map a Twilio message status string to :class:`SMSStatus`."""
    normalized = (twilio_status or "").lower()
    if normalized in {"delivered"}:
        return SMSStatus.DELIVERED
    if normalized in {"sent"}:
        return SMSStatus.SENT
    if normalized in {
        "failed",
        "undelivered",
        "canceled",
        "cancel-requested",
    }:
        return SMSStatus.FAILED
    return SMSStatus.QUEUED


class TwilioSMSProvider(SMSProvider):
    """Send SMS through the Twilio Messages API.

    Args:
        account_sid: Twilio account SID.
        auth_token: Twilio auth token.
        from_number: Sender number (E.164, e.g. ``"+15017122661"``).
        client: Optional pre-built ``twilio.rest.Client`` instance.  When
            ``None`` one is constructed lazily from the credentials.
    """

    name = "twilio"

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        client: Any | None = None,
    ) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self._client: Client | None = client

    def _get_client(self) -> Client:
        """Return a lazily-constructed Twilio client."""
        if self._client is not None:
            return self._client
        try:
            from twilio.rest import Client
        except ImportError as exc:  # pragma: no cover - env dependent
            raise SMSDeliveryError(
                "Twilio client is not installed. Install it with "
                "'pip install twilio' or 'pip install fastapi-admin-kit[notifications]'."
            ) from exc
        self._client = Client(self.account_sid, self.auth_token)
        return self._client

    async def send(self, to: str, message: str) -> SMSResult:
        """Send an SMS via Twilio's Messages API (offloaded to a thread)."""
        client = self._get_client()

        def _do_send() -> Any:
            return client.messages.create(
                to=to,
                from_=self.from_number,
                body=message,
            )

        try:
            msg = await _run_in_thread(_do_send)
        except Exception as exc:
            raise SMSDeliveryError(f"Twilio send failed: {exc}") from exc

        raw = {
            "sid": getattr(msg, "sid", ""),
            "status": getattr(msg, "status", ""),
            "to": getattr(msg, "to", ""),
            "error_message": getattr(msg, "error_message", None),
        }
        return SMSResult(
            message_id=raw["sid"],
            status=_map_status(raw["status"]),
            to=raw["to"],
            raw=raw,
        )

    async def check_status(self, message_id: str) -> SMSStatus:
        """Fetch and map the delivery status of a previously sent message."""
        client = self._get_client()

        def _do_fetch() -> Any:
            return client.messages(message_id).fetch()

        try:
            msg = await _run_in_thread(_do_fetch)
        except Exception as exc:
            raise SMSDeliveryError(f"Twilio status check failed: {exc}") from exc

        return _map_status(getattr(msg, "status", ""))


async def _run_in_thread(func):
    """Run a blocking call in the default executor."""
    import asyncio

    return await asyncio.to_thread(func)
