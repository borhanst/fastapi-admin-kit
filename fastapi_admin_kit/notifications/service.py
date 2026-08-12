"""Unified notification service.

The service abstracts the delivery channel (SMS, Email, In-App) behind a single
``notify()`` call.  It is a standalone module: import it in any FastAPI route or
service, register providers, and send.

Example::

    from fastapi_admin_kit.notifications import NotificationService

    service = NotificationService()
    service.register_sms_provider("twilio", TwilioSMSProvider(sid, token, from_num))
    service.register_sms_provider("custom", MyCustomSMSProvider(...))
    service.register_email_provider("smtp", SMTPEmailProvider(host, ...))

    await service.notify(user_id, "Your order shipped!", channels=["email", "sms"])

Features:
- Multi-channel send (e.g. Email + SMS simultaneously)
- Configurable per-notification channels
- Fallback to another channel when one fails
- Single + batch notifications
- Configurable templates
- Per-user opt-in/opt-out preferences (in-app history)
- In-app notifications persisted to the DB and pushed over WebSocket/SSE
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi_admin_kit.notifications.config import NotificationConfig
from fastapi_admin_kit.notifications.email import EmailProvider
from fastapi_admin_kit.notifications.models import (
    Notification,
    NotificationLog,
    NotificationPreference,
)
from fastapi_admin_kit.notifications.realtime import RealtimeNotificationHub
from fastapi_admin_kit.notifications.sms import SMSProvider

logger = logging.getLogger("fastapi_admin_kit.notifications")


@dataclass
class ChannelResult:
    """Result of delivering a notification over a single channel."""

    channel: str
    provider: str = ""
    success: bool = False
    message_id: str = ""
    error: str | None = None
    fallback_of: str | None = None


@dataclass
class NotificationResult:
    """Aggregate result of a ``notify()`` / ``notify_many()`` call."""

    user_id: str | int | None
    notification_id: int | None = None
    channels: list[ChannelResult] = field(default_factory=list)

    @property
    def successful(self) -> list[ChannelResult]:
        return [c for c in self.channels if c.success]

    @property
    def failed(self) -> list[ChannelResult]:
        return [c for c in self.channels if not c.success]

    @property
    def ok(self) -> bool:
        return any(c.success for c in self.channels)


class NotificationService:
    """Main entry point for sending notifications."""

    def __init__(
        self,
        config: NotificationConfig | None = None,
        session_factory: Any | None = None,
        hub: RealtimeNotificationHub | None = None,
    ) -> None:
        self.config = config or NotificationConfig()
        self.session_factory = session_factory
        self.hub = hub or RealtimeNotificationHub()
        self._sms_providers: dict[str, SMSProvider] = {}
        self._email_providers: dict[str, EmailProvider] = {}
        self._in_app = None

    # ------------------------------------------------------------------
    # Provider registration
    # ------------------------------------------------------------------

    def register_sms_provider(self, name: str, provider: SMSProvider) -> None:
        """Register an SMS provider under *name* (e.g. ``"custom"``)."""
        provider.name = getattr(provider, "name", None) or name
        self._sms_providers[name] = provider

    def register_email_provider(self, name: str, provider: EmailProvider) -> None:
        """Register an email provider under *name*."""
        provider.name = getattr(provider, "name", None) or name
        self._email_providers[name] = provider

    def register_in_app_provider(self, provider: Any) -> None:
        """Register a custom in-app delivery handler.

        The provider must implement ``async send(notification) -> dict`` where
        *notification* is the persisted :class:`Notification` row.
        """
        self._in_app = provider

    def set_default_sms_provider(self, name: str) -> None:
        self.config.default_sms_provider = name

    def set_default_email_provider(self, name: str) -> None:
        self.config.default_email_provider = name

    def sms_provider(self, name: str | None = None) -> SMSProvider:
        """Resolve an SMS provider by name (or the configured default)."""
        name = name or self.config.default_sms_provider
        provider = self._sms_providers.get(name)
        if provider is None:
            raise KeyError(
                f"SMS provider '{name}' is not registered. "
                f"Registered: {sorted(self._sms_providers)}"
            )
        return provider

    def email_provider(self, name: str | None = None) -> EmailProvider:
        """Resolve an email provider by name (or the configured default)."""
        name = name or self.config.default_email_provider
        provider = self._email_providers.get(name)
        if provider is None:
            raise KeyError(
                f"Email provider '{name}' is not registered. "
                f"Registered: {sorted(self._email_providers)}"
            )
        return provider

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    async def _preference_enabled(self, session: Any, user_id: str | int, channel: str) -> bool:
        """Return whether *channel* is opted-in for *user_id*.

        Absence of a preference row means "enabled by default".
        """
        from sqlalchemy import select

        result = await self._maybe_await(
            session.execute(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == str(user_id),
                    NotificationPreference.channel == channel,
                )
            )
        )
        pref = result.scalar_one_or_none()
        if pref is None:
            return True
        return bool(pref.enabled)

    async def set_preference(
        self, user_id: str | int, channel: str, enabled: bool, session: Any
    ) -> None:
        """Opt *user_id* in/out of *channel*."""
        from sqlalchemy import select

        result = await self._maybe_await(
            session.execute(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == str(user_id),
                    NotificationPreference.channel == channel,
                )
            )
        )
        pref = result.scalar_one_or_none()
        if pref is None:
            pref = NotificationPreference(user_id=str(user_id), channel=channel)
            session.add(pref)
        pref.enabled = enabled
        pref.updated_at = datetime.now(UTC)
        await self._commit(session)

    async def get_preferences(self, user_id: str | int, session: Any) -> dict[str, bool]:
        """Return a dict mapping channel -> enabled for *user_id*."""
        from sqlalchemy import select

        result = await self._maybe_await(
            session.execute(
                select(NotificationPreference).where(NotificationPreference.user_id == str(user_id))
            )
        )
        return {pref.channel: bool(pref.enabled) for pref in result.scalars()}

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def notify(
        self,
        user_id: str | int,
        message: str,
        channels: Sequence[str] | None = None,
        *,
        title: str | None = None,
        template: str | None = None,
        context: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        email: str | None = None,
        phone: str | None = None,
        session: Any = None,
    ) -> NotificationResult:
        """Send a notification to a single user.

        Args:
            user_id: Recipient identifier (admin user id or arbitrary key).
            message: Plain-text message body.
            channels: Channels to use (``"sms"``, ``"email"``, ``"in_app"``).
                Defaults to ``config.default_channels``.
            title: Notification title (used for email subject / in-app title).
            template: Named template to render instead of *title*/*message*.
            context: Context dict used when rendering *template*.
            data: Arbitrary structured payload attached to the notification.
            email: Recipient email address (required for the email channel).
            phone: Recipient phone number (required for the SMS channel).
            session: Async SQLAlchemy session.  When ``None`` and
                ``session_factory`` was provided, one is created per call.
        """
        channels = list(channels) if channels else list(self.config.default_channels)
        owned_session = session is None
        session = await self._get_session(session)
        user_key = str(user_id)

        rendered = {"title": title, "body": message}
        if template:
            rendered = self.config.templates.render(template, context)
            title = title or rendered["title"]
            message = rendered["body"]

        # Persist in-app record first so history is available even if a
        # channel below fails.
        notification_id: int | None = None
        if "in_app" in channels:
            notification_id = await self._persist_notification(
                session,
                user_id=user_key,
                email=email,
                title=title or "Notification",
                body=message,
                channels=list(channels),
                data=data,
            )

        results: list[ChannelResult] = []
        attempted: set[str] = set()

        for channel in channels:
            result = await self._deliver_channel(
                session,
                channel=channel,
                user_id=user_key,
                message=message,
                title=title or "Notification",
                email=email,
                phone=phone,
                notification_id=notification_id,
            )
            attempted.add(channel)
            results.append(result)

            # Fallback: if the channel failed, try configured fallback
            # channels that were not part of the original request.
            if not result.success:
                for fb in self.config.fallback_channels:
                    if fb in attempted or fb in channels:
                        continue
                    fb_result = await self._deliver_channel(
                        session,
                        channel=fb,
                        user_id=user_key,
                        message=message,
                        title=title or "Notification",
                        email=email,
                        phone=phone,
                        notification_id=notification_id,
                        fallback_of=channel,
                    )
                    attempted.add(fb)
                    results.append(fb_result)
                    if fb_result.success:
                        break

        if notification_id is not None:
            notif = await self._maybe_await(session.get(Notification, notification_id))
            if notif is not None:
                notif.status = "sent" if any(r.success for r in results) else "failed"
                await self._commit(session)

        if owned_session:
            await self._maybe_await(session.close())

        return NotificationResult(
            user_id=user_id,
            notification_id=notification_id,
            channels=results,
        )

    async def notify_many(
        self,
        recipients: Sequence[dict[str, Any]],
        message: str,
        channels: Sequence[str] | None = None,
        *,
        title: str | None = None,
        template: str | None = None,
        context: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        session: Any = None,
    ) -> list[NotificationResult]:
        """Send a notification to many recipients (batch).

        Each dict in *recipients* must contain ``user_id`` and may contain
        ``email`` and ``phone``.
        """
        results: list[NotificationResult] = []
        for recipient in recipients:
            result = await self.notify(
                recipient["user_id"],
                message,
                channels=channels,
                title=title,
                template=template,
                context=context,
                data=data,
                email=recipient.get("email"),
                phone=recipient.get("phone"),
                session=session,
            )
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_session(self, session: Any) -> Any:
        if session is not None:
            return self._adapt(session)
        if self.session_factory is not None:
            return self._adapt(self.session_factory())
        raise ValueError(
            "NotificationService requires a DB session. Pass session= or configure "
            "session_factory=."
        )

    @staticmethod
    def _adapt(session: Any) -> Any:
        """Wrap a raw SQLAlchemy session so sync + async both work via await."""
        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemySessionAdapter

        if isinstance(session, SqlAlchemySessionAdapter):
            return session
        return SqlAlchemySessionAdapter(session)

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        """Await *value* when it is awaitable (async sessions), else return it."""
        if hasattr(value, "__await__"):
            return await value
        return value

    async def _commit(self, session: Any) -> None:
        await self._maybe_await(session.commit())

    async def _persist_notification(
        self,
        session: Any,
        user_id: str,
        email: str | None,
        title: str,
        body: str,
        channels: list[str],
        data: dict[str, Any] | None,
    ) -> int:
        notif = Notification(
            user_id=user_id,
            user_email=email,
            title=title,
            body=body,
            channels=channels,
            data=data,
            status="pending",
            is_read=False,
        )
        session.add(notif)
        await self._maybe_await(session.flush())
        notif_id = int(notif.id)
        await self._push_in_app(user_id, notif)
        return notif_id

    async def _push_in_app(self, user_id: str, notif: Any) -> None:
        """Deliver a persisted notification to realtime subscribers."""
        payload = {
            "type": "notification",
            "notification": {
                "id": notif.id,
                "title": notif.title,
                "body": notif.body,
                "channels": notif.channels,
                "data": notif.data,
                "created_at": (notif.created_at.isoformat() if notif.created_at else None),
            },
        }
        if self._in_app is not None:
            try:
                await self._in_app.send(notif)
            except Exception:
                logger.exception("Custom in-app provider failed for user %s", user_id)
        await self.hub.publish(user_id, payload)

    async def _deliver_channel(
        self,
        session: Any,
        *,
        channel: str,
        user_id: str,
        message: str,
        title: str,
        email: str | None,
        phone: str | None,
        notification_id: int | None,
        fallback_of: str | None = None,
    ) -> ChannelResult:
        # Respect user opt-out preferences (skip in-app: always stored).
        if channel != "in_app":
            enabled = await self._preference_enabled(session, user_id, channel)
            if not enabled:
                return ChannelResult(
                    channel=channel,
                    provider="preferences",
                    success=False,
                    error="Opted out via channel preference.",
                    fallback_of=fallback_of,
                )

        result: ChannelResult | None = None
        if channel == "sms":
            result = await self._send_sms(user_id, phone, message)
        elif channel == "email":
            result = await self._send_email(user_id, email, title, message)
        elif channel == "in_app":
            result = ChannelResult(channel="in_app", provider="db", success=True)
        else:
            result = ChannelResult(
                channel=channel, success=False, error=f"Unknown channel '{channel}'."
            )

        await self._log_channel(
            session,
            notification_id=notification_id,
            user_id=user_id,
            channel=channel,
            provider=result.provider,
            recipient=phone if channel == "sms" else email,
            status="sent" if result.success else "failed",
            error=result.error,
        )
        if fallback_of:
            result.fallback_of = fallback_of
        return result

    async def _send_sms(self, user_id: str, phone: str | None, message: str) -> ChannelResult:
        if not phone:
            return ChannelResult(
                channel="sms",
                provider=self.config.default_sms_provider,
                success=False,
                error="No phone number provided for SMS.",
            )
        try:
            provider = self.sms_provider()
            sent = await provider.send(phone, message)
            return ChannelResult(
                channel="sms",
                provider=provider.name,
                success=True,
                message_id=sent.message_id,
            )
        except Exception as exc:
            logger.warning("SMS delivery failed for user %s: %s", user_id, exc)
            return ChannelResult(
                channel="sms",
                provider=self.config.default_sms_provider,
                success=False,
                error=str(exc),
            )

    async def _send_email(
        self, user_id: str, email: str | None, subject: str, message: str
    ) -> ChannelResult:
        if not email:
            return ChannelResult(
                channel="email",
                provider=self.config.default_email_provider,
                success=False,
                error="No email address provided.",
            )
        try:
            provider = self.email_provider()
            sent = await provider.send(email, subject=subject, text=message)
            return ChannelResult(
                channel="email",
                provider=provider.name,
                success=True,
                message_id=sent.message_id,
            )
        except Exception as exc:
            logger.warning("Email delivery failed for user %s: %s", user_id, exc)
            return ChannelResult(
                channel="email",
                provider=self.config.default_email_provider,
                success=False,
                error=str(exc),
            )

    async def _log_channel(
        self,
        session: Any,
        *,
        notification_id: int | None,
        user_id: str,
        channel: str,
        provider: str,
        recipient: str | None,
        status: str,
        error: str | None,
    ) -> None:
        try:
            session.add(
                NotificationLog(
                    notification_id=notification_id or 0,
                    user_id=user_id,
                    channel=channel,
                    provider=provider,
                    recipient=recipient,
                    status=status,
                    error=error,
                )
            )
            await self._commit(session)
        except Exception:
            logger.exception("Failed to write notification log")
