# Inline Editing & Actions

Edit records directly from list views and run bulk actions.

## Inline Editing

Edit records without leaving the list view using the 3-dot action menu.

### Enable Inline Editing

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    inline_edit = True
    inline_edit_fields = ["name", "price", "stock", "status"]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `inline_edit` | `bool` | `False` | Enable inline editing |
| `inline_edit_fields` | `list[str]` | `None` | Fields shown in inline form |
| `inline_exclude_fields` | `list[str]` | `None` | Fields excluded from inline edit |

### How It Works

1. Click the 3-dot menu on any row
2. Select "Edit"
3. An inline form expands below the row
4. Edit fields and click Save
5. HTMX saves without page reload

## Actions

### Action Types

| Location | Description |
|----------|-------------|
| `list` | Actions on the list view (bulk actions) |
| `row` | Actions per row in the list |
| `detail` | Actions on the detail/edit page |
| `submit_line` | Actions on form submit buttons |

### Built-in Actions

- **Delete** — Confirmation dialog before deletion (available on list, row, detail)

### Custom Actions with Decorator

```python
from fastapi_admin_kit.actions import action

@admin.register(Product)
class ProductAdmin(ModelAdmin):
    actions_row = ["activate"]
    actions_list = ["bulk_activate"]

    @action(
        description="Activate this product",
        icon="check_circle",
        variant="success",
    )
    async def activate(self, objects, request):
        for obj in objects:
            obj.is_active = True
            request.state.db_session.add(obj)
        await request.state.db_session.flush()

    @action(
        description="Activate selected products",
        icon="check_circle",
        variant="success",
        location="list",
    )
    async def bulk_activate(self, objects, request):
        for obj in objects:
            obj.is_active = True
            request.state.db_session.add(obj)
        await request.state.db_session.flush()
```

### Custom Actions with Class

```python
from fastapi_admin_kit.actions.base import Action, ModelAction

class ActivateAction(ModelAction):
    name = "activate"
    label = "Activate"
    icon = "check_circle"
    variant = "success"
    location = "row"
    confirmation_message = "Activate this product?"

    async def execute_single(self, obj, request):
        obj.is_active = True
        request.state.db_session.add(obj)
        await request.state.db_session.flush()

class BulkActivateAction(Action):
    name = "bulk_activate"
    label = "Activate Selected"
    icon = "check_circle"
    variant = "success"
    location = "list"
    permissions = ["edit"]

    async def execute(self, objects, request):
        for obj in objects:
            obj.is_active = True
            request.state.db_session.add(obj)
        await request.state.db_session.flush()

@admin.register(Product)
class ProductAdmin(ModelAdmin):
    actions_row = ["activate"]
    actions_list = ["bulk_activate"]
```

### Action Options

| Option | Type | Description |
|--------|------|-------------|
| `name` | `str` | Unique action identifier |
| `label` | `str` | Display text |
| `icon` | `str` | Material icon name |
| `variant` | `str` | `default`, `primary`, `danger`, `success`, `warning` |
| `location` | `str` | `list`, `row`, `detail`, `submit_line` |
| `permissions` | `list[str]` | Required permissions (e.g., `["edit"]`) |
| `confirmation_message` | `str` | Confirmation dialog text |
| `description` | `str` | Tooltip/description text |

## Lifecycle Hooks

Override behavior at specific points in the CRUD lifecycle:

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):

    def on_create(self, obj, request):
        """Called before INSERT"""
        obj.created_by = request.state.admin_user.id

    def after_create(self, obj, request):
        """Called after INSERT commit"""
        send_notification(f"New product: {obj.name}")

    def on_update(self, obj, data, request):
        """Called before UPDATE"""
        pass

    def after_update(self, obj, request):
        """Called after UPDATE commit"""
        pass

    def on_delete(self, obj, request):
        """Called before DELETE"""
        pass

    def after_delete(self, obj, request):
        """Called after DELETE commit"""
        pass
```

## Next Steps

- [Model Registration](model-registration.md) — Configure actions per model
- [Widgets & Forms](widgets-forms.md) — Form customization
