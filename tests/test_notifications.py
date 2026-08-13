"""Tests for the notification system (SMS, Email, In-App realtime)."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from fastapi_admin_kit.models import Base as AdminBase
from fastapi_admin_kit.notifications import (
    Notification,
    NotificationResult,
    NotificationService,
    NotificationTemplate,
    RealtimeNotificationHub,
    SMSProvider,
    SMSResult,
    SMSStatus,
    SMTPEmailProvider,
    TemplateRegistry,
    TwilioSMSProvider,
)
from fastapi_admin_kit.notifications.email import EmailDeliveryError, EmailResult
from fastapi_admin_kit.notifications.models import NotificationLog
from fastapi_admin_kit.notifications.sms import SMSDeliveryError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    AdminBase.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def sync_session_factory(engine):
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(engine)


class FakeSMSProvider(SMSProvider):
    """In-memory SMS provider for tests."""

    name = "fake"

    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.fail_next = False

    async def send(self, to: str, message: str) -> SMSResult:
        if self.fail_next:
            self.fail_next = False
            raise SMSDeliveryError("provider down")
        self.sent.append((to, message))
        return SMSResult(message_id=f"sms-{len(self.sent)}", status=SMSStatus.QUEUED, to=to)

    async def check_status(self, message_id: str) -> SMSStatus:
        return SMSStatus.DELIVERED


class FailingSMSProvider(SMSProvider):
    """SMS provider that always fails."""

    name = "failing"

    async def send(self, to: str, message: str) -> SMSResult:
        raise SMSDeliveryError("always fails")

    async def check_status(self, message_id: str) -> SMSStatus:
        return SMSStatus.FAILED


class FakeEmailProvider:
    """In-memory email provider for tests."""

    name = "fake_email"

    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, to, subject, html=None, text=None, cc=None, bcc=None):
        self.sent.append({"to": to, "subject": subject, "html": html, "text": text})
        return EmailResult(message_id=f"email-{len(self.sent)}", status="sent", to=to)


class FailingEmailProvider:
    name = "failing_email"

    async def send(self, to, subject, html=None, text=None, cc=None, bcc=None):
        raise EmailDeliveryError("smtp down")


@pytest.fixture
def service(sync_session_factory):
    svc = NotificationService(session_factory=sync_session_factory)
    svc.register_sms_provider("twilio", FakeSMSProvider())
    svc.register_email_provider("smtp", FakeEmailProvider())
    return svc


def _commit_sync(session):
    session.commit()


# ---------------------------------------------------------------------------
# SMS provider architecture
# ---------------------------------------------------------------------------


def test_sms_provider_abstract():
    """SMSProvider is abstract — cannot be instantiated directly."""
    with pytest.raises(TypeError):
        SMSProvider()  # type: ignore[abstract]


def test_custom_sms_provider_send(session):
    provider = FakeSMSProvider()
    result = asyncio.run(provider.send("+15551234567", "hello"))
    assert result.message_id.startswith("sms-")
    assert result.status == SMSStatus.QUEUED
    assert provider.sent == [("+15551234567", "hello")]


def test_custom_sms_provider_check_status():
    provider = FakeSMSProvider()
    status = asyncio.run(provider.check_status("sms-1"))
    assert status == SMSStatus.DELIVERED


def test_twilio_provider_requires_client_or_creds():
    provider = TwilioSMSProvider("sid", "token", "+15017122661")
    with pytest.raises(SMSDeliveryError):
        asyncio.run(provider.send("+15551234567", "hi"))


def test_twilio_provider_with_fake_client():
    class FakeMsg:
        sid = "SM123"
        status = "sent"
        to = "+15551234567"
        error_message = None

    class FakeMessages:
        def create(self, **kwargs):
            return FakeMsg()

    class FakeClient:
        messages = FakeMessages()

    provider = TwilioSMSProvider("sid", "token", "+15017122661", client=FakeClient())
    result = asyncio.run(provider.send("+15551234567", "hi"))
    assert result.message_id == "SM123"
    assert result.status == SMSStatus.SENT


def test_register_sms_provider(service):
    """Providers can be registered under a custom name."""
    service.register_sms_provider("custom", FakeSMSProvider())
    assert service.sms_provider("custom").name == "fake"


def test_sms_provider_missing_raises(service):
    with pytest.raises(KeyError):
        service.sms_provider("nope")


# ---------------------------------------------------------------------------
# Email provider
# ---------------------------------------------------------------------------


def test_smtp_email_provider_requires_content():
    provider = SMTPEmailProvider("smtp.example.com")
    with pytest.raises(EmailDeliveryError):
        asyncio.run(provider.send("a@b.com", "subject"))


def test_register_email_provider(service):
    provider = FakeEmailProvider()
    service.register_email_provider("custom_email", provider)
    assert service.email_provider("custom_email").name == "fake_email"


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def test_template_rendering():
    registry = TemplateRegistry()
    registry.register(
        NotificationTemplate(
            name="order_shipped",
            title="Order {order_id} shipped",
            body="Your order {order_id} is on the way.",
            email_subject="Order {order_id} shipped",
        )
    )
    rendered = registry.render("order_shipped", {"order_id": "1234"})
    assert rendered["title"] == "Order 1234 shipped"
    assert rendered["body"] == "Your order 1234 is on the way."
    assert rendered["email_subject"] == "Order 1234 shipped"


def test_template_missing_raises():
    registry = TemplateRegistry()
    with pytest.raises(KeyError):
        registry.render("missing", {})


# ---------------------------------------------------------------------------
# Service — single send
# ---------------------------------------------------------------------------


def test_notify_email_and_sms(service, session):
    sms = service.sms_provider()
    email = service.email_provider()

    result = asyncio.run(
        service.notify(
            "user-1",
            "Hello from the kit!",
            channels=["email", "sms"],
            email="user@example.com",
            phone="+15551234567",
            session=session,
        )
    )
    assert isinstance(result, NotificationResult)
    assert result.ok
    assert len(result.successful) == 2
    assert email.sent[0]["to"] == "user@example.com"
    assert sms.sent[0] == ("+15551234567", "Hello from the kit!")


def test_notify_missing_phone(service, session):
    result = asyncio.run(
        service.notify(
            "user-1",
            "no phone",
            channels=["sms"],
            session=session,
        )
    )
    assert not result.ok
    assert result.failed[0].error == "No phone number provided for SMS."


def test_notify_missing_email(service, session):
    result = asyncio.run(
        service.notify(
            "user-1",
            "no email",
            channels=["email"],
            session=session,
        )
    )
    assert not result.ok
    assert result.failed[0].error == "No email address provided."


def test_notify_unknown_channel(service, session):
    result = asyncio.run(
        service.notify(
            "user-1",
            "boom",
            channels=["pigeon"],
            session=session,
        )
    )
    assert not result.ok
    assert "Unknown channel" in result.failed[0].error


# ---------------------------------------------------------------------------
# Service — in-app + realtime
# ---------------------------------------------------------------------------


def test_notify_in_app_persists(service, session):
    result = asyncio.run(
        service.notify(
            "user-1",
            "In app message",
            channels=["in_app"],
            title="New alert",
            data={"kind": "test"},
            session=session,
        )
    )
    assert result.ok
    assert result.notification_id is not None

    notif = session.query(Notification).filter(Notification.user_id == "user-1").first()
    assert notif is not None
    assert notif.title == "New alert"
    assert notif.body == "In app message"
    assert notif.data == {"kind": "test"}
    assert notif.is_read is False


def test_realtime_hub_publish_delivers():
    hub = RealtimeNotificationHub()

    class FakeWS:
        def __init__(self):
            self.messages: list[str] = []

        async def send_text(self, payload):
            self.messages.append(payload)

    ws = FakeWS()
    hub.connect_ws("user-1", ws)
    assert hub.connection_count("user-1") == 1

    delivered = asyncio.run(hub.publish("user-1", {"type": "notification", "notification": {}}))
    assert delivered == 1
    assert len(ws.messages) == 1

    hub.disconnect_ws("user-1", ws)
    assert hub.connection_count("user-1") == 0


def test_realtime_hub_disconnect_during_publish():
    hub = RealtimeNotificationHub()

    class DeadWS:
        async def send_text(self, payload):
            raise RuntimeError("gone")

    hub.connect_ws("user-1", DeadWS())
    delivered = asyncio.run(hub.publish("user-1", {"a": 1}))
    assert delivered == 0
    assert hub.connection_count("user-1") == 0


def test_realtime_hub_sse_queues():
    hub = RealtimeNotificationHub()
    queue = asyncio.Queue()

    async def _run():
        hub.connect_sse("user-1", queue)
        assert hub.connection_count("user-1") == 1
        delivered = await hub.publish("user-1", {"type": "notification"})
        assert delivered == 1
        payload = await asyncio.wait_for(queue.get(), timeout=1.0)
        return payload

    payload = asyncio.run(_run())
    assert payload == {"type": "notification"}


def test_realtime_hub_is_connected_and_prune():
    hub = RealtimeNotificationHub(heartbeat_interval=0.1)

    class FakeWS:
        async def send_text(self, payload):
            pass

        async def close(self):
            pass

    hub.connect_ws("user-1", FakeWS())
    assert hub.is_connected("user-1")

    import time

    hub._last_active["user-1"] = time.monotonic() - 1000  # simulate idle
    pruned = asyncio.run(asyncio.to_thread(hub.prune_stale, 10.0))
    assert pruned >= 1
    assert not hub.is_connected("user-1")


# ---------------------------------------------------------------------------
# Service — fallback
# ---------------------------------------------------------------------------


def test_fallback_to_second_channel(service, session):
    """When the primary channel fails, fallback channels are attempted."""
    failing = FailingSMSProvider()
    service.register_sms_provider("failing", failing)
    service.set_default_sms_provider("failing")

    # fallback to email
    result = asyncio.run(
        service.notify(
            "user-1",
            "fallback test",
            channels=["sms"],
            email="user@example.com",
            phone="+15551234567",
            session=session,
        )
    )
    # sms fails, email is not in requested channels but IS a fallback channel
    assert result.ok
    email_delivery = [c for c in result.channels if c.channel == "email"]
    assert email_delivery and email_delivery[0].success
    assert email_delivery[0].fallback_of == "sms"


def test_no_fallback_when_channel_succeeds(service, session):
    """No fallback is attempted when the requested channel succeeds."""
    result = asyncio.run(
        service.notify(
            "user-1",
            "all good",
            channels=["email"],
            email="user@example.com",
            session=session,
        )
    )
    assert result.ok
    assert len(result.channels) == 1
    assert result.channels[0].channel == "email"


# ---------------------------------------------------------------------------
# Service — preferences (opt-in/out)
# ---------------------------------------------------------------------------


def test_preference_opt_out_blocks_channel(service, session):
    asyncio.run(service.set_preference("user-1", "sms", False, session=session))

    result = asyncio.run(
        service.notify(
            "user-1",
            "pref test",
            channels=["sms"],
            phone="+15551234567",
            session=session,
        )
    )
    assert not result.ok
    assert result.failed[0].error == "Opted out via channel preference."
    assert service.sms_provider().sent == []  # never called


def test_preference_get(service, session):
    asyncio.run(service.set_preference("user-1", "sms", False, session=session))
    prefs = asyncio.run(service.get_preferences("user-1", session=session))
    assert prefs["sms"] is False


def test_preference_defaults_to_enabled(service, session):
    prefs = asyncio.run(service.get_preferences("user-1", session=session))
    assert prefs == {}


# ---------------------------------------------------------------------------
# Service — batch send
# ---------------------------------------------------------------------------


def test_batch_send(service, session):
    recipients = [
        {"user_id": "user-1", "email": "a@example.com", "phone": "+15550000001"},
        {"user_id": "user-2", "email": "b@example.com", "phone": "+15550000002"},
    ]
    results = asyncio.run(
        service.notify_many(
            recipients,
            "batch message",
            channels=["email"],
            session=session,
        )
    )
    assert len(results) == 2
    assert all(r.ok for r in results)
    assert len(service.email_provider().sent) == 2


# ---------------------------------------------------------------------------
# Service — template usage
# ---------------------------------------------------------------------------


def test_notify_with_template(service, session):
    registry = TemplateRegistry()
    registry.register(
        NotificationTemplate(name="welcome", title="Welcome {name}", body="Hi {name}!")
    )
    service.config.templates = registry

    result = asyncio.run(
        service.notify(
            "user-1",
            "",
            channels=["email"],
            template="welcome",
            context={"name": "Ada"},
            email="ada@example.com",
            session=session,
        )
    )
    assert result.ok
    sent = service.email_provider().sent[0]
    assert sent["subject"] == "Welcome Ada"
    assert sent["text"] == "Hi Ada!"


# ---------------------------------------------------------------------------
# Logs / history
# ---------------------------------------------------------------------------


def test_notification_log_written(service, session):
    asyncio.run(
        service.notify(
            "user-1",
            "logged",
            channels=["email"],
            email="user@example.com",
            session=session,
        )
    )
    logs = session.query(NotificationLog).all()
    assert len(logs) == 1
    assert logs[0].channel == "email"
    assert logs[0].status == "sent"
    assert logs[0].recipient == "user@example.com"


def test_notification_log_failure_recorded(service, session):
    service.register_email_provider("failing_email", FailingEmailProvider())
    service.set_default_email_provider("failing_email")

    result = asyncio.run(
        service.notify(
            "user-1",
            "will fail",
            channels=["email"],
            email="user@example.com",
            session=session,
        )
    )
    assert not result.ok
    logs = session.query(NotificationLog).filter(NotificationLog.channel == "email").all()
    assert len(logs) == 1
    assert logs[0].status == "failed"
    assert logs[0].error == "smtp down"
