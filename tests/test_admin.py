"""Tests for Admin class — construction, setup, seeding, and wiring."""

import pytest
from fastapi import FastAPI
from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.orm import DeclarativeBase

from fastapi_admin_kit.admin import Admin
from fastapi_admin_kit.admin.admin_config import AdminConfig
from fastapi_admin_kit.auth import models as _auth_models  # noqa: F401 — register Role etc.
from fastapi_admin_kit.exceptions import ConfigError


def _collect_route_paths(app: FastAPI) -> list[str]:
    """Recursively collect route paths, including those inside _IncludedRouter wrappers."""
    paths: list[str] = []
    for route in app.routes:
        if hasattr(route, "path"):
            paths.append(route.path)
        tname = type(route).__name__
        if tname == "_IncludedRouter":
            incl = route.include_context
            prefix = incl.prefix
            for sub in incl.included_router.routes:
                if hasattr(sub, "path"):
                    paths.append(prefix + sub.path)
    return paths


# ---------------------------------------------------------------------------
# Test models
# ---------------------------------------------------------------------------


class _Base(DeclarativeBase):
    pass


class _Product(_Base):
    __tablename__ = "test_products"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    price = Column(Integer)
    is_active = Column(Boolean, default=True)


class _Category(_Base):
    __tablename__ = "test_categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine():
    """Create an in-memory SQLite engine with all test + admin tables."""
    from sqlalchemy import create_engine

    from fastapi_admin_kit.models.base import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    # Also create test model tables
    _Base.metadata.create_all(bind=engine)
    return engine


# ---------------------------------------------------------------------------
# 9.7 — Admin() constructs
# ---------------------------------------------------------------------------


class TestAdminConstruction:
    def test_default_init(self):
        admin = Admin()
        assert admin.title == "FastAPI Admin Kit"
        assert admin.admin_path == "/admin"
        assert admin.session_ttl == 28800
        assert admin.auto_discover is True
        assert admin.engine is None
        assert admin._app is None

    def test_custom_kwargs(self):
        admin = Admin(
            title="Acme Admin",
            admin_path="/ops",
            session_ttl=3600,
            per_page_default=50,
            secret_key="s3cret",
            auto_discover=False,
        )
        assert admin.title == "Acme Admin"
        assert admin.admin_path == "/ops"
        assert admin.session_ttl == 3600
        assert admin.per_page_default == 50
        assert admin.secret_key == "s3cret"
        assert admin.auto_discover is False

    def test_branding_kwargs(self):
        admin = Admin(
            logo_url="/static/logo.svg",
            favicon_url="/static/favicon.ico",
            primary_color="#ff0000",
            primary_color_dark="#cc0000",
            dark_mode_default=True,
        )
        assert admin.logo_url == "/static/logo.svg"
        assert admin.favicon_url == "/static/favicon.ico"
        assert admin.primary_color == "#ff0000"
        assert admin.primary_color_dark == "#cc0000"
        assert admin.dark_mode_default is True

    def test_auth_kwargs(self):
        admin = Admin(
            session_cookie_name="my_cookie",
            session_secure=True,
            superuser_emails=["admin@test.com"],
        )
        assert admin.session_cookie_name == "my_cookie"
        assert admin.session_secure is True
        assert admin.superuser_emails == ["admin@test.com"]

    def test_legacy_kwargs_merged_into_provided_config(self):
        """Regression: Admin(config=...) must not silently drop legacy kwargs.

        Previously passing a full ``AdminConfig`` ignored ``auth_backend``,
        ``title`` and friends — leaving the auth backend as None and causing
        every authenticated request to 401.
        """
        from fastapi_admin_kit.auth.backend import BuiltinAuthBackend

        admin = Admin(
            title="Acme Admin",
            auth_backend=BuiltinAuthBackend(),
            session_cookie_name="my_cookie",
            config=AdminConfig(),
        )
        assert admin.title == "Acme Admin"
        assert admin.auth_backend is not None
        assert admin.session_cookie_name == "my_cookie"

    def test_provided_config_values_not_overridden(self):
        """Explicit config fields win over legacy kwargs defaults."""
        from fastapi_admin_kit.auth.backend import BuiltinAuthBackend

        config = AdminConfig()
        config.ui.title = "Configured Title"
        config.auth.auth_backend = BuiltinAuthBackend()
        admin = Admin(config=config, auth_backend=BuiltinAuthBackend())
        assert admin.title == "Configured Title"
        assert admin.auth_backend is not None

    def test_template_dirs_flow_into_admin_template(self):
        """template_dirs set via AdminConfig reach the AdminTemplate."""
        config = AdminConfig(template_dirs=["/tmp/custom-templates"])
        admin = Admin(config=config)
        assert admin.template.template_dirs == ["/tmp/custom-templates"]

    def test_seed_roles_default(self):
        admin = Admin()
        assert len(admin.seed_roles) == 4
        assert admin.seed_roles[0].name == "SuperAdmin"
        assert admin.seed_roles[1].name == "Admin"
        assert admin.seed_roles[2].name == "Editor"
        assert admin.seed_roles[3].name == "Viewer"

    def test_seed_roles_custom(self):
        from fastapi_admin_kit.types import SeedRole

        custom = [SeedRole(name="Custom", description="Custom role")]
        admin = Admin(seed_roles=custom)
        assert len(admin.seed_roles) == 1
        assert admin.seed_roles[0].name == "Custom"

    def test_admin_path_strips_trailing_slash(self):
        admin = Admin(admin_path="/admin/")
        assert admin.admin_path == "/admin"


# ---------------------------------------------------------------------------
# 9.7 — setup() runs without error against SQLite
# ---------------------------------------------------------------------------


class TestAdminSetup:
    @pytest.fixture(autouse=True)
    def _clear_registry(self):
        from fastapi_admin_kit.registry import AdminRegistry

        AdminRegistry().clear()
        yield
        AdminRegistry().clear()

    @pytest.fixture()
    def engine(self):
        return _make_engine()

    @pytest.fixture()
    def app(self):
        return FastAPI()

    async def test_setup_creates_tables(self, engine, app):
        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            auto_discover=False,
        )
        await admin.setup()

        # Verify app.state is wired
        assert app.state.admin_engine is engine
        assert app.state.admin_session_backend is not None
        assert app.state.admin_config["title"] == "FastAPI Admin Kit"

    async def test_setup_stores_session_backend(self, engine, app):
        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            auto_discover=False,
        )
        await admin.setup()

        from fastapi_admin_kit.auth.session import SignedCookieSessionBackend

        assert isinstance(app.state.admin_session_backend, SignedCookieSessionBackend)

    async def test_setup_stores_auth_backend(self, engine, app):
        from fastapi_admin_kit.auth.backend import BuiltinAuthBackend

        backend = BuiltinAuthBackend()
        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            auth_backend=backend,
            auto_discover=False,
        )
        await admin.setup()

        assert app.state.admin_auth_backend is backend

    async def test_setup_init_jinja(self, engine, app):
        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            auto_discover=False,
        )
        await admin.setup()

        assert app.state.admin_jinja_env is not None

    async def test_setup_mounts_static(self, engine, app):
        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            auto_discover=False,
        )
        await admin.setup()

        paths = _collect_route_paths(app)
        assert any("static" in p for p in paths)

    async def test_setup_builds_router(self, engine, app):
        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            auto_discover=False,
        )
        admin.register(_Product)
        await admin.setup()

        paths = _collect_route_paths(app)
        assert any("test_products" in p for p in paths)


# ---------------------------------------------------------------------------
# 9.7 — Default roles are created on first run
# ---------------------------------------------------------------------------


class TestSeedRoles:
    @pytest.fixture(autouse=True)
    def _clear_registry(self):
        from fastapi_admin_kit.registry import AdminRegistry

        AdminRegistry().clear()
        yield
        AdminRegistry().clear()

    @pytest.fixture()
    def engine(self):
        return _make_engine()

    @pytest.fixture()
    def app(self):
        return FastAPI()

    async def test_default_roles_seeded(self, engine, app):
        from sqlalchemy.orm import Session

        from fastapi_admin_kit.migrations.models import Role

        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            auto_discover=False,
        )
        await admin.setup()

        session = Session(bind=engine)
        try:
            roles = session.query(Role).all()
            role_names = {r.name for r in roles}
            assert "SuperAdmin" in role_names
            assert "Admin" in role_names
            assert "Editor" in role_names
            assert "Viewer" in role_names
        finally:
            session.close()

    async def test_roles_not_reseeded_by_default(self, engine, app):
        from sqlalchemy.orm import Session

        from fastapi_admin_kit.migrations.models import Role

        # First setup — seeds roles
        admin1 = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            auto_discover=False,
        )
        await admin1.setup()

        session = Session(bind=engine)
        try:
            count1 = session.query(Role).count()
        finally:
            session.close()

        # Second setup — should NOT add more roles
        app2 = FastAPI()
        admin2 = Admin(
            app=app2,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            auto_discover=False,
        )
        await admin2.setup()

        session = Session(bind=engine)
        try:
            count2 = session.query(Role).count()
            assert count2 == count1
        finally:
            session.close()

    async def test_roles_overwrite(self, engine, app):
        from sqlalchemy.orm import Session

        from fastapi_admin_kit.migrations.models import Role

        # First setup
        admin1 = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            auto_discover=False,
        )
        await admin1.setup()

        session = Session(bind=engine)
        try:
            count1 = session.query(Role).count()
            assert count1 == 4
        finally:
            session.close()

        # Second setup with overwrite
        app2 = FastAPI()
        from fastapi_admin_kit.types import SeedRole

        admin2 = Admin(
            app=app2,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            auto_discover=False,
            seed_roles=[SeedRole(name="OnlyThis")],
            seed_roles_overwrite=True,
        )
        await admin2.setup()

        session = Session(bind=engine)
        try:
            roles = session.query(Role).all()
            assert len(roles) == 1
            assert roles[0].name == "OnlyThis"
        finally:
            session.close()

    async def test_custom_seed_roles_with_permissions(self, engine, app):
        from sqlalchemy.orm import Session

        from fastapi_admin_kit.migrations.models import Role
        from fastapi_admin_kit.types import SeedRole

        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            auto_discover=False,
            seed_roles=[
                SeedRole(
                    name="Finance",
                    description="Finance team",
                    permissions={
                        "invoices": {"view": True, "create": True, "edit": False, "delete": False},
                    },
                ),
            ],
        )
        await admin.setup()

        session = Session(bind=engine)
        try:
            role = session.query(Role).filter_by(name="Finance").first()
            assert role is not None
            assert role.description == "Finance team"

            # Get permissions via M2M relationship
            perms = role.permissions
            assert len(perms) == 1
            assert perms[0].table_name == "invoices"
            assert perms[0].can_view is True
            assert perms[0].can_create is True
            assert perms[0].can_edit is False
        finally:
            session.close()


# ---------------------------------------------------------------------------
# 9.7 — auto_discover=False skips auto-discovery
# ---------------------------------------------------------------------------


class TestAutoDiscover:
    @pytest.fixture(autouse=True)
    def _clear_registry(self):
        """Clear the singleton registry between tests."""
        from fastapi_admin_kit.registry import AdminRegistry

        AdminRegistry().clear()
        yield
        AdminRegistry().clear()

    @pytest.fixture()
    def engine(self):
        return _make_engine()

    @pytest.fixture()
    def app(self):
        return FastAPI()

    async def test_auto_discover_true(self, engine, app):
        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            auto_discover=True,
        )
        await admin.setup()

        # Should have discovered test models
        registered = admin.all_registered()
        table_names = {r.table_name for r in registered}
        assert "test_products" in table_names or "test_categories" in table_names

    async def test_auto_discover_false(self, engine, app):
        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            auto_discover=False,
        )
        await admin.setup()

        registered = admin.all_registered()
        table_names = {r.table_name for r in registered}
        assert "test_products" not in table_names
        assert "test_categories" not in table_names

    async def test_ai_enabled_registers_ai_models(self, engine, app):
        from fastapi_admin_kit.ai.config import AIConfig

        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            auto_discover=False,
            ai_enabled=True,
            ai=AIConfig(dashboard_enabled=True),
        )
        await admin.setup()

        registered = admin.all_registered()
        by_table = {r.table_name: r for r in registered}
        assert "admin_ai_conversations" in by_table
        assert "admin_ai_messages" in by_table
        assert "admin_ai_usage_log" in by_table
        assert by_table["admin_ai_conversations"].admin.tag == "ai"
        assert by_table["admin_ai_messages"].admin.tag == "ai"
        assert by_table["admin_ai_usage_log"].admin.tag == "ai"

        # admin_ai_attachments is internal and never shown in the sidebar.
        assert "admin_ai_attachments" not in by_table

        # The "ai" nav group exists with the 5 extra items (Chat/Dashboard/
        # Logs/Tools/Agents) plus the three registered model pages.
        ai_groups = [g for g in admin._nav_groups_built if g.tag == "ai"]
        assert ai_groups, "expected an 'ai' nav group"
        ai_urls = {item.url for item in ai_groups[0].items}
        assert "/admin/ai/chat" in ai_urls
        assert "/admin/ai/dashboard" in ai_urls
        assert "/admin/ai/logs" in ai_urls
        assert "/admin/ai/tools" in ai_urls
        assert "/admin/ai/agents" in ai_urls
        assert "/admin/admin_ai_conversations/" in ai_urls
        assert "/admin/admin_ai_attachments/" not in ai_urls

    async def test_ai_disabled_does_not_register_ai_models(self, engine, app):
        # Use the default auto_discover=True — this is the actual bug scenario.
        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
        )
        await admin.setup()

        registered = admin.all_registered()
        table_names = {r.table_name for r in registered}
        assert "admin_ai_conversations" not in table_names
        assert "admin_ai_messages" not in table_names
        assert "admin_ai_usage_log" not in table_names
        # Internal table is never registered regardless of the flag.
        assert "admin_ai_attachments" not in table_names

        # No nav group should contain an /admin/admin_ai_* URL.
        ai_urls = {item.url for group in admin._nav_groups_built for item in group.items}
        assert not any(url.startswith("/admin/admin_ai_") for url in ai_urls)
        # No "Other" bucket group.
        assert not any(g.tag == "other" for g in admin._nav_groups_built)

    async def test_ai_disabled_has_no_ai_html_routes(self, engine, app):
        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
        )
        await admin.setup()
        paths = _collect_route_paths(app)
        assert not any("/admin/admin_ai_conversations/" in p for p in paths)
        assert not any("/admin/admin_ai_messages/" in p for p in paths)
        assert not any("/admin/admin_ai_usage_log/" in p for p in paths)

    async def test_json_api_excludes_internal_and_ai_tables(self, engine, app):
        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
        )
        await admin.setup()
        paths = _collect_route_paths(app)
        assert not any("/api/admin_ai" in p for p in paths)
        assert not any("/api/admin_refresh_tokens" in p for p in paths)
        assert not any("/api/admin_user_permissions" in p for p in paths)
        assert not any("/api/admin_user_totp" in p for p in paths)

    async def test_notifications_registered_when_ai_off(self, engine, app):
        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
        )
        await admin.setup()
        table_names = {r.table_name for r in admin.all_registered()}
        assert "admin_notifications" in table_names
        assert "admin_notification_preferences" in table_names
        assert "admin_notification_logs" in table_names

    async def test_notifications_disabled_does_not_register_notification_models(self, engine, app):
        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            enable_notification=False,
        )
        await admin.setup()

        table_names = {r.table_name for r in admin.all_registered()}
        assert "admin_notifications" not in table_names
        assert "admin_notification_preferences" not in table_names
        assert "admin_notification_logs" not in table_names

        # No "notifications" sidebar group and no notification URLs.
        notif_urls = {item.url for group in admin._nav_groups_built for item in group.items}
        assert not any(url.startswith("/admin/admin_notification") for url in notif_urls)
        assert not any(g.tag == "notifications" for g in admin._nav_groups_built)

        # No notification routes (model pages or API) are mounted.
        paths = _collect_route_paths(app)
        assert not any("/admin/admin_notification" in p for p in paths)
        assert not any("/notifications" in p for p in paths)

    async def test_notifications_disabled_never_auto_discovered(self, engine, app):
        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            enable_notification=False,
            auto_discover=True,
        )
        await admin.setup()

        table_names = {r.table_name for r in admin.all_registered()}
        assert "admin_notifications" not in table_names
        assert "admin_notification_preferences" not in table_names
        assert "admin_notification_logs" not in table_names

    async def test_ai_tables_not_created_when_disabled(self, app):
        from sqlalchemy import create_engine

        from fastapi_admin_kit.models.base import Base
        from fastapi_admin_kit.schemas.builtin import AI_TABLE_NAMES

        engine = create_engine("sqlite:///:memory:")
        safe_tables = [t for name, t in Base.metadata.tables.items() if name not in AI_TABLE_NAMES]
        Base.metadata.create_all(bind=engine, tables=safe_tables)

        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
        )
        await admin.setup()
        from sqlalchemy import inspect as sa_inspect

        existing = set(sa_inspect(engine).get_table_names())
        assert "admin_ai_conversations" not in existing
        assert "admin_ai_messages" not in existing
        assert "admin_ai_usage_log" not in existing
        assert "admin_ai_attachments" not in existing

    async def test_ai_tables_created_when_enabled(self, app):
        from sqlalchemy import create_engine

        from fastapi_admin_kit.models.base import Base
        from fastapi_admin_kit.schemas.builtin import AI_TABLE_NAMES

        engine = create_engine("sqlite:///:memory:")
        safe_tables = [t for name, t in Base.metadata.tables.items() if name not in AI_TABLE_NAMES]
        Base.metadata.create_all(bind=engine, tables=safe_tables)

        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            ai_enabled=True,
        )
        await admin.setup()
        from sqlalchemy import inspect as sa_inspect

        existing = set(sa_inspect(engine).get_table_names())
        assert "admin_ai_conversations" in existing
        assert "admin_ai_messages" in existing
        assert "admin_ai_usage_log" in existing
        assert "admin_ai_attachments" in existing

    async def test_upgrade_path_ai_enabled_later_keeps_data(self, app):
        """Flip ai_enabled False -> True on the same engine; AI tables appear,
        pre-existing data survives."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from fastapi_admin_kit.migrations.models import Role, User
        from fastapi_admin_kit.models.base import Base
        from fastapi_admin_kit.schemas.builtin import AI_TABLE_NAMES

        # Engine with every admin table EXCEPT the AI ones (simulating an
        # existing project that was created with ai_enabled=False).
        engine = create_engine("sqlite:///:memory:")
        safe_tables = [t for name, t in Base.metadata.tables.items() if name not in AI_TABLE_NAMES]
        Base.metadata.create_all(bind=engine, tables=safe_tables)

        # Seed with AI disabled first.
        admin_off = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
        )
        await admin_off.setup()

        with Session(engine) as s:
            role = Role(name="Existing")
            user = User(
                email="keep@me.com",
                password="x",
                is_superuser=True,
                is_active=True,
            )
            user.roles.append(role)
            s.add(user)
            s.commit()
            seeded_user_id = user.id

        from sqlalchemy import inspect as sa_inspect

        assert "admin_ai_conversations" not in sa_inspect(engine).get_table_names()

        # Now boot a fresh Admin on the SAME engine with AI enabled.
        admin_on = Admin(
            app=FastAPI(),
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            ai_enabled=True,
        )
        await admin_on.setup()

        existing = set(sa_inspect(engine).get_table_names())
        assert "admin_ai_conversations" in existing
        assert "admin_ai_messages" in existing
        assert "admin_ai_usage_log" in existing
        assert "admin_ai_attachments" in existing

        # Pre-existing data untouched.
        with Session(engine) as s:
            kept = s.get(User, seeded_user_id)
            assert kept is not None
            assert kept.email == "keep@me.com"
            assert s.query(Role).filter_by(name="Existing").count() == 1

    async def test_alembic_metadata_always_includes_ai_tables(self):
        """get_admin_metadata() is never filtered by ai_enabled."""
        from fastapi_admin_kit.migrations.models import get_admin_metadata

        tables = set(get_admin_metadata().tables.keys())
        assert "admin_ai_conversations" in tables
        assert "admin_ai_messages" in tables
        assert "admin_ai_usage_log" in tables
        assert "admin_ai_attachments" in tables

    async def test_preflight_warns_when_ai_enabled_without_tables(self, app, caplog):
        """ai_enabled=True + SKIP_CREATE_TABLES=true against a DB lacking the
        AI tables logs a warning and does NOT raise."""
        import logging
        import os

        from sqlalchemy import create_engine

        from fastapi_admin_kit.models.base import Base
        from fastapi_admin_kit.schemas.builtin import AI_TABLE_NAMES

        # Engine with every admin table EXCEPT the AI ones.
        engine = create_engine("sqlite:///:memory:")
        safe_tables = [t for name, t in Base.metadata.tables.items() if name not in AI_TABLE_NAMES]
        Base.metadata.create_all(bind=engine, tables=safe_tables)

        os.environ["SKIP_CREATE_TABLES"] = "true"
        try:
            admin = Admin(
                app=app,
                engine=engine,
                secret_key="test-secret-key-long-enough-for-security!",
                ai_enabled=True,
            )
            with caplog.at_level(logging.WARNING):
                await admin.setup()
        finally:
            os.environ.pop("SKIP_CREATE_TABLES", None)

        assert any(
            "ai_enabled=True but these tables are missing" in rec.message for rec in caplog.records
        )


# ---------------------------------------------------------------------------
# 9.7 — Register decorator pattern
# ---------------------------------------------------------------------------


class TestAdminRegister:
    @pytest.fixture(autouse=True)
    def _clear_registry(self):
        from fastapi_admin_kit.registry import AdminRegistry

        AdminRegistry().clear()
        yield
        AdminRegistry().clear()

    def test_register_direct(self):
        admin = Admin()
        result = admin.register(_Product)
        # Should return a proxy that has .model attribute
        assert result.model is _Product

    def test_register_decorator(self):
        from fastapi_admin_kit.views import ModelAdmin

        admin = Admin()

        @admin.register(_Category)
        class CatAdmin(ModelAdmin):
            list_display = ["name"]

        # The decorator call returns a RegisteredModel (replacing CatAdmin in local scope)
        # Verify the registration worked via the registry
        registered = admin.get_registered("test_categories")
        assert registered is not None
        assert registered.model is _Category
        assert isinstance(registered.admin, ModelAdmin)
        assert registered.admin.list_display == ["name"]

    def test_register_with_explicit_admin_class(self):
        from fastapi_admin_kit.views import ModelAdmin

        class ProdAdmin(ModelAdmin):
            list_display = ["name", "price"]

        admin = Admin()
        result = admin.register(_Product, admin_class=ProdAdmin)
        assert isinstance(result.admin, ProdAdmin)


# ---------------------------------------------------------------------------
# 9.7 — lifespan() works
# ---------------------------------------------------------------------------


class TestLifespan:
    async def test_lifespan_context_manager(self):
        from sqlalchemy import create_engine

        from fastapi_admin_kit.models.base import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)

        app = FastAPI()
        admin = Admin(
            app=app,
            engine=engine,
            secret_key="test-secret-key-long-enough-for-security!",
            auto_discover=False,
        )

        async with admin.lifespan(app):
            # Inside lifespan — setup should have run
            assert app.state.admin_engine is engine
            assert app.state.admin_session_backend is not None

        # After lifespan — state should still be there (no teardown in this impl)
        assert app.state.admin_engine is engine


# ---------------------------------------------------------------------------
# 9.6 — auth_model validation
# ---------------------------------------------------------------------------


class TestAuthModelValidation:
    def test_valid_auth_model(self):
        """A model with the right attrs should not raise."""
        from fastapi_admin_kit.migrations.models import User

        # User has id, email, is_active, is_superuser, role_id
        admin = Admin(auth_model=User)
        # _validate_auth_model should not raise
        admin._validate_auth_model()

    def test_invalid_auth_model_missing_attrs(self):
        """A model missing required attrs should raise ConfigError."""

        class BadModel:
            pass

        admin = Admin(auth_model=BadModel)
        with pytest.raises(ConfigError, match="is missing required attributes"):
            admin._validate_auth_model()

    def test_invalid_auth_model_partial_attrs(self):
        """A model with some but not all required attrs should raise."""

        class PartialModel:
            id = 1
            email = "test@test.com"
            # missing is_active, is_superuser, role_id

        admin = Admin(auth_model=PartialModel)
        with pytest.raises(ConfigError, match="is missing"):
            admin._validate_auth_model()

    def test_no_auth_model_passes(self):
        """None auth_model should not raise."""
        admin = Admin(auth_model=None)
        admin._validate_auth_model()  # no error


# ---------------------------------------------------------------------------
# 9.1 — ConfigError on missing engine/app
# ---------------------------------------------------------------------------


class TestConfigErrors:
    async def test_setup_without_app_raises(self):
        admin = Admin(engine=_make_engine())
        with pytest.raises(ConfigError, match="requires a FastAPI app"):
            await admin.setup()

    async def test_setup_without_engine_raises(self):
        app = FastAPI()
        admin = Admin(app=app)
        with pytest.raises(ConfigError, match="requires a SQLAlchemy engine"):
            await admin.setup()
