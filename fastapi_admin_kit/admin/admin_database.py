"""Admin database setup and initialization."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class AdminDatabase:
    """Handles database setup, table creation, and role seeding."""

    def __init__(
        self,
        engine: Any | None = None,
        base: Any | None = None,
    ):
        self.engine = engine
        self.base = base

    async def _create_tables(self) -> None:
        """Create all admin database tables (async-safe)."""
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
        else:
            # Sync engine - direct call
            AdminBase.metadata.create_all(bind=self.engine)
            if self.base is not None:
                self.base.metadata.create_all(bind=self.engine)

    async def _seed_roles(
        self, seed_roles: list, seed_roles_overwrite: bool = False
    ) -> None:
        """Seed default roles if none exist (or if overwrite is enabled)."""
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
        from sqlalchemy.orm import Session, sessionmaker

        from fastapi_admin_kit.auth.models import AdminPermission, AdminRole

        is_async = isinstance(self.engine, AsyncEngine)

        if is_async:
            # Use AsyncSession for async engine
            session_local = sessionmaker(
                self.engine, class_=AsyncSession, expire_on_commit=False
            )
            async with session_local() as session:
                # Check existing count
                result = await session.execute(select(AdminRole))
                existing_count = len(result.scalars().all())

                if existing_count > 0 and not seed_roles_overwrite:
                    return

                if seed_roles_overwrite:
                    await session.execute(select(AdminRole).delete())

                for role_spec in seed_roles:
                    role = AdminRole(
                        name=role_spec.name, description=role_spec.description
                    )
                    session.add(role)
                    await session.flush()  # get role.id

                    if role_spec.permissions:
                        for table_name, perms in role_spec.permissions.items():
                            perm = AdminPermission(
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
                existing_count = session.query(AdminRole).count()

                if existing_count > 0 and not seed_roles_overwrite:
                    return

                if seed_roles_overwrite:
                    session.query(AdminRole).delete()

                for role_spec in seed_roles:
                    role = AdminRole(
                        name=role_spec.name, description=role_spec.description
                    )
                    session.add(role)
                    session.flush()  # get role.id

                    if role_spec.permissions:
                        for table_name, perms in role_spec.permissions.items():
                            perm = AdminPermission(
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
