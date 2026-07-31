"""Schema-first model definitions for built-in admin models.

Three-layer architecture:

1. **Protocol** (``auth/protocol.py``) — contract definition
2. **Schema** (this package) — declarative model definitions
3. **Materialization** (``backends/``) — backend converts schemas to native ORM models

Usage::

    from fastapi_admin_kit.schemas import Schema, Field, Relation
    from fastapi_admin_kit.schemas.builtin import USER_SCHEMA

    # Built-in schemas are ready to use
    columns = USER_SCHEMA.fields
    relations = USER_SCHEMA.relations
"""

from fastapi_admin_kit.schemas.builtin import (
    AUDIT_LOG_SCHEMA,
    LOGIN_ATTEMPT_SCHEMA,
    PERMISSION_SCHEMA,
    ROLE_SCHEMA,
    USER_SCHEMA,
)
from fastapi_admin_kit.schemas.schema import Field, Relation, Schema

__all__ = [
    "Field",
    "Relation",
    "Schema",
    "USER_SCHEMA",
    "ROLE_SCHEMA",
    "PERMISSION_SCHEMA",
    "AUDIT_LOG_SCHEMA",
    "LOGIN_ATTEMPT_SCHEMA",
]
