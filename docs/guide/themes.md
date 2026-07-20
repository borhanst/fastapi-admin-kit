# Themes & UI Customization

Customize the admin panel appearance with themes, colors, and layout options.

## Theme Presets

FastAPI Admin Kit ships with 6 built-in theme presets:

| Preset | Description |
|--------|-------------|
| `editorial` | Warm serif typography, paper-like textures |
| `modern` | Clean sans-serif, rounded corners |
| `midnight` | Dark theme with indigo accents |
| `paper` | Classic paper aesthetic |
| `forest` | Green-tinted natural theme |
| `minimal` | Sharp edges, no decorative elements |

### Use a Preset

```python
from fastapi_admin_kit.config import ThemeConfig

admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    theme=ThemeConfig(preset="modern"),
)
```

## Custom Colors

Override primary colors:

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    primary_color="#6366f1",
    primary_color_dark="#4f46e5",
)
```

## Dark Mode

### Default State

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    dark_mode_default=True,  # Start in dark mode
)
```

Users can toggle dark mode via the topbar toggle button. The preference is saved in localStorage.

## Layout Options

### Sidebar

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `sidebar_style` | `str` | `"default"` | Sidebar visual style |
| `sidebar_position` | `str` | `"left"` | `left` or `right` |
| `mobile_sidebar` | `str` | `"overlay"` | Mobile sidebar behavior |

### Table

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `table_style` | `str` | `"default"` | Table visual style |
| `table_row_height` | `str` | `"normal"` | `compact`, `normal`, or `relaxed` |

### Form

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `form_layout` | `str` | `"two-column"` | `single-column` or `two-column` |
| `form_spacing` | `str` | `"normal"` | `compact`, `normal`, or `relaxed` |

### Content

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `content_width` | `str` | `"default"` | `narrow`, `default`, or `wide` |
| `topbar_style` | `str` | `"default"` | Top navigation bar style |

## Custom CSS

### Inline CSS

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    custom_css="""
        .sidebar { background-color: #1e293b; }
        .topbar { border-bottom: 2px solid #6366f1; }
    """,
)
```

### External CSS File

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    custom_css_url="/static/admin-overrides.css",
)
```

## Custom JavaScript

### Inline JS

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    custom_js="console.log('Admin loaded');",
)
```

### External JS File

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    custom_js_url="/static/admin-overrides.js",
)
```

## Environment Badge

Show an environment badge in the topbar:

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    environment_label="Production",
    environment_color="danger",  # info, success, warning, danger
)
```

## Theme Settings Page

Users can customize themes visually at `/admin/settings/theme`.

## Custom Templates

Override any Jinja2 template by placing files in your template directory:

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
)
admin.add_template_dir("my_templates/")
```

Template hierarchy:

1. Your custom templates (highest priority)
2. Admin built-in templates

## Next Steps

- [Configuration](../getting-started/configuration.md) — All configuration options
- [Plugins](plugins.md) — Extend via plugins
