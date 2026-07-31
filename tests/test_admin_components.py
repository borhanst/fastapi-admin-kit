"""Tests for admin component classes."""

from unittest.mock import MagicMock, patch

import pytest

from fastapi_admin_kit.admin.admin_config import AdminConfig
from fastapi_admin_kit.admin.admin_database import AdminDatabase
from fastapi_admin_kit.admin.admin_router import AdminRouter
from fastapi_admin_kit.admin.admin_template import AdminTemplate
from fastapi_admin_kit.config import AuthConfig, UIConfig


class TestAdminConfig:
    """Test AdminConfig class."""

    def test_init_with_defaults(self):
        """Test AdminConfig initialization with default values."""
        config = AdminConfig()
        assert isinstance(config.ui, UIConfig)
        assert isinstance(config.auth, AuthConfig)
        assert config.ui.title == "FastAPI Admin Kit"
        assert config.auth.session_ttl == 28800

    def test_init_with_custom_configs(self):
        """Test AdminConfig initialization with custom config instances."""
        custom_ui = UIConfig(title="Custom Admin")
        custom_auth = AuthConfig(session_ttl=3600)

        config = AdminConfig(ui=custom_ui, auth=custom_auth)
        assert config.ui is custom_ui
        assert config.auth is custom_auth
        assert config.ui.title == "Custom Admin"
        assert config.auth.session_ttl == 3600

    def test_validate_all(self):
        """Test validate_all method."""
        config = AdminConfig()
        config.validate_all()  # Should not raise

    def test_get_ui_context(self):
        """Test get_ui_context method."""
        config = AdminConfig()
        context = config.get_ui_context()
        assert context["title"] == "FastAPI Admin Kit"
        assert "logo_url" in context

    def test_get_branding_config(self):
        """Test get_branding_config method."""
        config = AdminConfig()
        branding = config.get_branding_config()
        assert branding["title"] == "FastAPI Admin Kit"
        assert branding["primary_color"] == "#0ea5e9"

    def test_get_session_config(self):
        """Test get_session_config method."""
        config = AdminConfig()
        session_config = config.get_session_config()
        assert session_config["session_ttl"] == 28800
        assert session_config["session_cookie_name"] == "admin_session"

    def test_get_audit_config(self):
        """Test get_audit_config method."""
        config = AdminConfig()
        audit_config = config.get_audit_config()
        assert audit_config["audit_retention_days"] == 365

    def test_get_storage_config(self):
        """Test get_storage_config method."""
        config = AdminConfig()
        storage_config = config.get_storage_config()
        assert storage_config["uploads_url"] == "/uploads"

    def test_get_behavior_config(self):
        """Test get_behavior_config method."""
        config = AdminConfig()
        behavior_config = config.get_behavior_config()
        assert behavior_config["auto_discover"] is True
        assert behavior_config["dashboard_stats"] == []

    def test_get_nav_config(self):
        """Test get_nav_config method."""
        config = AdminConfig()
        nav_config = config.get_nav_config()
        assert nav_config["nav_groups"] == []
        assert nav_config["require_tags"] is False


class TestAdminDatabase:
    """Test AdminDatabase class."""

    def test_init_with_defaults(self):
        """Test AdminDatabase initialization with default values."""
        config = AdminDatabase()
        assert config.engine is None
        assert config.base is None

    def test_init_with_values(self):
        """Test AdminDatabase initialization with custom values."""
        mock_engine = MagicMock()
        mock_base = MagicMock()

        config = AdminDatabase(engine=mock_engine, base=mock_base)
        assert config.engine is mock_engine
        assert config.base is mock_base

    @pytest.mark.asyncio
    async def test_create_tables_with_async_engine(self):
        """Test _create_tables method exists and is callable."""
        config = AdminDatabase()
        assert callable(config._create_tables)

    def test_create_tables_with_sync_engine(self):
        """Test _create_tables with sync engine."""
        mock_sync_engine = MagicMock()

        config = AdminDatabase(engine=mock_sync_engine)
        config._create_tables = MagicMock()

        config._create_tables()
        config._create_tables.assert_called_once()

    @pytest.mark.asyncio
    async def test_seed_roles_with_async_engine(self):
        """Test _seed_roles method exists and is callable."""
        config = AdminDatabase()
        assert callable(config._seed_roles)

    def test_seed_roles_with_sync_engine(self):
        """Test _seed_roles with sync engine."""
        mock_sync_engine = MagicMock()

        seed_roles = []

        config = AdminDatabase(engine=mock_sync_engine)
        config._seed_roles = MagicMock()

        config._seed_roles(seed_roles)
        config._seed_roles.assert_called_once_with(seed_roles)

    def test_init_session_backend(self):
        """Test _init_session_backend method."""
        config = AdminDatabase()
        session_backend = config._init_session_backend(
            secret_key="test-secret-key-long-enough-for-security!",
            session_ttl=3600,
            cookie_name="test_cookie",
            secure=True,
        )

        assert session_backend is not None


class TestAdminRouter:
    """Test AdminRouter class."""

    def test_init_with_defaults(self):
        """Test AdminRouter initialization with default values."""
        router = AdminRouter()
        assert router.admin_path == "/admin"
        assert router.secret_key == ""

    def test_init_with_custom_values(self):
        """Test AdminRouter initialization with custom values."""
        router = AdminRouter(
            admin_path="/custom",
            secret_key="test-secret-key-long-enough-for-security!",
        )
        assert router.admin_path == "/custom"
        assert router.secret_key == "test-secret-key-long-enough-for-security!"

    def test_admin_path_strips_trailing_slash(self):
        """Test admin_path strips trailing slash."""
        router = AdminRouter(admin_path="/admin/")
        assert router.admin_path == "/admin"

    def test_build_router(self):
        """Test _build_router method exists and is callable."""
        router = AdminRouter()
        assert callable(router._build_router)

    def test_mount_static(self):
        """Test _mount_static method exists and is callable."""
        router = AdminRouter()
        assert callable(router._mount_static)

    def test_init_jinja(self):
        """Test _init_jinja method."""
        mock_app = MagicMock()

        router = AdminRouter()
        router._init_jinja(mock_app)

        assert hasattr(mock_app.state, "admin_jinja_env")


class TestAdminTemplate:
    """Test AdminTemplate class."""

    def test_init_with_defaults(self):
        """Test AdminTemplate initialization with default values."""
        template = AdminTemplate()
        assert template.title == "FastAPI Admin Kit"
        assert template.primary_color == "#0ea5e9"
        assert template._nav_groups_built == []

    def test_init_with_custom_values(self):
        """Test AdminTemplate initialization with custom values."""
        template = AdminTemplate(
            title="Custom Admin",
            logo_url="/logo.png",
            primary_color="#ff0000",
        )
        assert template.title == "Custom Admin"
        assert template.logo_url == "/logo.png"
        assert template.primary_color == "#ff0000"

    def test_init_jinja(self):
        """Test _init_jinja method."""
        mock_app = MagicMock()

        template = AdminTemplate()
        template._init_jinja(mock_app)

        assert hasattr(mock_app.state, "admin_jinja_env")

    def test_sidebar_template_kwargs(self):
        """Test sidebar_template_kwargs method."""
        from tests.conftest import run_async

        mock_request = MagicMock()
        template = AdminTemplate()

        async def _test():
            with patch.object(template, "build_sidebar_context", return_value={"nav_groups": []}):
                result = await template.sidebar_template_kwargs(mock_request)
                assert result == {"nav_groups": []}

        run_async(_test())

    def test_build_sidebar_context_without_user(self):
        """Test build_sidebar_context without user."""
        from tests.conftest import run_async

        mock_request = MagicMock()
        mock_request.state.admin_user = None
        mock_request.state.admin_user_snapshot = None
        template = AdminTemplate()

        async def _test():
            with patch(
                "fastapi_admin_kit.auth.permissions.PermissionChecker",
                return_value=None,
                create=True,
            ):
                result = await template.build_sidebar_context(mock_request)
                assert result["current_user"] is None
                assert "nav_groups" in result

        run_async(_test())

    def test_build_sidebar_context_with_user(self):
        """Test build_sidebar_context with user."""
        from tests.conftest import run_async

        mock_request = MagicMock()
        mock_user = MagicMock()
        mock_request.state.admin_user = mock_user
        mock_request.state.admin_user_snapshot = None

        template = AdminTemplate()

        async def _test():
            with patch("fastapi_admin_kit.auth.permissions.PermissionChecker") as mock_checker:
                mock_checker.return_value.permission_set.return_value = {"view": True}
                result = await template.build_sidebar_context(mock_request, user=mock_user)

                assert result["current_user"] is mock_user
                assert "nav_groups" in result

        run_async(_test())

    def test_apply_sidebar_context(self):
        """Test apply_sidebar_context method."""
        from tests.conftest import run_async

        mock_request = MagicMock()
        mock_user = MagicMock()
        context = {"existing_key": "existing_value"}

        template = AdminTemplate()

        async def _test():
            with patch.object(template, "build_sidebar_context", return_value={"nav_groups": []}):
                result = await template.apply_sidebar_context(mock_request, mock_user, context)
                assert result["existing_key"] == "existing_value"
                assert result["nav_groups"] == []

        run_async(_test())
