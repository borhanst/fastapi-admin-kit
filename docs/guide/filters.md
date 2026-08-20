# Filters

Filter list views with a robust, Django-style filtering system for text, boolean,
relation, and enum fields — in both the admin UI and the JSON API.

## Overview

FastAPI Admin Kit includes a set of built-in filter classes (auto-detected from
your model columns) plus a registry for custom filters. Filters are ORM-agnostic:
they build clauses through the `QueryBackend` protocol and work with both the
SQLAlchemy and the dependency-free in-memory backends.

## Built-in Filters

### TextFilter

Text matching with `exact`, `icontains`, `startswith` and `endswith` lookups:

```python
from fastapi_admin_kit.filters import TextFilter

@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_filter = ["name", "description"]
```

### ChoiceFilter

Filter by a related/foreign-key field, rendered as a select widget. Auto-detected
for FK and ManyToMany columns:

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_filter = ["category", "brand"]
```

### BooleanFilter

True/false toggle:

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_filter = ["is_active", "is_featured"]
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

### IntegerFilter / NumericFilter

Numeric filters with `gt`, `gte`, `lt`, `lte`, `range` and `in` lookups:

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_filter = ["price", "stock"]
```

### DateRangeFilter / DatetimeRangeFilter / TimeFilter

Temporal filters with `exact`, `gt`/`gte`/`lt`/`lte`, `range`, `in` and legacy
`from`/`to` lookups:

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_filter = ["created_at", "published_on"]
```

## Registry Auto-Detection

`FilterRegistry.auto_generate()` maps column types to filter classes:

| Column type            | Filter class           |
| ---------------------- | ---------------------- |
| FK / ManyToMany        | `ChoiceFilter`         |
| Boolean                | `BooleanFilter`        |
| DateTime / Timestamp   | `DatetimeRangeFilter`  |
| Date                   | `DateRangeFilter`      |
| Time                   | `TimeFilter`           |
| Integer / Float / ...  | `NumericFilter`        |
| Enum                   | `EnumFilter`           |
| otherwise              | `TextFilter`           |

## Custom Filters

Register custom filter types per model via `FilterRegistry.register()`:

```python
from fastapi_admin_kit.filters import FilterRegistry, NumericFilter

class RoundedPriceFilter(NumericFilter):
    def apply(self, query_adapter, query, model, value):
        clause = super().apply(query_adapter, query, model, value)
        if clause is None:
            return None
        return query_adapter.and_(clause, model.price > 0)

FilterRegistry().register("product", RoundedPriceFilter("price"))
```

Custom filter instances can also be placed directly in `list_filter`:

```python
from fastapi_admin_kit.filters import IntegerFilter

@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_filter = ["name", IntegerFilter("price", label="Price")]
```

## Query Parameter Lookups

Filters are applied as query parameters in both the admin UI list view and the
JSON API. Lookups follow the `django-filter` convention (`filter_<field>__<lookup>`):

```
filter_name=value              exact match
filter_name__icontains=term    case-insensitive contains
filter_name__startswith=Jo     starts with
filter_name__endswith=hn       ends with
filter_price__gt=100           greater than
filter_price__gte=100          greater than or equal
filter_price__lt=50            less than
filter_price__lte=200          less than or equal
filter_price__range=10,200     range (inclusive)
filter_id__in=1,2,3            in list
filter_is_active=1             boolean (1/true/yes, 0/false/no)
filter_category=1              relation exact match
```

Examples:

```
/admin/products/?filter_name__icontains=phone&filter_price__gte=100
/api/products/?filter_category=2&filter_price__range=10,200
```

Multiple filters are AND'd together. Range values are comma-separated pairs;
`in` values are comma-separated lists.

## Per-Filter UI Options

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

## Next Steps

- [Model Registration](model-registration.md) — Configure list filters
- [Widgets & Forms](widgets-forms.md) — Form widgets
