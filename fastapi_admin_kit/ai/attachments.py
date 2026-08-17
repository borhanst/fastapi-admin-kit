"""File validation constants and MIME sniffing helpers for AI chat attachments."""

from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath

# ---------------------------------------------------------------------------
# Allowed file extensions and their expected MIME types
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS: set[str] = {
    ".pdf",
    ".xlsx",
    ".xls",
    ".docx",
    ".doc",
    ".csv",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
}

EXTENSION_TO_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".csv": "text/csv",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# ---------------------------------------------------------------------------
# Magic-byte signatures for MIME sniffing
# ---------------------------------------------------------------------------

_MAGIC_SIGNATURES: list[tuple[bytes, str]] = [
    (b"%PDF-", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),  # xlsx, docx, etc.
    (
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
        "application/vnd.ms-excel",
    ),  # old xls
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # webp starts with RIFF....WEBP
]


def _sniff_mime(data: bytes) -> str | None:
    """Best-effort MIME type detection from file magic bytes."""
    for signature, mime in _MAGIC_SIGNATURES:
        if data[: len(signature)] == signature:
            if mime == "application/zip":
                # Need more context to distinguish xlsx vs docx vs other zips
                # For our whitelist, we accept the generic zip and rely on
                # extension validation for the specific subtype.
                return "application/zip"
            if mime == "image/webp":
                if len(data) >= 12 and data[8:12] == b"WEBP":
                    return "image/webp"
                return None
            return mime
    return None


def detect_mime(filename: str | None, content: bytes) -> str:
    """Detect MIME type using extension + magic-byte sniffing.

    Falls back to ``mimetypes.guess_type`` when magic-byte detection is
    inconclusive.  Returns ``"application/octet-stream"`` if unknown.
    """
    # 1. Try magic-byte sniffing first (most reliable)
    sniffed = _sniff_mime(content)
    if sniffed:
        return sniffed

    # 2. Fall back to extension-based guess
    if filename:
        guessed, _ = mimetypes.guess_type(filename)
        if guessed:
            return guessed

    return "application/octet-stream"


def validate_extension(filename: str | None) -> str:
    """Validate and return the lowercase extension of ``filename``.

    Raises ``ValueError`` if the extension is not in the allowed set.
    """
    if not filename:
        raise ValueError("Filename is required.")

    ext = PurePosixPath(filename).suffix.lower()
    if not ext:
        raise ValueError(f"File '{filename}' has no extension.")

    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"File extension '{ext}' is not allowed. "
            f"Allowed extensions: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    return ext


def validate_mime(extension: str, mime_type: str) -> None:
    """Validate that the detected MIME type is compatible with the file extension.

    Raises ``ValueError`` if there is a mismatch.
    """
    expected = EXTENSION_TO_MIME.get(extension)
    if expected is None:
        return  # Unknown extension — skip MIME validation

    if mime_type == "application/zip":
        # ZIP could be xlsx, docx, etc. — accept if extension matches
        if extension in {".xlsx", ".docx"}:
            return
        raise ValueError(f"ZIP file with extension '{extension}' has unexpected MIME type.")

    if mime_type != expected:
        raise ValueError(
            f"File extension '{extension}' does not match detected MIME type "
            f"'{mime_type}' (expected '{expected}')."
        )
