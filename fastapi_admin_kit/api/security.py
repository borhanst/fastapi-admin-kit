"""OpenAPI security schemes for the Admin JSON API (Swagger docs).

These are used as documented dependencies so Swagger UI shows "Authorize"
buttons for both HTTP Basic and HTTP Bearer. ``auto_error=False`` keeps them
purely declarative — the real auth enforcement lives in
:mod:`fastapi_admin_kit.api.deps` / the view handlers.
"""

from __future__ import annotations

from fastapi.security import HTTPBasic, HTTPBearer

basic_scheme = HTTPBasic(
    auto_error=False,
    scheme_name="BasicAuth",
    description="Admin credentials (email:password). Accepted by POST /api/auth/token.",
)

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="JWT access token returned by POST /api/auth/token.",
)
