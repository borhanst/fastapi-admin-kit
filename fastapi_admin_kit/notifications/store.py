"""Backend-agnostic persistence for the notification system.

``NotificationStore`` is the single home for every notification read/write.
It mirrors the canonical ``AIConversationStore`` pattern
(``ai/conversation.py``): all queries are built through a
:class:`QueryBackend` and executed through a :class:`SessionBackend`, so the
notification system never depends on SQLAlchemy directly.

The store is consumed by :class:`NotificationService`, which builds one per
operation from its configured ``backend`` / ``models``.

Backend contract the notification system depends on
------------------------------------------------------

- ``QueryBackend.select(model)`` / ``.where`` / ``.order_by`` / ``.limit`` /
  ``.offset`` / ``.count``
- ``SessionBackend.add`` / ``flush`` / ``commit`` / ``scalar_one_or_none`` /
  ``all`` / ``count`` / ``get`` / ``close``
- ``DatabaseBackend.materialize(schema)`` -> produces the ``Notification`` /
  ``NotificationPreference`` / ``NotificationLog`` model classes for that ORM
- ``DatabaseBackend.create_session_factory(connection)`` -> a standalone
  ``session_factory=``
- After ``flush()``, the object's auto-increment ``id`` is populated (the store
  returns it from ``create_notification``)
- ``session.add(fetched_obj)`` after mutation is accepted (idempotent in
  SQLAlchemy, overwrite-by-pk in the in-memory backend)

Adding a new ORM requires **zero** changes inside ``notifications/``: the new
ORM only needs to implement the protocols above, then pass its composite
``backend`` (with ``.query`` and ``.database``) to ``NotificationService``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from fastapi_admin_kit.backends import as_session_backend
from fastapi_admin_kit.schemas.builtin import (
    NOTIFICATION_LOG_SCHEMA,
    NOTIFICATION_PREFERENCE_SCHEMA,
    NOTIFICATION_SCHEMA,
)

if TYPE_CHECKING:
    from fastapi_admin_kit.backends.protocols import QueryBackend, SessionBackend


class NotificationStore:
    """ORM-agnostic persistence for notifications, preferences, and logs.

    All reads/writes go through the backend adapters: ``query_backend``
    (a :class:`QueryBackend`) builds queries and ``session_backend`` (a
    :class:`SessionBackend` wrapping the session) executes them.  When a
    composite ``backend`` is supplied its ``.query`` adapter is used and the
    notification models are materialized from ``NOTIFICATION_SCHEMA`` /
    ``NOTIFICATION_PREFERENCE_SCHEMA`` / ``NOTIFICATION_LOG_SCHEMA``.  Without
    a backend the store falls back to the ``migrations.models`` trio (the
    standalone / back-compat path).

    Mutating-fetch methods always re-``add()`` the fetched object before
    ``commit()`` so reconstructed rows (in-memory backend) persist; SQLAlchemy
    treats a re-``add()`` as a no-op.
    """

    def __init__(
        self,
        session: Any,
        *,
        query_backend: QueryBackend | None = None,
        session_backend: SessionBackend | None = None,
        backend: Any = None,
        models: Any = None,
    ) -> None:
        self.session = session
        # Prefer the explicit adapter, then the composite backend's adapter.
        if query_backend is None and backend is not None:
            query_backend = getattr(backend, "query", None)
        self._qb = query_backend
        self._sb = session_backend or as_session_backend(session, backend=backend)

        if models is not None:
            self.models = models
        elif backend is not None:
            database = getattr(backend, "database", backend)
            self.models = SimpleNamespace(
                Notification=database.materialize(NOTIFICATION_SCHEMA),
                NotificationPreference=database.materialize(NOTIFICATION_PREFERENCE_SCHEMA),
                NotificationLog=database.materialize(NOTIFICATION_LOG_SCHEMA),
            )
        else:
            # Standalone / back-compat: reuse the materialized SQLAlchemy models.
            from fastapi_admin_kit.migrations.models import (
                Notification,
                NotificationLog,
                NotificationPreference,
            )

            self.models = SimpleNamespace(
                Notification=Notification,
                NotificationPreference=NotificationPreference,
                NotificationLog=NotificationLog,
            )

        self.Notification = self.models.Notification
        self.NotificationPreference = self.models.NotificationPreference
        self.NotificationLog = self.models.NotificationLog

    # -- adapter-aware query helpers ----------------------------------------

    def _select(self, model: Any) -> Any:
        if self._qb is not None:
            return self._qb.select(model)
        from sqlalchemy import select

        return select(model)

    def _where(self, stmt: Any, *conditions: Any) -> Any:
        if self._qb is not None:
            return self._qb.where(stmt, *conditions)
        return stmt.where(*conditions)

    def _order_by(self, stmt: Any, *columns: Any) -> Any:
        if self._qb is not None:
            return self._qb.order_by(stmt, *columns)
        return stmt.order_by(*columns)

    def _limit(self, stmt: Any, n: int) -> Any:
        if self._qb is not None:
            return self._qb.limit(stmt, n)
        return stmt.limit(n)

    def _offset(self, stmt: Any, n: int) -> Any:
        if self._qb is not None:
            return self._qb.offset(stmt, n)
        return stmt.offset(n)

    def _count_query(self, stmt: Any) -> Any:
        """Turn a SELECT into the count query a ``SessionBackend.count`` accepts."""
        if self._qb is not None:
            return self._qb.count(stmt)
        from sqlalchemy import func, select

        return select(func.count()).select_from(stmt.subquery())

    # -- adapter-aware execution helpers ------------------------------------

    async def _exec(self, stmt: Any) -> Any:
        """Execute *stmt* through the session adapter and return the result."""
        return await self._maybe_await(self._sb.execute(stmt))

    def _add(self, obj: Any) -> None:
        self._sb.add(obj)

    async def _flush(self) -> None:
        await self._maybe_await(self._sb.flush())

    async def _commit(self) -> None:
        await self._maybe_await(self._sb.commit())

    async def _scalar_one_or_none(self, stmt: Any) -> Any | None:
        return await self._maybe_await(self._sb.scalar_one_or_none(stmt))

    async def _all(self, stmt: Any) -> list[Any]:
        return await self._maybe_await(self._sb.all(stmt))

    async def _count(self, stmt: Any) -> int:
        return await self._maybe_await(self._sb.count(self._count_query(stmt)))

    async def _get(self, model: Any, pk: Any) -> Any | None:
        return await self._maybe_await(self._sb.get(model, pk))

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        """Await *value* when it is awaitable (async sessions), else return it."""
        if hasattr(value, "__await__"):
            return await value
        return value

    # -- preferences --------------------------------------------------------

    async def get_preference(self, user_id: str | int, channel: str) -> Any | None:
        """Return the preference row for *user_id* / *channel*, or None."""
        stmt = self._where(
            self._select(self.NotificationPreference),
            self.NotificationPreference.user_id == str(user_id),
            self.NotificationPreference.channel == channel,
        )
        return await self._scalar_one_or_none(stmt)

    async def set_preference(self, user_id: str | int, channel: str, enabled: bool) -> None:
        """Opt *user_id* in/out of *channel*."""
        pref = await self.get_preference(user_id, channel)
        if pref is None:
            pref = self.NotificationPreference(user_id=str(user_id), channel=channel)
            self._add(pref)
        pref.enabled = enabled
        pref.updated_at = datetime.now(UTC)
        self._add(pref)
        await self._commit()

    async def get_preferences(self, user_id: str | int) -> dict[str, bool]:
        """Return a dict mapping channel -> enabled for *user_id*."""
        stmt = self._where(
            self._select(self.NotificationPreference),
            self.NotificationPreference.user_id == str(user_id),
        )
        prefs = await self._all(stmt)
        return {pref.channel: bool(pref.enabled) for pref in prefs}

    # -- notifications ------------------------------------------------------

    async def create_notification(
        self,
        *,
        user_id: str,
        email: str | None,
        title: str,
        body: str,
        channels: list[str],
        data: dict[str, Any] | None,
    ) -> int:
        """Persist a pending in-app notification and return its auto-increment id."""
        notif = self.Notification(
            user_id=user_id,
            user_email=email,
            title=title,
            body=body,
            channels=channels,
            data=data,
            status="pending",
            is_read=False,
        )
        self._add(notif)
        await self._flush()
        return int(notif.id)

    async def get_notification(
        self, notification_id: int, user_id: str | None = None
    ) -> Any | None:
        """Fetch a notification by id, optionally scoped to *user_id*."""
        if user_id is None:
            return await self._get(self.Notification, notification_id)
        stmt = self._where(
            self._select(self.Notification),
            self.Notification.id == notification_id,
            self.Notification.user_id == user_id,
        )
        return await self._scalar_one_or_none(stmt)

    async def set_notification_status(self, notification_id: int, status: str) -> bool:
        """Update the delivery status of a notification.  Returns False if missing."""
        notif = await self.get_notification(notification_id)
        if notif is None:
            return False
        notif.status = status
        self._add(notif)
        await self._commit()
        return True

    # -- logs ---------------------------------------------------------------

    async def create_log(
        self,
        *,
        notification_id: int | None,
        user_id: str,
        channel: str,
        provider: str,
        recipient: str | None,
        status: str,
        error: str | None,
    ) -> None:
        self._add(
            self.NotificationLog(
                notification_id=notification_id or 0,
                user_id=user_id,
                channel=channel,
                provider=provider,
                recipient=recipient,
                status=status,
                error=error,
            )
        )
        await self._commit()

    # -- router-facing reads ------------------------------------------------

    async def list_for_user(
        self,
        user_id: str | int,
        *,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> list[Any]:
        """List a user's in-app notifications, newest first."""
        stmt = self._where(
            self._select(self.Notification),
            self.Notification.user_id == str(user_id),
        )
        if unread_only:
            stmt = self._where(stmt, self.Notification.is_read == False)  # noqa: E712
        stmt = self._order_by(stmt, self.Notification.id.desc())
        stmt = self._limit(stmt, limit)
        stmt = self._offset(stmt, offset)
        return await self._all(stmt)

    async def unread_count(self, user_id: str | int) -> int:
        """Return the number of unread in-app notifications for *user_id*."""
        stmt = self._where(
            self._select(self.Notification),
            self.Notification.user_id == str(user_id),
            self.Notification.is_read == False,  # noqa: E712
        )
        return await self._count(stmt)

    async def mark_read(self, notification_id: int, user_id: str | int) -> bool:
        """Mark a user's notification as read.  Returns False if not found."""
        notif = await self.get_notification(notification_id, user_id=str(user_id))
        if notif is None:
            return False
        notif.is_read = True
        self._add(notif)
        await self._commit()
        return True
