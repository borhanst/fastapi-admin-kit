# Audit Logging

Track all changes made through the admin panel.

## Overview

Every create, update, and delete action is automatically recorded. No configuration needed — it works out of the box for all registered models.

## What Gets Logged

| Action | What's Recorded |
|--------|-----------------|
| CREATE | Full object snapshot |
| UPDATE | Before/after diff + full snapshot |
| DELETE | Full object snapshot before deletion |

## Audit Log Schema

```sql
CREATE TABLE admin_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    user_id         INTEGER REFERENCES admin_users(id),
    user_email      VARCHAR(255),           -- Denormalized for display
    action          VARCHAR(10) NOT NULL,    -- CREATE | UPDATE | DELETE
    model_name      VARCHAR(255) NOT NULL,   -- e.g., "Product"
    table_name      VARCHAR(255) NOT NULL,   -- e.g., "products"
    object_id       VARCHAR(255) NOT NULL,   -- PK as string
    object_repr     VARCHAR(500),           -- Human label
    changes         JSONB,                  -- Diff for UPDATE
    full_snapshot   JSONB,                  -- Full object state
    ip_address      VARCHAR(45),            -- IPv4 or IPv6
    user_agent      TEXT,
    timestamp       TIMESTAMP WITH TIME ZONE DEFAULT now()
);
```

## Change Diff Format

For UPDATE actions, only changed fields are recorded:

```json
{
    "price": {
        "before": 99.99,
        "after": 149.99
    },
    "stock": {
        "before": 10,
        "after": 0
    }
}
```

## How It Works

The system uses SQLAlchemy event hooks:

```python
# Attached automatically at startup
@event.listens_for(session_factory, "before_flush")
def before_flush(session, flush_context, instances):
    # Capture state before changes
    for obj in session.dirty:
        obj._audit_before = snapshot(obj)

@event.listens_for(session_factory, "after_flush")
def after_flush(session, flush_context):
    # Record changes after flush
    for obj in session.new:
        write_audit(session, user, "CREATE", obj)
    
    for obj in session.dirty:
        before = obj._audit_before
        after = snapshot(obj)
        diff = compute_diff(before, after)
        if diff:
            write_audit(session, user, "UPDATE", obj, diff)
    
    for obj in session.deleted:
        write_audit(session, user, "DELETE", obj)
```

## Audit Log UI

Access the audit log at `/admin/audit-log/`:

### Features

- Timeline-style feed sorted by timestamp
- Color coding: green = CREATE, yellow = UPDATE, red = DELETE
- Each entry shows: timestamp, user, action, model, object
- Click to expand full diff or snapshot
- Diff view: before/after table with highlighted changes

### Filters

Filter the audit log by:

- **Model:** `?model=Product`
- **User:** `?user_id=5`
- **Action:** `?action=UPDATE`
- **Date range:** `?from=2024-01-01&to=2024-12-31`
- **Object:** `?object_id=42`

### Per-Object History

Every edit form has a "History" tab showing all audit entries for that specific record.

## Configuration

### Enable/Disable Audit Logging

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    audit_enabled=True,  # Default: True
)
```

### Audit Retention

Set how long to keep audit logs:

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    audit_retention_days=365,  # Keep for 1 year
)
```

Default: keep forever (no purge).

### Purge Old Logs

Run manually or schedule as a cron job:

```python
from fastapi_admin_kit.audit import purge_old_logs

# Delete logs older than retention period
purge_old_logs(session, retention_days=365)
```

## Custom Audit Writer

Override the default audit writer:

```python
from fastapi_admin_kit.audit import AuditWriter

class MyAuditWriter(AuditWriter):
    
    def write(self, session, user, action, obj, diff=None, snapshot=None):
        # Custom write logic
        # e.g., send to external service
        pass

admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    audit_writer=MyAuditWriter(),
)
```

## External Audit Sinks

Send audit logs to external services:

```python
from fastapi_admin_kit.audit import AuditSink

class ElasticSearchSink(AuditSink):
    
    def emit(self, entry):
        # Send to Elasticsearch
        es.index(index="audit-logs", body=entry.to_dict())

class WebhookSink(AuditSink):
    
    def emit(self, entry):
        # Send to webhook
        requests.post("https://your-service.com/audit", json=entry.to_dict())

admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    audit_sinks=[ElasticSearchSink(), WebhookSink()],
)
```

## Context Variable

The current user is available via a context variable:

```python
from fastapi_admin_kit.audit.context import get_audit_user

# In any code path
user = get_audit_user()
if user:
    print(f"Action by: {user.email}")
```

This is set by middleware on every admin request.

## Snapshot Function

Objects are serialized to JSON-safe dicts:

```python
from fastapi_admin_kit.audit.diff import snapshot, serialize_value

# snapshot() converts a SQLAlchemy object to a dict
data = snapshot(product_instance)

# serialize_value() makes individual values JSON-safe
# - datetime → ISO format string
# - Decimal → float
# - UUID → string
# - bytes → "<binary>"
```

## Performance Considerations

### Indexes

The audit log table has these indexes for fast queries:

```sql
CREATE INDEX idx_audit_model ON admin_audit_log(model_name, table_name);
CREATE INDEX idx_audit_user ON admin_audit_log(user_id);
CREATE INDEX idx_audit_timestamp ON admin_audit_log(timestamp DESC);
CREATE INDEX idx_audit_object ON admin_audit_log(table_name, object_id);
```

### Large Tables

For high-traffic tables, consider:

1. **Disable audit per model:**

```python
@admin.register(HighVolumeModel)
class HighVolumeModelAdmin(ModelAdmin):
    audit_enabled = False
```

2. **Use external sinks** instead of database storage

3. **Purge regularly** with `audit_retention_days`

## Next Steps

- [Plugins](plugins.md) — Extend with custom plugins
- [Configuration](../getting-started/configuration.md) — More configuration options
- [API Reference](../api/admin.md) — Admin API documentation
