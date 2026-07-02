"""Shared SQLAlchemy DeclarativeBase for all admin tables."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all fastapi_admin_kit SQLAlchemy models."""
