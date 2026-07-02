"""Tests for admin configuration classes."""

import pytest

from fastapi_admin_kit.config.audit import AuditConfig
from fastapi_admin_kit.config.auth import AuthConfig
from fastapi_admin_kit.config.behavior import BehaviorConfig
from fastapi_admin_kit.config.nav import NavConfig
from fastapi_admin_kit.config.storage import StorageConfig
from fastapi_admin_kit.config.ui import UIConfig
from fastapi_admin_kit.exceptions import ConfigError


class TestAuthConfig:
    """Test AuthConfig class."""

    def test_init_with_defaults(self):
        """Test AuthConfig initialization with default values."""
        config = AuthConfig()
        assert config.auth_model is None
        assert config.auth_backend is None
        assert config.session_ttl == 28800
        assert config.session_cookie_name == "admin_session"
        assert config.session_secure is False
        assert config.superuser_emails == []

    def test_init_with_values(self):
        """Test AuthConfig initialization with custom values."""

        class MockAuthModel:
            pass

        class MockAuthBackend:
            pass

        config = AuthConfig(
            auth_model=MockAuthModel,
            auth_backend=MockAuthBackend(),
            session_ttl=3600,
            session_cookie_name="custom_session",
            session_secure=True,
            superuser_emails=["admin@example.com", "super@example.com"],
        )

        assert config.auth_model is MockAuthModel
        assert isinstance(config.auth_backend, MockAuthBackend)
        assert config.session_ttl == 3600
        assert config.session_cookie_name == "custom_session"
        assert config.session_secure is True
        assert config.superuser_emails == [
            "admin@example.com",
            "super@example.com",
        ]

    def test_validate_auth_model_none(self):
        """Test validate_auth_model when auth_model is None."""
        config = AuthConfig()
        config.validate_auth_model()  # Should not raise

    def test_validate_auth_model_valid(self):
        """Test validate_auth_model with valid auth_model."""

        class ValidAuthModel:
            id = None
            email = None
            is_active = None
            is_superuser = None
            roles = None

        config = AuthConfig(auth_model=ValidAuthModel)
        config.validate_auth_model()  # Should not raise

    def test_validate_auth_model_invalid(self):
        """Test validate_auth_model with invalid auth_model."""

        class InvalidAuthModel:
            id = None
            email = None
            is_active = None
            is_superuser = None
            # Missing role_id

        config = AuthConfig(auth_model=InvalidAuthModel)
        with pytest.raises(ConfigError) as exc_info:
            config.validate_auth_model()

        assert "does not satisfy AdminUserProtocol" in str(exc_info.value)
        assert "Missing attributes" in str(exc_info.value)


class TestAuditConfig:
    """Test AuditConfig class."""

    def test_init_with_defaults(self):
        """Test AuditConfig initialization with default values."""
        config = AuditConfig()
        assert config.audit_retention_days == 365

    def test_init_with_value(self):
        """Test AuditConfig initialization with custom value."""
        config = AuditConfig(audit_retention_days=730)
        assert config.audit_retention_days == 730

    def test_validate_audit_config_valid(self):
        """Test validate_audit_config with valid value."""
        config = AuditConfig(audit_retention_days=365)
        config.validate_audit_config()  # Should not raise

    def test_validate_audit_config_zero(self):
        """Test validate_audit_config with zero value."""
        config = AuditConfig(audit_retention_days=0)
        config.validate_audit_config()  # Should not raise

    def test_validate_audit_config_negative(self):
        """Test validate_audit_config with negative value."""
        config = AuditConfig(audit_retention_days=-1)
        with pytest.raises(ConfigError) as exc_info:
            config.validate_audit_config()

        assert "must be non-negative" in str(exc_info.value)


class TestUIConfig:
    """Test UIConfig class."""

    def test_init_with_defaults(self):
        """Test UIConfig initialization with default values."""
        config = UIConfig()
        assert config.title == "FastAPI Console"
        assert config.logo_url is None
        assert config.favicon_url is None
        assert config.primary_color == "#0ea5e9"
        assert config.primary_color_dark == "#0284c7"
        assert config.dark_mode_default is False
        assert config.per_page_default == 25

    def test_init_with_values(self):
        """Test UIConfig initialization with custom values."""
        config = UIConfig(
            title="My Admin",
            logo_url="/logo.png",
            favicon_url="/favicon.ico",
            primary_color="#ff0000",
            primary_color_dark="#cc0000",
            dark_mode_default=True,
            per_page_default=50,
        )

        assert config.title == "My Admin"
        assert config.logo_url == "/logo.png"
        assert config.favicon_url == "/favicon.ico"
        assert config.primary_color == "#ff0000"
        assert config.primary_color_dark == "#cc0000"
        assert config.dark_mode_default is True
        assert config.per_page_default == 50

    def test_apply_to_template_context(self):
        """Test apply_to_template_context method."""
        config = UIConfig(
            title="Test Admin",
            logo_url="/logo.png",
            primary_color="#0000ff",
        )

        context = config.apply_to_template_context()
        assert context["title"] == "Test Admin"
        assert context["logo_url"] == "/logo.png"
        assert context["primary_color"] == "#0000ff"
        assert "favicon_url" in context
        assert "primary_color_dark" in context
        assert "dark_mode_default" in context
        assert "per_page_default" in context


class TestBehaviorConfig:
    """Test BehaviorConfig class."""

    def test_init_with_defaults(self):
        """Test BehaviorConfig initialization with default values."""
        config = BehaviorConfig()
        assert config.auto_discover is True
        assert config.dashboard_stats == []
        assert config.dashboard_charts is True

    def test_init_with_values(self):
        """Test BehaviorConfig initialization with custom values."""
        config = BehaviorConfig(
            auto_discover=False,
            dashboard_stats=["users", "posts"],
            dashboard_charts=False,
        )

        assert config.auto_discover is False
        assert config.dashboard_stats == ["users", "posts"]
        assert config.dashboard_charts is False

    def test_validate_behavior_config_valid(self):
        """Test validate_behavior_config with valid value."""
        config = BehaviorConfig()
        config.validate_behavior_config()  # Should not raise

    def test_validate_behavior_config_per_page_default(self):
        """Test validate_behavior_config with per_page_default."""
        config = BehaviorConfig()
        config.validate_behavior_config()  # Should not raise


class TestStorageConfig:
    """Test StorageConfig class."""

    def test_init_with_defaults(self):
        """Test StorageConfig initialization with default values."""
        config = StorageConfig()
        assert config.storage is None
        assert config.uploads_url == "/uploads"

    def test_init_with_values(self):
        """Test StorageConfig initialization with custom values."""

        class MockStorage:
            pass

        config = StorageConfig(
            storage=MockStorage(),
            uploads_url="/custom/uploads",
        )

        assert isinstance(config.storage, MockStorage)
        assert config.uploads_url == "/custom/uploads"

    def test_validate_storage_config_valid(self):
        """Test validate_storage_config with valid value."""
        config = StorageConfig(uploads_url="/uploads")
        config.validate_storage_config()  # Should not raise

    def test_validate_storage_config_empty(self):
        """Test validate_storage_config with empty uploads_url."""
        config = StorageConfig(uploads_url="")
        config.validate_storage_config()  # Should not raise

    def test_validate_storage_config_invalid(self):
        """Test validate_storage_config with invalid value."""
        config = StorageConfig(uploads_url="invalid-url")
        with pytest.raises(ConfigError) as exc_info:
            config.validate_storage_config()

        assert "must start with '/'" in str(exc_info.value)


class TestNavConfig:
    """Test NavConfig class."""

    def test_init_with_defaults(self):
        """Test NavConfig initialization with default values."""
        config = NavConfig()
        assert config.nav_groups == []
        assert config.sidebar_builder is None
        assert config.require_tags is False

    def test_init_with_values(self):
        """Test NavConfig initialization with custom values."""

        class MockSidebarBuilder:
            pass

        config = NavConfig(
            nav_groups=[{"name": "Users"}],
            sidebar_builder=MockSidebarBuilder(),
            require_tags=True,
        )

        assert config.nav_groups == [{"name": "Users"}]
        assert isinstance(config.sidebar_builder, MockSidebarBuilder)
        assert config.require_tags is True

    def test_validate_nav_config_valid(self):
        """Test validate_nav_config with valid values."""
        config = NavConfig(nav_groups=[{"name": "Users"}])
        config.validate_nav_config()  # Should not raise

    def test_validate_nav_config_require_tags(self):
        """Test validate_nav_config with require_tags=True."""
        config = NavConfig(nav_groups=[{"name": "Users"}], require_tags=True)
        config.validate_nav_config()  # Should not raise

    def test_validate_nav_config_require_tags_invalid(self):
        """Test validate_nav_config with require_tags=True but no nav_groups."""
        config = NavConfig(nav_groups=[], require_tags=True)
        with pytest.raises(ConfigError) as exc_info:
            config.validate_nav_config()

        assert "require_tags=True requires nav_groups" in str(exc_info.value)
