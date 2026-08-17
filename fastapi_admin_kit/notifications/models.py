"""Database models for in-app notifications.

These are thin re-exports of the schema-materialized models from
``fastapi_admin_kit.migrations.models``.  Keeping the names here gives the
notifications package a single import point that is also usable outside the
admin panel (the models are plain SQLAlchemy classes).
"""

from fastapi_admin_kit.migrations.models import (
    Notification,
    NotificationLog,
    NotificationPreference,
)

__all__ = ["Notification", "NotificationPreference", "NotificationLog"]
