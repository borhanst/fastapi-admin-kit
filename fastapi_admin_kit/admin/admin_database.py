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
    ):
        self.engine = engine
        self.base = base
        self.database_config = database_config
        self._backend = SqlAlchemyDatabaseBackend(
            admin_database=self, database_config=database_config
        )

    def _ensure_engine(self) -> Any:
        """Create the async engine from ``database_config`` if no engine is set."""
        if self.engine is None and self.database_config is not None:
            self.engine = self.database_config.create_engine()
        return self.engine

    async def _create_tables(self) -> None:
        """Create all admin database tables (async-safe)."""
        from sqlalchemy.ext.asyncio import AsyncEngine

        from fastapi_admin_kit.audit import (
            models as _audit_models,  # noqa: F401
        )

        # Import models to register them with metadata
        from fastapi_admin_kit.auth import models as _auth_models  # noqa: F401
        from fastapi_admin_kit.models.base import Base as AdminBase

        if isinstance(self.engine, AsyncEngine):
            # Async engine - use run_sync
            async with self.engine.begin() as conn:
                # Create admin tables
                await conn.run_sync(AdminBase.metadata.create_all)
                # Create user tables if Base is provided
                if self.base is not None:
                    await conn.run_sync(self.base.metadata.create_all)
                # Auto-migrate: add missing columns
                await conn.run_sync(self._auto_migrate, AdminBase.metadata)
                if self.base is not None:
                    await conn.run_sync(self._auto_migrate, self.base.metadata)
        else:
            # Sync engine - direct call
            AdminBase.metadata.create_all(bind=self.engine)
            if self.base is not None:
                self.base.metadata.create_all(bind=self.engine)
            # Auto-migrate: add missing columns
            self._auto_migrate_sync(AdminBase.metadata)
            if self.base is not None:
                self._auto_migrate_sync(self.base.metadata)

    def _auto_migrate_sync(self, metadata: Any) -> None:
        """Sync version of auto-migrate."""
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy import text

        inspector = sa_inspect(self.engine)
        for table_name, table in metadata.tables.items():
            if not inspector.has_table(table_name):
                continue
            safe_table = _validate_identifier(table_name)
            existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name not in existing_cols:
                    safe_col = _validate_identifier(col.name, "column")
                    col_type = col.type.compile(self.engine.dialect)
                    nullable = "NULL" if col.nullable else "NOT NULL"
                    default = ""
                    if col.server_default is not None:
                        default_sql = col.server_default.arg
                        if hasattr(default_sql, "text"):
                            default_sql = default_sql.text
                        default = f" DEFAULT {default_sql}"
                    elif col.default is not None and col.default.is_seq:
                        pass
                    sql = text(
                        f"""ALTER TABLE {safe_table}
                        ADD COLUMN {safe_col} {col_type}
                        {nullable}{default}"""
                    )
                    with self.engine.begin() as conn:
                        conn.execute(sql)

    def _auto_migrate(self, sync_conn: Any, metadata: Any) -> None:
        """Add missing columns to existing tables (sync, called via run_sync)."""
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy import text

        dialect = sync_conn.dialect if hasattr(sync_conn, "dialect") else None
        if dialect is None:
            return

        inspector = sa_inspect(sync_conn)
        for table_name, table in metadata.tables.items():
            if not inspector.has_table(table_name):
                continue
            safe_table = _validate_identifier(table_name)
            existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name not in existing_cols:
                    safe_col = _validate_identifier(col.name, "column")
                    col_type = col.type.compile(dialect)
                    nullable = "NULL" if col.nullable else "NOT NULL"
                    default = ""
                    if col.server_default is not None:
                        default_sql = col.server_default.arg
                        if hasattr(default_sql, "text"):
                            default_sql = default_sql.text
                        default = f" DEFAULT {default_sql}"
                    elif not col.nullable:
                        # SQLite requires a default for NOT NULL columns being added
                        type_defaults = {
                            "VARCHAR": "''",
                            "TEXT": "''",
                            "INTEGER": "0",
                            "FLOAT": "0.0",
                            "BOOLEAN": "0",
                            "DATETIME": "''",
                        }
                        sql_type = col_type.upper().split("(")[0]
                        temp_val = type_defaults.get(sql_type, "''")
                        default = f" DEFAULT {temp_val}"
                    sql = text(
                        f"""ALTER TABLE {safe_table}
                        ADD COLUMN
                        {safe_col} {col_type} {nullable}{default}
                        """
                    )
                    sync_conn.execute(sql)

    async def _seed_roles(self, seed_roles: list, seed_roles_overwrite: bool = False) -> None:
        """Seed default roles if none exist (or if overwrite is enabled)."""
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
        from sqlalchemy.orm import Session, sessionmaker

        from fastapi_admin_kit.auth.models import Permission, Role

        is_async = isinstance(self.engine, AsyncEngine)

        if is_async:
            # Use AsyncSession for async engine
            session_local = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
            async with session_local() as session:
                # Check existing count
                result = await session.execute(select(Role))
                existing_count = len(result.scalars().all())

                if existing_count > 0 and not seed_roles_overwrite:
                    return

                if seed_roles_overwrite:
                    await session.execute(select(Role).delete())

                for role_spec in seed_roles:
                    role = Role(name=role_spec.name, description=role_spec.description)
                    session.add(role)
                    await session.flush()  # get role.id
                    # Eagerly load M2M relationship for async session
                    await session.refresh(role, ["permissions"])

                    if role_spec.permissions:
                        for table_name, perms in role_spec.permissions.items():
                            # Find or create permission for this table
                            from sqlalchemy import select as sa_select

                            result = await session.execute(
                                sa_select(Permission).filter_by(table_name=table_name)
                            )
                            existing = result.scalar_one_or_none()
                            if existing is None:
                                perm = Permission(
                                    name=table_name,
                                    table_name=table_name,
                                    can_view=perms.get("view", False),
                                    can_create=perms.get("create", False),
                                    can_edit=perms.get("edit", False),
                                    can_delete=perms.get("delete", False),
                                )
                                session.add(perm)
                                await session.flush()
                            else:
                                perm = existing
                            # Link permission to role via M2M
                            role.permissions.append(perm)

                await session.commit()
        else:
            # Use sync Session for sync engine
            session = Session(bind=self.engine)
            try:
                existing_count = session.query(Role).count()

                if existing_count > 0 and not seed_roles_overwrite:
                    return

                if seed_roles_overwrite:
                    session.query(Role).delete()

                for role_spec in seed_roles:
                    role = Role(name=role_spec.name, description=role_spec.description)
                    session.add(role)
                    session.flush()  # get role.id

                    if role_spec.permissions:
                        for table_name, perms in role_spec.permissions.items():
                            # Find or create permission for this table
                            existing = (
                                session.query(Permission).filter_by(table_name=table_name).first()
                            )
                            if existing is None:
                                perm = Permission(
                                    name=table_name,
                                    table_name=table_name,
                                    can_view=perms.get("view", False),
                                    can_create=perms.get("create", False),
                                    can_edit=perms.get("edit", False),
                                    can_delete=perms.get("delete", False),
                                )
                                session.add(perm)
                                session.flush()
                            else:
                                perm = existing
                            # Link permission to role via M2M
                            role.permissions.append(perm)

                session.commit()
            finally:
                session.close()

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
