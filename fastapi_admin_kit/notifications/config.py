"""Notification configuration and template registry."""

from __future__ import annotations

import string
from dataclasses import dataclass, field
from typing import Any


class NotificationTemplate:
    """A named, configurable notification template.

    Title/body may contain ``{placeholder}`` fields which are substituted with
    context values via :meth:`render`.
    """

    def __init__(
        self,
        name: str,
        title: str,
        body: str = "",
        sms_body: str | None = None,
        email_subject: str | None = None,
        email_html: str | None = None,
    ) -> None:
        self.name = name
        self.title = title
        self.body = body
        self.sms_body = sms_body if sms_body is not None else body
        self.email_subject = email_subject if email_subject is not None else title
        self.email_html = email_html

    def render(self, context: dict[str, Any] | None = None) -> dict[str, str]:
        """Render the template with *context*.

        Returns a dict with ``title``, ``body``, ``sms_body``, ``email_subject``
        and ``email_html`` keys.
        """
        ctx = context or {}
        formatter = string.Formatter()
        safe = {k: v for k, v in ctx.items() if not isinstance(v, dict | list | tuple)}
        return {
            "title": formatter.vformat(self.title, (), safe),
            "body": formatter.vformat(self.body, (), safe),
            "sms_body": formatter.vformat(self.sms_body, (), safe),
            "email_subject": formatter.vformat(self.email_subject, (), safe),
            "email_html": (
                formatter.vformat(self.email_html, (), safe) if self.email_html else None
            ),
        }


class TemplateRegistry:
    """Registry of named :class:`NotificationTemplate` objects."""

    def __init__(self) -> None:
        self._templates: dict[str, NotificationTemplate] = {}

    def register(self, template: NotificationTemplate) -> None:
        self._templates[template.name] = template

    def get(self, name: str) -> NotificationTemplate | None:
        return self._templates.get(name)

    def all(self) -> list[NotificationTemplate]:
        return list(self._templates.values())

    def render(self, name: str, context: dict[str, Any] | None = None) -> dict[str, str]:
        template = self.get(name)
        if template is None:
            raise KeyError(f"Notification template '{name}' not found.")
        return template.render(context)


@dataclass
class ChangeNotificationConfig:
    """Configuration for change notifications (create/update/delete).

    Attributes:
        enabled: Whether change notifications are active for this model.
        default_channels: Channels used when no per-recipient channels are specified.
        events: Which events trigger notifications.
        exclude_actor: Whether to exclude the actor (the admin who made the change)
            from receiving their own notifications.
        template_name: Name of a ``NotificationTemplate`` to use for title/body;
            if ``None``, fallback title/body are used.
    """

    enabled: bool = True
    default_channels: list[str] = field(default_factory=lambda: ["in_app"])
    events: list[str] = field(default_factory=lambda: ["create", "update", "delete"])
    exclude_actor: bool = True
    template_name: str | None = None


@dataclass
class NotificationConfig:
    """Top-level configuration for the notification system.

    Attributes:
        default_channels: Channels used when ``notify()`` is called without
            an explicit ``channels`` argument.
        fallback_channels: Ordered channels attempted when a primary channel
            fails (fallback mechanism).
        default_sms_provider: Name of the default SMS provider.
        default_email_provider: Name of the default email provider.
        templates: Template registry used by :class:`NotificationService`.
        change_notifications: Per-model change notification configuration.
    """

    default_channels: list[str] = field(default_factory=lambda: ["sms", "email"])
    fallback_channels: list[str] = field(default_factory=lambda: ["sms", "email"])
    default_sms_provider: str = "twilio"
    default_email_provider: str = "smtp"
    templates: TemplateRegistry = field(default_factory=TemplateRegistry)
    change_notifications: ChangeNotificationConfig = field(default_factory=ChangeNotificationConfig)
