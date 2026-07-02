"""Navigation configuration."""

from typing import Any

from fastapi_admin_kit.exceptions import ConfigError


class NavConfig:
    """Navigation configuration."""

    def __init__(
        self,
        nav_groups: list[Any] | None = None,
        sidebar_builder: Any | None = None,
        require_tags: bool = False,
        site_dropdown: list[dict[str, str]] | None = None,
        dashboard_permission: str | None = None,
        settings_permission: str | None = None,
    ):
        self.nav_groups = nav_groups or []
        self.sidebar_builder = sidebar_builder
        self.require_tags = require_tags
        self.site_dropdown = site_dropdown or []
        self.dashboard_permission = dashboard_permission
        self.settings_permission = settings_permission

    def validate_nav_config(self) -> None:
        """Validate navigation configuration."""
        if self.require_tags and not self.nav_groups:
            raise ConfigError(
                "require_tags=True requires nav_groups to be configured"
            )
