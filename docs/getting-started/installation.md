# Installation

## Requirements

- Python 3.11 or higher
- FastAPI 0.100.0 or higher
- SQLAlchemy 2.0 or higher

## Install with pip

```bash
pip install fastapi-admin-kit
```

### Database extras

```bash
pip install fastapi-admin-kit[postgres]  # PostgreSQL via asyncpg
pip install fastapi-admin-kit[mysql]     # MySQL via aiomysql
```

### Full install (uvicorn + JWT)

```bash
pip install fastapi-admin-kit[full]
```

### All extras

```bash
pip install fastapi-admin-kit[full,postgres,sqlmodel]
```

## Install with uv

```bash
uv add fastapi-admin-kit
```

### Database extras

```bash
uv add fastapi-admin-kit[postgres]  # PostgreSQL via asyncpg
uv add fastapi-admin-kit[mysql]     # MySQL via aiomysql
```

### Full install (uvicorn + JWT)

```bash
uv add fastapi-admin-kit[full]
```

### All extras

```bash
uv add fastapi-admin-kit[full,postgres,sqlmodel]
```

## Install from source

```bash
git clone https://github.com/borhanst/fastapi-admin-kit.git
cd fastapi-admin-kit
pip install -e .
```

Or with uv:

```bash
git clone https://github.com/borhanst/fastapi-admin-kit.git
cd fastapi-admin-kit
uv sync
```

## Optional Extras

| Extra | pip | uv | What it installs |
|---|---|---|---|
| `full` | `pip install fastapi-admin-kit[full]` | `uv add fastapi-admin-kit[full]` | `uvicorn` + `pyjwt` for dev server and JWT API auth |
| `postgres` | `pip install fastapi-admin-kit[postgres]` | `uv add fastapi-admin-kit[postgres]` | `asyncpg` for PostgreSQL |
| `mysql` | `pip install fastapi-admin-kit[mysql]` | `uv add fastapi-admin-kit[mysql]` | `aiomysql` for MySQL |
| `sqlmodel` | `pip install fastapi-admin-kit[sqlmodel]` | `uv add fastapi-admin-kit[sqlmodel]` | `sqlmodel` for SQLModel support |
| `dev` | `pip install fastapi-admin-kit[dev]` | `uv add --dev fastapi-admin-kit[dev]` | `pytest`, `ruff`, `hatch`, etc. for development |
| `docs` | `pip install fastapi-admin-kit[docs]` | `uv add --group docs fastapi-admin-kit[docs]` | `mkdocs`, `mkdocs-material` for building docs |

## Dependencies

fastapi-admin-kit automatically installs:

- `fastapi` — Web framework
- `sqlalchemy` — ORM
- `jinja2` — Templating
- `python-multipart` — Form parsing
- `itsdangerous` — Session signing
- `bcrypt` — Password hashing
- `aiosqlite` — SQLite async driver

Optional (via extras):

- `uvicorn` — ASGI server (`[full]`)
- `pyjwt` — JWT tokens for API auth (`[full]`)
- `asyncpg` — PostgreSQL async driver (`[postgres]`)
- `aiomysql` — MySQL async driver (`[mysql]`)
- `sqlmodel` — SQLModel support (`[sqlmodel]`)

## Verify Installation

```python
from fastapi_admin_kit import Admin, __version__

print(f"fastapi-admin-kit v{__version__} installed successfully")
```

## Next Steps

- [Quick Start](quickstart.md) — Get your admin panel running in 5 minutes
- [Configuration](configuration.md) — Customize the admin to fit your needs
