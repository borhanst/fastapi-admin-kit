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

### SimpleFilter

Django `SimpleListFilter` style: declare `parameter_name` + `title` as class
attributes and pass the *class itself* in `list_filter` — no constructor args,
no instance:

```python
from fastapi_admin_kit.filters import SimpleFilter

class InStockFilter(SimpleFilter):
    parameter_name = "in_stock"
    title = "Stock Status"
    field_type = "boolean"

    def apply(self, query_adapter, query, model, value):
        raw = value.get("exact") if isinstance(value, dict) else value
        if raw and raw.lower() in ("1", "true"):
            return model.stock > 0
        if raw:
            return model.stock <= 0
        return None

    def get_choices(self, session=None):
        return [("", "All"), ("1", "In stock"), ("0", "Out of stock")]

@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_filter = [InStockFilter]   # class itself, no instantiation
```

## Query Parameter Lookups

Filters are applied as query parameters in both the admin UI list view and the
JSON API. Lookups follow the field-name convention (`<field>__<lookup>`):

```
name=value                     exact match
name__icontains=term           case-insensitive contains
name__startswith=Jo            starts with
name__endswith=hn              ends with
price__gt=100                  greater than
price__gte=100                 greater than or equal
price__lt=50                   less than
price__lte=200                 less than or equal
price__range=10,200            range (inclusive)
id__in=1,2,3                   in list
is_active=1                    boolean (1/true/yes, 0/false/no)
category=1                     relation exact match
```

Examples:

```
/admin/products/?name__icontains=phone&price__gte=100
/api/products/?category=2&price__range=10,200
```

Multiple filters are AND'd together. Range values are comma-separated pairs;
`in` values are comma-separated lists.

On the JSON API, the list endpoint documents every configured filter as
optional query parameters in the OpenAPI/Swagger schema — add a filter to
`list_filter` and it (plus the lookups its field type supports) shows up in
`/openapi.json` automatically.

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
