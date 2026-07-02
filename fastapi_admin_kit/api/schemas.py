"""Pydantic schemas for the Admin JSON API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TokenRequest(BaseModel):
    """Request body for token authentication."""

    email: str
    password: str


class TokenResponse(BaseModel):
    """Response containing access and refresh tokens."""

    access_token: str
    refresh_token: str = ""
    token_type: str = "bearer"
    expires_in: int = 0


class RefreshRequest(BaseModel):
    """Request body for token refresh."""

    refresh_token: str


class RefreshResponse(BaseModel):
    """Response containing refreshed access and refresh tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 0


class PaginationParams(BaseModel):
    """Pagination query parameters."""

    page: int = 1
    per_page: int = 25
    q: str = ""
    order: str = ""
    after: str | None = None
    before: str | None = None


class PaginatedResponse(BaseModel):
    """Paginated list response."""

    items: list[Any]
    total: int
    page: int | None = None
    per_page: int
    total_pages: int | None = None
    next_cursor: str | None = None
    has_next: bool = False


class ErrorResponse(BaseModel):
    """Error response."""

    detail: str


class TwoFARequiredResponse(BaseModel):
    """Response when 2FA is required."""

    requires_2fa: bool = True
    temp_token: str


class TwoFAVerifyRequest(BaseModel):
    """Request body for 2FA verification."""

    temp_token: str
    code: str
