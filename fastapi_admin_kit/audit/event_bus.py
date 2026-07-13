"""Audit event bus — publish/subscribe system for audit events."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi_admin_kit.audit.diff import snapshot
from fastapi_admin_kit.audit.events import AuditEvent


class AuditEventBus:
    """Central event bus for audit events.

    The listener publishes events here. Loggers and other subscribers
    consume them. This decouples the SQLAlchemy event hooks from the
    audit logging implementation.
    """

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable[[AuditEvent], None]]] = {
            "CREATE": [],
            "UPDATE": [],
            "DELETE": [],
        }

    def subscribe(self, event_type: str, listener: Callable[[AuditEvent], None]) -> None:
        """Register a listener for a specific event type.

        Args:
            event_type: "CREATE", "UPDATE", or "DELETE"
            listener: Callable that receives an AuditEvent
        """
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(listener)

    def publish(self, event: AuditEvent) -> None:
        """Publish an event to all listeners of its type.

        Args:
            event: The AuditEvent to publish
        """
        for listener in self._listeners.get(event.event_type, []):
            listener(event)

    def emit_for_object(
        self,
        obj: Any,
        event_type: str,
        context: dict[str, Any],
        changes: dict[str, Any] | None = None,
        snapshot_data: dict[str, Any] | None = None,
    ) -> None:
        """Build an AuditEvent from a SQLAlchemy object and publish it.

        All data is extracted from *snapshot_data* to avoid touching the
        ORM object — critical inside ``after_flush`` where attributes are
        expired on async sessions.

        Args:
            obj: The SQLAlchemy model instance (used only for class/table
                metadata which are class-level, not instance attributes)
            event_type: "CREATE", "UPDATE", or "DELETE"
            context: Audit context dict
            changes: Pre-computed diff (used for UPDATE)
            snapshot_data: Pre-computed snapshot dict
        """
        obj_snapshot = snapshot_data if snapshot_data is not None else snapshot(obj)

        # Extract id and repr from the snapshot to avoid accessing
        # potentially-expired instance attributes.
        object_id = str(obj_snapshot.get("id", ""))
        object_repr = str(obj_snapshot.get("id", obj.__class__.__name__))[:255]

        if event_type == "UPDATE" and changes is not None:
            event_changes = changes
        else:
            event_changes = None

        event = AuditEvent(
            event_type=event_type,
            model_name=obj.__class__.__name__,
            table_name=obj.__tablename__,
            object_id=object_id,
            object_repr=object_repr,
            changes=event_changes,
            full_snapshot=obj_snapshot,
            user_id=context.get("user_id"),
            user_email=context.get("user_email"),
            ip_address=context.get("ip_address"),
            user_agent=context.get("user_agent"),
        )
        self.publish(event)
