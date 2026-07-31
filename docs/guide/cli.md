# CLI Tools

Manage users, permissions, and database migrations from the command line.

## Overview

FastAPI Admin Kit ships with two CLI aliases: `fak-admin` (full name) and `fak` (short alias). Both work identically.

```bash
fak-admin <command> [options]
fak <command> [options]
```

All commands accept `-d DATABASE_URL` or read the `DATABASE_URL` environment variable.

## Commands

### createsuperuser

Create a new admin superuser:

```bash
fak createsuperuser -e admin@example.com -p mypassword
fak-admin createsuperuser -e admin@example.com -p mypassword
```

| Option | Description |
|--------|-------------|
| `-e, --email` | User email (required) |
| `-p, --password` | User password (required) |
| `-d, --database-url` | Database URL (or set `DATABASE_URL` env var) |

### users

List all admin users:

```bash
fak users
fak-admin users
```

| Option | Description |
|--------|-------------|
| `-d, --database-url` | Database URL |

### changepassword

Change a user's password:

```bash
fak changepassword -e admin@example.com -p newpassword
fak-admin changepassword -e admin@example.com -p newpassword
```

| Option | Description |
|--------|-------------|
| `-e, --email` | User email (required) |
| `-p, --password` | New password (required) |
| `-d, --database-url` | Database URL |

### createpermissions

Create permissions for specified tables:

```bash
# Base class mode — create permissions for all subclasses
fak createpermissions --base myapp.models.Base

# Single model — full dot-notation path
fak createpermissions myapp.models.User

# Multiple models
fak createpermissions myapp.models.User myapp.models.Product

# Legacy short names (still supported)
fak createpermissions User Product
```

| Option | Description |
|--------|-------------|
| `tables` | Model paths with dot notation (e.g., `myapp.models.User`) |
| `-b, --base` | Base class path — creates permissions for all subclasses |
| `-a, --app` | App module to import for model discovery (e.g., `example:app`) |
| `-d, --database-url` | Database URL |

### createadminpermissions

Create permissions for all admin models (scans subclasses of the admin Base class):

```bash
fak createadminpermissions
```

| Option | Description |
|--------|-------------|
| `-d, --database-url` | Database URL |

### deletepermissions

Delete permissions for specified tables:

```bash
fak deletepermissions User Product
```

| Option | Description |
|--------|-------------|
| `tables` | Class or table names (required) |
| `-d, --database-url` | Database URL |

### migrate

Add missing columns or drop obsolete columns from tables (dev mode only):

```bash
fak migrate User Product
fak-admin migrate User Product
```

| Option | Description |
|--------|-------------|
| `tables` | Class or table names (required) |
| `-d, --database-url` | Database URL |

### migrate-alembic

Run Alembic migrations (production mode):

```bash
# Run all pending migrations (equivalent to alembic upgrade head)
fak migrate-alembic

# Run to specific revision
fak migrate-alembic <revision>

# Use custom app path to find alembic.ini
fak migrate-alembic --app myapp:app
```

| Option | Description |
|--------|-------------|
| `revision` | Target revision (default: `head`) |
| `-a, --app` | App module path (e.g., `myapp:app`) to locate alembic.ini |

### init-alembic

Initialize Alembic configuration for migrations:

```bash
# New project with auto-generated initial migration
fak init-alembic --app myapp:app --auto-migrate

# Existing project with database (creates baseline migration)
fak init-alembic --app myapp:app --baseline

# Force overwrite existing alembic config
fak init-alembic --app myapp:app --force

# Custom database URL
fak init-alembic --app myapp:app -d "postgresql+asyncpg://user:pass@localhost/db"
```

| Option | Description |
|--------|-------------|
| `-a, --app` | App module path (e.g., `myapp:app`) to locate project root |
| `-d, --database-url` | Database URL to write to alembic.ini |
| `--auto-migrate` | Auto-generate initial migration for admin models |
| `--baseline` | Create baseline migration for existing database (stamps head) |
| `--force` | Overwrite existing alembic.ini and alembic/ directory |

### migrate-permissions

Convert old shared permissions to per-role format:

```bash
fak migrate-permissions
fak-admin migrate-permissions
```

| Option | Description |
|--------|-------------|
| `-d, --database-url` | Database URL |

### init

Scaffold a new FastAPI project with uv:

```bash
fak init myproject
fak init myproject --layout src
fak init myproject --no-venv --no-git
```

| Option | Description |
|--------|-------------|
| `name` | Project name |
| `-l, --layout` | Layout: `flat`, `app`, or `src` |
| `-d, --directory` | Target directory |
| `--no-venv` | Skip uv venv creation |
| `--no-git` | Skip git init |

## Database URL

All commands accept the database URL via:

1. `-d` flag: `fak users -d "sqlite+aiosqlite:///./app.db"`
2. Environment variable: `export DATABASE_URL="sqlite+aiosqlite:///./app.db"`

If neither is set, defaults to `sqlite+aiosqlite:///./app.db`.

## Next Steps

- [Quick Start](../getting-started/quickstart.md) — Get started with the admin
- [Authentication & RBAC](auth-rbac.md) — Set up roles and permissions
