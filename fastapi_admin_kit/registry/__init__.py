"""Registry package — AdminRegistry and related components."""

from fastapi_admin_kit.registry.core import (
    AdminRegistry,
    RegisteredModel,
    build_registered_model,
)

__all__ = ["AdminRegistry", "RegisteredModel", "build_registered_model"]
