"""CLI commands for FastAPI Admin Kit."""

from __future__ import annotations

import argparse
import sys

from fastapi_admin_kit.cli.migrate import (
    handle_migrate_command,
    register_migrate_commands,
)
from fastapi_admin_kit.cli.permissions import (
    handle_permission_command,
    register_permission_commands,
)
from fastapi_admin_kit.cli.scaffold import scaffold_project
from fastapi_admin_kit.cli.user import (
    handle_user_command,
    register_user_commands,
)


def _init_project(args: argparse.Namespace) -> None:
    """Create a new FastAPI project with uv."""
    scaffold_project(
        project_name=args.name,
        layout=args.layout,
        directory=args.directory,
        skip_venv=args.no_venv,
        skip_git=args.no_git,
    )


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="FastAPI Admin Kit CLI — manage admin users and scaffold projects.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Register command groups
    register_user_commands(subparsers)
    register_permission_commands(subparsers)
    register_migrate_commands(subparsers)

    # init — scaffold a new FastAPI project
    init_parser = subparsers.add_parser("init", help="Create a new FastAPI project with uv")
    init_parser.add_argument("name", nargs="?", default=None, help="Project name")
    init_parser.add_argument(
        "-l",
        "--layout",
        choices=["flat", "app", "src"],
        default=None,
        help="Project layout (flat, app, src). Interactive if omitted.",
    )
    init_parser.add_argument(
        "-d",
        "--directory",
        default=None,
        help="Target directory (defaults to project name)",
    )
    init_parser.add_argument("--no-venv", action="store_true", help="Skip uv venv creation")
    init_parser.add_argument("--no-git", action="store_true", help="Skip git init")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # Dispatch
    if args.command in ("createsuperuser", "users", "changepassword"):
        handle_user_command(args)
    elif args.command == "createpermissions":
        handle_permission_command(args)
    elif args.command in ("migrate", "migrate-permissions"):
        handle_migrate_command(args)
    elif args.command == "init":
        _init_project(args)


if __name__ == "__main__":
    main()
