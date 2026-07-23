"""Audit diff utilities — snapshot and diff computation for SQLAlchemy models.

``serialize_value()`` is ORM-agnostic and stays here.
``snapshot()`` and ``compute_diff()`` delegate to the active AuditBackend.
"""

from __future__ import annotations

import datetime
import decimal
import enum
from typing import Any
from uuid import UUID


def serialize_value(val: Any) -> Any:
    """Convert a value to a JSON-serializable form.

    Handles:
        - datetime.datetime -> ISO string
        - datetime.date -> ISO string
        - datetime.time -> ISO string
        - decimal.Decimal -> string
        - UUID -> string
        - bytes -> base64 string? (but we'll keep as is for now, or maybe hex?)
        - Enum -> value or name? We'll use value.
        - Other types returned as-is if they are JSON serializable (int, float, str, bool, None)
    """
    if val is None:
        return None
    if isinstance(val, datetime.datetime | datetime.date | datetime.time):
        return val.isoformat()
    if isinstance(val, decimal.Decimal):
        return str(val)
    if isinstance(val, UUID):
        return str(val)
    if isinstance(val, bytes):
        return val.hex()
    if isinstance(val, enum.Enum):
        return val.value
    return val


def snapshot(obj: Any) -> dict[str, Any]:
    """Snapshot all mapped columns of a SQLAlchemy model instance.

    Returns a dict mapping column name to serialized value.
    Delegates to the active AuditBackend.
    """
    from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyAuditBackend

    backend = SqlAlchemyAuditBackend()
    return backend.snapshot(obj)


def compute_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compute the difference between two snapshots.

    Returns a dict of changed fields, each containing:
        {"old": <value>, "new": <value>}
    Only fields that have changed are included.
    Delegates to the active AuditBackend.
    """
    from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyAuditBackend

    backend = SqlAlchemyAuditBackend()
    return backend.compute_diff(before, after)
