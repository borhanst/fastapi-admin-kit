"""Audit logger — interface for audit log persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod

from fastapi_admin_kit.audit.events import AuditEvent


class AuditLogger(ABC):
    """Abstract interface for persisting audit events.

    Implementations handle the actual storage (database, file, etc.).
    This separation allows testing audit logic without a database, and
    swapping storage backends without changing the event flow.
    """

    @abstractmethod
    def log_create(self, event: AuditEvent) -> None:
        """Persist a CREATE audit event."""

    @abstractmethod
    def log_update(self, event: AuditEvent) -> None:
        """Persist an UPDATE audit event."""

    @abstractmethod
    def log_delete(self, event: AuditEvent) -> None:
        """Persist a DELETE audit event."""
