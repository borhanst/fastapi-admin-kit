"""Admin configuration orchestration."""

from typing import TYPE_CHECKING

from fastapi_admin_kit.config import (
    AuditConfig,
    AuthConfig,
    BehaviorConfig,
    NavConfig,
    StorageConfig,
    UIConfig,
)

if TYPE_CHECKING:
    pass


class AdminConfig:
    """Orchestrates all configuration classes with validation."""

    def __init__(
        self,
        ui: UIConfig | None = None,
        auth: AuthConfig | None = None,
        audit: AuditConfig | None = None,
        behavior: BehaviorConfig | None = None,
        storage: StorageConfig | None = None,
        nav: NavConfig | None = None,
    ):
        self.ui = ui or UIConfig()
        self.auth = auth or AuthConfig()
        self.audit = audit or AuditConfig()
        self.behavior = behavior or BehaviorConfig()
        self.storage = storage or StorageConfig()
        self.nav = nav or NavConfig()

    def validate_all(self) -> None:
        """Validate all configuration components."""
        self.auth.validate_auth_model()
        self.audit.validate_audit_config()
        self.storage.validate_storage_config()
        self.nav.validate_nav_config()

    def get_ui_context(self) -> dict:
        """Get UI configuration for template context."""
        return self.ui.apply_to_template_context()

    def get_branding_config(self) -> dict:
        """Get branding configuration."""
        return {
            "title": self.ui.title,
            "logo_url": self.ui.logo_url,
            "favicon_url": self.ui.favicon_url,
            "primary_color": self.ui.primary_color,
            "primary_color_dark": self.ui.primary_color_dark,
            "dark_mode_default": self.ui.dark_mode_default,
        }

    def get_session_config(self) -> dict:
        """Get session configuration."""
        return {
            "session_ttl": self.auth.session_ttl,
            "session_cookie_name": self.auth.session_cookie_name,
            "session_secure": self.auth.session_secure,
        }

    def get_audit_config(self) -> dict:
        """Get audit configuration."""
        return {
            "audit_retention_days": self.audit.audit_retention_days,
        }

    def get_storage_config(self) -> dict:
        """Get storage configuration."""
        return {
            "uploads_url": self.storage.uploads_url,
        }

    def get_behavior_config(self) -> dict:
        """Get behavior configuration."""
        return {
            "auto_discover": self.behavior.auto_discover,
            "dashboard_stats": self.behavior.dashboard_stats,
            "dashboard_charts": self.behavior.dashboard_charts,
        }

    def get_nav_config(self) -> dict:
        """Get navigation configuration."""
        return {
            "nav_groups": self.nav.nav_groups,
            "sidebar_builder": self.nav.sidebar_builder,
            "require_tags": self.nav.require_tags,
            "dashboard_permission": self.nav.dashboard_permission,
            "settings_permission": self.nav.settings_permission,
        }
