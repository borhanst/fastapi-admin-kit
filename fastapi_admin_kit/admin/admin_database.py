"""Admin database setup and initialization."""

from __future__ import annotations

from typing import Any

from fastapi_admin_kit.config.database import DatabaseConfig


class AdminDatabase:
    """Handles database setup, table creation, and role seeding."""

    def __init__(
        self,
        engine: Any | None = None,
        base: Any | None = None,
        database_config: DatabaseConfig | None = None,
    ):
        self.engine = engine
        self.base = base
        self.database_config = database_config

    def _ensure_engine(self) -> Any:
        """Create the async engine from ``database_config`` if no engine is set."""
        if self.engine is None and self.database_config is not None:
            self.engine = self.database_config.create_engine()
        return self.engine

    async def _create_tables(self) -> None:
        """Create all admin database tables (async-safe)."""
        from sqlalchemy import inspect as sa_inspect, text
        from sqlalchemy.ext.asyncio import AsyncEngine

        from fastapi_admin_kit.audit import models as _audit_models  # noqa: F401

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
                await conn.run_sync(self._auto_migrate, AdminBase)
                if self.base is not None:
                    await conn.run_sync(self._auto_migrate, self.base)
        else:
            # Sync engine - direct call
            AdminBase.metadata.create_all(bind=self.engine)
            if self.base is not None:
                self.base.metadata.create_all(bind=self.engine)
            # Auto-migrate: add missing columns
            self._auto_migrate_sync(AdminBase)
            if self.base is not None:
                self._auto_migrate_sync(self.base)

    def _auto_migrate_sync(self, metadata: Any) -> None:
        """Sync version of auto-migrate."""
        from sqlalchemy import text, inspect as sa_inspect

        inspector = sa_inspect(self.engine)
        for table_name, table in metadata.tables.items():
            if not inspector.has_table(table_name):
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name not in existing_cols:
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
                        f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type} {nullable}{default}"
                    )
                    with self.engine.begin() as conn:
                        conn.execute(sql)

    async def _auto_migrate(self, conn: Any, metadata: Any) -> None:
        """Add missing columns to existing tables."""
        from sqlalchemy import inspect as sa_inspect, text

        dialect = conn.bind.dialect if hasattr(conn, "bind") else None
        if dialect is None:
            return

        def _run(sync_conn):
            inspector = sa_inspect(sync_conn)
            for table_name, table in metadata.tables.items():
                if not inspector.has_table(table_name):
                    continue
                existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
                for col in table.columns:
                    if col.name not in existing_cols:
                        col_type = col.type.compile(dialect)
                        nullable = "NULL" if col.nullable else "NOT NULL"
                        default = ""
                        if col.server_default is not None:
                            default_sql = col.server_default.arg
                            if hasattr(default_sql, "text"):
                                default_sql = default_sql.text
                            default = f" DEFAULT {default_sql}"
                        sql = text(
                            f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type} {nullable}{default}"
                        )
                        sync_conn.execute(sql)

        await conn.run_sync(_run)

    async def _seed_roles(
        self, seed_roles: list, seed_roles_overwrite: bool = False
    ) -> None:
        """Seed default roles if none exist (or if overwrite is enabled)."""
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
        from sqlalchemy.orm import Session, sessionmaker

        from fastapi_admin_kit.auth.models import Permission, Role

        is_async = isinstance(self.engine, AsyncEngine)

        if is_async:
            # Use AsyncSession for async engine
            session_local = sessionmaker(
                self.engine, class_=AsyncSession, expire_on_commit=False
            )
            async with session_local() as session:
                # Check existing count
                result = await session.execute(select(Role))
                existing_count = len(result.scalars().all())

                if existing_count > 0 and not seed_roles_overwrite:
                    return

                if seed_roles_overwrite:
                    await session.execute(select(Role).delete())

                for role_spec in seed_roles:
                    role = Role(
                        name=role_spec.name, description=role_spec.description
                    )
                    session.add(role)
                    await session.flush()  # get role.id

                    if role_spec.permissions:
                        for table_name, perms in role_spec.permissions.items():
                            perm = Permission(
                                role_id=role.id,
                                table_name=table_name,
                                can_view=perms.get("view", False),
                                can_create=perms.get("create", False),
                                can_edit=perms.get("edit", False),
                                can_delete=perms.get("delete", False),
                            )
                            session.add(perm)

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
                    role = Role(
                        name=role_spec.name, description=role_spec.description
                    )
                    session.add(role)
                    session.flush()  # get role.id

                    if role_spec.permissions:
                        for table_name, perms in role_spec.permissions.items():
                            perm = Permission(
                                role_id=role.id,
                                table_name=table_name,
                                can_view=perms.get("view", False),
                                can_create=perms.get("create", False),
                                can_edit=perms.get("edit", False),
                                can_delete=perms.get("delete", False),
                            )
                            session.add(perm)

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
