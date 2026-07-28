"""Password hashing and validation — single source of truth for password operations."""

from __future__ import annotations

import re

import bcrypt


class PasswordManager:
    """Unified password operations backed by bcrypt.

    Usage::

        from fastapi_admin_kit.auth.password import password_manager

        hashed = password_manager.hash("secret")
        ok = password_manager.verify("secret", hashed)
        stale = password_manager.needs_rehash(hashed)
    """

    _default_rounds: int = 12

    @classmethod
    def hash(cls, password: str) -> str:
        """Hash a plaintext password. Returns the hashed string."""
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=cls._default_rounds)).decode()

    @staticmethod
    def verify(password: str, hashed: str) -> bool:
        """Verify a plaintext password against a hash. Returns True if match."""
        try:
            return bcrypt.checkpw(password.encode(), hashed.encode())
        except (ValueError, TypeError):
            return False

    @classmethod
    def needs_rehash(cls, hashed: str) -> bool:
        """Check if a hash should be re-hashed (e.g. rounds too low).

        Returns True if the stored hash was created with fewer rounds
        than the current default, or if the hash cannot be parsed.
        """
        try:
            # bcrypt hashes encode rounds as: $2b$<rounds>$...
            parts = hashed.split("$")
            if len(parts) < 3:
                return True
            actual_rounds = int(parts[3]) if parts[3].isdigit() else 0
            return actual_rounds < cls._default_rounds
        except (IndexError, ValueError):
            return True


password_manager = PasswordManager()


def validate_password_strength(
    password: str,
    min_length: int = 12,
    require_uppercase: bool = True,
    require_lowercase: bool = True,
    require_digit: bool = True,
    require_special: bool = True,
) -> list[str]:
    """Validate password strength. Returns a list of error messages (empty = valid)."""
    errors: list[str] = []

    if len(password) < min_length:
        errors.append(f"Password must be at least {min_length} characters long.")
    if require_uppercase and not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter.")
    if require_lowercase and not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter.")
    if require_digit and not re.search(r"\d", password):
        errors.append("Password must contain at least one digit.")
    if require_special and not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        errors.append("Password must contain at least one special character.")

    return errors
