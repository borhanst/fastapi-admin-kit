"""AI chat configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass
class AIChatConfig:
    """Configuration for the AI chat interface."""

    max_file_size_mb: int = 10
    allowed_extensions: list[str] = field(default_factory=lambda: sorted(ALLOWED_EXTENSIONS))
