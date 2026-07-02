# Authentication & RBAC

Set up user authentication and role-based access control.

## Authentication

### Built-in Auth (Default)

The admin ships with a complete auth system. No configuration needed:

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key=os.environ["SECRET_KEY"],
)
```

This creates:

- `admin_users` table
- `admin_roles` table
- `admin_permissions` table
- Login page at `/admin/login/`
- Session-based authentication

### Default Credentials

On first run, a superuser is created:

- **Email:** admin@example.com
- **Password:** admin

!!! warning
    Change the default password immediately in production!

### Authentication Flow

```
POST /admin/login/
    → Validate email + bcrypt password
    → Create signed session cookie
    → Redirect to /admin/

GET /admin/*
    → Read session cookie
    → Verify signature
    → Load AdminUser from DB
    → Inject into request.state.admin_user
```

### Session Configuration

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key=os.environ["SECRET_KEY"],
    session_ttl=28800,  # 8 hours in seconds
)
```

## Extending the Built-in Model

### Add Extra Columns

```python
from fastapi_admin_kit.auth.models import AdminUser as _AdminUser

class AdminUser(_AdminUser):
    __tablename__ = "admin_users"  # Same table
    
    department = Column(String(100))
    avatar_url = Column(String(500))
    phone = Column(String(20))
```

### Replace with Your Own Model

```python
from fastapi_admin_kit.auth import AuthBackend

class MyUserBackend(AuthBackend):
    
    async def authenticate(self, email: str, password: str, session: Session):
        user = session.query(User).filter_by(email=email).first()
        if not user or not verify_password(password, user.hashed_password):
            return None
        return user
    
    async def get_user(self, user_id: int, session: Session):
        return session.query(User).get(user_id)

admin = Admin(
    app=app,
    engine=engine,
    secret_key=os.environ["SECRET_KEY"],
    auth_backend=MyUserBackend(),
)
```

## Role-Based Access Control (RBAC)

### How It Works

Permissions come from two sources, merged together:

```
User → Role Permissions (OR) → Direct User Permissions → Effective Permissions
```

Each permission entry controls four actions per model: view, create, edit, delete.

### Permission Tables

```sql
-- Roles
CREATE TABLE admin_roles (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) UNIQUE NOT NULL,
    description TEXT
);

-- Permissions per role per model
CREATE TABLE admin_permissions (
    id          SERIAL PRIMARY KEY,
    role_id     INTEGER REFERENCES admin_roles(id),
    table_name  VARCHAR(255) NOT NULL,
    can_view    BOOLEAN DEFAULT FALSE,
    can_create  BOOLEAN DEFAULT FALSE,
    can_edit    BOOLEAN DEFAULT FALSE,
    can_delete  BOOLEAN DEFAULT FALSE
);
```

### Permission Checker

The `PermissionChecker` merges permissions from two sources:

1. **Role-based** — all assigned roles (M2M via `admin_user_roles`), OR'd together
2. **Direct per-user overrides** — `AdminUserPermission` records, OR'd on top

```python
from fastapi_admin_kit.auth.permissions import PermissionChecker

checker = PermissionChecker(session, user)

# Check if user can perform an action on a table
await checker.has_permission("products", "view")   # True/False
await checker.has_permission("products", "create")  # True/False
await checker.has_permission("products", "edit")    # True/False
await checker.has_permission("products", "delete")  # True/False

# Get allowed fields (None = all allowed, empty set = none allowed)
await checker.get_allowed_fields("products", "view")   # set[str] | None
await checker.get_allowed_fields("products", "edit")   # set[str] | None

# Sync convenience for templates
await checker.load_permissions("products")
perm_set = checker.permission_set("products")  # PermissionSet dataclass
# perm_set.can_view, perm_set.can_create, perm_set.can_edit, perm_set.can_delete
```

### Superuser Bypass

Users with `is_superuser=True` bypass all permission checks — `has_permission()` always returns `True`.

## Default Roles

| Role | View | Create | Edit | Delete |
|------|------|--------|------|--------|
| SuperAdmin | All | All | All | All |
| Admin | All | All | All | All (except users) |
| Editor | All | Content | Content | None |
| Viewer | All | None | None | None |

## FastAPI Dependencies

Use dependencies to protect routes:

```python
from fastapi_admin_kit.auth.dependencies import require_permission

@router.get("/products/")
async def list_products(
    _=Depends(require_permission("products", "view"))
):
    # Only users with view permission can access
    pass

@router.post("/products/")
async def create_product(
    _=Depends(require_permission("products", "create"))
):
    # Only users with create permission can access
    pass
```

## UI Adapts to Permissions

The admin UI automatically hides elements based on permissions:

```jinja2
{# Show create button only if user has permission #}
{% if permissions.can_create %}
    <a href="{{ url_for('admin_create', model=model_name) }}">
        + New {{ verbose_name }}
    </a>
{% endif %}

{# Show edit button only if user has permission #}
{% if permissions.can_edit %}
    <a href="{{ url_for('admin_edit', model=model_name, id=obj.id) }}">
        Edit
    </a>
{% endif %}

{# Show delete button only if user has permission #}
{% if permissions.can_delete %}
    <button hx-post="{{ url_for('admin_delete', model=model_name, id=obj.id) }}">
        Delete
    </button>
{% endif %}
```

### Sidebar Visibility

The sidebar automatically filters navigation items based on user permissions:

- **Superusers** see all navigation items
- **Regular users** only see models where `can_view=True`
- Models without permission records are hidden

This filtering happens server-side in `build_sidebar_context()` — users never see links to models they can't access.

## Role Management UI

Access the role management interface at `/admin/roles/`:

- List all roles with user counts
- Create new roles
- Edit role permissions
- Delete roles

### Permission Matrix Editor

The UI shows a table where:

- **Rows** = registered models
- **Columns** = actions (view, create, edit, delete)
- **Cells** = checkboxes

Check/uncheck permissions and click "Save" to update.

## Field-Level Permissions

Restrict access to specific fields:

```sql
CREATE TABLE admin_field_permissions (
    id          SERIAL PRIMARY KEY,
    role_id     INTEGER REFERENCES admin_roles(id),
    table_name  VARCHAR(255) NOT NULL,
    field_name  VARCHAR(255) NOT NULL,
    can_view    BOOLEAN DEFAULT TRUE,
    can_edit    BOOLEAN DEFAULT TRUE
);
```

### Check Field Permissions

```python
checker = PermissionChecker(session, user)

# Get allowed fields for viewing
allowed_fields = await checker.get_allowed_fields("products", "view")

# Returns None if no restrictions (all allowed)
# Returns set of field names if restricted
```

## Direct User Permissions

In addition to role-based permissions, you can assign permissions directly to individual users. Direct permissions are OR'd with role permissions — a user gets the union of both.

### How It Works

```
User → Role Permissions (OR) → Direct Permissions → Effective Permissions
```

The `admin_user_permissions` table stores per-user overrides:

```sql
CREATE TABLE admin_user_permissions (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES admin_users(id),
    table_name  VARCHAR(255) NOT NULL,
    can_view    BOOLEAN DEFAULT FALSE,
    can_create  BOOLEAN DEFAULT FALSE,
    can_edit    BOOLEAN DEFAULT FALSE,
    can_delete  BOOLEAN DEFAULT FALSE
);
```

### Permission Widget

The role and user forms include an autocomplete-enabled permission widget. When editing a role or user, you can:

1. Search for models by name using the autocomplete input
2. Toggle view/create/edit/delete permissions per model
3. Remove permissions by clicking the remove button

The widget uses the `/admin/tables/search?q=<query>` endpoint to find registered models.

## Custom Auth Backend

Implement your own authentication:

```python
from fastapi_admin_kit.auth import AuthBackend
from fastapi import HTTPException

class MyAuthBackend(AuthBackend):
    
    async def authenticate(self, email: str, password: str, session: Session):
        """Validate credentials and return user"""
        user = session.query(User).filter_by(email=email).first()
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        if not user.is_active:
            return None
        return user
    
    async def get_user(self, user_id: int, session: Session):
        """Load user by ID from session"""
        return session.query(User).get(user_id)
    
    def get_user_id(self, user):
        """Extract user ID for session"""
        return user.id

admin = Admin(
    app=app,
    engine=engine,
    secret_key=os.environ["SECRET_KEY"],
    auth_backend=MyAuthBackend(),
)
```

## Security Notes

### HTTPS in Production

Always use HTTPS in production:

```python
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

app.add_middleware(HTTPSRedirectMiddleware)
```

### Secret Key

Use a strong, random secret key:

```python
import secrets
secret_key = secrets.token_urlsafe(32)
```

Store in environment variables, never in code.

### Session Security

Sessions are signed cookies, not encrypted. The payload is visible but tamper-proof:

```json
{ "user_id": 5, "issued_at": 1710000000 }
```

## Next Steps

- [Widgets & Forms](widgets-forms.md) — Customize form fields
- [Audit Logging](audit-logging.md) — Track all changes
- [Plugins](plugins.md) — Extend with custom plugins
