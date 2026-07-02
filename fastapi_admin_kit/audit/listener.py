"""Audit listener — SQLAlchemy event listeners that write audit rows atomically.

AuditLog rows are created inside ``before_flush`` and added to the session
via ``session.add()``.  SQLAlchemy re-runs ``before_flush`` until no new
pending objects appear, so the audit rows ride along in the same flush pass.
No IO, no queries, no ``MissingGreenlet`` — just already-loaded attributes.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import instance_state

from fastapi_admin_kit.audit.context import get_audit_context
from fastapi_admin_kit.audit.diff import serialize_value
from fastapi_admin_kit.audit.models import AuditLog


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
    """Snapshot all mapped columns of a SQLAlchemy model instance."""
    if not hasattr(obj, "__table__"):
        return {}
    from sqlalchemy.inspection import inspect as sa_inspect

    mapper = sa_inspect(obj.__class__)
    data: dict[str, Any] = {}
    for column in mapper.columns:
        data[column.key] = serialize_value(getattr(obj, column.key))
    return data


def _compute_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compute changed fields between two snapshots.

    Returns ``{"field": {"old": ..., "new": ...}}`` for each difference.
    """
    diff: dict[str, Any] = {}
    all_keys = set(before.keys()) | set(after.keys())
    for key in all_keys:
        old_val = before.get(key)
        new_val = after.get(key)
        if old_val != new_val:
            diff[key] = {"old": old_val, "new": new_val}
    return diff


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
    """Set up SQLAlchemy ``before_flush`` listener for audit logging.

    Args:
        session_factory: The session factory (sync or async).
        registry: The AdminRegistry instance.
    """

    @event.listens_for(Session, "before_flush")
    def before_flush(session: Session, flush_context: Any, instances: Any) -> None:
        """Create AuditLog rows for all tracked mutations.

        Runs inside the same flush pass — ``session.add()`` puts the
        AuditLog into the pending set and SQLAlchemy will re-run
        ``before_flush`` until no new objects appear.  No queries, no
        lazy-loads, only already-loaded attribute history.
        """
        context = get_audit_context()

        # ── INSERT ──────────────────────────────────────────────────
        for obj in list(session.new):
            if not is_registered_model(obj, registry):
                continue
            if obj.__tablename__ == AuditLog.__tablename__:
                continue
            row = _build_audit_row(obj, "CREATE", context)
            session.add(row)

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
