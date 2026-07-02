"""Audit module — AuditLog model, SQLAlchemy event listener, diff, context, middleware."""

from __future__ import annotations

from fastapi_admin_kit.audit.context import (
    AuditContext,
    clear_audit_context,
    get_audit_context,
    set_audit_context,
)
from fastapi_admin_kit.audit.diff import compute_diff, snapshot
from fastapi_admin_kit.audit.event_bus import AuditEventBus
from fastapi_admin_kit.audit.events import AuditEvent
from fastapi_admin_kit.audit.listener import (
    attach_audit_listener,
    is_registered_model,
)
from fastapi_admin_kit.audit.logger import AuditLogger
from fastapi_admin_kit.audit.middleware import AuditContextMiddleware
from fastapi_admin_kit.audit.models import AuditLog

__all__ = [
    "AuditContext",
    "AuditContextMiddleware",
    "AuditEvent",
    "AuditEventBus",
    "AuditLog",
    "AuditLogger",
    "attach_audit_listener",
    "clear_audit_context",
    "compute_diff",
    "get_audit_context",
    "is_registered_model",
    "set_audit_context",
    "snapshot",
]
