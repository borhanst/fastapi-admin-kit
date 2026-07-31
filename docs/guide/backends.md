# Multi-ORM Backend Architecture

FastAPI Admin Kit uses a **protocol-driven, multi-ORM architecture** that decouples the admin layer from any specific ORM. Built-in adapters ship for SQLAlchemy, and you can swap in custom backends for MongoDB, Django ORM, or any data layer.

## Architecture Overview

Three-layer decoupling:

```
Admin UI (FastAPI + Jinja2 + HTMX)
        |
        ▼
┌─────────────────────────────────────┐
│    Protocol Interfaces               │
│   (structure-only contracts)         │
└───────────────┬───────────────────────┘
                |
                ▼
┌─────────────────────────────────────┐
│       Schema Layer (declarative)    │
│   Backend-agnostic model definitions│
└───────────────┬───────────────────────┘
                |
                ▼
┌─────────────────────────────────────┐
│    Materialization Layer (adapters) │
│    Convert schemas to native ORM models │
└─────────────────────┬─────────────────┘
                      |
                      ▼
┌─────────────────────────────────────┐
│      Backend (composite adapter)     │
│  Wires introspection, sessions, queries│
│                 and audit together      │
└─────────────────────────────────────┘
```

## Protocol Interfaces

Six protocol interfaces define the contracts that all ORM backends must implement:

### 1. `IntrospectionBackend`
Inspects models to extract column metadata, primary keys, relationships, and type information.
- `inspect_model()` — returns columns and relationships
- `get_pk_field()` — primary key field names
- `cast_pk_value()` — type-safe PK casting
- `is_abstract()` — skip abstract models
- `get_relationship_names()` — all relationship keys
- `get_relationship()` — get a relationship by name
- `get_relationship_local_columns()` — FK columns for relationships
- `get_column_type_name()` — database type for columns
- `get_column_attr()` — column attribute from field name

### 2. `SessionBackend`
Per-request session lifecycle with get/add/flushor validate methods.

### 3. `QueryBackend`
Chainable query building: select, filter, sort, join, and paginate.

### 4. `AuditBackend`
Change tracking: attach listeners, snapshot changes, and compute diffs.

### 5. `DatabaseBackend`
Connection lifecycle: create engine, run DDL, auto-migrate schemas.

## Schema Layer

Built-in admin models (User, Role, Permission, AuditLog, LoginAttempt) are defined as backend-agnostic `Schema` objects:

```python
from fastapi_admin_kit.schemas import Schema, Field, Relation
from fastapi_admin_kit.schemas.builtin import USER_SCHEMA

# Schema is ORM-agnostic
# Backends materialize() it into native models
```

### Schema Components

- `Field` — column definition (name, type, nullable, etc.)
- `Relation` — relationship definition (many-to-many, one-to-many, many-to-one)
- `Schema` — model with table_name, fields, and relations

## Materialization Layer

Each backend implements `materialize(schema, base)` to convert `Schema` objects into native ORM model classes:

### SQLAlchemy Backend
- Converts schema fields to SQLAlchemy `Column` objects
- Handles type mapping (integer→Integer, string→String, datetime→DateTime)
- Supports auto-increment, nullable, unique, indexes
- Creates dynamically with ``__tablename__`` and ``__table_args__``

Custom backends implement the same materialization for their ORM.

## Backend Composition

The **SqlAlchemyBackend** is a composite adapter that wires all adapters:

```python
class SqlAlchemyBackend:
    def __init__(self, admin_database=None, **adapters):
        self.introspection = SqlAlchemyIntrospectionAdapter()
        self.query = SqlAlchemyQueryAdapter()
        self.audit = SqlAlchemyAuditBackend()
        self.database = SqlAlchemyDatabaseBackend(admin_database=admin_database)
```

## Using Custom Backends

### When to Use a Custom Backend

1. **Different ORM** — MongoDB, Django, Peewee, CouchDB
2. **Non-SQL data sources** — REST APIs, GraphQL, Kafka
3. **Legacy systems** — Existing database models
4. **Performance** — No SQL when not needed

### Defining a Custom Backend

```python
from fastapi_admin_kit.backends import (
    IntrospectionBackend,
    SessionBackend,
    QueryBackend,
    AuditBackend,
    DatabaseBackend,
)

class MyIntrospectionBackend(IntrospectionBackend):
    def inspect_model(self, model):
        # Your implementation
        ...

    def get_pk_field(self, model):
        # Your implementation
        ...
class MySessionBackend(SessionBackend):
    # Implement all 10+ session methods
    pass

class MyQueryBackend(QueryBackend):
    # Implement all 12+ query methods
    pass

class MyAuditBackend(AuditBackend):
    # Implement attach_listeners(), snapshot(), compute_diff()
    pass

class MyDatabaseBackend(DatabaseBackend):
    # Implement create_connection(), create_tables(), auto_migrate()
    pass

class MyBackend:
    """Optional composite backend for convenience"""
    def __init__(self):
        self.introspection = MyIntrospectionBackend()
        self.session = MySessionBackend()
        self.query = MyQueryBackend()
        self.audit = MyAuditBackend()
        self.database = MyDatabaseBackend()
```

### Integrating with Admin

```python
from fastapi_admin_kit import Admin
from fastapi_admin_kit.backends import AdminState

# Pass your custom backend to Admin
admin = Admin(
    app=app,
    engine=your_engine,
    backend=MyBackend()  # Your custom backend
)

# Backend adapters are registered in app.state
state: AdminState = app.state.admin_state
state.backend              # Your backend instance
state.admin_backend        # Composite backend (alias)
state.admin_session_backend  # Session adapter
state.admin_query_adapter   # Query adapter
state.admin_introspection_adapter  # Introspection adapter
state.admin_audit_backend   # Audit backend
```

## Available Backends

### Built-in: SqlAlchemyBackend

The default backend for FastAPI Admin Kit. Ships with all adapters optimized for SQLAlchemy+SQLModel.

**Location:** `fastapi_admin_kit.backends.sqlalchemy.SqlAlchemyBackend`

**Composition:**
- `SqlAlchemyIntrospectionAdapter` — model introspection
- `SqlAlchemySessionAdapter` — async session handling
- `SqlAlchemyQueryAdapter` — chainable queries
- `SqlAlchemyAuditBackend` — change tracking
- `SqlAlchemyDatabaseBackend` — DDL and migration

### Available Adapters

You can compose custom backend from individual adapters:

```python
from fastapi_admin_kit.backends.sqlalchemy import (
    SqlAlchemyIntrospectionAdapter,
    SqlAlchemySessionAdapter,
    SqlAlchemyQueryAdapter,
    SqlAlchemyAuditBackend,
    SqlAlchemyDatabaseBackend,
)

backend = SqlAlchemyBackend(  # Uses all default adapters
    introspection=SqlAlchemyIntrospectionAdapter(),
    query=SqlAlchemyQueryAdapter(),
    audit=SqlAlchemyAuditBackend(),
    database=SqlAlchemyDatabaseBackend(admin_database=db),
)
```

## Backend Configuration

### Default Behavior

When you pass only `app` and `engine` to `Admin()`:

```python
admin = Admin(app=app, engine=engine, secret_key="...")
# Automatically uses SqlAlchemyBackend with all adapters
```

### Passing Custom Backend

```python
admin = Admin(
    app=app,
    engine=engine,
    backend=MyCustomBackend(),  # Replaces the default SqlAlchemyBackend
)
```

### Backend Adapter Overrides

Replace individual adapters (useful for testing or partial overrides):

```python
admin = Admin(
    app=app,
    engine=engine,
    backend=SqlAlchemyBackend(
        introspection=MyCustomIntrospectionAdapter(),  # Custom only
        query=SqlAlchemyQueryAdapter(),  # Default
        audit=SqlAlchemyAuditBackend(),  # Default
    ),
)
```

## Backend Benefits

### 1. Zero Breaking Changes
Existing code using only `Admin(app, engine)` continues to work.

### 2. Migration Path
Can gradually customize without refactoring:

```python
# Step 1: Keep defaults
admin = Admin(app=app, engine=engine)

# Step 2: Replace one adapter (e.g., introspection)
admin.backend.introspection = MyIntrospectionBackend(engine)

# Step 3: Full custom backend
admin = Admin(app=app, engine=engine, backend=MyFullBackend())
```

### 3. Better Testability

```python
# Mock backends in tests
mock_introspection = Mock(spec=IntrospectionBackend)
mock_query = Mock(spec=QueryBackend)
mock_session = Mock(spec=SessionBackend)

admin = Admin(
    app=app,
    engine=test_engine,
    backend=SqlAlchemyBackend(
        introspection=mock_introspection,
        query=mock_query,
        session=mock_session,
    ),
)
```

### 4. Future-Proof

New ORMs (Django, Peewee, ODBC, NoSQL) can plug in without changes to the admin UI, registration logic, or authentication/authorization code.

## Backend Protocol Reference

See the exact protocol definitions:

```python
from fastapi_admin_kit.backends import (
    IntrospectionBackend,
    SessionBackend,
    QueryBackend,
    AuditBackend,
    DatabaseBackend,
)
```

Each protocol method has a detailed doc comment in ``backends/protocols.py``. The SQLAlchemy adapters in ``backends/sqlalchemy.py`` show a concrete implementation.

## Next Steps

- [Model Registration](model-registration.md) — Continue with model setup
- [Schema-first Guide](../guide/model-registration.md) — Learn schema-first approach
- [API Reference](../api/admin.md) — Backend-specific API documentation
