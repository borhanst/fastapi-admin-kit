"""Database migration CLI commands."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys


async def _migrate_permissions(args: argparse.Namespace) -> None:
    """Convert old shared permissions to per-role permissions."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.orm import selectinload
    from sqlalchemy.pool import NullPool

    from fastapi_admin_kit.auth.models import Permission, Role
    from fastapi_admin_kit.models.base import Base as AdminBase  # noqa: F401

    from .user import _resolve_database_url

    database_url = _resolve_database_url(args.database_url)
    engine = create_async_engine(database_url, poolclass=NullPool)

    # Pattern: old permissions have names like "admin_users", "product_view"
    # New permissions have names like "1:admin_users", "2:product_view"
    old_perm_pattern = re.compile(r"^\d+:")  # Starts with digit: is new format

    async with engine.begin() as conn:
        await conn.run_sync(AdminBase.metadata.create_all)

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    converted = 0
    skipped = 0

    async with async_session() as session:
        # Load all roles with their permissions
        result = await session.execute(select(Role).options(selectinload(Role.permissions)))
        roles = result.scalars().all()

        for role in roles:
            old_perms = []
            for perm in role.permissions:
                # Check if this is an old shared permission (not starting with role_id:)
                if not old_perm_pattern.match(perm.name):
                    old_perms.append(perm)

            if not old_perms:
                skipped += 1
                continue

            for old_perm in old_perms:
                # Check if a per-role permission already exists for this table
                new_name = f"{role.id}:{old_perm.table_name}"
                existing = await session.execute(
                    select(Permission).where(Permission.name == new_name)
                )
                existing_perm = existing.scalar_one_or_none()

                if existing_perm is None:
                    # Create new per-role permission
                    new_perm = Permission(
                        name=new_name,
                        table_name=old_perm.table_name,
                        can_view=old_perm.can_view,
                        can_create=old_perm.can_create,
                        can_edit=old_perm.can_edit,
                        can_delete=old_perm.can_delete,
                    )
                    session.add(new_perm)
                    role.permissions.append(new_perm)
                else:
                    # Link existing per-role permission if not already linked
                    if existing_perm not in role.permissions:
                        role.permissions.append(existing_perm)

                # Unlink old shared permission from this role
                role.permissions.remove(old_perm)
                converted += 1

        await session.commit()

    await engine.dispose()

    print(f"Converted {converted} permission(s) to per-role format.")
    print(f"Roles processed: {len(roles)}, skipped (no old perms): {skipped}")


async def _migrate_tables(args: argparse.Namespace) -> None:
    """Add missing columns or drop obsolete columns from specified tables."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from fastapi_admin_kit.audit import models as _audit_models  # noqa: F401
    from fastapi_admin_kit.auth import models as _auth_models  # noqa: F401
    from fastapi_admin_kit.models.base import Base as AdminBase

    from .helpers import resolve_table_names
    from .user import _resolve_database_url

    database_url = _resolve_database_url(args.database_url)
    engine = create_async_engine(database_url, poolclass=NullPool)

    names = args.tables
    if not names:
        print("Error: No tables specified. Usage: fak migrate User Product")
        await engine.dispose()
        sys.exit(1)

    resolved = resolve_table_names(names)

    altered = 0

    async with engine.begin() as conn:
        for input_name, table_name in resolved.items():
            if table_name not in AdminBase.metadata.tables:
                print(f"Warning: '{input_name}' not found in metadata, skipping.")
                continue

            table = AdminBase.metadata.tables[table_name]

            # Get current model indexes
            model_indexes = set()
            for idx in table.indexes:
                if idx.name:
                    model_indexes.add(idx.name)

            # Drop indexes that exist in DB but not in model
            result = await conn.execute(
                text(
                    f"SELECT name, sql FROM sqlite_master "
                    f"WHERE type='index' AND tbl_name='{table_name}'"
                )
            )
            for idx_name, idx_sql in result.fetchall():
                if idx_name.startswith("sqlite_"):
                    continue  # Skip internal indexes
                if idx_name not in model_indexes:
                    try:
                        await conn.execute(text(f"DROP INDEX {idx_name}"))
                        print(f"  Dropped index '{idx_name}'")
                        altered += 1
                    except Exception:
                        pass

            # Check if table exists
            result = await conn.execute(
                text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
            )
            table_exists = result.scalar_one_or_none() is not None

            if not table_exists:
                # Create table from model
                await conn.run_sync(table.create)
                print(f"  Created table '{table_name}'")
                altered += 1
                continue

            result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
            existing_cols = {row[1] for row in result.fetchall()}
            model_cols = {col.name for col in table.columns}

            # If columns differ, recreate table
            if existing_cols != model_cols:
                # Backup existing data
                result = await conn.execute(text(f"SELECT * FROM {table_name}"))
                rows = result.fetchall()
                col_names_db = [
                    row[1]
                    for row in (
                        await conn.execute(text(f"PRAGMA table_info({table_name})"))
                    ).fetchall()
                ]

                # Drop old table
                await conn.execute(text(f"DROP TABLE {table_name}"))

                # Create new table from model
                await conn.run_sync(table.create)

                # Insert back data that matches new schema
                if rows:
                    new_cols = [col.name for col in table.columns]
                    insert_cols = [c for c in new_cols if c in col_names_db]
                    if insert_cols:
                        placeholders = ", ".join([f":{c}" for c in insert_cols])
                        cols_str = ", ".join(insert_cols)
                        sql = text(f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})")
                        for row in rows:
                            data = dict(zip(col_names_db, row))
                            filtered = {k: v for k, v in data.items() if k in insert_cols}
                            await conn.execute(sql, filtered)

                print(f"  Recreated table '{table_name}'")
                altered += 1

    await engine.dispose()

    if altered == 0:
        print("No changes needed. All columns up to date.")
    else:
        print(f"Migration complete. {altered} table(s) updated.")


def register_migrate_commands(subparsers) -> None:
    """Register database migration subcommands."""
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Add missing columns or drop obsolete columns from tables",
    )
    migrate_parser.add_argument(
        "tables",
        nargs="+",
        help="Class or table names to migrate (e.g., User Product admin_roles)",
    )
    migrate_parser.add_argument(
        "-d",
        "--database-url",
        default=None,
        help="Database URL (or set DATABASE_URL env var)",
    )

    # migrate-permissions subcommand
    perm_migrate_parser = subparsers.add_parser(
        "migrate-permissions",
        help="Convert old shared permissions to per-role permissions",
    )
    perm_migrate_parser.add_argument(
        "-d",
        "--database-url",
        default=None,
        help="Database URL (or set DATABASE_URL env var)",
    )


def handle_migrate_command(args: argparse.Namespace) -> None:
    """Dispatch migration commands."""
    if args.command == "migrate":
        asyncio.run(_migrate_tables(args))
    elif args.command == "migrate-permissions":
        asyncio.run(_migrate_permissions(args))
