"""ORM-agnostic tests — notifications driven entirely through the in-memory backend.

This proves the ``notifications/`` package depends only on the backend protocol
seam: notify / preferences / log / list / read are exercised against
``MemoryQueryAdapter`` + ``MemoryDatabaseBackend.materialize(...)`` +
``MemorySessionBackend``, so no SQLAlchemy is reached on that path.
"""

from __future__ import annotations

import asyncio

from fastapi_admin_kit.backends import InMemoryBackend
from fastapi_admin_kit.backends.memory import MemoryQueryAdapter, MemorySessionBackend
from fastapi_admin_kit.notifications.service import NotificationService
from fastapi_admin_kit.notifications.store import NotificationStore


def _notifications_backend():
    backend = InMemoryBackend()
    connection = backend.database.create_connection()
    service = NotificationService(
        backend=backend,
        session_factory=backend.database.create_session_factory(connection),
    )
    return backend, connection, service


def _store(backend, connection) -> NotificationStore:
    factory = backend.database.create_session_factory(connection)
    return NotificationStore(factory(), backend=backend)


def test_store_uses_memory_adapters():
    backend, connection, _ = _notifications_backend()
    store = _store(backend, connection)
    assert isinstance(store._sb, MemorySessionBackend)
    assert isinstance(store._qb, MemoryQueryAdapter)
    assert store.Notification.__tablename__ == "admin_notifications"
    assert store.NotificationPreference.__tablename__ == "admin_notification_preferences"
    assert store.NotificationLog.__tablename__ == "admin_notification_logs"


def test_create_notification_returns_auto_increment_id():
    backend, connection, _ = _notifications_backend()
    store = _store(backend, connection)
    nid = asyncio.run(
        store.create_notification(
            user_id="u1", email=None, title="T", body="B", channels=["in_app"], data=None
        )
    )
    assert isinstance(nid, int)
    assert nid == 1
    notification = asyncio.run(store.get_notification(nid))
    assert notification is not None
    assert notification.title == "T"
    # Post-add id semantics are exposed, like SQLAlchemy after flush.
    obj = asyncio.run(store.get_notification(nid))
    assert obj.id == nid


def test_notify_in_app_persists_to_memory():
    backend, connection, service = _notifications_backend()
    result = asyncio.run(
        service.notify("user-1", "Hello world", channels=["in_app"], title="Hi", data={"k": 1})
    )
    assert result.ok
    assert result.notification_id is not None
    rows = connection["admin_notifications"]
    assert len(rows) == 1
    assert rows[0]["title"] == "Hi"
    assert rows[0]["user_id"] == "user-1"
    assert rows[0]["status"] == "sent"


def test_notification_log_written_to_memory():
    backend, connection, service = _notifications_backend()
    result = asyncio.run(service.notify("user-1", "logged", channels=["in_app"]))
    assert result.notification_id is not None
    logs = connection["admin_notification_logs"]
    assert len(logs) == 1
    assert logs[0]["channel"] == "in_app"
    assert logs[0]["status"] == "sent"


def test_preferences_via_memory():
    backend, connection, _ = _notifications_backend()
    store = _store(backend, connection)
    assert asyncio.run(store.get_preferences("user-1")) == {}

    asyncio.run(store.set_preference("user-1", "sms", False))
    assert asyncio.run(store.get_preferences("user-1")) == {"sms": False}
    assert connection["admin_notification_preferences"][0]["enabled"] is False

    # Mutating-fetch re-add persists the update (overwrite-by-pk in memory).
    asyncio.run(store.set_preference("user-1", "sms", True))
    assert asyncio.run(store.get_preferences("user-1")) == {"sms": True}
    assert len(connection["admin_notification_preferences"]) == 1


def test_opt_out_blocks_email_channel():
    backend, connection, service = _notifications_backend()
    asyncio.run(service.set_preference("user-1", "email", False, session=connection))

    result = asyncio.run(service.notify("user-1", "no", channels=["email"], email="a@example.com"))
    assert not result.ok
    assert result.failed[0].error == "Opted out via channel preference."


def test_list_unread_count_and_mark_read():
    backend, connection, service = _notifications_backend()
    result = asyncio.run(service.notify("user-1", "unread", channels=["in_app"], title="T"))
    nid = result.notification_id
    assert asyncio.run(service.unread_count("user-1")) == 1

    rows = asyncio.run(service.list_notifications("user-1"))
    assert [r.id for r in rows] == [nid]

    assert asyncio.run(service.mark_read(nid, "user-1")) is True
    assert asyncio.run(service.unread_count("user-1")) == 0
    assert asyncio.run(service.list_notifications("user-1", unread_only=True)) == []

    # A different user cannot read or list the notification.
    assert asyncio.run(service.mark_read(nid, "other-user")) is False
    assert asyncio.run(service.list_notifications("other-user")) == []
