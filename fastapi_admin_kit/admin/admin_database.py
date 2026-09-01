"""Admin database setup and initialization."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyDatabaseBackend
from fastapi_admin_kit.config.database import DatabaseConfig

logger = logging.getLogger(__name__)

_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(name: str, kind: str = "table") -> str:
    """Validate a SQL identifier to prevent injection."""
    if not _TABLE_NAME_RE.match(name):
        raise ValueError(f"Invalid {kind} name: {name!r}")
    return name


class AdminDatabase:
    """Handles database setup, table creation, and role seeding.

    Delegates engine creation, table creation, and auto-migration to
    :class:`SqlAlchemyDatabaseBackend`.
    """

    def __init__(
        self,
        engine: Any | None = None,
        base: Any | None = None,
        database_config: DatabaseConfig | None = None,
        use_alembic: bool = False,
    ):
        self.engine = engine
        self.base = base
        self.database_config = database_config
        self.use_alembic = use_alembic
        self._backend = SqlAlchemyDatabaseBackend(
            admin_database=self, database_config=database_config
        )

    @property
    def resolved_engine(self) -> Any:
        """Return the SQLAlchemy engine, lazily creating it from
        ``database_config`` if no engine was passed at construction time.

        This is the property to use everywhere a backend call needs an
        engine. Reading the raw ``self.engine`` attribute can be ``None``
        when the project supplied a ``database_config`` instead of an
        ``engine`` — calling methods on it then surfaces a confusing
        ``AttributeError: 'NoneType' object has no attribute
        '_run_ddl_visitor'`` from deep inside SQLAlchemy.
        """
        return self._ensure_engine()

    def _ensure_engine(self) -> Any:
        """Create the async engine from ``database_config`` if no engine is set."""
        if self.engine is None and self.database_config is not None:
            self.engine = self.database_config.create_engine()
        return self.engine

    async def _create_tables(
        self,
        include_ai_tables: bool = True,
        extra_exclude_tables: list[str] | None = None,
    ) -> None:
        """Create all admin database tables (async-safe).

        If ``use_alembic=True`` (production mode), this method does nothing
        and expects Alembic to manage the schema via migrations.

        When ``include_ai_tables=False`` (AI disabled), the four
        ``admin_ai_*`` tables are skipped. This is safe because the AI schemas
        declare ``relations=[]`` and no FK columns (the "log pattern"), so
        excluding them cannot break ``create_all`` dependency sorting.

        ``extra_exclude_tables`` lets callers (typically the ``Admin`` setup
        path) drop built-in tables that should not be created for this
        installation — most notably the default ``admin_users`` /
        ``admin_user_roles`` tables when a project supplies a custom
        ``auth_model``. Filtering at ``create_all`` time avoids mutating the
        shared ``AdminBase.metadata`` (whose FacadeDict is immutable).
        """
        if self.use_alembic:
            logger.info("use_alembic=True: skipping create_all; schema managed by Alembic")
            return

        from fastapi_admin_kit.migrations.models import Base as AdminBase
        from fastapi_admin_kit.schemas.builtin import AI_TABLE_NAMES

        exclude = set(extra_exclude_tables or ())

        # If the configured backend cloned the project's auth_model table
        # into AdminBase.metadata (so its FK can resolve within the same
        # MetaData), drop the clone from the create_all table list — the
        # project's own metadata owns the real table and DDL for it
        # would conflict. Check both the backend and the database
        # instance for the cloned names (the backend stores them on the
        # database when available, which is the more reliable path for
        # tests that swap the backend).
        cloned = set()
        backend = getattr(self, "_backend", None)
        if backend is not None:
            cloned = getattr(backend, "_cloned_auth_tables", set()) or set()
        cloned |= getattr(self, "_cloned_auth_tables", set()) or set()
        exclude |= cloned

        def _filtered(metadata: Any) -> Any:
            drop = exclude | (set() if include_ai_tables else AI_TABLE_NAMES)
            if not drop:
                return None  # create_all(tables=None) == all tables
            return [t for name, t in metadata.tables.items() if name not in drop]

        ai_filtered_admin = _filtered(AdminBase.metadata)
        ai_filtered_base = _filtered(self.base.metadata) if self.base is not None else None

        engine = self.resolved_engine
        if engine is None:
            raise RuntimeError(
                "AdminDatabase has no engine: pass `engine=` or "
                "`database_config=` to Admin() so the admin tables can be "
                "created. If you manage schema via Alembic, set "
                "`use_alembic=True` on Admin() to skip create_all."
            )

        await self._run_backend(
            self._backend.create_tables,
            engine,
            AdminBase.metadata,
            ai_filtered_admin,
        )
        if self.base is not None:
            await self._run_backend(
                self._backend.create_tables,
                engine,
                self.base.metadata,
                ai_filtered_base,
            )
        await self._run_backend(self._backend.auto_migrate, engine, AdminBase.metadata)
        if self.base is not None:
            await self._run_backend(self._backend.auto_migrate, engine, self.base.metadata)

    async def _missing_tables(self, ai_enabled: bool, names: list[str]) -> set[str]:
        """Return the subset of ``names`` whose tables do not exist yet.

        Used as a preflight check when AI is enabled but ``create_all`` did not
        run (Alembic / ``SKIP_CREATE_TABLES=true``). Wrapped in try/except by
        the caller so a flaky inspector can never block startup.
        """
        if not ai_enabled:
            return set()

        result = self._backend.has_tables(self.engine, names)
        if hasattr(result, "__await__"):
            result = await result
        return result

    async def _seed_roles(self, seed_roles: list, seed_roles_overwrite: bool = False) -> None:
        """Seed default roles if none exist (or if overwrite is enabled).

        Delegates to the backend's ``seed_roles`` with a session factory built
        from the current engine.
        """
        factory = self._backend.create_session_factory(self.engine)
        result = self._backend.seed_roles(factory, seed_roles, seed_roles_overwrite)
        if hasattr(result, "__await__"):
            await result

    @staticmethod
    async def _run_backend(method: Any, *args: Any) -> None:
        """Await a backend method that may return a coroutine (async) or None."""
        result = method(*args)
        if hasattr(result, "__await__"):
            await result

    def _init_session_backend(
        self, secret_key: str, session_ttl: int, cookie_name: str, secure: bool
    ) -> Any:
        """Create and store the signed-cookie session backend."""
        from fastapi_admin_kit.auth.session import SignedCookieSessionBackend

        return SignedCookieSessionBackend(
            secret_key=secret_key,
            session_ttl=session_ttl,
            cookie_name=cookie_name,
            secure=secure,
        )
