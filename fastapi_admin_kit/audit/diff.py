"""Audit diff utilities — snapshot and diff computation for SQLAlchemy models."""

from __future__ import annotations

import datetime
import decimal
import enum
from typing import Any
from uuid import UUID

from sqlalchemy.inspection import inspect as sqlalchemy_inspect


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
        # For simplicity, we'll return the hex representation.
        # Alternatively, we could use base64, but hex is simpler.
        return val.hex()
    if isinstance(val, enum.Enum):
        return val.value
    # For other types, we assume they are JSON serializable (or let JSON encoder handle it)
    return val


def snapshot(obj: Any) -> dict[str, Any]:
    """Snapshot all mapped columns of a SQLAlchemy model instance.

    Returns a dict mapping column name to serialized value.
    """
    if not hasattr(obj, "__table__"):
        raise ValueError("Object is not a SQLAlchemy model instance")

    mapper = sqlalchemy_inspect(obj.__class__)
    data = {}
    for column in mapper.columns:
        # Skip foreign key columns that are represented by relationships?
        # We'll include all columns for simplicity.
        value = getattr(obj, column.key)
        data[column.key] = serialize_value(value)
    return data


def compute_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compute the difference between two snapshots.

    Returns a dict of changed fields, each containing:
        {"old": <value>, "new": <value>}
    Only fields that have changed are included.
    """
    diff = {}
    all_keys = set(before.keys()) | set(after.keys())
    for key in all_keys:
        old_val = before.get(key)
        new_val = after.get(key)
        if old_val != new_val:
            diff[key] = {"old": old_val, "new": new_val}
    return diff
