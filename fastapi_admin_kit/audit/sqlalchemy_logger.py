"""SQLAlchemy audit logger — persists audit events to the database."""

from __future__ import annotations

from typing import Any

from fastapi_admin_kit.audit.events import AuditEvent
from fastapi_admin_kit.audit.logger import AuditLogger
from fastapi_admin_kit.audit.models import AuditLog


class SqlAlchemyAuditLogger(AuditLogger):
    """Writes AuditEvents to the admin_audit_log table.

    Buffers AuditLog entries during synchronous SQLAlchemy event callbacks
    (e.g. ``after_flush``) and flushes them to the database asynchronously
    after the main transaction commits.  This avoids triggering implicit
    autoflush inside a sync event handler, which would raise
    ``MissingGreenlet`` with async sessions.
    """

    def __init__(self, session: Any = None) -> None:
        self._session = session
        self._pending: list[AuditLog] = []

    def log_create(self, event: AuditEvent) -> None:
        self._buffer(event)

    def log_update(self, event: AuditEvent) -> None:
        self._buffer(event)

    def log_delete(self, event: AuditEvent) -> None:
        self._buffer(event)

    def log_export(self, event: AuditEvent) -> None:
        self._buffer(event)

    def log_import(self, event: AuditEvent) -> None:
        self._buffer(event)

    def _buffer(self, event: AuditEvent) -> None:
        entry = AuditLog(
            user_id=event.user_id,
            user_email=event.user_email,
            action=event.event_type,
            model_name=event.model_name,
            table_name=event.table_name,
            object_id=event.object_id,
            object_repr=event.object_repr,
            changes=event.changes,
            full_snapshot=event.full_snapshot,
            ip_address=event.ip_address,
            user_agent=event.user_agent,
        )
        self._pending.append(entry)

    async def flush_pending(self, session: Any) -> None:
        """Write all buffered entries to *session* and clear the buffer."""
        if not self._pending:
            return
        for entry in self._pending:
            session.add(entry)
        self._pending.clear()
        await session.flush()
