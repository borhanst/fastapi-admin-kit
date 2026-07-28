# Navigation & Sidebar

Customize the admin sidebar, navigation groups, and menu structure.

## Auto-Generated Sidebar

By default, the sidebar is auto-generated from registered models:

- Models are grouped by their `tag` or `tags` attribute
- Icons come from the `icon` attribute
- Order is controlled by `nav_order` (lower = higher position)

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    tag = "inventory"
    icon = "inventory_2"
    nav_order = 10
```

## Custom Nav Groups

Define your own navigation structure:

```python
from fastapi_admin_kit.nav import NavGroupConfig

admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    nav_groups=[
        NavGroupConfig(
            label="Products",
            icon="inventory_2",
            items=["products", "categories"],
        ),
        NavGroupConfig(
            label="Orders",
            icon="shopping_cart",
            items=["orders", "payments"],
        ),
    ],
)
```

## Sidebar Builder

Override the entire sidebar generation with a custom builder:

```python
from fastapi_admin_kit.nav import SidebarBuilder

class MySidebarBuilder(SidebarBuilder):
    def build(self, request, user):
        # Custom sidebar logic
        items = [...]
        return items

admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    sidebar_builder=MySidebarBuilder(),
)
```

## Navigation Options

### Per-Model Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `icon` | `str` | `None` | Material Symbols icon name |
| `tag` | `str` | `None` | Single nav group tag |
| `tags` | `list[str]` | `None` | Multiple nav group tags |
| `nav_order` | `int` | `999` | Sidebar ordering (lower = higher) |
| `nav_children` | `list[NavItemConfig]` | `None` | Nested sub-menu items |
| `verbose_name` | `str` | Auto | Display name in sidebar |
| `verbose_name_plural` | `str` | Auto | Plural display name |

### Admin-Level Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `nav_groups` | `list[NavGroupConfig]` | `None` | Custom navigation groups |
| `sidebar_builder` | `SidebarBuilder` | `None` | Custom sidebar builder |
| `require_tags` | `bool` | `False` | Require models to have nav tags |
| `sidebar_style` | `str` | `"default"` | Sidebar visual style |
| `sidebar_position` | `str` | `"left"` | `left` or `right` |
| `mobile_sidebar` | `str` | `"overlay"` | Mobile sidebar behavior |

## Nested Nav Items

Create sub-menu items:

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    nav_children = [
        {"label": "All Products", "url": "/admin/products/"},
        {"label": "Active Only", "url": "/admin/products/?is_active=true"},
    ]
```

## Active State

The current page is automatically highlighted in the sidebar based on the URL.

## Collapsible Sidebar

The sidebar can be collapsed to icons-only mode. Users toggle it with a button in the topbar.

## Nav Badges

Show counts or status badges on sidebar items via custom sidebar builders.

## Next Steps

- [Model Registration](model-registration.md) — Configure per-model nav options
- [Configuration](../getting-started/configuration.md) — Admin-level nav options
