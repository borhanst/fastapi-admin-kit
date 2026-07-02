# Widgets & Forms

Customize how form fields are rendered and validated.

## How Forms Work

Forms are generated in two layers:

```
SQLAlchemy Model
      │
      ▼
┌─────────────────────────────────────────┐
│  LAYER 1 — Python Widget Class          │
│  Parse, validate, produce context       │
└─────────────────────┬───────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────┐
│  LAYER 2 — Jinja2 Macro (HTML)          │
│  Renders the HTML using the context     │
└─────────────────────────────────────────┘
```

You can override either layer independently:

| Override | Changes |
|----------|---------|
| Widget class only | Parse logic + validation |
| Macro only | HTML output |
| Both | Complete custom field |
| Neither | Zero config auto-detection |

## Built-in Widgets

### TextInputWidget

For `String` and `VARCHAR` columns:

```python
from fastapi_admin_kit.widgets import TextInputWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "name": TextInputWidget(maxlength=100),
    }
```

### TextareaWidget

For `Text` columns:

```python
from fastapi_admin_kit.widgets import TextareaWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "description": TextareaWidget(rows=10),
    }
```

### NumberInputWidget

For `Integer`, `Float`, `Numeric` columns:

```python
from fastapi_admin_kit.widgets import NumberInputWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "price": NumberInputWidget(step=0.01, min=0),
        "stock": NumberInputWidget(step=1, min=0),
    }
```

### ToggleWidget

For `Boolean` columns:

```python
from fastapi_admin_kit.widgets import ToggleWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "is_active": ToggleWidget(),
    }
```

### SelectWidget

For `Enum` columns:

```python
from fastapi_admin_kit.widgets import SelectWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "status": SelectWidget(choices=[
            ("draft", "Draft"),
            ("published", "Published"),
            ("archived", "Archived"),
        ]),
    }
```

### DateTimeWidget

For `DateTime` and `Date` columns:

```python
from fastapi_admin_kit.widgets import DateTimeWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "published_at": DateTimeWidget(),
    }
```

### JSONEditorWidget

For `JSON` columns:

```python
from fastapi_admin_kit.widgets import JSONEditorWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "metadata": JSONEditorWidget(),
    }
```

### RelationPickerWidget

For `ForeignKey` columns:

```python
from fastapi_admin_kit.widgets import RelationPickerWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "category": RelationPickerWidget(
            search_fields=["name"],  # Fields to search
            display_field="name",    # Field to display
        ),
    }
```

### MultiRelationPickerWidget

For `relationship()` with `uselist=True`:

```python
from fastapi_admin_kit.widgets import MultiRelationPickerWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "tags": MultiRelationPickerWidget(
            search_fields=["name"],
            display_field="name",
        ),
    }
```

### AutocompleteWidget

Datalist autocomplete for text fields with static or dynamic suggestions:

```python
from fastapi_admin_kit.widgets import AutocompleteWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "brand": AutocompleteWidget(
            suggestions=["Nike", "Adidas", "Puma", "Reebok"],
        ),
    }
```

Dynamic suggestions via a callable:

```python
def get_category_suggestions():
    return ["Electronics", "Clothing", "Home", "Sports"]

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "category_name": AutocompleteWidget(
            suggestions_fn=get_category_suggestions,
        ),
    }
```

### PasswordWidget

For password fields — never pre-fills values:

```python
from fastapi_admin_kit.widgets import PasswordWidget

class UserAdmin(ModelAdmin):
    form_widgets = {
        "password": PasswordWidget(),
    }
```

### ReadOnlyWidget

Displays a value without allowing edits:

```python
from fastapi_admin_kit.widgets import ReadOnlyWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "sku": ReadOnlyWidget(),
    }
```

### HiddenWidget

Hidden input field:

```python
from fastapi_admin_kit.widgets import HiddenWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "internal_code": HiddenWidget(),
    }
```

### DatePickerWidget

For `Date` columns (separate from DateTimePicker):

```python
from fastapi_admin_kit.widgets import DatePickerWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "release_date": DatePickerWidget(),
    }
```

### DateTimePickerWidget

For `DateTime` columns:

```python
from fastapi_admin_kit.widgets import DateTimePickerWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "published_at": DateTimePickerWidget(),
    }
```

### FileUploadWidget

For file uploads with size limits and type filtering:

```python
from fastapi_admin_kit.widgets import FileUploadWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "document": FileUploadWidget(
            max_size_mb=10,
            accept=".pdf,.doc,.docx",
        ),
    }
```

### ImageUploadWidget

Specialized file upload restricted to images:

```python
from fastapi_admin_kit.widgets import ImageUploadWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "avatar": ImageUploadWidget(
            max_size_mb=5,
            accept="image/*",
        ),
    }
```

### WysiwygWidget

Rich text editor for HTML content:

```python
from fastapi_admin_kit.widgets import WysiwygWidget

class ArticleAdmin(ModelAdmin):
    form_widgets = {
        "content": WysiwygWidget(height=300),
    }
```

### ArrayWidget

Dynamic list input for JSON array columns:

```python
from fastapi_admin_kit.widgets import ArrayWidget

class ProductAdmin(ModelAdmin):
    form_widgets = {
        "tags": ArrayWidget(min_items=1, max_items=10),
    }
```

## Custom Widget

Create your own widget by extending the base class:

```python
from fastapi_admin_kit.widgets.base import Widget, FieldMeta
from typing import Any

class ColorPickerWidget(Widget):
    macro_name = "color_picker"
    
    def render_context(self, field: FieldMeta, value: Any) -> dict:
        ctx = super().render_context(field, value)
        ctx["presets"] = ["#ef4444", "#f59e0b", "#10b981", "#3b82f6", "#8b5cf6"]
        return ctx
    
    def parse(self, raw: str | None) -> str | None:
        if raw and not raw.startswith("#"):
            return f"#{raw}"
        return raw
    
    def validate(self, value: Any, field: FieldMeta) -> list[str]:
        errors = super().validate(value, field)
        if value and not value.startswith("#"):
            errors.append(f"{field.label} must be a valid hex color.")
        return errors
```

### Register the Widget

```python
from fastapi_admin_kit.widgets import WidgetRegistry

# Register globally
WidgetRegistry.register("color", ColorPickerWidget)

# Or use per-model
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    form_widgets = {
        "color": ColorPickerWidget(),
    }
```

### Create the Jinja2 Macro

```jinja2
{# templates/macros/form_fields.html #}

{% macro color_picker(field, value, id, name, presets) %}
<div class="color-picker-wrapper">
    <input
        type="color"
        id="{{ id }}"
        name="{{ name }}"
        value="{{ value or '#000000' }}"
        class="form-color"
    >
    <div class="color-presets">
        {% for preset in presets %}
            <button
                type="button"
                class="color-preset"
                style="background-color: {{ preset }}"
                @click="$refs.colorInput.value = '{{ preset }}'"
            ></button>
        {% endfor %}
    </div>
</div>
{% endmacro %}
```

## Widget Registry

The widget registry maps column types to widgets:

```python
from fastapi_admin_kit.widgets import WidgetRegistry

# Default mappings
WidgetRegistry.COLUMN_TYPE_MAP = {
    "String": "text_input",
    "Text": "textarea",
    "Integer": "number_input",
    "Float": "number_input",
    "Boolean": "toggle",
    "Date": "date_picker",
    "DateTime": "datetime_picker",
    "Enum": "select",
    "JSON": "json_editor",
}
```

### Override by Type

```python
# Make all String fields use textarea
WidgetRegistry.register_type("String", TextareaWidget(rows=3))
```

### Override by Field Name

```python
# Make any field named "description" use textarea
WidgetRegistry.register_field_pattern("description", TextareaWidget(rows=10))
```

## Form Validation

### Field-Level Validation

```python
from fastapi_admin_kit.widgets.base import Widget, FieldMeta
from typing import Any

class PriceWidget(Widget):
    macro_name = "number_input"
    
    def validate(self, value: Any, field: FieldMeta) -> list[str]:
        errors = super().validate(value, field)
        
        if value is not None:
            try:
                price = float(value)
                if price < 0:
                    errors.append("Price cannot be negative.")
                if price > 999999.99:
                    errors.append("Price is too large.")
            except ValueError:
                errors.append("Price must be a number.")
        
        return errors
```

### Object-Level Validation

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    
    def validate_object(self, obj, data, request) -> list[str]:
        """Validate the entire object after all fields are parsed"""
        errors = []
        
        if data.get("sale_price") and data["sale_price"] >= data.get("price", 0):
            errors.append("Sale price must be less than regular price.")
        
        if data.get("stock") == 0 and data.get("is_active"):
            errors.append("Out of stock items cannot be active.")
        
        return errors
```

### Global Validation Hook

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    global_validator=my_global_validator,
)

def my_global_validator(obj, data, request) -> list[str]:
    """Validate across all models"""
    return []
```

## HTMX Partial Validation

Fields validate on blur via HTMX:

```jinja2
<input
    type="text"
    name="name"
    hx-post="/admin/products/validate/field/"
    hx-trigger="blur"
    hx-vals='{"field": "name"}'
    hx-target="#field-name-errors"
>
<div id="field-name-errors"></div>
```

The server returns error HTML that replaces the error container.

## Relationship Widgets

### ForeignKey (Searchable Dropdown)

```python
class Product(Base):
    category_id = Column(Integer, ForeignKey("categories.id"))
    category = relationship("Category")
```

Automatically rendered as:

```html
<select id="field-category" name="category_id" hx-get="/admin/categories/search/" hx-trigger="keyup delay:300ms">
    <option value="">Select category...</option>
    <!-- Options loaded via HTMX -->
</select>
```

### Many-to-Many (Multi-Select)

```python
class Product(Base):
    tags = relationship("Tag", secondary="product_tags")
```

Rendered as a multi-select with search and removable tags.

## File Upload

File uploads are handled by the storage backend configured on the Admin instance:

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    storage=LocalStorageBackend(path="/uploads"),
    uploads_url="/uploads",
)
```

Use `FileUploadWidget` or `ImageUploadWidget` on the model field to enable upload UI:

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    form_widgets = {
        "image_url": ImageUploadWidget(max_size_mb=5),
        "document": FileUploadWidget(max_size_mb=10, accept=".pdf,.doc"),
    }
```

## Form Context

The form context dictionary passed to templates:

```python
{
    "model_name": "products",
    "verbose_name": "Product",
    "obj": product_instance,  # None for create
    "form_fields": [
        {
            "name": "name",
            "label": "Name",
            "required": True,
            "readonly": False,
            "widget": TextInputWidget,
            "value": "Product Name",
            "errors": [],
        },
        # ... more fields
    ],
    "permissions": {
        "can_view": True,
        "can_create": True,
        "can_edit": True,
        "can_delete": True,
    },
    "submit_url": "/admin/products/create/",
    "back_url": "/admin/products/",
}
```

## Next Steps

- [Audit Logging](audit-logging.md) — Track all changes
- [Plugins](plugins.md) — Extend with custom plugins
- [API Reference](../api/widgets.md) — Widget API documentation
