"""Local filesystem storage backend — saves files to a local directory."""

from __future__ import annotations

import os
from pathlib import Path

from starlette.datastructures import UploadFile

from fastapi_admin_kit.storage.base import StorageBackend


class LocalStorageBackend(StorageBackend):
    """Saves uploaded files to a local directory and serves via StaticFiles.

    Parameters
    ----------
    upload_dir:
        Absolute or relative path where files are stored.
    base_url:
        The URL prefix that maps to ``upload_dir`` (e.g. ``"/uploads"``).
    max_size_mb:
        Maximum allowed file size in megabytes. ``None`` means no limit.
    """

    def __init__(
        self,
        upload_dir: str | Path = "uploads",
        base_url: str = "/uploads",
        max_size_mb: float | None = None,
    ) -> None:
        self.upload_dir = Path(upload_dir)
        self.base_url = base_url.rstrip("/")
        self.max_size_mb = max_size_mb

    async def save(self, file: UploadFile, directory: str = "") -> str:
        """Save an uploaded file. Returns the relative path within storage."""
        filename = self.sanitize_filename(file.filename or "unnamed")
        target_dir = self.upload_dir / directory
        target_dir.mkdir(parents=True, exist_ok=True)

        target_path = target_dir / filename
        content = await file.read()

        if self.max_size_mb is not None:
            max_bytes = int(self.max_size_mb * 1024 * 1024)
            if len(content) > max_bytes:
                raise ValueError(
                    f"File size ({len(content)} bytes) exceeds maximum "
                    f"allowed size ({self.max_size_mb} MB)."
                )

        with open(target_path, "wb") as f:
            f.write(content)

        # Return path relative to upload_dir, using forward slashes
        if directory:
            return f"{directory}/{filename}"
        return filename

    async def delete(self, path: str) -> None:
        """Delete a file at the given relative path."""
        target = self.upload_dir / path
        if target.is_file():
            os.remove(target)

    def url(self, path: str) -> str:
        """Return the public URL for a stored file."""
        return f"{self.base_url}/{path}"

    def ensure_dir(self) -> None:
        """Create the upload directory if it doesn't exist."""
        self.upload_dir.mkdir(parents=True, exist_ok=True)
