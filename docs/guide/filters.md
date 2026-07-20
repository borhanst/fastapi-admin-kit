# Filters

Filter list views with sidebar filters for text, boolean, relation, and enum fields.

## Overview

Filters appear in the sidebar of list views, allowing users to narrow down results. FastAPI Admin Kit includes four built-in filter types and a registry for custom filters.

## Built-in Filters

### TextFilter

Text/substring matching:

```python
from fastapi_admin_kit.filters import TextFilter

@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_filter = ["name", "description"]
```

### BooleanFilter

True/false toggle:

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_filter = ["is_active", "is_featured"]
```

### RelationFilter

Filter by related model:

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_filter = ["category", "brand"]
```

### EnumFilter

Filter by enum choices:

```python
from sqlalchemy import Enum

class Product(Base):
    status = Column(Enum("draft", "published", "archived"))

@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_filter = ["status"]
```

## Configuration

### Basic Usage

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_filter = ["is_active", "category", "status"]
```

### Horizontal Layout

Display filters horizontally instead of vertically:

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_filter = ["is_active", "category"]
    list_filter_horizontal = True
```

### Per-Filter Options

Customize individual filter UI:

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_filter = ["is_active", "category"]
    list_filter_options = {
        "is_active": {"label": "Active Only"},
        "category": {"label": "Product Category"},
    }
```

## Filter Registry

Register custom filter types globally:

```python
from fastapi_admin_kit.filters import FilterRegistry

class DateRangeFilter(Filter):
    """Custom date range filter"""
    ...

FilterRegistry.register("date_range", DateRangeFilter)
```

## Query Behavior

Filters are applied as query parameters:

```
/admin/products/?is_active=true&category=electronics
```

Multiple filters are AND'd together.

## Next Steps

- [Model Registration](model-registration.md) — Configure list filters
- [Widgets & Forms](widgets-forms.md) — Form widgets
