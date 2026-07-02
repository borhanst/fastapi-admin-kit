"""File storage backends."""

from fastapi_admin_kit.storage.base import StorageBackend
from fastapi_admin_kit.storage.local import LocalStorageBackend

__all__ = ["StorageBackend", "LocalStorageBackend"]
