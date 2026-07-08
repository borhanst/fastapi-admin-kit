"""Database configuration — connection settings and async engine factory."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any


class DatabaseType(StrEnum):
    """Supported database types for async connections."""

    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"


_ASYNC_DRIVERS: dict[DatabaseType, str] = {
    DatabaseType.SQLITE: "aiosqlite",
    DatabaseType.POSTGRESQL: "asyncpg",
    DatabaseType.MYSQL: "aiomysql",
}

_DIALECT_MAP: dict[str, DatabaseType] = {
    "sqlite": DatabaseType.SQLITE,
    "postgresql": DatabaseType.POSTGRESQL,
    "mysql": DatabaseType.MYSQL,
}

# Known sync drivers that should be replaced per dialect
_SYNC_DRIVERS: dict[str, str] = {
    "psycopg2": "asyncpg",
    "psycopg": "asyncpg",
    "pg8000": "asyncpg",
    "pymysql": "aiomysql",
    "mysqldb": "aiomysql",
}


def _ensure_async_url(url: str, db_type: DatabaseType | None = None) -> str:
    """Normalise a database URL to use an async driver.

    - If the URL already has the correct async driver, return as-is.
    - If it has a known sync driver, replace it with the async equivalent.
    - If it has no driver, inject the async driver for the detected dialect.
    - If the dialect is unknown or unparseable, return the URL unchanged.
    """
    match = re.match(r"^(\w+)(?:\+(\w+))?(://.*)$", url)
    if not match:
        return url

    dialect, driver, rest = match.groups()

    detected = db_type or _DIALECT_MAP.get(dialect)
    if detected is None:
        return url

    expected_driver = _ASYNC_DRIVERS[detected]

    if driver is None:
        return f"{dialect}+{expected_driver}{rest}"

    if driver == expected_driver:
        return url

    sync_replacement = _SYNC_DRIVERS.get(driver)
    if sync_replacement:
        return f"{dialect}+{sync_replacement}{rest}"

    return url


class DatabaseConfig:
    """Database connection configuration.

    Two usage modes (``url`` takes precedence):

    1. **Full URL** — pass ``url="sqlite+aiosqlite:///./db.sqlite3"``.
       The URL is automatically inspected and its driver is upgraded to an
       async driver if necessary (e.g. ``sqlite:///…`` → ``sqlite+aiosqlite:///…``).

    2. **Structured fields** — set ``db_type``, ``host``, ``port``,
       ``database``, ``username``, ``password`` individually.

    Always creates a **SQLAlchemy async engine** via :meth:`create_engine`.
    """

    def __init__(
        self,
        db_type: DatabaseType = DatabaseType.SQLITE,
        url: str | None = None,
        host: str = "",
        port: int | None = None,
        database: str = "",
        username: str = "",
        password: str = "",
        echo: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_pre_ping: bool = True,
        connect_args: dict[str, Any] | None = None,
    ) -> None:
        self.db_type = db_type
        self.url = url
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.echo = echo
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_pre_ping = pool_pre_ping
        self.connect_args = connect_args or {}

    def build_url(self) -> str:
        """Build or normalise the async connection URL from this config."""
        if self.url is not None:
            return _ensure_async_url(self.url, self.db_type)

        driver = _ASYNC_DRIVERS[self.db_type]

        if self.db_type == DatabaseType.SQLITE:
            return f"sqlite+{driver}:///{self.database}"

        port_part = f":{self.port}" if self.port else ""
        return (
            f"{self.db_type.value}+{driver}://"
            f"{self.username}:{self.password}@"
            f"{self.host}{port_part}/{self.database}"
        )

    def create_engine(self) -> Any:
        """Create a SQLAlchemy **async** engine from this config."""
        from sqlalchemy.ext.asyncio import create_async_engine

        url = self.build_url()
        kwargs: dict[str, Any] = {
            "echo": self.echo,
            "pool_pre_ping": self.pool_pre_ping,
        }

        if self.db_type != DatabaseType.SQLITE:
            kwargs["pool_size"] = self.pool_size
            kwargs["max_overflow"] = self.max_overflow

        if self.connect_args:
            kwargs["connect_args"] = self.connect_args

        return create_async_engine(url, **kwargs)
