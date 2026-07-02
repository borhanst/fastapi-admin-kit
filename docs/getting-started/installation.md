# Installation

## Requirements

- Python 3.11 or higher
- FastAPI 0.100.0 or higher
- SQLAlchemy 2.0 or higher

## Install with pip

```bash
pip install fastapi-console
```

## Install with uv (recommended)

```bash
uv add fastapi-console
```

## Install from source

```bash
git clone https://github.com/borhanst/fastapi-console.git
cd fastapi-console
pip install -e .
```

## Dependencies

fastapi-console automatically installs:

- `fastapi` — Web framework
- `sqlalchemy` — ORM
- `jinja2` — Templating
- `itsdangerous` — Session signing
- `bcrypt` — Password hashing
- `uvicorn` — ASGI server

## Verify Installation

```python
from fastapi_admin_kit import Admin
print("fastapi-console installed successfully")
```

## Next Steps

- [Quick Start](quickstart.md) — Get your admin panel running in 5 minutes
- [Configuration](configuration.md) — Customize the admin to fit your needs
