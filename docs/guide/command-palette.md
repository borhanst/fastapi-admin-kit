# Command Palette

A global search interface that lets you quickly navigate to any model or field in the admin panel.

## Opening the Palette

- Press `⌘K` (macOS) or `Ctrl+K` (Windows/Linux)
- Click the search bar in the top navigation

## How It Works

The command palette performs a pure metadata scan — no database queries. It searches:

- **Model names** — Matches against verbose names and table names
- **Field names** — Matches against field labels and column names

Results are ranked with model matches first, followed by field matches (max 15 results).

## Keyboard Navigation

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate results |
| `Enter` | Open selected result |
| `Esc` | Close palette |

## API Endpoint

The search functionality is exposed via:

```
GET /admin/search/suggestions?q=<query>
```

**Response format:**

```json
{
  "suggestions": [
    {
      "type": "model",
      "model": "products",
      "label": "Products",
      "sublabel": "products",
      "url": "/admin/products"
    },
    {
      "type": "field",
      "model": "products",
      "field": "name",
      "label": "Products → Name",
      "sublabel": "products.name",
      "url": "/admin/products?q=name"
    }
  ],
  "query": "name"
}
```

## Customizing Search Results

To influence what appears in search results, configure these on your `ModelAdmin`:

```python
@admin.register(Product)
class ProductAdmin(ModelAdmin):
    # These fields appear in command palette suggestions
    search_fields = ["name", "sku", "description"]
    list_display = ["name", "price", "stock"]
```

Fields listed in `search_fields` and `list_display` are included as searchable items in the palette.

## Disabling Search for a Model

To exclude a model from the command palette, set `skip_auto_routes`:

```python
@admin.register(InternalLog)
class InternalLogAdmin(ModelAdmin):
    skip_auto_routes = True  # Won't appear in command palette
```
