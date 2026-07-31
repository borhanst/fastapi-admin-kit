"""Database migration CLI commands."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(name: str, kind: str = "table") -> str:
    """Validate a SQL identifier to prevent injection. Raises ValueError if invalid."""
    if not _TABLE_NAME_RE.match(name):
        raise ValueError(f"Invalid {kind} name: {name!r}")
    return name


async def _migrate_permissions(args: argparse.Namespace) -> None:
    """Convert old shared permissions to per-role permissions."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.orm import selectinload
    from sqlalchemy.pool import NullPool

    from fastapi_admin_kit.migrations.models import Permission, Role

    from .user import _resolve_database_url

    database_url = _resolve_database_url(args.database_url)
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"timeout": 30}
    engine = create_async_engine(database_url, poolclass=NullPool, connect_args=connect_args)

    # Pattern: old permissions have names like "admin_users", "product_view"
    # New permissions have names like "1:admin_users", "2:product_view"
    old_perm_pattern = re.compile(r"^\d+:")  # Starts with digit: is new format

    from fastapi_admin_kit.migrations.models import Base as AdminBase

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

    logger.info("Converted %d permission(s) to per-role format.", converted)
    logger.info("Roles processed: %d, skipped (no old perms): %d", len(roles), skipped)


async def _migrate_tables(args: argparse.Namespace) -> None:
    """Add missing columns or drop obsolete columns from specified tables."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from fastapi_admin_kit.migrations.models import Base as AdminBase

    from .helpers import resolve_table_names
    from .user import _resolve_database_url

    database_url = _resolve_database_url(args.database_url)
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"timeout": 30}
    engine = create_async_engine(database_url, poolclass=NullPool, connect_args=connect_args)

    names = args.tables
    if not names:
        logger.error("No tables specified. Usage: fak migrate User Product")
        await engine.dispose()
        sys.exit(1)

    resolved = resolve_table_names(names)

    altered = 0

    async with engine.begin() as conn:
        for input_name, table_name in resolved.items():
            if table_name not in AdminBase.metadata.tables:
                logger.warning("'%s' not found in metadata, skipping.", input_name)
                continue

            safe_name = _validate_identifier(table_name)
            table = AdminBase.metadata.tables[table_name]

            # Get current model indexes
            model_indexes = set()
            for idx in table.indexes:
                if idx.name:
                    model_indexes.add(idx.name)

            # Drop indexes that exist in DB but not in model
            result = await conn.execute(
                text("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=:tbl"),
                {"tbl": safe_name},
            )
            for idx_name, idx_sql in result.fetchall():
                if idx_name.startswith("sqlite_"):
                    continue  # Skip internal indexes
                if idx_name not in model_indexes:
                    safe_idx = _validate_identifier(idx_name, "index")
                    try:
                        await conn.execute(text(f"DROP INDEX {safe_idx}"))
                        logger.info("Dropped index '%s'", idx_name)
                        altered += 1
                    except Exception:
                        pass

            # Check if table exists
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name=:tbl"),
                {"tbl": safe_name},
            )
            table_exists = result.scalar_one_or_none() is not None

            if not table_exists:
                # Create table from model
                await conn.run_sync(table.create)
                logger.info("Created table '%s'", table_name)
                altered += 1
                continue

            result = await conn.execute(text(f"PRAGMA table_info({safe_name})"))
            existing_cols = {row[1] for row in result.fetchall()}
            model_cols = {col.name for col in table.columns}

            # If columns differ, recreate table
            if existing_cols != model_cols:
                # Backup existing data
                result = await conn.execute(text(f"SELECT * FROM {safe_name}"))
                rows = result.fetchall()
                col_names_db = [
                    row[1]
                    for row in (
                        await conn.execute(text(f"PRAGMA table_info({safe_name})"))
                    ).fetchall()
                ]

                # Drop old table
                await conn.execute(text(f"DROP TABLE {safe_name}"))

                # Create new table from model
                await conn.run_sync(table.create)

                # Insert back data that matches new schema
                if rows:
                    new_cols = [col.name for col in table.columns]
                    insert_cols = [c for c in new_cols if c in col_names_db]
                    if insert_cols:
                        placeholders = ", ".join([f":{c}" for c in insert_cols])
                        cols_str = ", ".join(insert_cols)
                        sql = text(f"INSERT INTO {safe_name} ({cols_str}) VALUES ({placeholders})")
                        for row in rows:
                            data = dict(zip(col_names_db, row))
                            filtered = {k: v for k, v in data.items() if k in insert_cols}
                            await conn.execute(sql, filtered)

                logger.info("Recreated table '%s'", table_name)
                altered += 1

    await engine.dispose()

    if altered == 0:
        logger.info("No changes needed. All columns up to date.")
    else:
        logger.info("Migration complete. %d table(s) updated.", altered)


ALEMBIC_INI_TEMPLATE = """# Alembic configuration for FastAPI Admin Kit
[alembic]
script_location = alembic
prepend_sys_path = .
version_path_separator = os
sqlalchemy.url = sqlite+aiosqlite:///./your_database.db

# Logging configuration
[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
"""

ALEMBIC_ENV_TEMPLATE = '''"""Alembic environment configuration for FastAPI Admin Kit.

This file is generated by ``fak init-alembic``. You can customize it
for your project's needs.
"""

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Add project root to path so models can be imported
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Import admin models (materialized from schemas)
from fastapi_admin_kit.migrations.models import Base as AdminBase

# Import your application models here
# from myapp.models import Base as AppBase

# Combine metadata for autogenerate
target_metadata = [AdminBase.metadata]
# If you have app models, add them:
# target_metadata.append(AppBase.metadata)

config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
'''

ALEMBIC_SCRIPT_MAKO_TEMPLATE = '''"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision if down_revision else ""}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision) if down_revision else "None"}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels) if branch_labels else "None"}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on) if depends_on else "None"}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
'''


def _init_alembic(args: argparse.Namespace) -> None:
    """Initialize Alembic configuration for the project."""
    import subprocess

    # Extract module path from --app (e.g., "example:app" -> "example")
    if args.app:
        module_part = args.app.split(":")[0]
        # Try to find the module's file location
        import importlib.util

        spec = importlib.util.find_spec(module_part)
        if spec and spec.origin:
            project_root = Path(spec.origin).parent
        else:
            project_root = Path.cwd()
    else:
        project_root = Path.cwd()

    alembic_dir = project_root / "alembic"
    ini_file = project_root / "alembic.ini"

    # Check if alembic already exists
    if alembic_dir.exists() or ini_file.exists():
        if not args.force:
            print("Alembic already initialized in this project.")
            print("To integrate admin models, add to your existing alembic/env.py:")
            print()
            print("    from fastapi_admin_kit.migrations.models import Base as AdminBase")
            print("    target_metadata = [AdminBase.metadata]  # add your app metadata too")
            print()
            print("Then run: alembic revision --autogenerate -m 'add admin models'")
            print()
            if args.baseline:
                print("For baseline migration, run with --baseline flag.")
            return
        else:
            print("Overwriting existing Alembic configuration (--force used).")
            if alembic_dir.exists():
                shutil.rmtree(alembic_dir)
            if ini_file.exists():
                ini_file.unlink()

    # Create alembic directory structure
    alembic_dir.mkdir(parents=True, exist_ok=True)
    (alembic_dir / "versions").mkdir(exist_ok=True)

    # Write alembic.ini
    ini_content = ALEMBIC_INI_TEMPLATE
    if args.database_url:
        ini_content = ini_content.replace(
            "sqlalchemy.url = sqlite+aiosqlite:///./your_database.db",
            f"sqlalchemy.url = {args.database_url}",
        )
    ini_file.write_text(ini_content)

    # Write alembic/env.py
    (alembic_dir / "env.py").write_text(ALEMBIC_ENV_TEMPLATE)

    # Write script.py.mako
    (alembic_dir / "script.py.mako").write_text(ALEMBIC_SCRIPT_MAKO_TEMPLATE)

    print(f"Created Alembic configuration in {project_root}:")
    print(f"  - {ini_file}")
    print(f"  - {alembic_dir}/env.py")
    print(f"  - {alembic_dir}/script.py.mako")
    print(f"  - {alembic_dir}/versions/")

    # Auto-generate first migration if requested
    if args.auto_migrate:
        print("\nGenerating initial migration...")
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
            result = subprocess.run(
                ["alembic", "revision", "--autogenerate", "-m", "init admin models"],
                cwd=project_root,
                capture_output=True,
                text=True,
                env=env,
            )
            if result.returncode == 0:
                print("Initial migration created successfully.")
                print(result.stdout)
            else:
                print("Warning: Could not auto-generate migration:")
                print(result.stderr)
                print("\nRun manually: alembic revision --autogenerate -m 'init admin models'")
        except FileNotFoundError:
            print("Warning: 'alembic' command not found. Install with: pip install alembic")
            print("Then run: alembic revision --autogenerate -m 'init admin models'")

    # Baseline existing database if requested
    if args.baseline:
        print("\nCreating baseline migration for existing database...")
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
            # Generate empty baseline migration
            result = subprocess.run(
                ["alembic", "revision", "-m", "baseline_existing_schema"],
                cwd=project_root,
                capture_output=True,
                text=True,
                env=env,
            )
            if result.returncode == 0:
                print("Baseline migration created.")
                # Stamp as head (mark as applied without running SQL)
                result = subprocess.run(
                    ["alembic", "stamp", "head"],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    env=env,
                )
                if result.returncode == 0:
                    print("Baseline stamped as head.")
                else:
                    print("Warning: Could not stamp baseline:")
                    print(result.stderr)
            else:
                print("Warning: Could not create baseline migration:")
                print(result.stderr)
        except FileNotFoundError:
            print("Warning: 'alembic' command not found. Install with: pip install alembic")

    print("\nNext steps:")
    print("  1. Edit alembic.ini and set your sqlalchemy.url")
    print("  2. Add your app models to alembic/env.py (optional)")
    print("  3. Run: alembic revision --autogenerate -m 'your migration'")
    print("  4. Run: alembic upgrade head")


def _alembic_upgrade(args: argparse.Namespace) -> None:
    """Run alembic upgrade head."""
    import subprocess

    project_root = Path(args.app).resolve() if args.app else Path.cwd()

    alembic_dir = project_root / "alembic"
    ini_file = project_root / "alembic.ini"

    if not alembic_dir.exists() or not ini_file.exists():
        print("Error: Alembic not initialized in this project.")
        print("Run: fak init-alembic --app your_app")
        sys.exit(1)

    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
        cmd = ["alembic", "upgrade"]
        if args.revision:
            cmd.append(args.revision)
        else:
            cmd.append("head")
        result = subprocess.run(cmd, cwd=project_root, env=env)
        sys.exit(result.returncode)
    except FileNotFoundError:
        print("Error: 'alembic' command not found. Install with: pip install alembic")
        sys.exit(1)


def register_migrate_commands(subparsers) -> None:
    """Register database migration subcommands."""
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Add missing columns or drop obsolete columns from tables (dev mode)",
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

    # migrate --alembic subcommand
    alembic_migrate_parser = subparsers.add_parser(
        "migrate-alembic",
        help="Run alembic upgrade head (production mode)",
    )
    alembic_migrate_parser.add_argument(
        "revision",
        nargs="?",
        default="head",
        help="Target revision (default: head)",
    )
    alembic_migrate_parser.add_argument(
        "-a",
        "--app",
        default=None,
        help="App module path (e.g., 'myapp:app') to locate alembic.ini",
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

    # init-alembic subcommand
    init_alembic_parser = subparsers.add_parser(
        "init-alembic",
        help="Initialize Alembic configuration for migrations",
    )
    init_alembic_parser.add_argument(
        "-a",
        "--app",
        default=None,
        help="App module path (e.g., 'myapp:app') to locate project root",
    )
    init_alembic_parser.add_argument(
        "-d",
        "--database-url",
        default=None,
        help="Database URL to write to alembic.ini",
    )
    init_alembic_parser.add_argument(
        "--auto-migrate",
        action="store_true",
        help="Auto-generate initial migration for admin models",
    )
    init_alembic_parser.add_argument(
        "--baseline",
        action="store_true",
        help="Create baseline migration for existing database (stamp head)",
    )
    init_alembic_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing Alembic configuration",
    )


def handle_migrate_command(args: argparse.Namespace) -> None:
    """Dispatch migration commands."""
    if args.command == "migrate":
        asyncio.run(_migrate_tables(args))
    elif args.command == "migrate-permissions":
        asyncio.run(_migrate_permissions(args))
    elif args.command == "migrate-alembic":
        _alembic_upgrade(args)
    elif args.command == "init-alembic":
        _init_alembic(args)
