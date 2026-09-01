# Redis & Caching

Optional Redis-backed rate limiting and response caching, built on
[`fastapi-redis-sdk`](https://pypi.org/project/fastapi-redis-sdk/). Both
features degrade gracefully — without Redis the admin behaves exactly as
before.

## Install

Redis support is an optional extra:

```bash
pip install fastapi-admin-kit[redis]
```

## Enabling Redis

Set `REDIS_URL` in your environment. That alone switches the login rate
limiter to the distributed Redis backend:

```dotenv
REDIS_URL=redis://localhost:6379/0
```

No Redis? No problem. The admin falls back to the existing in-memory
sliding-window rate limiter, keeping full backward compatibility.

## Redis-backed login rate limiting

When `REDIS_URL` is set (and the SDK is installed) the auth endpoints use a
distributed `RateLimitBackend` so the attempt counters hold across every
worker or pod. Guarded endpoints:

| Endpoint | Bucket key | Default limit |
|----------|-----------|---------------|
| `POST /admin/login` (HTML) | client IP | 5 per 900 s |
| `POST /api/auth/token` | client IP + email (failed attempts) | 10 per 900 s |
| `POST /api/auth/refresh` | client IP | 60 per 300 s |
| `POST /api/auth/logout` | client IP | 30 per 300 s |

The Redis backend fails open: if Redis becomes unreachable the admin logs the
failure and allows the request rather than taking login down. With no
`REDIS_URL` an in-memory limiter is used.

!!! warning "Multi-worker deployments"

    The in-memory fallback keeps counters **per process**. With multiple
    workers or replicas each worker has its own counters, so the effective
    limit multiplies by the worker count. For production deployments behind
    multiple workers, set `REDIS_URL` **or** terminate rate limiting at your
    gateway/reverse proxy.

## Trusted proxies & client IP

Rate limiting and audit logs key on the **socket peer address** by default.
`X-Forwarded-For` is ignored unless you declare your reverse proxies —
otherwise any client could rotate its rate-limit bucket per request by
sending a fresh header:

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    trusted_proxies=["10.0.0.0/8", "172.17.0.1"],  # IPs or CIDR networks
)
```

When the direct peer matches `trusted_proxies`, the `X-Forwarded-For` chain
is walked right-to-left, skipping trusted hops, and the first untrusted
address is used as the client IP.

## Opt-in response caching

Caching is **off by default**. Enable it per-admin or globally:

```dotenv
# Global defaults (also settable per Admin)
FASTAPI_ADMIN_KIT_CACHE_ENABLED=false
FASTAPI_ADMIN_KIT_CACHE_TTL=300
```

Programmatically:

```python
admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    cache_enabled=True,
    cache_ttl=120,  # seconds; explicit value wins over the env default
)
```

When caching is active, the HTML list and detail GET endpoints for every
registered model get a Redis-backed `cache()` dependency keyed on an eviction
group per model table. Responses automatically carry
`X-Redis-Cache: HIT` / `X-Redis-Cache: MISS` headers.

Write operations invalidate naturally via eviction groups scoped to each
model's table, and `cache_ttl=0` disables expiration.

## Configuration reference

| Env var | Default | Purpose |
|---------|---------|---------|
| `REDIS_URL` | *(unset)* | Enables Redis-backed rate limiting and caching when set |
| `FASTAPI_ADMIN_KIT_CACHE_ENABLED` | `false` | Global opt-in switch for response caching |
| `FASTAPI_ADMIN_KIT_CACHE_TTL` | `300` | Default cache TTL in seconds |
