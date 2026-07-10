"""Password strength validation."""

from __future__ import annotations

import re


def validate_password_strength(
    password: str,
    *,
    min_length: int = 12,
    require_uppercase: bool = True,
    require_lowercase: bool = True,
    require_digit: bool = True,
    require_special: bool = True,
) -> list[str]:
    """
    Validate password strength. Returns a list of error messages (empty = valid)
    """
    errors: list[str] = []

    if len(password) < min_length:
        errors.append(
            f"Password must be at least {min_length} characters long."
        )

    if require_uppercase and not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter.")

    if require_lowercase and not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter.")

    if require_digit and not re.search(r"\d", password):
        errors.append("Password must contain at least one digit.")

    if require_special and not re.search(
        r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", password
    ):
        errors.append("Password must contain at least one special character.")

    return errors
