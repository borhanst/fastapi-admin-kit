"""Dispatcher for model change notifications.

Wires admin change events (create / update / delete) into the notification
system.  Called from CRUD view hooks after database operations commit.

Default recipient behaviour (when the model admin does not override
``get_notification_recipients``):

- every active superuser receives a notification;
- regular active admins receive a notification only when they have at least
  one enabled ``NotificationPreference`` row;
- the actor (the admin who triggered the change) is excluded when
  ``ChangeNotificationConfig.exclude_actor`` is True (the default).
"""

from __future__ import annotations

import inspect
from typing import Any

from fastapi_admin_kit.db import get_db_session
from fastapi_admin_kit.migrations.models import NotificationPreference
from fastapi_admin_kit.notifications.config import ChangeNotificationConfig
from fastapi_admin_kit.notifications.service import NotificationService


def _resolve_user_model(request: Any) -> Any:
    """Return the user model that owns ``is_superuser``/``is_active``.

    Prefers the project's ``auth_model`` when one is configured (so joins and
    recipient lookups route to the project's user table). Falls back to the
    built-in admin ``User`` when no custom auth_model is set.
    """
    builtin_user: Any | None
    try:
        from fastapi_admin_kit.migrations.models import User as BuiltinUser
    except Exception:
        builtin_user = None
    else:
        builtin_user = BuiltinUser

    admin = getattr(request.app.state, "admin", None)
    auth_model = getattr(admin, "auth_model", None) if admin is not None else None
    if auth_model is not None and auth_model is not builtin_user:
        return auth_model
    return builtin_user


def _get_query_backend(request: Any) -> Any:
    """Return the configured :class:`QueryBackend` from app state.

    Falls back to importing the SQLAlchemy adapter when the app has not yet
    wired the backend (e.g. very early startup paths or test harnesses that
    bypass ``Admin()``).
    """
    qb = getattr(request.app.state, "admin_query_adapter", None)
    if qb is not None:
        return qb
    from fastapi_admin_kit.backends import SqlAlchemyQueryAdapter

    return SqlAlchemyQueryAdapter()


async def dispatch_model_change(
    request: Any,
    *,
    registered: Any,
    event: str,
    obj: Any | None = None,
    object_id: str | int | None = None,
    object_repr: str | None = None,
    actor: Any | None = None,
) -> None:
    """Dispatch a model-change notification.

    Args:
        request: Current FastAPI request.
        registered: Registered model information.
        event: One of ``"create"``, ``"update"``, or ``"delete"``.
        obj: The affected object instance (optional).
        object_id: The affected object's primary key (optional).
        object_repr: Human-readable object representation (optional).
        actor: The admin user who triggered the change (optional).
    """

    cfg: ChangeNotificationConfig = getattr(
        registered.admin, "change_notifications", ChangeNotificationConfig()
    )

    # Early exit if change notifications are disabled
    if not cfg.enabled:
        return

    # Early exit if this event is not in the enabled set
    if event not in cfg.events:
        return

    # Resolve recipients via the model admin hook
    recipients = registered.admin.get_notification_recipients(event, request=request, obj=obj)

    # Support both sync and async get_notification_recipients implementations
    if inspect.isawaitable(recipients):
        recipients = await recipients

    # ``[]`` means "disable notifications for this model"
    if recipients == []:
        return

    from fastapi_admin_kit.auth.identity import get_current_user_from_cookie

    current_user = await get_current_user_from_cookie(request)
    actor_id = getattr(current_user, "id", None) if current_user is not None else None

    # If ``None``, use the default behaviour:
    #   - superusers always recipients
    #   - regular admins only if they have enabled NotificationPreference rows
    if recipients is None:
        session = get_db_session(request)
        user_model = _resolve_user_model(request)
        if user_model is None:
            return
        qb = _get_query_backend(request)

        recipients = []
        superusers_q = qb.where(
            qb.select(user_model),
            user_model.is_superuser.is_(True),
            user_model.is_active.is_(True),
        )
        superusers = await session.all(superusers_q)
        for user in superusers:
            recipients.append(
                {
                    "id": getattr(user, "id", None),
                    "email": getattr(user, "email", None),
                    "phone": getattr(user, "phone", None),
                    "channels": cfg.default_channels,
                }
            )

        pref_q = qb.where(
            qb.select(NotificationPreference),
            NotificationPreference.enabled.is_(True),
        )
        pref_user_ids = {
            str(getattr(row, "user_id", None))
            for row in await session.all(pref_q)
            if getattr(row, "user_id", None) is not None
        }
        if pref_user_ids:
            # Pull active non-superusers and filter by pref in Python so the
            # query stays backend-agnostic (no cast()/String literal needed).
            regular_q = qb.where(
                qb.select(user_model),
                user_model.is_superuser.is_(False),
                user_model.is_active.is_(True),
            )
            for user in await session.all(regular_q):
                if str(getattr(user, "id", "")) in pref_user_ids:
                    recipients.append(
                        {
                            "id": getattr(user, "id", None),
                            "email": getattr(user, "email", None),
                            "phone": getattr(user, "phone", None),
                            "channels": cfg.default_channels,
                        }
                    )

    # Never notify the actor about their own change.
    if cfg.exclude_actor and actor_id is not None:
        recipients = [r for r in recipients if str(r.get("id")) != str(actor_id)]

    if not recipients:
        return

    # Build data payload for the notification
    actor_email: str | None = None
    if actor is not None:
        actor_email = getattr(actor, "email", None)

    data = {
        "model_name": registered.model.__name__,
        "table_name": registered.table_name,
        "event": event,
        "object_id": str(object_id) if object_id is not None else "",
        "object_repr": object_repr or "",
        "actor_email": actor_email or "",
    }

    # Determine title and body from config template or fallback
    title: str = ""
    body: str = ""

    if cfg.template_name is not None:
        from fastapi_admin_kit.notifications.config import TemplateRegistry

        registry: TemplateRegistry = getattr(
            registered.admin,
            "notification_template_registry",
            TemplateRegistry(),
        )
        try:
            rendered = registry.render(cfg.template_name, data)
            title = rendered.get("title", "")
            body = rendered.get("body", "")
        except KeyError:
            title = f"{registered.model.__name__} {event}"
            body = f"{registered.model.__name__} was {event}d."
    else:
        title = f"{registered.model.__name__} {event}"
        body = f"{registered.model.__name__} was {event}d."

    # Build recipient dicts for service.notifyMany
    recipient_dicts: list[dict[str, Any]] = []
    for r in recipients:
        recipient_dicts.append(
            {
                "user_id": r["id"],
                "email": r.get("email"),
                "phone": r.get("phone"),
                "channels": r.get("channels", cfg.default_channels),
            }
        )

    # Use the app's configured service (same hub the WebSocket endpoint
    # subscribes to) so in-app notifications are pushed in realtime.
    service: NotificationService | None = getattr(request.app.state, "notification_service", None)
    if service is None:
        service = getattr(request.state, "notification_service", None)
    if service is None:
        # No service configured — there is nothing to deliver.
        return

    # Resolve a DB session for the service (from per-request state or fallback)
    session = get_db_session(request)

    # Dispatch notifications to all recipients
    await service.notify_many(
        recipients=recipient_dicts,
        message=body,
        channels=None,  # let service use per-recipient channels or defaults
        title=title,
        data=data,
        session=session,
    )
