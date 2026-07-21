"""Permission management CLI commands."""

from __future__ import annotations

import argparse
import asyncio

ACTIONS = ["view", "create", "edit", "delete"]


async def _create_permissions(args: argparse.Namespace) -> None:
    """Create 4 CRUD permissions for specified tables or all registered tables.

    Supports two modes for specifying models:
    1. --base path.to.Base  → create permissions for all subclasses of the base
    2. Positional args       → full dotted paths to individual models (e.g. app.models.User)
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    from fastapi_admin_kit.auth.models import Permission
    from fastapi_admin_kit.models.base import Base

    from .helpers import resolve_model_by_path, resolve_models_from_base, resolve_table_names
    from .user import _resolve_database_url

    database_url = _resolve_database_url(args.database_url)
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"timeout": 30}
    engine = create_async_engine(database_url, poolclass=NullPool, connect_args=connect_args)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # --- Resolve which models to create permissions for ---

    table_names: dict[str, str] = {}  # display_name -> table_name

    if args.base:
        # Mode 1: --base flag → import base class, find all subclasses
        models = resolve_models_from_base(args.base, app_module=args.app)
        if not models:
            print(f"No model subclasses found for base '{args.base}'.")
            await engine.dispose()
            return
        print(f"Found {len(models)} model(s) subclassing '{args.base}':")
        for cls in models:
            table_names[cls.__name__] = cls.__tablename__
            print(f"  {cls.__name__} -> {cls.__tablename__}")
    elif args.tables:
        # Mode 2: positional args → resolve each one
        names = args.tables
        # Detect if these are dotted paths (contain a dot) or legacy short names
        has_dot = any("." in n for n in names)
        if has_dot:
            # Dotted paths — import directly
            for path in names:
                try:
                    cls = resolve_model_by_path(path, app_module=args.app)
                    table_names[cls.__name__] = cls.__tablename__
                    print(f"  Resolving '{path}' -> table_name='{cls.__tablename__}'")
                except (ImportError, AttributeError, TypeError) as exc:
                    print(f"  WARNING: Could not resolve '{path}': {exc}")
        else:
            # Legacy short class/table names
            table_names = resolve_table_names(names, app_module=args.app)
            for input_name, tname in table_names.items():
                print(f"  Resolving '{input_name}' -> table_name='{tname}'")
    else:
        # No tables specified — discover all from built-in models
        from fastapi_admin_kit.audit.models import AuditLog
        from fastapi_admin_kit.auth.models import (
            LoginAttempt,
            Permission,
            RefreshToken,
            Role,
            User,
            UserPermission,
            UserTOTP,
        )

        all_models = [
            User,
            Role,
            Permission,
            UserPermission,
            RefreshToken,
            UserTOTP,
            LoginAttempt,
            AuditLog,
        ]
        for cls in all_models:
            table_names[cls.__name__] = cls.__tablename__

    if not table_names:
        print("No tables found to create permissions for.")
        await engine.dispose()
        return

    created = 0
    skipped = 0

    async with async_session() as session:
        with session.no_autoflush:
            for display_name, table_name in table_names.items():
                for action in ACTIONS:
                    perm_name = f"{table_name}_{action}"

                    result = await session.execute(
                        select(Permission).where(Permission.name == perm_name)
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        skipped += 1
                        continue

                    perm = Permission(
                        name=perm_name,
                        table_name=table_name,
                        can_view=(action == "view"),
                        can_create=(action == "create"),
                        can_edit=(action == "edit"),
                        can_delete=(action == "delete"),
                    )
                    session.add(perm)
                    created += 1

            await session.commit()

    await engine.dispose()

    print(f"\nPermissions created: {created}, skipped (already exist): {skipped}")


async def _create_admin_permissions(args: argparse.Namespace) -> None:
    """Create 4 CRUD permissions for all admin models.

    Finds all models by scanning subclasses of the admin Base class.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    from fastapi_admin_kit.auth.models import Permission
    from fastapi_admin_kit.models.base import Base

    from .helpers import resolve_models_from_base
    from .user import _resolve_database_url

    admin_base_path = "fastapi_admin_kit.models.base.Base"

    models = resolve_models_from_base(admin_base_path)
    if not models:
        print("No admin models found.")
        return

    table_names: dict[str, str] = {}
    print(f"Found {len(models)} admin model(s):")
    for cls in models:
        table_names[cls.__name__] = cls.__tablename__
        print(f"  {cls.__name__} -> {cls.__tablename__}")

    database_url = _resolve_database_url(args.database_url)
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"timeout": 30}
    engine = create_async_engine(database_url, poolclass=NullPool, connect_args=connect_args)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    created = 0
    skipped = 0

    async with async_session() as session:
        with session.no_autoflush:
            for display_name, table_name in table_names.items():
                for action in ACTIONS:
                    perm_name = f"{table_name}_{action}"

                    result = await session.execute(
                        select(Permission).where(Permission.name == perm_name)
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        skipped += 1
                        continue

                    perm = Permission(
                        name=perm_name,
                        table_name=table_name,
                        can_view=(action == "view"),
                        can_create=(action == "create"),
                        can_edit=(action == "edit"),
                        can_delete=(action == "delete"),
                    )
                    session.add(perm)
                    created += 1

            await session.commit()

    await engine.dispose()

    print(f"\nPermissions created: {created}, skipped (already exist): {skipped}")


async def _delete_permissions(args: argparse.Namespace) -> None:
    """Delete all permissions and clear role-permission associations."""
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    from fastapi_admin_kit.auth.models import Permission, admin_role_permissions
    from fastapi_admin_kit.models.base import Base

    from .user import _resolve_database_url

    database_url = _resolve_database_url(args.database_url)
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"timeout": 30}
    engine = create_async_engine(database_url, poolclass=NullPool, connect_args=connect_args)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # First clear role-permission associations
        await session.execute(delete(admin_role_permissions))
        # Then delete all permissions
        await session.execute(delete(Permission))
        await session.commit()

    await engine.dispose()

    print("Deleted all permissions (and role-permission associations).")


def register_permission_commands(subparsers) -> None:
    """Register permission management subcommands."""
    perm_parser = subparsers.add_parser(
        "createpermissions",
        help="Create 4 CRUD permissions for tables",
    )
    perm_parser.add_argument(
        "tables",
        nargs="*",
        help=(
            "Model paths with dot notation (e.g., myapp.models.User myapp.models.Product). "
            "If empty and --base is not set, creates for all built-in tables."
        ),
    )
    perm_parser.add_argument(
        "-b",
        "--base",
        default=None,
        help=(
            "Dot-notation path to a base class. Creates permissions for all "
            "SQLAlchemy model subclasses of this base (e.g., myapp.models.Base)"
        ),
    )
    perm_parser.add_argument(
        "-a",
        "--app",
        default=None,
        help="App module to import for model discovery (e.g., example:app)",
    )
    perm_parser.add_argument(
        "-d",
        "--database-url",
        default=None,
        help="Database URL (or set DATABASE_URL env var)",
    )

    admin_perm_parser = subparsers.add_parser(
        "createadminpermissions",
        help="Create CRUD permissions for all admin models",
    )
    admin_perm_parser.add_argument(
        "-d",
        "--database-url",
        default=None,
        help="Database URL (or set DATABASE_URL env var)",
    )

    del_parser = subparsers.add_parser(
        "deletepermissions",
        help="Delete all permissions and role-permission associations",
    )
    del_parser.add_argument(
        "-a",
        "--app",
        default=None,
        help="App module to import for model discovery (e.g., example:app)",
    )
    del_parser.add_argument(
        "-d",
        "--database-url",
        default=None,
        help="Database URL (or set DATABASE_URL env var)",
    )


def handle_permission_command(args: argparse.Namespace) -> None:
    """Dispatch permission management commands."""
    if args.command == "createpermissions":
        asyncio.run(_create_permissions(args))
    elif args.command == "createadminpermissions":
        asyncio.run(_create_admin_permissions(args))
    elif args.command == "deletepermissions":
        asyncio.run(_delete_permissions(args))
