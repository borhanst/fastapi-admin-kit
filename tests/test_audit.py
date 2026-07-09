"""Tests for the Audit Event System (item 4 — Extract Audit Event System)."""

import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import Session

from fastapi_admin_kit.audit.context import (
    AuditContext,
    clear_audit_context,
    get_audit_context,
    set_audit_context,
)
from fastapi_admin_kit.audit.diff import compute_diff, serialize_value, snapshot
from fastapi_admin_kit.audit.event_bus import AuditEventBus
from fastapi_admin_kit.audit.events import AuditEvent
from fastapi_admin_kit.audit.logger import AuditLogger
from fastapi_admin_kit.audit.models import AuditLog
from fastapi_admin_kit.audit.sqlalchemy_logger import SqlAlchemyAuditLogger
from fastapi_admin_kit.auth.models import (  # noqa: F401 — ensure tables exist
    Role,
    User,
)
from fastapi_admin_kit.models.base import Base

# ---------------------------------------------------------------------------
# Test model for audit listener tests
# ---------------------------------------------------------------------------


class FakeProduct(Base):
    __tablename__ = "fake_products"
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    price = Column(Integer)


# ---------------------------------------------------------------------------
# AuditEvent tests
# ---------------------------------------------------------------------------


class TestAuditEvent:
    def test_create_event_with_defaults(self):
        event = AuditEvent(
            event_type="CREATE",
            model_name="Product",
            table_name="products",
            object_id="1",
        )
        assert event.event_type == "CREATE"
        assert event.model_name == "Product"
        assert event.table_name == "products"
        assert event.object_id == "1"
        assert event.changes is None
        assert event.full_snapshot is None
        assert event.user_id is None
        assert event.timestamp is not None
        assert event.timestamp.tzinfo is not None

    def test_create_event_with_all_fields(self):
        ts = datetime.datetime(2025, 1, 15, 12, 0, 0, tzinfo=datetime.UTC)
        event = AuditEvent(
            event_type="UPDATE",
            model_name="User",
            table_name="users",
            object_id="42",
            object_repr="admin@test.com",
            changes={"name": {"old": "A", "new": "B"}},
            full_snapshot={"id": 42, "name": "B"},
            user_id=1,
            user_email="admin@test.com",
            ip_address="127.0.0.1",
            user_agent="Mozilla/5.0",
            timestamp=ts,
        )
        assert event.event_type == "UPDATE"
        assert event.changes == {"name": {"old": "A", "new": "B"}}
        assert event.user_id == 1
        assert event.ip_address == "127.0.0.1"

    def test_to_dict(self):
        event = AuditEvent(
            event_type="DELETE",
            model_name="Order",
            table_name="orders",
            object_id="99",
        )
        data = event.to_dict()
        assert data["event_type"] == "DELETE"
        assert data["model_name"] == "Order"
        assert "timestamp" in data
        assert isinstance(data["timestamp"], str)

    def test_from_dict(self):
        ts = "2025-01-15T12:00:00+00:00"
        data = {
            "event_type": "CREATE",
            "model_name": "Product",
            "table_name": "products",
            "object_id": "1",
            "timestamp": ts,
        }
        event = AuditEvent.from_dict(data)
        assert event.event_type == "CREATE"
        assert event.model_name == "Product"
        assert isinstance(event.timestamp, datetime.datetime)

    def test_roundtrip_serialization(self):
        event = AuditEvent(
            event_type="UPDATE",
            model_name="Item",
            table_name="items",
            object_id="5",
            changes={"x": {"old": 1, "new": 2}},
        )
        data = event.to_dict()
        restored = AuditEvent.from_dict(data)
        assert restored.event_type == event.event_type
        assert restored.changes == event.changes
        assert restored.model_name == event.model_name


# ---------------------------------------------------------------------------
# AuditEventBus tests
# ---------------------------------------------------------------------------


class TestAuditEventBus:
    def test_publish_calls_subscribers(self):
        bus = AuditEventBus()
        received = []
        bus.subscribe("CREATE", lambda e: received.append(e))

        event = AuditEvent(
            event_type="CREATE", model_name="M", table_name="t", object_id="1"
        )
        bus.publish(event)
        assert len(received) == 1
        assert received[0] is event

    def test_subscribe_multiple_listeners(self):
        bus = AuditEventBus()
        results_a = []
        results_b = []
        bus.subscribe("DELETE", lambda e: results_a.append("a"))
        bus.subscribe("DELETE", lambda e: results_b.append("b"))

        event = AuditEvent(
            event_type="DELETE", model_name="M", table_name="t", object_id="1"
        )
        bus.publish(event)
        assert results_a == ["a"]
        assert results_b == ["b"]

    def test_publish_only_notifies_matching_type(self):
        bus = AuditEventBus()
        create_received = []
        update_received = []
        bus.subscribe("CREATE", lambda e: create_received.append(e))
        bus.subscribe("UPDATE", lambda e: update_received.append(e))

        event = AuditEvent(
            event_type="CREATE", model_name="M", table_name="t", object_id="1"
        )
        bus.publish(event)
        assert len(create_received) == 1
        assert len(update_received) == 0

    def test_unknown_event_type_does_not_raise(self):
        bus = AuditEventBus()
        event = AuditEvent(
            event_type="UNKNOWN", model_name="M", table_name="t", object_id="1"
        )
        bus.publish(event)  # should not raise

    def test_emit_for_object_publishes_event(self):
        bus = AuditEventBus()
        received = []
        bus.subscribe("CREATE", lambda e: received.append(e))

        obj = FakeProduct(id=1, name="Widget", price=999)
        context = {
            "user_id": 1,
            "user_email": "a@b.com",
            "ip_address": "10.0.0.1",
            "user_agent": "test",
        }
        bus.emit_for_object(obj, "CREATE", context)

        assert len(received) == 1
        event = received[0]
        assert event.event_type == "CREATE"
        assert event.model_name == "FakeProduct"
        assert event.table_name == "fake_products"
        assert event.object_id == "1"
        assert event.user_id == 1
        assert event.full_snapshot is not None
        assert event.full_snapshot["name"] == "Widget"

    def test_emit_for_object_with_changes(self):
        bus = AuditEventBus()
        received = []
        bus.subscribe("UPDATE", lambda e: received.append(e))

        obj = FakeProduct(id=1, name="Updated", price=1999)
        changes = {"name": {"old": "Widget", "new": "Updated"}}
        bus.emit_for_object(obj, "UPDATE", {}, changes=changes)

        event = received[0]
        assert event.changes == changes
        assert event.full_snapshot["name"] == "Updated"


# ---------------------------------------------------------------------------
# AuditContext tests
# ---------------------------------------------------------------------------


class TestAuditContext:
    def setup_method(self):
        clear_audit_context()

    def test_set_and_get_context(self):
        set_audit_context({"user_id": 42})
        ctx = get_audit_context()
        assert ctx["user_id"] == 42

    def test_merge_context(self):
        set_audit_context({"user_id": 1})
        set_audit_context({"ip_address": "127.0.0.1"})
        ctx = get_audit_context()
        assert ctx["user_id"] == 1
        assert ctx["ip_address"] == "127.0.0.1"

    def test_clear_context(self):
        set_audit_context({"user_id": 1})
        clear_audit_context()
        assert get_audit_context() == {}

    def test_audit_context_class(self):
        ac = AuditContext()
        ac.set_context(user=None, request=None)
        assert ac.get_context() == {}

    def test_audit_context_class_with_user(self):
        user = MagicMock(id=10, email="test@test.com")
        ac = AuditContext()
        ac.set_context(user=user)
        ctx = ac.get_context()
        assert ctx["user_id"] == 10
        assert ctx["user_email"] == "test@test.com"

    def test_audit_context_class_clear(self):
        ac = AuditContext()
        set_audit_context({"user_id": 1})
        ac.clear_context()
        assert get_audit_context() == {}


# ---------------------------------------------------------------------------
# AuditLogger interface tests
# ---------------------------------------------------------------------------


class TestAuditLoggerInterface:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            AuditLogger()

    def test_concrete_subclass(self):
        class MemLogger(AuditLogger):
            def __init__(self):
                self.events = []

            def log_create(self, event):
                self.events.append(("CREATE", event))

            def log_update(self, event):
                self.events.append(("UPDATE", event))

            def log_delete(self, event):
                self.events.append(("DELETE", event))

        logger = MemLogger()
        ev = AuditEvent(
            event_type="CREATE", model_name="M", table_name="t", object_id="1"
        )
        logger.log_create(ev)
        assert len(logger.events) == 1
        assert logger.events[0][0] == "CREATE"


# ---------------------------------------------------------------------------
# SqlAlchemyAuditLogger tests
# ---------------------------------------------------------------------------


class TestSqlAlchemyAuditLogger:
    @pytest.fixture
    def session(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            yield s

    def test_log_create(self, session):
        logger = SqlAlchemyAuditLogger(session)
        event = AuditEvent(
            event_type="CREATE",
            model_name="Product",
            table_name="products",
            object_id="1",
            full_snapshot={"id": 1, "name": "Widget"},
        )
        logger.log_create(event)
        # Manually flush the buffered entries (sync path for tests)
        for entry in logger._pending:
            session.add(entry)
        logger._pending.clear()
        session.flush()

        rows = session.query(AuditLog).all()
        assert len(rows) == 1
        assert rows[0].action == "CREATE"
        assert rows[0].model_name == "Product"
        assert rows[0].full_snapshot == {"id": 1, "name": "Widget"}

    def test_log_update(self, session):
        logger = SqlAlchemyAuditLogger(session)
        event = AuditEvent(
            event_type="UPDATE",
            model_name="User",
            table_name="users",
            object_id="5",
            changes={"name": {"old": "A", "new": "B"}},
            full_snapshot={"id": 5, "name": "B"},
        )
        logger.log_update(event)
        for entry in logger._pending:
            session.add(entry)
        logger._pending.clear()
        session.flush()

        row = session.query(AuditLog).one()
        assert row.action == "UPDATE"
        assert row.changes == {"name": {"old": "A", "new": "B"}}

    def test_log_delete(self, session):
        logger = SqlAlchemyAuditLogger(session)
        event = AuditEvent(
            event_type="DELETE",
            model_name="Order",
            table_name="orders",
            object_id="10",
        )
        logger.log_delete(event)
        for entry in logger._pending:
            session.add(entry)
        logger._pending.clear()
        session.flush()

        row = session.query(AuditLog).one()
        assert row.action == "DELETE"
        assert row.object_id == "10"

    def test_preserves_user_info(self, session):
        logger = SqlAlchemyAuditLogger(session)
        event = AuditEvent(
            event_type="CREATE",
            model_name="M",
            table_name="t",
            object_id="1",
            user_id=7,
            user_email="admin@test.com",
            ip_address="10.0.0.1",
            user_agent="Mozilla/5.0",
        )
        logger.log_create(event)
        for entry in logger._pending:
            session.add(entry)
        logger._pending.clear()
        session.flush()

        row = session.query(AuditLog).one()
        assert row.user_id == 7
        assert row.user_email == "admin@test.com"
        assert row.ip_address == "10.0.0.1"
        assert row.user_agent == "Mozilla/5.0"


# ---------------------------------------------------------------------------
# Diff utilities tests
# ---------------------------------------------------------------------------


class TestDiffUtilities:
    def test_serialize_value_none(self):
        assert serialize_value(None) is None

    def test_serialize_value_datetime(self):
        dt = datetime.datetime(2025, 1, 15, 12, 0, 0)
        assert serialize_value(dt) == "2025-01-15T12:00:00"

    def test_serialize_value_date(self):
        d = datetime.date(2025, 1, 15)
        assert serialize_value(d) == "2025-01-15"

    def test_serialize_value_decimal(self):
        from decimal import Decimal

        assert serialize_value(Decimal("3.14")) == "3.14"

    def test_serialize_value_uuid(self):
        from uuid import UUID

        u = UUID("12345678-1234-5678-1234-567812345678")
        assert serialize_value(u) == "12345678-1234-5678-1234-567812345678"

    def test_serialize_value_bytes(self):
        assert serialize_value(b"\xde\xad") == "dead"

    def test_serialize_value_enum(self):
        import enum

        class Color(enum.Enum):
            RED = "red"

        assert serialize_value(Color.RED) == "red"

    def test_serialize_value_passthrough(self):
        assert serialize_value(42) == 42
        assert serialize_value("hello") == "hello"
        assert serialize_value(True) is True

    def test_snapshot_returns_all_columns(self):
        obj = FakeProduct(id=1, name="Test", price=100)
        s = snapshot(obj)
        assert s["id"] == 1
        assert s["name"] == "Test"
        assert s["price"] == 100

    def test_snapshot_raises_on_non_model(self):
        with pytest.raises(ValueError, match="not a SQLAlchemy model"):
            snapshot("not a model")

    def test_compute_diff_no_changes(self):
        before = {"a": 1, "b": 2}
        after = {"a": 1, "b": 2}
        assert compute_diff(before, after) == {}

    def test_compute_diff_with_changes(self):
        before = {"a": 1, "b": 2}
        after = {"a": 1, "b": 99}
        diff = compute_diff(before, after)
        assert diff == {"b": {"old": 2, "new": 99}}

    def test_compute_diff_new_field(self):
        before = {"a": 1}
        after = {"a": 1, "b": 2}
        diff = compute_diff(before, after)
        assert diff == {"b": {"old": None, "new": 2}}

    def test_compute_diff_removed_field(self):
        before = {"a": 1, "b": 2}
        after = {"a": 1}
        diff = compute_diff(before, after)
        assert diff == {"b": {"old": 2, "new": None}}


# ---------------------------------------------------------------------------
# Listener integration tests (with real SQLAlchemy flush)
# ---------------------------------------------------------------------------


class TestAuditListenerIntegration:
    @pytest.fixture
    def engine(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        return engine

    @pytest.fixture
    def session_and_bus(self, engine):
        from fastapi_admin_kit.audit.event_bus import AuditEventBus

        # Fake registry that recognizes fake_products
        registry = MagicMock()
        registry.get.side_effect = lambda tn: (
            MagicMock() if tn == "fake_products" else None
        )

        bus = AuditEventBus()
        # Wire up a logger that writes to a session
        logger_session = Session(engine)
        logger = SqlAlchemyAuditLogger(logger_session)
        bus.subscribe("CREATE", logger.log_create)
        bus.subscribe("UPDATE", logger.log_update)
        bus.subscribe("DELETE", logger.log_delete)

        return logger_session, bus

    def test_create_emits_event(self, session_and_bus):
        session, bus = session_and_bus
        received = []
        bus.subscribe("CREATE", lambda e: received.append(e))

        obj = FakeProduct(id=1, name="Widget", price=999)
        bus.emit_for_object(
            obj, "CREATE", {"user_id": 1, "user_email": "a@b.com"}
        )
        session.flush()

        assert len(received) == 1
        assert received[0].event_type == "CREATE"
        assert received[0].full_snapshot["name"] == "Widget"

    def test_update_emits_event_with_diff(self, session_and_bus):
        session, bus = session_and_bus
        received = []
        bus.subscribe("UPDATE", lambda e: received.append(e))

        obj = FakeProduct(id=1, name="Updated", price=1999)
        changes = {
            "name": {"old": "Widget", "new": "Updated"},
            "price": {"old": 999, "new": 1999},
        }
        bus.emit_for_object(obj, "UPDATE", {}, changes=changes)
        session.flush()

        assert len(received) == 1
        assert received[0].changes == changes

    def test_delete_emits_event(self, session_and_bus):
        session, bus = session_and_bus
        received = []
        bus.subscribe("DELETE", lambda e: received.append(e))

        obj = FakeProduct(id=1, name="Widget", price=999)
        bus.emit_for_object(obj, "DELETE", {})
        session.flush()

        assert len(received) == 1
        assert received[0].event_type == "DELETE"
