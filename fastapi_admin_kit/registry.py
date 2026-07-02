"""AdminRegistry — singleton holding all registered models.

This module provides backward-compatible imports for the registry package.
The actual implementation is in fastapi_admin_kit.registry.core.
"""

from __future__ import annotations

from fastapi_admin_kit.registry.core import (
    AdminRegistry,
    RegisteredModel,
    _all_declarative_subclasses,
)

__all__ = ["AdminRegistry", "RegisteredModel", "_all_declarative_subclasses"]
