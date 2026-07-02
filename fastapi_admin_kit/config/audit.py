"""Audit configuration."""

from fastapi_admin_kit.exceptions import ConfigError


class AuditConfig:
    """Audit configuration."""

    def __init__(
        self,
        audit_retention_days: int = 365,
    ):
        self.audit_retention_days = audit_retention_days

    def validate_audit_config(self) -> None:
        """Validate audit configuration."""
        if self.audit_retention_days < 0:
            raise ConfigError("audit_retention_days must be non-negative")
