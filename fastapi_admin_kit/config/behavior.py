"""Behavior configuration."""

from __future__ import annotations

from typing import Any


class BehaviorConfig:
    """Behavior configuration."""

    def __init__(
        self,
        auto_discover: bool = True,
        dashboard_stats: list[str] | None = None,
        dashboard_charts: bool = True,
        dashboard_callback: str | None = None,
        dashboard_components: list[Any] | None = None,
    ):
        self.auto_discover = auto_discover
        self.dashboard_stats = dashboard_stats or []
        self.dashboard_charts = dashboard_charts
        self.dashboard_callback = dashboard_callback
        self.dashboard_components = dashboard_components or []

    def validate_behavior_config(self) -> None:
        """Validate behavior configuration."""
        pass
