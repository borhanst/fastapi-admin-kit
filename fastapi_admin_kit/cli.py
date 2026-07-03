"""CLI commands for FastAPI Admin Kit."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys


def _resolve_database_url(url: str | None = None) -> str:
    """Resolve database URL from argument, env var, or default."""
    if url:
        return url
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    print(
        "Error: --database-url not specified and DATABASE_URL env var not set."
    )
    sys.exit(1)


async def _create_superuser(args: argparse.Namespace) -> None:
    """Create a superuser."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from fastapi_admin_kit.auth.backend import pwd_context
    from fastapi_admin_kit.auth.models import AdminUser
    from fastapi_admin_kit.models.base import Base

    database_url = _resolve_database_url(args.database_url)
    engine = create_async_engine(database_url)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(AdminUser).where(AdminUser.email == args.email)
        )
        existing = result.scalar_one_or_none()
        if existing:
            print(f"Error: User with email '{args.email}' already exists.")
            await engine.dispose()
            sys.exit(1)

        hashed_password = pwd_context.hash(args.password)
        user = AdminUser(
            email=args.email,
            hashed_password=hashed_password,
            full_name=args.name or "",
            is_superuser=True,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        print("Superuser created successfully!")
        print(f"  Email: {user.email}")
        print(f"  Name:  {user.full_name or '(none)'}")
        print(f"  ID:    {user.id}")

    await engine.dispose()


async def _list_users(args: argparse.Namespace) -> None:
    """List all admin users."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from fastapi_admin_kit.auth.models import AdminUser
    from fastapi_admin_kit.models.base import Base
    database_url = _resolve_database_url(args.database_url)
    engine = create_async_engine(database_url)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        from sqlalchemy import select

        result = await session.execute(select(AdminUser))
        users = result.scalars().all()

        if not users:
            print("No admin users found.")
            await engine.dispose()
            return

        print(
            f"{'ID':<6} {'Email':<30} {'Name':<20} {'Superuser':<10} {'Active':<8}"
        )
        print("-" * 74)
        for user in users:
            print(
                f"{user.id:<6} {user.email:<30} {(user.full_name or ''):<20} "
                f"{'Yes' if user.is_superuser else 'No':<10} "
                f"{'Yes' if user.is_active else 'No':<8}"
            )

    await engine.dispose()


async def _change_password(args: argparse.Namespace) -> None:
    """Change password for an existing user."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from fastapi_admin_kit.auth.backend import pwd_context
    from fastapi_admin_kit.auth.models import AdminUser
    from fastapi_admin_kit.models.base import Base

    database_url = _resolve_database_url(args.database_url)
    engine = create_async_engine(database_url)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(AdminUser).where(AdminUser.email == args.email)
        )
        user = result.scalar_one_or_none()

        if not user:
            print(f"Error: User with email '{args.email}' not found.")
            await engine.dispose()
            sys.exit(1)

        user.hashed_password = pwd_context.hash(args.password)
        await session.commit()

        print(f"Password changed successfully for '{user.email}'!")

    await engine.dispose()


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(

        prog="fconsole",

        description="FastAPI Admin Kit CLI — manage admin users and database.",
    )
    subparsers = parser.add_subparsers(
        dest="command", help="Available commands"
    )

    # create-superuser
    create_parser = subparsers.add_parser(
        "createsuperuser", help="Create a new superuser"
    )
    create_parser.add_argument(
        "-e", "--email", required=True, help="Email address for the superuser"
    )
    create_parser.add_argument(
        "-p", "--password", required=True, help="Password for the superuser"
    )
    create_parser.add_argument(
        "-n", "--name", default="", help="Full name for the superuser"
    )
    create_parser.add_argument(
        "-d",
        "--database-url",
        default=None,
        help="Database URL (or set DATABASE_URL env var)",
    )

    # list-users
    list_parser = subparsers.add_parser(
        "users", help="List all admin users"
    )
    list_parser.add_argument(
        "-d",
        "--database-url",
        default=None,
        help="Database URL (or set DATABASE_URL env var)",
    )

    # changepassword
    pw_parser = subparsers.add_parser(
        "changepassword", help="Change password for an existing user"
    )
    pw_parser.add_argument(
        "-e", "--email", required=True, help="Email of the user"
    )
    pw_parser.add_argument(
        "-p", "--password", required=True, help="New password"
    )
    pw_parser.add_argument(
        "-d",
        "--database-url",
        default=None,
        help="Database URL (or set DATABASE_URL env var)",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "createsuperuser":
        asyncio.run(_create_superuser(args))
    elif args.command == "users":
        asyncio.run(_list_users(args))
    elif args.command == "changepassword":
        asyncio.run(_change_password(args))


if __name__ == "__main__":
    main()
