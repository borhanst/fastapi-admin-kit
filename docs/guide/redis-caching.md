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

When `REDIS_URL` is set (and the SDK is installed) the login endpoint uses a
distributed `RateLimitBackend` so the attempt counters hold across every
worker or pod. Defaults are 5 attempts per 900-second window.

The Redis backend fails open: if Redis becomes unreachable the admin logs the
failure and allows the request rather than taking login down. With no
`REDIS_URL` the existing in-memory limiter is used.

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
