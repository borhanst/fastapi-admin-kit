# Pagination

Control how list views paginate results.

## Overview

FastAPI Console supports three pagination strategies:

| Strategy | Best For | How It Works |
|----------|----------|--------------|
| **Offset** | Small-medium datasets | Traditional page numbers (page 1, 2, 3...) |
| **Cursor** | Large datasets | Keyset pagination with opaque cursors |
| **Dynamic** | Mixed workloads | Auto-switches based on total count |

## Offset Pagination

Traditional page-number pagination using `OFFSET/LIMIT`. The default strategy.

```python
from fastapi_admin_kit.pagination import OffsetPagination

@admin.register(Product)
class ProductAdmin(ModelAdmin):
    pagination = OffsetPagination()
```

**How it works:**

- Counts total records
- Computes `total_pages = ceil(total / per_page)`
- Clamps page number to valid range
- Returns page number, total pages, and total count

**Template context:**

```
page: 3
total_pages: 10
total: 250
per_page: 25
```

**When to use:**

- Datasets under ~100k records
- When users need to jump to specific pages
- When showing page numbers in the UI

## Cursor Pagination

Keyset pagination using opaque base64-encoded cursors. More efficient for large datasets.

```python
from fastapi_admin_kit.pagination import CursorPagination

@admin.register(Product)
class ProductAdmin(ModelAdmin):
    pagination = CursorPagination(cursor_column="id")
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `cursor_column` | `str` | `None` | Column to use for cursor (default: primary key) |

**How it works:**

- Fetches `per_page + 1` records to detect if there's a next page
- Encodes the last seen value as a base64 cursor
- Forward navigation: `WHERE id > cursor_value`
- Backward navigation: `WHERE id < cursor_value`

**Template context:**

```
next_cursor: "eyJpZCI6IDI1fQ=="
has_next: true
mode: "cursor"
```

**When to use:**

- Datasets over 100k records
- Real-time data where records are frequently inserted
- When page-number jumping isn't needed
- Infinite scroll UIs

## Dynamic Pagination

Automatically switches between offset and cursor based on total record count.

```python
from fastapi_admin_kit.pagination import DynamicPagination

@admin.register(Product)
class ProductAdmin(ModelAdmin):
    # Use offset for < 1000 records, cursor for >= 1000
    pagination = DynamicPagination(threshold=1000)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `cursor_column` | `str` | `None` | Column for cursor pagination |
| `threshold` | `int` | `1000` | Record count to switch strategies |

**How it works:**

- Counts total records
- If `total <= threshold`: uses `OffsetPagination`
- If `total > threshold`: uses `CursorPagination`

**Template context:**

```
# When using offset mode:
mode: "dynamic_offset"
page: 1
total_pages: 5

# When using cursor mode:
mode: "dynamic_cursor"
next_cursor: "eyJpZCI6IDI1fQ=="
has_next: true
```

**When to use:**

- Datasets with unpredictable size
- When you want page numbers for small tables but cursor for large ones
- Migration from offset to cursor pagination

## Configuration

### Per-Model Pagination

Set pagination per model via `ModelAdmin`:

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    per_page = 50
    pagination = CursorPagination(cursor_column="created_at")

@admin.register(Category)
class CategoryAdmin(ModelAdmin):
    per_page = 25
    pagination = OffsetPagination()  # Default for small tables
```

### Global Default

Set the default pagination strategy for all models via `Admin`:

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    per_page_default=25,
)
```

Models without explicit `pagination` use the offset strategy by default.

## Template Variables

All pagination strategies provide these template variables:

| Variable | Type | Description |
|----------|------|-------------|
| `items` | `list` | Current page records |
| `total` | `int` | Total record count |
| `per_page` | `int` | Records per page |
| `page` | `int \| None` | Current page number (offset only) |
| `total_pages` | `int \| None` | Total pages (offset only) |
| `next_cursor` | `str \| None` | Next page cursor (cursor only) |
| `has_next` | `bool` | Whether next page exists |
| `mode` | `str` | Active pagination mode |

## API Response Format

The JSON API returns pagination metadata in list responses:

```json
{
    "items": [...],
    "total": 250,
    "page": 3,
    "per_page": 25,
    "total_pages": 10,
    "next_cursor": "eyJpZCI6IDc1fQ==",
    "has_next": true
}
```

## Next Steps

- [Model Registration](model-registration.md) — Configure per-model options
- [Widgets & Forms](widgets-forms.md) — Customize form fields
- [API Reference](../api/admin.md) — Pagination API documentation
