"""Audit context — thread-local storage for audit information."""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi_admin_kit.audit.events import AuditEvent

# Context variable to store audit context (user, IP, user_agent, etc.)
_current_audit_context: ContextVar[dict] = ContextVar("_current_audit_context", default={})


def get_audit_context() -> dict:
    """Get the current audit context."""
    return _current_audit_context.get()


def set_audit_context(data: dict) -> None:
    """Set the audit context (merges with existing)."""
    current = get_audit_context()
    current.update(data)
    _current_audit_context.set(current)


def clear_audit_context() -> None:
    """Clear the audit context."""
    _current_audit_context.set({})


class AuditContext:
    """Manages the current audit context for a request lifecycle.

    Wraps the ContextVar-based functions in a class interface that
    can be injected into the event bus and listener.
    """

    def set_context(self, user: Any = None, request: Any = None) -> None:
        """Set audit context from a user object and/or request.

        Args:
            user: An object with 'id' and 'email' attributes (e.g. User)
            request: A Starlette/FastAPI Request with client and headers
        """
        data: dict[str, Any] = {}
        if user is not None:
            data["user_id"] = getattr(user, "id", None)
            data["user_email"] = getattr(user, "email", None)
        if request is not None:
            if request.client is not None:
                data["ip_address"] = request.client.host
            user_agent = request.headers.get("user-agent")
            if user_agent:
                data["user_agent"] = user_agent
        if data:
            set_audit_context(data)

    def get_context(self) -> dict:
        """Get the current audit context."""
        return get_audit_context()

    def clear_context(self) -> None:
        """Clear the audit context."""
        clear_audit_context()


async def log_audit_event(request: Any, event: AuditEvent) -> None:
    """Persist an AuditEvent directly to the database.

    Used for EXPORT/IMPORT events that don't go through the SQLAlchemy
    before_flush listener.
    """
    from fastapi_admin_kit.audit.models import AuditLog
    from fastapi_admin_kit.db import get_db_session

    session = get_db_session(request)
    ctx = get_audit_context()

    entry = AuditLog(
        action=event.event_type,
        model_name=event.model_name,
        table_name=event.table_name,
        object_id=event.object_id,
        object_repr=event.object_repr,
        changes=event.changes,
        full_snapshot=event.full_snapshot,
        user_id=event.user_id or ctx.get("user_id"),
        user_email=event.user_email or ctx.get("user_email"),
        ip_address=event.ip_address or ctx.get("ip_address"),
        user_agent=event.user_agent or ctx.get("user_agent"),
    )
    session.add(entry)
    await session.flush()
