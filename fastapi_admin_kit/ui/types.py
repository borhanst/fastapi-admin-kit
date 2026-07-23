"""UI configuration types — tabs, sections, template sections."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TabConfig:
    """Configuration for changelist tabs."""

    title: str
    url: str = ""
    permission: str | None = None
    is_active: bool = False


@dataclass
class TableSection:
    """Expandable section showing a related table."""

    title: str
    related_model: Any = None
    related_field: str = ""
    list_display: list[str] = field(default_factory=list)


@dataclass
class TemplateSection:
    """Expandable section rendering a custom template."""

    title: str
    template: str = ""
    context_fn: Any = None
