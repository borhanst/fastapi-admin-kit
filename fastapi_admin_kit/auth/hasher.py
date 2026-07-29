"""Password hasher — pluggable protocol + default bcrypt implementation.

For new code, prefer ``fastapi_admin_kit.auth.password.password_manager``.
This module is kept for backward compatibility and custom hasher support.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class PasswordHasher(ABC):
    """Abstract base class for password hashing.

    Implement hash() and verify() to create a custom hasher.
    """

    @staticmethod
    @abstractmethod
    def hash(password: str) -> str:
        """Hash a plaintext password. Returns the hashed string."""
        ...

    @staticmethod
    @abstractmethod
    def verify(password: str, hashed: str) -> bool:
        """Verify a plaintext password against a hash. Returns True if match."""
        ...


class BcryptHasher(PasswordHasher):
    """Default hasher using bcrypt — delegates to PasswordManager."""

    @staticmethod
    def hash(password: str) -> str:
        from fastapi_admin_kit.auth.password import password_manager

        return password_manager.hash(password)

    @staticmethod
    def verify(password: str, hashed: str) -> bool:
        from fastapi_admin_kit.auth.password import password_manager

        return password_manager.verify(password, hashed)
