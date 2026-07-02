"""Storage configuration."""

from typing import Any

from fastapi_admin_kit.exceptions import ConfigError


class StorageConfig:
    """Storage configuration."""

    def __init__(
        self,
        storage: Any | None = None,
        uploads_url: str = "/uploads",
    ):
        self.storage = storage
        self.uploads_url = uploads_url

    def validate_storage_config(self) -> None:
        """Validate storage configuration."""
        if self.uploads_url and not self.uploads_url.startswith("/"):
            raise ConfigError("uploads_url must start with '/' or be empty")
