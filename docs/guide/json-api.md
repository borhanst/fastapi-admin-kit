# JSON API

REST API for external frontend apps with JWT token authentication.

## Overview

FastAPI Admin Kit provides a JSON API alongside the HTML admin panel. The API shares the same RBAC system, making it easy to build custom frontends or mobile apps.

## Endpoints

The API is mounted at `/admin/api/` by default.

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/admin/api/auth/login` | Obtain JWT token pair |
| `POST` | `/admin/api/auth/refresh` | Refresh access token |
| `POST` | `/admin/api/auth/logout` | Invalidate refresh token |
| `GET` | `/admin/api/auth/me` | Get current user info |

### CRUD

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/admin/api/{model}/` | List records |
| `POST` | `/admin/api/{model}/` | Create record |
| `GET` | `/admin/api/{model}/{id}` | Get single record |
| `PUT` | `/admin/api/{model}/{id}` | Update record |
| `DELETE` | `/admin/api/{model}/{id}` | Delete record |

### Roles

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/admin/api/roles/` | List roles |
| `POST` | `/admin/api/roles/` | Create role |
| `GET` | `/admin/api/roles/{id}` | Get role |
| `PUT` | `/admin/api/roles/{id}` | Update role |
| `DELETE` | `/admin/api/roles/{id}` | Delete role |

### Search

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/admin/api/search?q={query}` | Search across models |

## Authentication

### Token Obtain

```bash
curl -X POST http://localhost:8000/admin/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "mypassword"}'
```

Response:

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

### Using the Token

```bash
curl http://localhost:8000/admin/api/products/ \
  -H "Authorization: Bearer eyJ..."
```

### Token Refresh

```bash
curl -X POST http://localhost:8000/admin/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "eyJ..."}'
```

## Requirements

The JSON API requires the `pyjwt` package:

```bash
pip install fastapi-admin-kit[full]
```

## RBAC

The API uses the same permission system as the HTML admin:

- Users can only access models they have `view` permission for
- Create/edit/delete require corresponding permissions
- Superusers bypass all permission checks

## Schema Generation

Auto-generated JSON schemas are available for each model:

```bash
curl http://localhost:8000/admin/api/schema/products/
```

## Next Steps

- [Authentication & RBAC](auth-rbac.md) — Set up permissions
- [Configuration](../getting-started/configuration.md) — Admin options
