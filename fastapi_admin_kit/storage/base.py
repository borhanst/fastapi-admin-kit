"""Storage backend ABC — defines the interface for file storage implementations."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from pathlib import PurePosixPath

from starlette.datastructures import UploadFile


class StorageBackend(ABC):
    """Abstract base class for file storage backends.

    Implementations must define ``save``, ``delete``, and ``url``.
    ``sanitize_filename`` is shared across all backends.
    """

    @abstractmethod
    async def save(self, file: UploadFile, directory: str = "") -> str:
        """Save an uploaded file and return its relative path within storage."""

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Delete a file at the given relative path."""

    @abstractmethod
    def url(self, path: str) -> str:
        """Return the public URL for a stored file (relative path)."""

    def sanitize_filename(self, filename: str) -> str:
        """Sanitize an uploaded filename.

        Prepends a UUID prefix to prevent collisions and strips path
        separators to avoid directory traversal.
        """
        # Strip any directory components
        name = PurePosixPath(filename).name
        if not name:
            name = "unnamed"

        # Remove null bytes and path separators
        name = name.replace("\x00", "")
        name = name.replace("/", "_").replace("\\", "_")

        # Prepend UUID for uniqueness
        prefix = uuid.uuid4().hex[:12]
        return f"{prefix}_{name}"
