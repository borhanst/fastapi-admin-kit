"""Backend protocols and SQLAlchemy adapters for multi-ORM support.

Protocols::

    from fastapi_admin_kit.backends import (
        IntrospectionBackend,
        SessionBackend,
        QueryBackend,
        AuditBackend,
        DatabaseBackend,
    )

SQLAlchemy adapters::

    from fastapi_admin_kit.backends import (
        SqlAlchemyIntrospectionAdapter,
        SqlAlchemySessionAdapter,
        SqlAlchemyQueryAdapter,
        SqlAlchemyAuditBackend,
        SqlAlchemyDatabaseBackend,
    )
"""

from fastapi_admin_kit.backends.protocols import (
    AuditBackend,
    ColumnMetaType,
    DatabaseBackend,
    IntrospectionBackend,
    QueryBackend,
    QueryType,
    RelationMetaType,
    SessionBackend,
    SessionType,
)
from fastapi_admin_kit.backends.sqlalchemy import (
    SqlAlchemyAuditBackend,
    SqlAlchemyDatabaseBackend,
    SqlAlchemyIntrospectionAdapter,
    SqlAlchemyQueryAdapter,
    SqlAlchemySessionAdapter,
)

__all__ = [
    # Protocols
    "AuditBackend",
    "ColumnMetaType",
    "DatabaseBackend",
    "IntrospectionBackend",
    "QueryBackend",
    "QueryType",
    "RelationMetaType",
    "SessionBackend",
    "SessionType",
    # SQLAlchemy adapters
    "SqlAlchemyAuditBackend",
    "SqlAlchemyDatabaseBackend",
    "SqlAlchemyIntrospectionAdapter",
    "SqlAlchemyQueryAdapter",
    "SqlAlchemySessionAdapter",
]
