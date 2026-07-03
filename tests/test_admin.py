"""Tests for Admin class — construction, setup, seeding, and wiring."""

import pytest
from fastapi import FastAPI
from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.orm import DeclarativeBase

from fastapi_admin_kit.admin import Admin
from fastapi_admin_kit.auth import models as _auth_models  # noqa: F401 — register AdminRole etc.
from fastapi_admin_kit.exceptions import ConfigError

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
        admin = Admin(app=app, engine=engine, secret_key="test-secret-key-long-enough-for-security!", auto_discover=False)
        await admin.setup()

        from fastapi_admin_kit.auth.session import SignedCookieSessionBackend

        assert isinstance(app.state.admin_session_backend, SignedCookieSessionBackend)

    async def test_setup_stores_auth_backend(self, engine, app):
        from fastapi_admin_kit.auth.backend import BuiltinAuthBackend

        backend = BuiltinAuthBackend()
        admin = Admin(
            app=app, engine=engine, secret_key="test-secret-key-long-enough-for-security!", auth_backend=backend, auto_discover=False
        )
        await admin.setup()

        assert app.state.admin_auth_backend is backend

    async def test_setup_init_jinja(self, engine, app):
        admin = Admin(app=app, engine=engine, secret_key="test-secret-key-long-enough-for-security!", auto_discover=False)
        await admin.setup()

        assert app.state.admin_jinja_env is not None

    async def test_setup_mounts_static(self, engine, app):
        admin = Admin(app=app, engine=engine, secret_key="test-secret-key-long-enough-for-security!", auto_discover=False)
        await admin.setup()

        routes = [getattr(r, 'path', '') for r in app.routes]
        assert any("static" in r for r in routes)

    async def test_setup_builds_router(self, engine, app):
        admin = Admin(app=app, engine=engine, secret_key="test-secret-key-long-enough-for-security!", auto_discover=False)
        admin.register(_Product)
        await admin.setup()

        routes = [getattr(r, 'path', '') for r in app.routes]
        assert any("test_products" in r for r in routes)


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

        from fastapi_admin_kit.auth.models import AdminRole

        admin = Admin(app=app, engine=engine, secret_key="test-secret-key-long-enough-for-security!", auto_discover=False)
        await admin.setup()

        session = Session(bind=engine)
        try:
            roles = session.query(AdminRole).all()
            role_names = {r.name for r in roles}
            assert "SuperAdmin" in role_names
            assert "Admin" in role_names
            assert "Editor" in role_names
            assert "Viewer" in role_names
        finally:
            session.close()

    async def test_roles_not_reseeded_by_default(self, engine, app):
        from sqlalchemy.orm import Session

        from fastapi_admin_kit.auth.models import AdminRole

        # First setup — seeds roles
        admin1 = Admin(app=app, engine=engine, secret_key="test-secret-key-long-enough-for-security!", auto_discover=False)
        await admin1.setup()

        session = Session(bind=engine)
        try:
            count1 = session.query(AdminRole).count()
        finally:
            session.close()

        # Second setup — should NOT add more roles
        app2 = FastAPI()
        admin2 = Admin(app=app2, engine=engine, secret_key="test-secret-key-long-enough-for-security!", auto_discover=False)
        await admin2.setup()

        session = Session(bind=engine)
        try:
            count2 = session.query(AdminRole).count()
            assert count2 == count1
        finally:
            session.close()

    async def test_roles_overwrite(self, engine, app):
        from sqlalchemy.orm import Session

        from fastapi_admin_kit.auth.models import AdminRole

        # First setup
        admin1 = Admin(app=app, engine=engine, secret_key="test-secret-key-long-enough-for-security!", auto_discover=False)
        await admin1.setup()

        session = Session(bind=engine)
        try:
            count1 = session.query(AdminRole).count()
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
            roles = session.query(AdminRole).all()
            assert len(roles) == 1
            assert roles[0].name == "OnlyThis"
        finally:
            session.close()

    async def test_custom_seed_roles_with_permissions(self, engine, app):
        from sqlalchemy.orm import Session

        from fastapi_admin_kit.auth.models import AdminPermission, AdminRole
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
            role = session.query(AdminRole).filter_by(name="Finance").first()
            assert role is not None
            assert role.description == "Finance team"

            perms = session.query(AdminPermission).filter_by(role_id=role.id).all()
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
        admin = Admin(app=app, engine=engine, secret_key="test-secret-key-long-enough-for-security!", auto_discover=True)
        await admin.setup()

        # Should have discovered test models
        registered = admin.all_registered()
        table_names = {r.table_name for r in registered}
        assert "test_products" in table_names or "test_categories" in table_names

    async def test_auto_discover_false(self, engine, app):
        admin = Admin(app=app, engine=engine, secret_key="test-secret-key-long-enough-for-security!", auto_discover=False)
        await admin.setup()

        registered = admin.all_registered()
        table_names = {r.table_name for r in registered}
        assert "test_products" not in table_names
        assert "test_categories" not in table_names


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
        from fastapi_admin_kit.auth.models import AdminUser

        # AdminUser has id, email, is_active, is_superuser, role_id
        admin = Admin(auth_model=AdminUser)
        # _validate_auth_model should not raise
        admin._validate_auth_model()

    def test_invalid_auth_model_missing_attrs(self):
        """A model missing required attrs should raise ConfigError."""

        class BadModel:
            pass

        admin = Admin(auth_model=BadModel)
        with pytest.raises(ConfigError, match="does not satisfy AdminUserProtocol"):
            admin._validate_auth_model()

    def test_invalid_auth_model_partial_attrs(self):
        """A model with some but not all required attrs should raise."""

        class PartialModel:
            id = 1
            email = "test@test.com"
            # missing is_active, is_superuser, role_id

        admin = Admin(auth_model=PartialModel)
        with pytest.raises(ConfigError, match="Missing attributes:"):
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
