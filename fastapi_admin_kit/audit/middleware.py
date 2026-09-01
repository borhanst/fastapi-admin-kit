"""Audit middleware — sets and clears audit context from the request."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from fastapi_admin_kit.audit.context import clear_audit_context, set_audit_context
from fastapi_admin_kit.auth.proxy import get_client_ip


class AuditContextMiddleware(BaseHTTPMiddleware):
    """Middleware to set audit context from the request and clear it after.

    Sets IP address and user-agent before the handler runs.  The user
    identity (user_id, user_email) is added later by
    :func:`fastapi_admin_kit.auth.identity.resolve_user` once the auth
    dependency resolves the current user — which always happens before
    any ``session.commit()`` that would trigger audit listeners.

    The IP is resolved through the shared trusted-proxy helper: without a
    configured ``trusted_proxies`` list the socket peer address is used and
    ``X-Forwarded-For`` is ignored (attacker-controlled otherwise).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        context_data: dict = {}

        if request.client is not None:
            context_data["ip_address"] = get_client_ip(request)

        user_agent = request.headers.get("user-agent")
        if user_agent:
            context_data["user_agent"] = user_agent

        if context_data:
            set_audit_context(context_data)

        response = await call_next(request)

        clear_audit_context()

        return response
