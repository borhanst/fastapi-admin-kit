"""Integration helpers — wire the notification system into a FastAPI app.

The notification module is standalone: ``NotificationService`` does not require
the admin panel.  To expose the API endpoints, mount the router on any app and
store the service on ``app.state``::

    from fastapi_admin_kit.notifications import NotificationService, notifications_router

    service = NotificationService(...)
    app.include_router(notifications_router, prefix="/api/notifications")

    # (optional) register for realtime fallback polling on app.state:
    app.state.notification_service = service
"""

from __future__ import annotations

from typing import Any


def configure_notifications(app: Any, service: Any, prefix: str = "/api/notifications") -> None:
    """Mount the notification router and register the service on *app*.

    Args:
        app: FastAPI application.
        service: The :class:`NotificationService` instance.
        prefix: URL prefix for the notification routes.

    When the app hosts an admin panel, the admin's configured notification
    paths are aligned with *prefix* so the topbar dropdown polls and connects
    to the real mount point (the admin default assumes ``<admin_path>/notifications``).
    An explicitly configured ``notifications_api_path`` on the ``Admin`` is
    respected and left untouched.
    """
    from fastapi_admin_kit.notifications.router import router

    app.state.notification_service = service
    app.include_router(router, prefix=prefix)

    admin = getattr(app.state, "admin", None)
    if admin is None:
        return
    if not prefix.endswith("/"):
        prefix = prefix + "/"
    default_api = f"{getattr(admin.router, 'admin_path', '/admin')}/notifications"
    current_api = getattr(admin.config, "notifications_api_path", None)
    if current_api in (None, default_api):
        admin.config.notifications_api_path = prefix.rstrip("/")
    if admin.config.notifications_list_path is None:
        admin.config.notifications_list_path = (
            f"{getattr(admin.router, 'admin_path', '/admin')}/admin_notifications/"
        )
