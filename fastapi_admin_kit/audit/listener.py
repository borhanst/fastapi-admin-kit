"""Audit listener — SQLAlchemy event listeners that write audit rows atomically.

AuditLog rows are created inside ``before_flush`` (UPDATE/DELETE) and
``after_flush_postexec`` (CREATE) and added to the session via ``session.add()``.
CREATE uses ``after_flush_postexec`` so the auto-generated primary key is available.
No IO, no queries, no ``MissingGreenlet`` — just already-loaded attributes.
"""

from __future__ import annotations

import threading
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import instance_state

from fastapi_admin_kit.audit.context import get_audit_context
from fastapi_admin_kit.audit.diff import serialize_value
from fastapi_admin_kit.audit.models import AuditLog

_pending_creates: dict[int, list[tuple[Any, dict[str, Any], dict[str, Any]]]] = {}
_pending_lock = threading.Lock()


def is_registered_model(obj: Any, registry: Any) -> bool:
    """Check if a model class is registered with the admin."""
    if not hasattr(obj, "__tablename__"):
        return False
    table_name = getattr(obj, "__tablename__")
    return registry.get(table_name) is not None


def _snapshot_from_committed(obj: Any) -> dict[str, Any]:
    """Snapshot column values from the committed (pre-flush) state.

    Uses SQLAlchemy attribute history to read the *old* values that were
    in the database before the current pending changes.  No attribute
    access that could trigger lazy-load I/O.
    """
    if not hasattr(obj, "__table__"):
        return {}
    mapper = instance_state(obj).manager.mapper
    data: dict[str, Any] = {}
    for column in mapper.columns:
        attr = instance_state(obj).attrs[column.key]
        history = attr.history
        if history.deleted:
            data[column.key] = serialize_value(history.deleted[0])
        elif history.unchanged:
            data[column.key] = serialize_value(history.unchanged[0])
        else:
            data[column.key] = serialize_value(getattr(obj, column.key))
    return data


def _snapshot_current(obj: Any) -> dict[str, Any]:
    """Snapshot all mapped columns of a SQLAlchemy model instance.

    Delegates to the SqlAlchemyAuditBackend. Returns {} for non-model objects.
    """
    from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyAuditBackend

    backend = SqlAlchemyAuditBackend()
    try:
        return backend.snapshot(obj)
    except ValueError:
        return {}


def _compute_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compute changed fields between two snapshots.

    Returns ``{"field": {"old": ..., "new": ...}}`` for each difference.
    Delegates to the SqlAlchemyAuditBackend.
    """
    from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyAuditBackend

    backend = SqlAlchemyAuditBackend()
    return backend.compute_diff(before, after)


def _build_audit_row(
    obj: Any,
    action: str,
    context: dict[str, Any],
    *,
    changes: dict[str, Any] | None = None,
    snapshot_data: dict[str, Any] | None = None,
) -> AuditLog:
    """Create an AuditLog row from an ORM object and audit context."""
    snap = snapshot_data if snapshot_data is not None else _snapshot_current(obj)
    return AuditLog(
        action=action,
        model_name=type(obj).__name__,
        table_name=obj.__tablename__,
        object_id=str(snap.get("id", getattr(obj, "id", ""))),
        object_repr=str(obj)[:500],
        changes=changes,
        full_snapshot=snap,
        user_id=context.get("user_id"),
        user_email=context.get("user_email"),
        ip_address=context.get("ip_address"),
        user_agent=context.get("user_agent"),
    )


def attach_audit_listener(
    session_factory: Any,
    registry: Any,
) -> None:
    """Set up SQLAlchemy ``before_flush`` and ``after_flush_postexec`` listeners.

    Args:
        session_factory: The session factory (sync or async).
        registry: The AdminRegistry instance.
    """

    @event.listens_for(Session, "before_flush")
    def before_flush(session: Session, flush_context: Any, instances: Any) -> None:
        """Capture new objects and create AuditLog rows for UPDATE/DELETE.

        New objects are stored to create audit rows in ``after_flush_postexec``
        where their auto-generated primary keys are available.
        """
        context = get_audit_context()
        session_id = id(session)

        # ── INSERT (capture for after_flush_postexec) ───────────────
        new_items = []
        for obj in list(session.new):
            if not is_registered_model(obj, registry):
                continue
            if obj.__tablename__ == AuditLog.__tablename__:
                continue
            snap = _snapshot_current(obj)
            new_items.append((obj, snap, context))

        if new_items:
            with _pending_lock:
                _pending_creates[session_id] = new_items

        # ── UPDATE ──────────────────────────────────────────────────
        for obj in list(session.dirty):
            if not is_registered_model(obj, registry):
                continue
            if obj.__tablename__ == AuditLog.__tablename__:
                continue
            before = _snapshot_from_committed(obj)
            after = _snapshot_current(obj)
            diff = _compute_diff(before, after)
            if not diff:
                continue
            row = _build_audit_row(obj, "UPDATE", context, changes=diff, snapshot_data=after)
            session.add(row)

        # ── DELETE ──────────────────────────────────────────────────
        for obj in list(session.deleted):
            if not is_registered_model(obj, registry):
                continue
            if obj.__tablename__ == AuditLog.__tablename__:
                continue
            snap = _snapshot_current(obj)
            row = _build_audit_row(obj, "DELETE", context, snapshot_data=snap)
            session.add(row)

    @event.listens_for(Session, "after_flush_postexec")
    def after_flush_postexec(session: Session, flush_context: Any) -> None:
        """Create AuditLog rows for CREATE mutations after flush.

        This runs after the flush completes, so auto-generated primary keys
        are available on the ORM objects.
        """
        session_id = id(session)

        with _pending_lock:
            pending = _pending_creates.pop(session_id, [])

        if not pending:
            return

        for obj, snap, context in pending:
            # Update snapshot with the now-available id
            snap["id"] = getattr(obj, "id", None)
            row = _build_audit_row(obj, "CREATE", context, snapshot_data=snap)
            session.add(row)
