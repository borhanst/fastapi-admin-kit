"""Password hasher — pluggable protocol + default bcrypt implementation."""

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
    """Default hasher using bcrypt."""

    @staticmethod
    def hash(password: str) -> str:
        import bcrypt

        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def verify(password: str, hashed: str) -> bool:
        import bcrypt

        try:
            return bcrypt.checkpw(password.encode(), hashed.encode())
        except (ValueError, TypeError):
            return False
