# Configuration

Customize the admin panel to fit your needs.

## Database Configuration

Configure the database connection using `DatabaseConfig` and `DatabaseType`.

```python
from fastapi_admin_kit import Admin, DatabaseConfig, DatabaseType
```

### DatabaseType

| Value | Database | Async Driver |
|-------|----------|-------------|
| `DatabaseType.SQLITE` | SQLite | aiosqlite |
| `DatabaseType.POSTGRESQL` | PostgreSQL | asyncpg |
| `DatabaseType.MYSQL` | MySQL | aiomysql |

### DatabaseConfig

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `url` | `str` | `None` | Full connection URL (auto-normalized to async driver) |
| `db_type` | `DatabaseType` | `SQLITE` | Database dialect (used when no URL given) |
| `host` | `str` | `""` | Database host |
| `port` | `int` | `None` | Database port |
| `database` | `str` | `""` | Database name/file path |
| `username` | `str` | `""` | Database username |
| `password` | `str` | `""` | Database password |
| `echo` | `bool` | `False` | Log all SQL statements |
| `pool_size` | `int` | `5` | Connection pool size (not for SQLite) |
| `max_overflow` | `int` | `10` | Max overflow connections (not for SQLite) |
| `pool_pre_ping` | `bool` | `True` | Verify connections before use |

### URL Auto-Normalization

When passing a `url`, `DatabaseConfig` automatically ensures the correct async driver:

| Input URL | Normalized Output |
|-----------|------------------|
| `sqlite:///./db.sqlite3` | `sqlite+aiosqlite:///./db.sqlite3` |
| `sqlite+aiosqlite:///./db.sqlite3` | unchanged |
| `postgresql://user:pass@localhost/mydb` | `postgresql+asyncpg://user:pass@localhost/mydb` |
| `postgresql+psycopg2://user:pass@localhost/mydb` | `postgresql+asyncpg://user:pass@localhost/mydb` |
| `mysql://user:pass@localhost/mydb` | `mysql+aiomysql://user:pass@localhost/mydb` |

### Usage Modes

**Mode 1 — URL string (auto-normalized):**

```python
db_config = DatabaseConfig(url="sqlite:///./app.db")
engine = db_config.create_engine()
```

**Mode 2 — Structured fields:**

```python
db_config = DatabaseConfig(
    db_type=DatabaseType.POSTGRESQL,
    host="localhost",
    port=5432,
    database="mydb",
    username="user",
    password="secret",
)
engine = db_config.create_engine()
```

**Mode 3 — Pass directly to Admin (engine created automatically):**

```python
admin = Admin(
    app=app,
    database_config=DatabaseConfig(url="sqlite:///./app.db"),
    secret_key="your-secret-key",
)
```

## Admin Initialization

```python
from fastapi_admin_kit import Admin

admin = Admin(
    app=app,
    engine=engine,           # existing: pass pre-created engine
    # OR
    database_config=db_config,  # new: pass config instead
    secret_key="your-secret-key",
    # ... other options
)
```

## Configuration Options

### Branding

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `title` | `str` | `"Admin"` | Admin panel title |
| `logo_url` | `str` | `None` | URL to logo image |
| `favicon_url` | `str` | `None` | URL to favicon |
| `primary_color` | `str` | `"#6366f1"` | Primary brand color (CSS) |
| `primary_color_dark` | `str` | `"#4f46e5"` | Primary color for dark mode |

### Behavior

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `admin_path` | `str` | `"/admin"` | URL prefix for admin |
| `per_page_default` | `int` | `20` | Default rows per page |
| `session_ttl` | `int` | `28800` | Session lifetime in seconds (8 hours) |
| `dark_mode_default` | `bool` | `False` | Start in dark mode |

### Theme

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `theme_preset` | `str` | `"editorial"` | Built-in theme preset |
| `theme_css` | `str` | `None` | Custom CSS variables |

#### Available Presets

| Preset | Description |
|--------|-------------|
| `editorial` | Warm serif typography, paper-like textures |
| `modern` | Clean sans-serif, rounded corners |
| `midnight` | Dark theme with indigo accents |
| `paper` | Classic paper aesthetic |
| `forest` | Green-tinted natural theme |
| `minimal` | Sharp edges, no decorative elements |

### UI Layout

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `sidebar_style` | `str` | `"default"` | Sidebar visual style |
| `sidebar_position` | `str` | `"left"` | `left` or `right` |
| `table_style` | `str` | `"default"` | Table visual style |
| `table_row_height` | `str` | `"normal"` | `compact`, `normal`, or `relaxed` |
| `form_layout` | `str` | `"two-column"` | `single-column` or `two-column` |
| `form_spacing` | `str` | `"normal"` | `compact`, `normal`, or `relaxed` |
| `content_width` | `str` | `"default"` | `narrow`, `default`, or `wide` |
| `topbar_style` | `str` | `"default"` | Top navigation bar style |
| `mobile_sidebar` | `str` | `"overlay"` | Mobile sidebar behavior |

### Dashboard

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `dashboard_stats` | `list[str]` | `None` | Models to show stats for |
| `dashboard_charts` | `bool` | `False` | Enable activity charts |
| `dashboard_grid` | `str` | `"auto"` | Dashboard grid layout |
| `dashboard_card_style` | `str` | `"default"` | Dashboard card visual style |
| `dashboard_stat_size` | `str` | `"normal"` | Stat card size |
| `dashboard_permission` | `str` | `None` | Permission required to view dashboard |
| `settings_permission` | `str` | `None` | Permission required to view settings |

### Audit Logging

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `audit_retention_days` | `int` | `None` | Days to keep audit logs (None = forever) |
| `audit_enabled` | `bool` | `True` | Enable/disable audit logging |

### Storage

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `storage` | `StorageBackend` | `None` | File storage backend (S3, local) |
| `uploads_url` | `str` | `"/uploads"` | URL prefix for uploaded files |

### Security

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `secret_key` | `str` | `""` | Secret key for session signing (min 32 chars) |
| `session_cookie_name` | `str` | `"admin_session"` | Session cookie name |
| `session_secure` | `bool` | `False` | Require HTTPS for cookies |
| `session_samesite` | `str` | `"strict"` | SameSite cookie policy |
| `superuser_emails` | `list[str]` | `None` | Emails that get superuser access |

### Seed Roles

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `seed_roles` | `list[SeedRole]` | Built-in 4 roles | Custom seed roles |
| `seed_roles_overwrite` | `bool` | `False` | Overwrite existing roles on setup |

### Navigation

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `nav_groups` | `list[NavGroupConfig]` | `None` | Custom navigation groups |
| `sidebar_builder` | `SidebarBuilder` | `None` | Custom sidebar builder |
| `require_tags` | `bool` | `False` | Require models to have nav tags |

### Customization

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `custom_css` | `str` | `""` | Inline custom CSS |
| `custom_css_url` | `str` | `""` | External CSS file URL |
| `custom_js` | `str` | `""` | Inline custom JavaScript |
| `custom_js_url` | `str` | `""` | External JS file URL |
| `show_history` | `bool` | `True` | Show object history tab |
| `show_view_on_site` | `bool` | `True` | Show "View on site" button |
| `environment_label` | `str` | `None` | Environment badge text (e.g., "Staging") |
| `environment_color` | `str` | `"info"` | Environment badge color |

## Example Configuration

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key=os.environ["SECRET_KEY"],
    
    # Branding
    title="Acme Corp Admin",
    logo_url="/static/acme-logo.svg",
    primary_color="#0ea5e9",
    primary_color_dark="#0284c7",
    
    # Behavior
    admin_path="/admin",
    per_page_default=25,
    session_ttl=28800,
    
    # UI Layout
    sidebar_position="left",
    form_layout="two-column",
    table_row_height="normal",
    
    # Environment
    environment_label="Staging",
    environment_color="warning",
    
    # Audit
    audit_retention_days=365,
    
    # Dashboard
    dashboard_stats=["products", "orders", "users"],
    dashboard_charts=True,
    
    # Custom CSS/JS
    custom_css_url="/static/admin-overrides.css",
)
```

## Environment Variables

Store sensitive values in environment variables:

```python
import os

admin = Admin(
    app=app,
    engine=engine,
    secret_key=os.environ["SECRET_KEY"],
)
```

Set in your shell:

```bash
export SECRET_KEY="your-super-secret-key"
```

Or use a `.env` file with `python-dotenv`:

```python
from dotenv import load_dotenv
load_dotenv()
```

## HTTPS in Production

When deploying behind a reverse proxy (nginx, Caddy):

```python
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

# Force HTTPS
app.add_middleware(HTTPSRedirectMiddleware)

# Or trust specific hosts
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["admin.example.com"])
```

## Next Steps

- [Model Registration](../guide/model-registration.md) — Configure individual models
- [Authentication & RBAC](../guide/auth-rbac.md) — Set up roles and permissions
