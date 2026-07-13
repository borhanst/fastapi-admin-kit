"""Protocol for user models that can be used as the admin auth model."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AdminUserProtocol(Protocol):
    """
    Any user model passed as auth_model= must satisfy this interface.
    These are the only attributes the admin framework reads from the user object.
    """

    id: int | str  # primary key (any type)
    email: str  # used for audit log denormalization
    is_active: bool  # inactive users are refused login
    is_superuser: bool  # bypasses all permission checks if True

    # Many-to-many roles — the admin reads this to look up permissions.
    # Must be an iterable of role objects, each with an `id` attribute.
    roles: list  # list of Role objects (or compatible)
