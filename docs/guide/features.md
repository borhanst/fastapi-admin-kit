# Features

Everything FastAPI Admin Kit offers, in one place.

![Dashboard](../assets/images/admin-dashboard.png)

---

## Core

| Feature | Description | Link |
|---------|-------------|------|
| Zero-Config Auto-Discovery | Register a model, get full CRUD UI automatically | [Model Registration](model-registration.md) |
| SQLAlchemy & SQLModel | Works with both ORMs out of the box | [Quick Start](../getting-started/quickstart.md) |
| Async-First | Built for async FastAPI with `AsyncSession` support | [Quick Start](../getting-started/quickstart.md) |
| Database Support | PostgreSQL, MySQL, and SQLite with auto URL normalization | [Configuration](../getting-started/configuration.md) |
| Auto-Migration | Automatically adds missing columns to existing tables | [CLI Tools](cli.md) |
| Plugin System | Extend every layer (widgets, auth, routes, audit, storage) via plugins | [Plugins](plugins.md) |

---

## Authentication & Security

| Feature | Description | Link |
|---------|-------------|------|
| Built-in Auth | Session-based authentication with login page at `/admin/login/` | [Auth & RBAC](auth-rbac.md) |
| Custom Auth Backend | Bring your own user model and authentication logic | [Auth & RBAC](auth-rbac.md) |
| RBAC | Role-based access control with per-model permissions (view, create, edit, delete) | [Auth & RBAC](auth-rbac.md) |
| Direct User Permissions | Per-user permission overrides, OR'd with role permissions | [Auth & RBAC](auth-rbac.md) |
| Field-Level Permissions | Restrict access to specific fields per role | [Auth & RBAC](auth-rbac.md) |
| Superuser Bypass | `is_superuser=True` bypasses all permission checks | [Auth & RBAC](auth-rbac.md) |
| TOTP Two-Factor Auth | QR code setup, enable/disable, backup codes via `/admin/profile/2fa` | [Auth & RBAC](auth-rbac.md) |
| CSRF Protection | Signed CSRF tokens on all state-changing requests | [Auth & RBAC](auth-rbac.md) |
| Rate Limiting | Sliding-window rate limiter on authentication endpoints | [Auth & RBAC](auth-rbac.md) |
| Password Hashing | bcrypt with configurable rounds | [Auth & RBAC](auth-rbac.md) |
| Session Security | Signed cookies with `SameSite=Strict`, `Secure`, and configurable TTL | [Configuration](../getting-started/configuration.md) |
| Secret Key Validation | Enforces minimum 32-character secret key at startup | [Configuration](../getting-started/configuration.md) |
| SQL Injection Prevention | Identifier validation on all raw SQL in CLI and auto-migrate | [Security](../getting-started/configuration.md) |

---

## User Management

| Feature | Description | Link |
|---------|-------------|------|
| Default Roles | SuperAdmin, Admin, Editor, Viewer seeded automatically | [Auth & RBAC](auth-rbac.md) |
| Custom Seed Roles | Define your own roles and permissions at startup | [Configuration](../getting-started/configuration.md) |
| Permission Matrix UI | Visual checkbox grid for managing role permissions | [Auth & RBAC](auth-rbac.md) |
| User Management UI | Create, edit, list, and delete admin users from the panel | [CLI Tools](cli.md) |
| Profile Page | Users can view and edit their own profile at `/admin/profile` | [Auth & RBAC](auth-rbac.md) |
| Password Change | Users can change their own password from the profile page | [Auth & RBAC](auth-rbac.md) |

---

## UI & Design

| Feature | Description | Link |
|---------|-------------|------|
| Modern UI | Tailwind CSS, HTMX, and Alpine.js for a fast, responsive experience | [Themes & UI](themes.md) |
| Dark Mode | Toggle between light and dark mode, configurable default | [Themes & UI](themes.md) |
| Theme Presets | editorial, modern, midnight, paper, forest, minimal | [Themes & UI](themes.md) |
| Theme Settings Page | Visual theme builder at `/admin/settings/theme` | [Themes & UI](themes.md) |
| Custom Themes | Override primary colors, CSS variables, and layout settings | [Themes & UI](themes.md) |
| Responsive Design | Mobile-friendly with collapsible sidebar | [Themes & UI](themes.md) |
| Shell Layout | Topbar, sidebar, content area with loading bar | [Themes & UI](themes.md) |
| Sidebar Customization | Position (left/right), style, collapse, nav groups | [Navigation](navigation.md) |
| Table Styling | Row height (compact/normal/relaxed), custom styles | [Themes & UI](themes.md) |
| Form Layout | Single-column or two-column, configurable spacing | [Themes & UI](themes.md) |
| Content Width | Narrow, default, or wide layout | [Themes & UI](themes.md) |
| Environment Badge | Show "Production", "Staging", etc. with color coding | [Themes & UI](themes.md) |
| Flash Messages | Success/error messages after operations via signed session cookie | [Themes & UI](themes.md) |
| Custom CSS/JS | Inject inline or external CSS and JavaScript globally | [Themes & UI](themes.md) |
| Custom Templates | Override any Jinja2 template | [Themes & UI](themes.md) |
| Custom Icons | Material Symbols icon support throughout | [Themes & UI](themes.md) |

---

## CRUD Operations

| Feature | Description | Link |
|---------|-------------|------|
| List View | Paginated table with search, filters, and bulk actions | [Model Registration](model-registration.md) |
| Create Form | Auto-generated from model columns with validation | [Widgets & Forms](widgets-forms.md) |
| Edit Form | Pre-populated form with field-level validation | [Widgets & Forms](widgets-forms.md) |
| Delete | Confirmation dialog before deletion | [Inline Editing & Actions](inline-editing-actions.md) |
| Inline Editing | Edit records directly from list view with 3-dot action menu | [Inline Editing & Actions](inline-editing-actions.md) |
| Bulk Actions | Select multiple rows and apply actions (delete, custom) | [Inline Editing & Actions](inline-editing-actions.md) |
| Row Actions | Per-row action menu with custom actions | [Inline Editing & Actions](inline-editing-actions.md) |
| Detail Actions | Actions on detail/edit pages | [Inline Editing & Actions](inline-editing-actions.md) |
| Submit-Line Actions | Actions on form submit buttons | [Inline Editing & Actions](inline-editing-actions.md) |

---

## Widgets (17 built-in)

| Widget | Description | Link |
|--------|-------------|------|
| `TextInputWidget` | String/VARCHAR fields | [Widgets & Forms](widgets-forms.md) |
| `TextareaWidget` | Text fields with configurable rows | [Widgets & Forms](widgets-forms.md) |
| `NumberInputWidget` | Integer/Float with step and min/max | [Widgets & Forms](widgets-forms.md) |
| `ToggleWidget` | Boolean toggle switch | [Widgets & Forms](widgets-forms.md) |
| `SelectWidget` | Enum dropdown with choices | [Widgets & Forms](widgets-forms.md) |
| `DatePickerWidget` | Date-only picker | [Widgets & Forms](widgets-forms.md) |
| `DateTimePickerWidget` | DateTime picker | [Widgets & Forms](widgets-forms.md) |
| `JsonEditorWidget` | JSON editor | [Widgets & Forms](widgets-forms.md) |
| `AutocompleteWidget` | Datalist autocomplete with static/dynamic suggestions | [Widgets & Forms](widgets-forms.md) |
| `PasswordWidget` | Masked input, never pre-fills | [Widgets & Forms](widgets-forms.md) |
| `ReadOnlyWidget` | Display-only value | [Widgets & Forms](widgets-forms.md) |
| `HiddenWidget` | Hidden input field | [Widgets & Forms](widgets-forms.md) |
| `FileUploadWidget` | File upload with size limits and type filtering | [Storage & Uploads](storage.md) |
| `ImageUploadWidget` | Image-specific upload with preview | [Storage & Uploads](storage.md) |
| `WysiwygWidget` | Rich text editor for HTML content | [Widgets & Forms](widgets-forms.md) |
| `ArrayWidget` | Dynamic list input for JSON arrays | [Widgets & Forms](widgets-forms.md) |
| `RelationPickerWidget` | Searchable FK dropdown | [Widgets & Forms](widgets-forms.md) |
| `MultiRelationWidget` | Multi-select with search and removable tags | [Widgets & Forms](widgets-forms.md) |

---

## Form Features

| Feature | Description | Link |
|---------|-------------|------|
| Auto-Generated Forms | Columns mapped to widgets automatically | [Widgets & Forms](widgets-forms.md) |
| Fieldsets | Group form fields into titled sections | [Model Registration](model-registration.md) |
| Conditional Fields | Show/hide fields based on other field values | [Model Registration](model-registration.md) |
| Field Overrides | Replace widget for any field via `formfield_overrides` | [Widgets & Forms](widgets-forms.md) |
| Extra Fields | Add non-model fields to forms | [Model Registration](model-registration.md) |
| Readonly Fields | Show fields without allowing edits | [Model Registration](model-registration.md) |
| Placeholders | Custom placeholder text per field | [Model Registration](model-registration.md) |
| Unsaved Changes Warning | Browser warning when leaving with unsaved edits | [Widgets & Forms](widgets-forms.md) |
| HTMX Partial Validation | Field-level validation on blur without page reload | [Widgets & Forms](widgets-forms.md) |
| Object-Level Validation | Cross-field validation after all fields are parsed | [Widgets & Forms](widgets-forms.md) |
| Global Validator | Validate across all models | [Widgets & Forms](widgets-forms.md) |

---

## List View Features

| Feature | Description | Link |
|---------|-------------|------|
| Search | Full-text search across specified fields | [Model Registration](model-registration.md) |
| Relation Search | Search across FK and M2M relations (`user__email`, `tags__name`) | [Model Registration](model-registration.md) |
| Filters | Sidebar filters (text, boolean, relation, enum) | [Filters](filters.md) |
| Filter Registry | Register custom filter types | [Filters](filters.md) |
| Ordering | Default sort order with clickable column headers | [Model Registration](model-registration.md) |
| Pagination | Offset, cursor, or dynamic strategies per model | [Pagination](pagination.md) |
| Custom Columns | `@column` decorator for computed columns with formatting, icons, width | [Model Registration](model-registration.md) |
| Column Export | CSV export support per column | [Model Registration](model-registration.md) |

---

## Audit Logging

| Feature | Description | Link |
|---------|-------------|------|
| Automatic Tracking | Every create, update, and delete is recorded | [Audit Logging](audit-logging.md) |
| Change Diffs | Before/after comparison for updates | [Audit Logging](audit-logging.md) |
| Full Snapshots | Complete object state at time of change | [Audit Logging](audit-logging.md) |
| User Attribution | Records who performed each action | [Audit Logging](audit-logging.md) |
| IP & User-Agent | Captures request metadata | [Audit Logging](audit-logging.md) |
| Audit Log UI | Timeline view with filters by model, user, action, date | [Audit Logging](audit-logging.md) |
| Per-Object History | Edit forms show audit history for that record | [Audit Logging](audit-logging.md) |
| Retention Policy | Configurable retention period with automatic purge | [Audit Logging](audit-logging.md) |
| External Sinks | Send audit logs to Elasticsearch, webhooks, etc. | [Audit Logging](audit-logging.md) |
| Custom Audit Writer | Override the default audit recording logic | [Audit Logging](audit-logging.md) |

---

## Dashboard

| Feature | Description | Link |
|---------|-------------|------|
| Stat Cards | Display key metrics with values and descriptions | [Dashboard](dashboard.md) |
| Charts | Line, bar, pie, and doughnut chart placeholders | [Dashboard](dashboard.md) |
| Tables | Dashboard table components | [Dashboard](dashboard.md) |
| Progress Bars | Visual progress indicators | [Dashboard](dashboard.md) |
| Link Buttons | Quick-action buttons | [Dashboard](dashboard.md) |
| Configurable Grid | Auto or custom grid layout | [Dashboard](dashboard.md) |
| Permission Gating | Restrict dashboard access by permission | [Dashboard](dashboard.md) |

---

## Navigation

| Feature | Description | Link |
|---------|-------------|------|
| Auto-Generated Sidebar | Models grouped by tags automatically | [Navigation](navigation.md) |
| Custom Nav Groups | Define your own navigation structure | [Navigation](navigation.md) |
| Sidebar Builder | Custom sidebar builder protocol | [Navigation](navigation.md) |
| Nav Ordering | Control sidebar item order with `nav_order` | [Navigation](navigation.md) |
| Nested Nav Items | Create sub-menu items with `nav_children` | [Navigation](navigation.md) |
| Active State | Current page highlighted in sidebar | [Navigation](navigation.md) |
| Collapsible Sidebar | Sidebar collapses to icons on toggle | [Navigation](navigation.md) |

---

## CLI Tools (`fak-admin` / `fak`)

| Command | Description | Link |
|---------|-------------|------|
| `createsuperuser` | Create admin users with email and password | [CLI Tools](cli.md) |
| `users` | List all admin users | [CLI Tools](cli.md) |
| `changepassword` | Change a user's password | [CLI Tools](cli.md) |
| `createpermissions` | Create permissions for tables | [CLI Tools](cli.md) |
| `createadminpermissions` | Create permissions for all admin-registered models | [CLI Tools](cli.md) |
| `deletepermissions` | Delete permissions for tables | [CLI Tools](cli.md) |
| `migrate` | Add missing columns or drop obsolete columns | [CLI Tools](cli.md) |
| `migrate-permissions` | Convert old shared permissions to per-role format | [CLI Tools](cli.md) |
| `init` | Scaffold a new FastAPI project with uv | [CLI Tools](cli.md) |

---

## JSON API

| Feature | Description | Link |
|---------|-------------|------|
| REST Endpoints | Full CRUD API for all registered models | [JSON API](json-api.md) |
| Token Authentication | JWT-based auth for external frontends | [JSON API](json-api.md) |
| Token Refresh | Refresh token rotation | [JSON API](json-api.md) |
| Role Management API | CRUD for roles via API | [JSON API](json-api.md) |
| Search API | Programmatic search endpoint | [JSON API](json-api.md) |
| Schema Generation | Auto-generated JSON schemas for models | [JSON API](json-api.md) |

---

## Pagination

| Feature | Description | Link |
|---------|-------------|------|
| Offset Pagination | Traditional page numbers (default) | [Pagination](pagination.md) |
| Cursor Pagination | Keyset pagination with opaque cursors for large datasets | [Pagination](pagination.md) |
| Dynamic Pagination | Auto-switches between offset and cursor based on record count | [Pagination](pagination.md) |

---

## Storage & File Uploads

| Feature | Description | Link |
|---------|-------------|------|
| LocalStorageBackend | File uploads to local filesystem | [Storage & Uploads](storage.md) |
| Storage Backend Protocol | Implement custom backends (S3, GCS, etc.) | [Storage & Uploads](storage.md) |
| Upload Widgets | File and image upload with size limits and type filtering | [Storage & Uploads](storage.md) |

---

## Search

| Feature | Description | Link |
|---------|-------------|------|
| Command Palette | `Cmd+K` / `Ctrl+K` to search models and fields | [Command Palette](command-palette.md) |
| List View Search | Per-model search across configured fields | [Model Registration](model-registration.md) |
| Relation Search | Search across foreign key and many-to-many relationships | [Model Registration](model-registration.md) |
| Search API | JSON endpoint for programmatic search | [JSON API](json-api.md) |

---

## Filters

| Feature | Description | Link |
|---------|-------------|------|
| TextFilter | Text/substring matching | [Filters](filters.md) |
| BooleanFilter | True/false toggle | [Filters](filters.md) |
| RelationFilter | Filter by related model | [Filters](filters.md) |
| EnumFilter | Filter by enum choices | [Filters](filters.md) |
| Filter Registry | Register custom filter types | [Filters](filters.md) |

---

## Customization & Extensibility

| Feature | Description | Link |
|---------|-------------|------|
| ModelAdmin | Full control over list, form, and behavior per model | [Model Registration](model-registration.md) |
| Lifecycle Hooks | `on_create`, `after_create`, `on_update`, `after_update`, `on_delete`, `after_delete` | [Inline Editing & Actions](inline-editing-actions.md) |
| Custom Actions | Decorator-based action system for list, row, detail, and submit-line | [Inline Editing & Actions](inline-editing-actions.md) |
| Custom Widgets | Extend the `Widget` base class with custom parse, validate, render | [Widgets & Forms](widgets-forms.md) |
| Widget Registry | Override widgets by type or field name pattern | [Widgets & Forms](widgets-forms.md) |
| Custom Auth Backend | Implement `AuthBackend` protocol | [Auth & RBAC](auth-rbac.md) |
| Custom Session Backend | Swap session storage | [Auth & RBAC](auth-rbac.md) |
| Custom Permission Checker | Override RBAC logic | [Auth & RBAC](auth-rbac.md) |
| Custom Audit Writer | Override audit recording | [Audit Logging](audit-logging.md) |
| Custom Sidebar Builder | Override sidebar generation | [Navigation](navigation.md) |
| Hook/Event Bus | Register before/after hooks for any lifecycle event | [Plugins](plugins.md) |
| Template Overrides | Override any Jinja2 template | [Themes & UI](themes.md) |
| Custom Template Dirs | Add your own template directories | [Themes & UI](themes.md) |
| Jinja2 Globals & Filters | Inject custom functions into templates | [Plugins](plugins.md) |
| Column Decorator | `@column()` with header, format, icon, width, exportable options | [Model Registration](model-registration.md) |

---

## Code Quality

| Feature | Description |
|---------|-------------|
| Type Hints | Ships with `py.typed` marker |
| Ruff Linting | Enforced in CI |
| Ruff Formatting | Enforced in CI |
| Test Coverage | 580+ tests with coverage reporting |
| CI/CD | GitHub Actions for tests, lint, and PyPI publishing |
| Pre-commit Hooks | Ruff lint and format on commit |
