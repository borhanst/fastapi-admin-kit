"""User management CLI commands."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import sys


def _resolve_database_url(url: str | None = None) -> str:
    """Resolve database URL from argument, env var, or default."""
    if url:
        return _ensure_async_url(url)
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return _ensure_async_url(env_url)
    print("Error: --database-url not specified and DATABASE_URL env var not set.")
    sys.exit(1)


def _ensure_async_url(url: str) -> str:
    """Ensure SQLite URLs use the async driver."""
    if url.startswith("sqlite:///") and not url.startswith("sqlite+aiosqlite"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return url


def _hash_password(model: type, password: str) -> str:
    """Hash a password using the model's hash_password or the default hasher."""
    hasher = getattr(model, "hash_password", None)
    if hasher is None:
        from fastapi_admin_kit.auth.password import password_manager

        return password_manager.hash(password)
    try:
        result = hasher(password)
        if result is None:
            from fastapi_admin_kit.auth.password import password_manager

            return password_manager.hash(password)
        return result
    except TypeError:
        from fastapi_admin_kit.auth.password import password_manager

        return password_manager.hash(password)


def _import_auth_model(import_path: str) -> type:
    """Import an auth model class from a dotted module path."""
    module_path, _, class_name = import_path.rpartition(".")
    if not module_path or not class_name:
        print("Error: --auth-model must be a dotted path like 'myapp.models.MyUser'.")
        sys.exit(1)
    try:
        cwd = os.getcwd()
        if cwd not in sys.path:
            sys.path.insert(0, cwd)
        module = importlib.import_module(module_path)
        model = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        print(f"Error: Could not import auth_model '{import_path}': {exc}")
        sys.exit(1)
    return model


async def _create_superuser(args: argparse.Namespace) -> None:
    """Create a superuser."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    from fastapi_admin_kit.models.base import Base

    database_url = _resolve_database_url(args.database_url)
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"timeout": 30}
    engine = create_async_engine(database_url, poolclass=NullPool, connect_args=connect_args)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        with session.no_autoflush:
            from sqlalchemy import select

            from fastapi_admin_kit.backends import SqlAlchemyIntrospectionAdapter

            UserModel = _import_auth_model(args.auth_model) if args.auth_model else None  # noqa: N806
            if UserModel is None:
                from fastapi_admin_kit.auth.models import User as UserModel

            result = await session.execute(select(UserModel).where(UserModel.email == args.email))
            existing = result.scalar_one_or_none()
            if existing:
                print(f"Error: User with email '{args.email}' already exists.")
                await engine.dispose()
                sys.exit(1)

            hashed_password = _hash_password(UserModel, args.password)
            introspection = SqlAlchemyIntrospectionAdapter()
            columns, _ = introspection.inspect_model(UserModel)
            column_keys = {c.name for c in columns}

            user_kwargs = {
                "email": args.email,
                "is_superuser": True,
                "is_active": True,
            }
            if "hashed_password" in column_keys:
                user_kwargs["hashed_password"] = hashed_password
            if "password" in column_keys:
                user_kwargs["password"] = hashed_password

            user = UserModel(**user_kwargs)
            session.add(user)
            await session.commit()
            await session.refresh(user)

            if not user.hashed_password:
                print(f"Error: hashed_password was not saved for '{user.email}'.")
                print("  Check that your custom model's hashed_password column is not nullable")
                print("  and that no SQLAlchemy events or custom __init__ are overriding it.")
                await engine.dispose()
                sys.exit(1)

        print("Superuser created successfully!")
        print(f"  Email: {user.email}")
        # print(f"  Name:  {user.full_name or '(none)'}")
        print(f"  ID:    {user.id}")

    await engine.dispose()


async def _list_users(args: argparse.Namespace) -> None:
    """List all admin users."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    from fastapi_admin_kit.models.base import Base

    database_url = _resolve_database_url(args.database_url)
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"timeout": 30}
    engine = create_async_engine(database_url, poolclass=NullPool, connect_args=connect_args)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        from sqlalchemy import select

        UserModel = _import_auth_model(args.auth_model) if args.auth_model else None  # noqa: N806
        if UserModel is None:
            from fastapi_admin_kit.auth.models import User as UserModel

        result = await session.execute(select(UserModel))
        users = result.scalars().all()

        if not users:
            print("No admin users found.")
            await engine.dispose()
            return

        print(f"{'ID':<6} {'Email':<30} {'Name':<20} {'Superuser':<10} {'Active':<8}")
        print("-" * 74)
        for user in users:
            print(
                f"{user.id:<6} {user.email:<30} "
                f"{'Yes' if user.is_superuser else 'No':<10} "
                f"{'Yes' if user.is_active else 'No':<8}"
            )

    await engine.dispose()


async def _change_password(args: argparse.Namespace) -> None:
    """Change password for an existing user."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    from fastapi_admin_kit.models.base import Base

    database_url = _resolve_database_url(args.database_url)
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"timeout": 30}
    engine = create_async_engine(database_url, poolclass=NullPool, connect_args=connect_args)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        with session.no_autoflush:
            from sqlalchemy import select

            UserModel = _import_auth_model(args.auth_model) if args.auth_model else None  # noqa: N806
            if UserModel is None:
                from fastapi_admin_kit.auth.models import User as UserModel

            result = await session.execute(select(UserModel).where(UserModel.email == args.email))
            user = result.scalar_one_or_none()

            if not user:
                print(f"Error: User with email '{args.email}' not found.")
                await engine.dispose()
                sys.exit(1)

            user.hashed_password = _hash_password(UserModel, args.password)
            await session.commit()

            print(f"Password changed successfully for '{user.email}'!")

    await engine.dispose()


def register_user_commands(subparsers) -> None:
    """Register user management subcommands."""
    # createsuperuser
    create_parser = subparsers.add_parser("createsuperuser", help="Create a new superuser")
    create_parser.add_argument(
        "-e", "--email", required=True, help="Email address for the superuser"
    )
    create_parser.add_argument("-p", "--password", required=True, help="Password for the superuser")
    create_parser.add_argument("-n", "--name", default="", help="Full name for the superuser")
    create_parser.add_argument(
        "-d",
        "--database-url",
        default=None,
        help="Database URL (or set DATABASE_URL env var)",
    )
    create_parser.add_argument(
        "-a",
        "--auth-model",
        default=None,
        help="Dotted path to custom auth model (e.g. 'myapp.models.MyUser')",
    )

    # users
    list_parser = subparsers.add_parser("users", help="List all admin users")
    list_parser.add_argument(
        "-d",
        "--database-url",
        default=None,
        help="Database URL (or set DATABASE_URL env var)",
    )
    list_parser.add_argument(
        "-a",
        "--auth-model",
        default=None,
        help="Dotted path to custom auth model (e.g. 'myapp.models.MyUser')",
    )

    # changepassword
    pw_parser = subparsers.add_parser("changepassword", help="Change password for an existing user")
    pw_parser.add_argument("-e", "--email", required=True, help="Email of the user")
    pw_parser.add_argument("-p", "--password", required=True, help="New password")
    pw_parser.add_argument(
        "-d",
        "--database-url",
        default=None,
        help="Database URL (or set DATABASE_URL env var)",
    )
    pw_parser.add_argument(
        "-a",
        "--auth-model",
        default=None,
        help="Dotted path to custom auth model (e.g. 'myapp.models.MyUser')",
    )


def handle_user_command(args: argparse.Namespace) -> None:
    """Dispatch user management commands."""
    if args.command == "createsuperuser":
        asyncio.run(_create_superuser(args))
    elif args.command == "users":
        asyncio.run(_list_users(args))
    elif args.command == "changepassword":
        asyncio.run(_change_password(args))
