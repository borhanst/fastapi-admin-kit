"""Pagination strategies for FastAPI Console."""

from fastapi_admin_kit.pagination.base import BasePagination, PaginationResult
from fastapi_admin_kit.pagination.cursor import CursorPagination
from fastapi_admin_kit.pagination.dynamic import DynamicPagination
from fastapi_admin_kit.pagination.offset import OffsetPagination

__all__ = [
    "BasePagination",
    "PaginationResult",
    "OffsetPagination",
    "CursorPagination",
    "DynamicPagination",
]
