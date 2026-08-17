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

from sqlalchemy import String, cast, select

from fastapi_admin_kit.db import get_db_session
from fastapi_admin_kit.migrations.models import NotificationPreference, User
from fastapi_admin_kit.notifications.config import ChangeNotificationConfig
from fastapi_admin_kit.notifications.service import NotificationService


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

        recipients = []
        superusers = await session.all(
            select(User).where(
                User.is_superuser.is_(True),
                User.is_active.is_(True),
            )
        )
        for user in superusers:
            recipients.append(
                {
                    "id": getattr(user, "id", None),
                    "email": getattr(user, "email", None),
                    "phone": getattr(user, "phone", None),
                    "channels": cfg.default_channels,
                }
            )

        pref_user_ids = set(
            await session.all(
                select(NotificationPreference.user_id).where(
                    NotificationPreference.enabled.is_(True)
                )
            )
        )
        if pref_user_ids:
            regular = await session.all(
                select(User).where(
                    User.is_superuser.is_(False),
                    User.is_active.is_(True),
                    cast(User.id, String).in_(pref_user_ids),
                )
            )
            for user in regular:
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
