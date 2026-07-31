"""SQLAlchemy model for the admin audit log.

.. deprecated:: 2.1.0
   This module is deprecated. Use ``fastapi_admin_kit.migrations.models`` instead,
   which materializes models from schemas for both runtime and Alembic migrations.
   This module will be removed in v3.0.
"""

from __future__ import annotations

import warnings

from fastapi_admin_kit.migrations.models import AuditLog

warnings.warn(
    "fastapi_admin_kit.audit.models is deprecated and will be removed in v3.0. "
    "Use fastapi_admin_kit.migrations.models instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["AuditLog"]
