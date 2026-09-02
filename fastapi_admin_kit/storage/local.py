"""Local filesystem storage backend — saves files to a local directory."""

from __future__ import annotations

import os
import re
from pathlib import Path

from starlette.datastructures import UploadFile

from fastapi_admin_kit.storage.base import DEFAULT_MAX_SIZE_MB, StorageBackend

_DIRECTORY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class LocalStorageBackend(StorageBackend):
    """Saves uploaded files to a local directory and serves via StaticFiles.

    Parameters
    ----------
    upload_dir:
        Absolute or relative path where files are stored.
    base_url:
        The URL prefix that maps to ``upload_dir`` (e.g. ``"/uploads"``).
    max_size_mb:
        Maximum allowed file size in megabytes. ``None`` means the
        :data:`~fastapi_admin_kit.storage.base.DEFAULT_MAX_SIZE_MB` limit
        (10 MB) applies.
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

    def _resolve_within_jail(self, relative: str | Path) -> Path:
        """Resolve *relative* against the upload dir, refusing escapes.

        Raises ``ValueError`` when the resolved path lands outside the
        upload directory (path traversal such as ``../../.env``, sibling
        escapes, or absolute paths). Windows-style separators are rejected
        outright: stored paths always use forward slashes.
        """
        text = str(relative)
        if "\x00" in text or "\\" in text:
            raise ValueError("Invalid storage path.")
        base = self.upload_dir.resolve()
        candidate = (base / relative).resolve()
        if not candidate.is_relative_to(base):
            raise ValueError("Path escapes the upload directory.")
        return candidate

    def _effective_max_bytes(self) -> float:
        max_mb = self.max_size_mb if self.max_size_mb is not None else DEFAULT_MAX_SIZE_MB
        return int(max_mb * 1024 * 1024)

    async def save(self, file: UploadFile, directory: str = "") -> str:
        """Save an uploaded file. Returns the relative path within storage."""
        if directory and not _DIRECTORY_RE.match(directory):
            raise ValueError("Invalid storage directory name.")

        filename = self.sanitize_filename(file.filename or "unnamed")

        if directory:
            target_dir = self._resolve_within_jail(directory)
        else:
            target_dir = self.upload_dir.resolve()
        target_dir.mkdir(parents=True, exist_ok=True)

        target_path = target_dir / filename
        # Belt-and-braces: even a sanitized filename must stay jailed.
        self._resolve_within_jail(target_path.relative_to(self.upload_dir.resolve()))

        max_bytes = self._effective_max_bytes()
        max_mb = self.max_size_mb if self.max_size_mb is not None else DEFAULT_MAX_SIZE_MB
        # Check the declared size BEFORE reading the body into RAM (DoS guard);
        # fall back to a post-read check for streams that don't report size.
        size = getattr(file, "size", None)
        if size is not None and size > max_bytes:
            raise ValueError(
                f"File size ({size} bytes) exceeds maximum allowed size ({max_mb} MB)."
            )
        content = await file.read()
        if len(content) > max_bytes:
            raise ValueError(
                f"File size ({len(content)} bytes) exceeds maximum allowed size ({max_mb} MB)."
            )

        with open(target_path, "wb") as f:
            f.write(content)

        # Return path with leading / for database storage
        # e.g., "/uploads/filename.jpg" or "/uploads/directory/filename.jpg"
        # The leading / ensures the path is stored with a slash prefix
        if directory:
            return f"/{self.upload_dir}/{directory}/{filename}"
        return f"/{self.upload_dir}/{filename}"

    async def delete(self, path: str) -> None:
        """Delete a file at the given relative path.

        Raises ``ValueError`` when *path* escapes the upload directory.
        """
        target = self._resolve_within_jail(path)
        if target.is_file():
            os.remove(target)

    def url(self, path: str, strip_prefix: bool = False) -> str:
        """Return the public URL for a stored file.

        Parameters
        ----------
        path : str
            The relative path stored in the database.
        strip_prefix : bool, default False
            When True, strips the leading ``/`` from the URL.
            Use ``strip_prefix=True`` when you want the path without
            leading slash for ``src`` attributes in templates.
        """
        # Strip upload_dir prefix if present, to avoid double-prefix in URL
        upload_dir_str = str(self.upload_dir)
        if path.startswith(upload_dir_str + "/"):
            path = path[len(upload_dir_str) + 1 :]
        elif path.startswith(upload_dir_str):
            path = path[len(upload_dir_str) :]

        url = f"{self.base_url}/{path}"

        # Optionally strip leading / from URL
        if strip_prefix:
            url = url.lstrip("/")

        return url

    def ensure_dir(self) -> None:
        """Create the upload directory if it doesn't exist."""
        self.upload_dir.mkdir(parents=True, exist_ok=True)
