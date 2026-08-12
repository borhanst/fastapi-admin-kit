"""Single JSON serializer for the AI module.

Supersedes the three near-identical sanitizers that used to live in
``ai/conversation.py`` (``_json_safe``) and ``ai/dashboard.py`` (the two
copies of ``_safe_dict``/``_sanitize``).  Having one serializer is the
locality win called for by the architecture review: a fix to how
``Decimal``/``datetime``/pydantic ``model_dump`` values are handled is made
in exactly one place.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


def serialize(value: Any) -> Any:
    """Return a JSON-serializable copy of ``value``.

    Recursively converts dataclasses (e.g. pydantic-ai ``ModelMessage``),
    pydantic models (e.g. ``QueryResult``), ``Enum``, ``UUID``, ``Decimal``,
    ``datetime``/``date``/``time``, and other non-primitive objects into plain
    JSON-friendly structures so they can be stored in a JSON column or sent
    across the wire.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, Mapping):
        return {k: serialize(v) for k, v in value.items()}

    if isinstance(value, list | tuple | set | frozenset):
        return [serialize(v) for v in value]

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return serialize(dataclasses.asdict(value))

    # Pydantic models — includes QueryResult, ReportSpec, ORM-like objects.
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return serialize(model_dump())
        except Exception:  # noqa: BLE001
            pass

    if isinstance(value, datetime | date | time) or value.__class__.__module__.startswith(
        "datetime"
    ):
        return value.isoformat()

    if isinstance(value, Decimal):
        return float(value)

    if hasattr(value, "__dict__"):
        try:
            return serialize(vars(value))
        except TypeError:
            pass

    return str(value)
