"""Dashboard component classes for Unfold-style dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CardComponent:
    """Stat card component."""

    type: str = "card"
    title: str = ""
    value: Any = ""
    description: str = ""
    url: str = ""


@dataclass
class ChartComponent:
    """Chart component (placeholder for JS chart library integration)."""

    type: str = "chart"
    title: str = ""
    chart_type: str = "line"  # line, bar, pie, doughnut
    data: dict = field(default_factory=dict)
    height: int = 300


@dataclass
class TableComponent:
    """Table component for dashboard."""

    type: str = "table"
    title: str = ""
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class ProgressComponent:
    """Progress bar component."""

    type: str = "progress"
    title: str = ""
    value: int = 0  # 0-100
    description: str = ""


@dataclass
class LinkComponent:
    """Link/button component."""

    type: str = "button"
    title: str = ""
    description: str = ""
    url: str = "#"
    icon: str | None = None


@dataclass
class ButtonComponent:
    """Alias for LinkComponent."""

    type: str = "button"
    title: str = ""
    description: str = ""
    url: str = "#"
    icon: str | None = None
