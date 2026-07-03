# Plugins

Extend the admin with custom plugins.

## Plugin Architecture

The admin is built as a layered stack of replaceable components. Every layer exposes a protocol that you can implement:

```
Admin Init
    │
    ▼
Plugin Registry
    │
    ├──► Inspector Layer (Column/Rel meta)
    ├──► Auth Layer (Backend/Session)
    ├──► RBAC Layer (Checker/Rules)
    ├──► Widget Registry (Type→Widget map)
    ├──► Hook/Event Bus (before/after)
    ├──► Route Factory (Auto-generated)
    ├──► Form Pipeline (Fields → Widgets → Render)
    ├──► Template Layer (Jinja2)
    ├──► Storage Layer (Local/S3/...)
    └──► Audit Layer (Writer/Serializer/Sinks)
```

Every arrow is a protocol boundary — a place where you can insert your own implementation.

## Creating a Plugin

### Basic Plugin Structure

```python
from fastapi_admin_kit.plugins import AdminPlugin

class MyPlugin(AdminPlugin):
    name = "my-plugin"
    description = "My custom plugin"
    version = "1.0.0"
    
    def setup(self, admin):
        """Called when the plugin is registered"""
        # Register widgets
        admin.widget_registry.register("my_widget", MyWidget)
        
        # Add routes
        admin.add_route("/my-endpoint/", my_handler)
        
        # Register hooks
        admin.hooks.register("after_create", self.on_create)
    
    def on_create(self, obj, request):
        """Hook called after object creation"""
        print(f"Created: {obj}")
```

### Register the Plugin

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    plugins=[MyPlugin()],
)
```

## Extension Points

### Widget Plugins

Add or override widgets:

```python
class RichTextPlugin(AdminPlugin):
    name = "richtext"
    
    def setup(self, admin):
        # Register new widget
        admin.widget_registry.register("richtext", RichTextWidget)
        
        # Override built-in widget by type
        admin.widget_registry.register_type("Text", RichTextWidget)
        
        # Override by field name pattern
        admin.widget_registry.register_field_pattern("content", RichTextWidget)
```

### Form Pipeline Plugins

Customize form generation:

```python
class CustomFormPlugin(AdminPlugin):
    name = "custom-form"
    
    def setup(self, admin):
        # Custom field label resolver
        admin.form_pipeline.set_label_resolver(my_label_resolver)
        
        # Custom required detector
        admin.form_pipeline.set_required_detector(my_required_detector)
        
        # Custom field ordering
        admin.form_pipeline.set_field_orderer(my_field_orderer)
        
        # Add extra (non-model) fields
        admin.form_pipeline.add_extra_field("confirm_password", PasswordWidget())
```

### Validation Plugins

Add custom validation:

```python
class ValidationPlugin(AdminPlugin):
    name = "validation"
    
    def setup(self, admin):
        # Global validator
        admin.add_global_validator(my_global_validator)
        
        # Async validator
        admin.add_async_validator(my_async_validator)
```

### Lifecycle Hook Plugins

Tap into object lifecycle:

```python
class LifecyclePlugin(AdminPlugin):
    name = "lifecycle"
    
    def setup(self, admin):
        # Per-model hooks
        admin.hooks.register("before_create", self.before_create)
        admin.hooks.register("after_create", self.after_create)
        admin.hooks.register("before_update", self.before_update)
        admin.hooks.register("after_update", self.after_update)
        admin.hooks.register("before_delete", self.before_delete)
        admin.hooks.register("after_delete", self.after_delete)
    
    def after_create(self, obj, request):
        # Send notification
        send_notification(f"New {type(obj).__name__} created")
```

### Route Plugins

Add custom routes:

```python
class APIPlugin(AdminPlugin):
    name = "api"
    
    def setup(self, admin):
        # Add global admin routes
        admin.add_route("/api/stats/", self.get_stats)
        
        # Add routes to specific model
        admin.add_model_route("products", "/export/", self.export_products)
        
        # Custom bulk actions
        admin.add_bulk_action("products", "export_csv", self.export_csv)
    
    async def get_stats(self, request):
        return {"total_products": db.query(Product).count()}
```

### Auth Plugins

Customize authentication:

```python
class OAuthPlugin(AdminPlugin):
    name = "oauth"
    
    def setup(self, admin):
        # Custom auth backend
        admin.set_auth_backend(OAuthBackend())
        
        # Custom session backend
        admin.set_session_backend(RedisSessionBackend())
        
        # Multi-factor auth hook
        admin.auth.add_mfa_hook(self.verify_mfa)
```

### RBAC Plugins

Customize permissions:

```python
class ABACPlugin(AdminPlugin):
    name = "abac"
    
    def setup(self, admin):
        # Custom permission checker
        admin.set_permission_checker(ABACChecker())
        
        # Custom permission actions
        admin.add_permission_action("approve", "Approve")
        admin.add_permission_action("reject", "Reject")
```

### Storage Plugins

Customize file storage:

```python
class S3Plugin(AdminPlugin):
    name = "s3-storage"
    
    def setup(self, admin):
        # Set storage backend
        admin.set_storage(S3Storage(
            bucket="my-bucket",
            region="us-east-1",
            access_key=os.environ["AWS_ACCESS_KEY_ID"],
            secret_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        ))
```

### Audit Log Plugins

Customize audit logging:

```python
class AuditPlugin(AdminPlugin):
    name = "custom-audit"
    
    def setup(self, admin):
        # Custom audit writer
        admin.set_audit_writer(MyAuditWriter())
        
        # Custom snapshot serializer
        admin.set_snapshot_serializer(MySnapshotSerializer())
        
        # Add audit sinks
        admin.add_audit_sink(ElasticSearchSink())
        admin.add_audit_sink(WebhookSink())
```

### Dashboard Plugins

Customize the dashboard:

```python
class DashboardPlugin(AdminPlugin):
    name = "dashboard"
    
    def setup(self, admin):
        # Custom stat cards
        admin.dashboard.add_stat_card("revenue", self.get_revenue)
        
        # Custom charts
        admin.dashboard.add_chart("sales", self.render_sales_chart)
        
        # Custom widgets
        admin.dashboard.add_widget("recent_orders", self.render_recent_orders)
```

### UI & Template Plugins

Customize the UI:

```python
class UIPlugin(AdminPlugin):
    name = "ui"
    
    def setup(self, admin):
        # Custom template directory
        admin.add_template_dir("my_templates/")
        
        # Override individual template
        admin.override_template("pages/list.html", "my_templates/list.html")
        
        # Inject custom CSS/JS
        admin.add_css("my_styles.css")
        admin.add_js("my_script.js")
        
        # Custom sidebar sections
        admin.sidebar.add_section("Reports", [
            {"label": "Sales", "url": "/admin/reports/sales/"},
            {"label": "Inventory", "url": "/admin/reports/inventory/"},
        ])
        
        # Custom Jinja2 globals
        admin.jinja_env.globals["my_function"] = my_function
        
        # Custom Jinja2 filters
        admin.jinja_env.filters["my_filter"] = my_filter
```

### Inspector Plugins

Customize model inspection:

```python
class InspectorPlugin(AdminPlugin):
    name = "inspector"
    
    def setup(self, admin):
        # Custom column type inspector
        admin.inspector.set_column_inspector(MyColumnInspector())
        
        # Custom relationship inspector
        admin.inspector.set_relationship_inspector(MyRelationshipInspector())
```

## Complete Plugin Example

### Rich Text Editor Plugin

```python
from fastapi_admin_kit.plugins import AdminPlugin
from fastapi_admin_kit.widgets import Widget

class RichTextWidget(Widget):
    macro_name = "richtext"
    
    def render_context(self, field, value):
        ctx = super().render_context(field, value)
        ctx["toolbar"] = ["bold", "italic", "link", "image"]
        return ctx

class RichTextPlugin(AdminPlugin):
    name = "richtext"
    description = "Adds rich text editor support"
    version = "1.0.0"
    
    def setup(self, admin):
        # Register widget
        admin.widget_registry.register("richtext", RichTextWidget)
        
        # Auto-detect Text fields as richtext
        admin.widget_registry.register_type("Text", RichTextWidget)
        
        # Add template
        admin.add_template_dir("richtext_templates/")
        
        # Add CSS/JS
        admin.add_css("richtext.css")
        admin.add_js("richtext.js")

# Usage
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    plugins=[RichTextPlugin()],
)
```

### Tenant Isolation Plugin

```python
from fastapi_admin_kit.plugins import AdminPlugin
from fastapi import Request

class TenantPlugin(AdminPlugin):
    name = "tenant"
    description = "Multi-tenant data isolation"
    version = "1.0.0"
    
    def setup(self, admin):
        # Add middleware
        admin.add_middleware(TenantMiddleware)
        
        # Override queryset per model
        admin.hooks.register("get_queryset", self.filter_queryset)
    
    def filter_queryset(self, query, model, request):
        """Filter query by tenant"""
        tenant_id = request.state.tenant_id
        return query.filter_by(tenant_id=tenant_id)

class TenantMiddleware:
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)
            # Extract tenant from session/header
            request.state.tenant_id = get_tenant_from_request(request)
        return await self.app(scope, receive, send)

# Usage
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    plugins=[TenantPlugin()],
)
```

## Plugin Load Order

Plugins are loaded in the order they're registered. If two plugins register the same extension point, the last one wins.

```python
admin = Admin(
    plugins=[
        PluginA(),  # Loaded first
        PluginB(),  # Loaded second (overrides PluginA if conflict)
    ],
)
```

## Third-Party Plugin Contract

To create a distributable plugin package:

1. Create a package with `AdminPlugin` subclass
2. Add entry point in `pyproject.toml`:

```toml
[project.entry-points."fastapi_admin_kit.plugins"]
my_plugin = "my_plugin:MyPlugin"
```

3. Users install with:

```bash
pip install fastapi-admin-kit-my-plugin
```

4. Auto-discover:

```python
admin = Admin(
    auto_discover_plugins=True,
)
```

## Next Steps

- [Configuration](../getting-started/configuration.md) — Admin configuration options
- [API Reference](../api/admin.md) — Admin API documentation
