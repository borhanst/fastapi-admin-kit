"""Admin class — public API, wires everything at init."""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment

from fastapi_admin_kit.admin.admin_config import AdminConfig
from fastapi_admin_kit.admin.admin_database import AdminDatabase
from fastapi_admin_kit.admin.admin_router import AdminRouter
from fastapi_admin_kit.admin.admin_template import AdminTemplate
from fastapi_admin_kit.config import (
    AuditConfig,
    AuthConfig,
    BehaviorConfig,
    NavConfig,
    StorageConfig,
    ThemeConfig,
    UIConfig,
)
from fastapi_admin_kit.exceptions import ConfigError
from fastapi_admin_kit.registry import AdminRegistry, RegisteredModel
from fastapi_admin_kit.types import SeedRole

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from fastapi_admin_kit.auth.backend import AuthBackend
    from fastapi_admin_kit.nav import NavGroupConfig, SidebarBuilder
    from fastapi_admin_kit.storage.base import StorageBackend
    from fastapi_admin_kit.views import ModelAdmin


# ---------------------------------------------------------------------------
# Default seed roles per AUTH_RBAC_SYSTEM.md §13
# ---------------------------------------------------------------------------

DEFAULT_SEED_ROLES: list[SeedRole] = [
    SeedRole(
        name="SuperAdmin",
        description="Full system access — equivalent to is_superuser=True",
        permissions={},  # empty = all permissions (superuser)
    ),
    SeedRole(
        name="Admin",
        description="Site administration — all permissions except admin_users",
        permissions={
            "admin_users": {
                "view": True,
                "create": False,
                "edit": False,
                "delete": False,
            },
        },
    ),
    SeedRole(
        name="Editor",
        description="Content editing — full CRUD on non-system models",
        permissions={},  # non-system models get full CRUD
    ),
    SeedRole(
        name="Viewer",
        description="Read-only access",
        permissions={},  # view-only for all models
    ),
]


class _RegistrationProxy:
    """Dual-purpose return value from Admin.register().

    Acts as a proxy to the underlying RegisteredModel so attribute access
    (``.model``, ``.admin``, etc.) works transparently.  Also supports
    use as a class decorator::

        @admin.register(Product)
        class ProductAdmin(ModelAdmin): ...

    When called with a class, it re-registers with that admin class and
    returns the resulting RegisteredModel.
    """

    def __init__(self, admin: Admin, registered: RegisteredModel) -> None:
        object.__setattr__(self, "_admin", admin)
        object.__setattr__(self, "_registered", registered)

    def __call__(self, admin_class: type[ModelAdmin]) -> RegisteredModel:
        reg: AdminRegistry = self._admin.registry
        registered = reg.register(self._registered.model, admin_class)
        object.__setattr__(self, "_registered", registered)
        return registered

    def __getattr__(self, name: str) -> Any:
        return getattr(self._registered, name)


class Admin:
    """Main admin interface. Register models and mount to your FastAPI app.

    Uses component-based architecture with:
    - config: AdminConfig (UI, auth, audit, behavior, storage, nav settings)
    - database: AdminDatabase (engine, table creation, role seeding)
    - router: AdminRouter (routing, static files, Jinja)
    - template: AdminTemplate (branding, sidebar context)
    """

    def __init__(
        self,
        app: FastAPI | None = None,
        engine: Engine | None = None,
        *,
        # Component instances (new API)
        config: AdminConfig | None = None,
        database: AdminDatabase | None = None,
        router: AdminRouter | None = None,
        template: AdminTemplate | None = None,
        # Legacy kwargs for backward compatibility
        base: type | None = None,
        title: str = "FastAPI Console",
        logo_url: str | None = None,
        favicon_url: str | None = None,
        primary_color: str = "#0ea5e9",
        primary_color_dark: str = "#0284c7",
        dark_mode_default: bool = False,
        per_page_default: int = 25,
        session_ttl: int = 28800,
        audit_retention_days: int = 365,
        dashboard_stats: list[str] | None = None,
        dashboard_charts: bool = True,
        admin_path: str = "/admin",
        secret_key: str = "",
        auth_model: type | None = None,
        auth_backend: AuthBackend | None = None,
        session_cookie_name: str = "admin_session",
        session_secure: bool = False,
        session_samesite: str = "strict",
        seed_roles: list[SeedRole] | None = None,
        seed_roles_overwrite: bool = False,
        superuser_emails: list[str] | None = None,
        storage: StorageBackend | None = None,
        uploads_url: str = "/uploads",
        auto_discover: bool = True,
        nav_groups: list[NavGroupConfig] | None = None,
        sidebar_builder: SidebarBuilder | None = None,
        require_tags: bool = False,
        theme: ThemeConfig | None = None,
        # UI component config
        sidebar_style: str = "default",
        sidebar_position: str = "left",
        table_style: str = "default",
        table_row_height: str = "normal",
        form_layout: str = "two-column",
        form_spacing: str = "normal",
        dashboard_grid: str = "auto",
        dashboard_card_style: str = "default",
        dashboard_stat_size: str = "normal",
        content_width: str = "default",
        topbar_style: str = "default",
        custom_css: str = "",
        custom_css_url: str = "",
        custom_js: str = "",
        custom_js_url: str = "",
        show_history: bool = True,
        show_view_on_site: bool = True,
        environment_label: str | None = None,
        environment_color: str = "info",
        mobile_sidebar: str = "overlay",
        dashboard_permission: str | None = None,
        settings_permission: str | None = None,
    ):
        self.registry = AdminRegistry()
        self._app: FastAPI | None = app

        # Add CSRF middleware early (must be before app starts)
        if app is not None:
            from fastapi_admin_kit.auth.csrf import (
                CSRFMiddleware,
                auth_redirect_handler,
            )

            app.add_exception_handler(401, auth_redirect_handler)
            app.add_middleware(CSRFMiddleware)
            self._csrf_middleware_added = True
        else:
            self._csrf_middleware_added = False

        # Build components from legacy kwargs if components not provided
        if config is None:
            config = AdminConfig(
                ui=UIConfig(
                    title=title,
                    logo_url=logo_url,
                    favicon_url=favicon_url,
                    primary_color=primary_color,
                    primary_color_dark=primary_color_dark,
                    dark_mode_default=dark_mode_default,
                    per_page_default=per_page_default,
                    theme=theme,
                    sidebar_style=sidebar_style,
                    sidebar_position=sidebar_position,
                    table_style=table_style,
                    table_row_height=table_row_height,
                    form_layout=form_layout,
                    form_spacing=form_spacing,
                    dashboard_grid=dashboard_grid,
                    dashboard_card_style=dashboard_card_style,
                    dashboard_stat_size=dashboard_stat_size,
                    content_width=content_width,
                    topbar_style=topbar_style,
                    custom_css=custom_css,
                    custom_css_url=custom_css_url,
                    custom_js=custom_js,
                    custom_js_url=custom_js_url,
                    show_history=show_history,
                    show_view_on_site=show_view_on_site,
                    environment_label=environment_label,
                    environment_color=environment_color,
                    mobile_sidebar=mobile_sidebar,
                ),
                auth=AuthConfig(
                    auth_model=auth_model,
                    auth_backend=auth_backend,
                    session_ttl=session_ttl,
                    session_cookie_name=session_cookie_name,
                    session_secure=session_secure,
                    superuser_emails=superuser_emails,
                    session_samesite=session_samesite,
                ),
                audit=AuditConfig(audit_retention_days=audit_retention_days),
                behavior=BehaviorConfig(
                    auto_discover=auto_discover,
                    dashboard_stats=dashboard_stats or [],
                    dashboard_charts=dashboard_charts,
                ),
                storage=StorageConfig(storage=storage, uploads_url=uploads_url),
                nav=NavConfig(
                    nav_groups=nav_groups or [],
                    sidebar_builder=sidebar_builder,
                    require_tags=require_tags,
                    dashboard_permission=dashboard_permission,
                    settings_permission=settings_permission,
                ),
            )

        if database is None:
            database = AdminDatabase(engine=engine, base=base)

        if router is None:
            router = AdminRouter(
                admin_path=admin_path,
                secret_key=secret_key or os.environ.get("SECRET_KEY", ""),
            )

        if template is None:
            template = AdminTemplate(
                title=config.ui.title,
                logo_url=config.ui.logo_url,
                favicon_url=config.ui.favicon_url,
                primary_color=config.ui.primary_color,
                primary_color_dark=config.ui.primary_color_dark,
                dark_mode_default=config.ui.dark_mode_default,
                dashboard_permission=config.nav.dashboard_permission,
                settings_permission=config.nav.settings_permission,
            )

        self.config = config
        self.database = database
        self.router = router
        self.template = template

        # RBAC
        self.seed_roles = (
            seed_roles if seed_roles is not None else DEFAULT_SEED_ROLES
        )
        self.seed_roles_overwrite = seed_roles_overwrite

        # Built sidebar (populated during setup)
        self._nav_groups_built: list[Any] = []

        # Internal state (populated during setup)
        self._session_backend: Any = None
        self._jinja_env: Environment | None = None
        self._router_built: bool = False

        if app is not None and engine is not None:
            # Deferred setup — user will call await admin.setup() via lifespan
            pass

    # ------------------------------------------------------------------
    # Backward-compatible property accessors
    # ------------------------------------------------------------------

    @property
    def title(self) -> str:
        return self.config.ui.title

    @property
    def logo_url(self) -> str | None:
        return self.config.ui.logo_url

    @property
    def favicon_url(self) -> str | None:
        return self.config.ui.favicon_url

    @property
    def primary_color(self) -> str:
        return self.config.ui.primary_color

    @property
    def primary_color_dark(self) -> str:
        return self.config.ui.primary_color_dark

    @property
    def dark_mode_default(self) -> bool:
        return self.config.ui.dark_mode_default

    @property
    def per_page_default(self) -> int:
        return self.config.ui.per_page_default

    @property
    def admin_path(self) -> str:
        return self.router.admin_path

    @property
    def secret_key(self) -> str:
        return self.router.secret_key

    @property
    def engine(self) -> Engine | None:
        return self.database.engine

    @property
    def base(self) -> type | None:
        return self.database.base

    @property
    def session_ttl(self) -> int:
        return self.config.auth.session_ttl

    @property
    def audit_retention_days(self) -> int:
        return self.config.audit.audit_retention_days

    @property
    def dashboard_stats(self) -> list[str]:
        return self.config.behavior.dashboard_stats

    @property
    def dashboard_charts(self) -> bool:
        return self.config.behavior.dashboard_charts

    @property
    def auth_model(self) -> type | None:
        return self.config.auth.auth_model

    @property
    def auth_backend(self) -> AuthBackend | None:
        return self.config.auth.auth_backend

    @property
    def session_cookie_name(self) -> str:
        return self.config.auth.session_cookie_name

    @property
    def session_secure(self) -> bool:
        return self.config.auth.session_secure

    @property
    def superuser_emails(self) -> list[str]:
        return self.config.auth.superuser_emails

    @property
    def storage(self) -> StorageBackend | None:
        return self.config.storage.storage

    @property
    def uploads_url(self) -> str:
        return self.config.storage.uploads_url

    @property
    def auto_discover(self) -> bool:
        return self.config.behavior.auto_discover

    @property
    def nav_groups(self) -> list[NavGroupConfig]:
        return self.config.nav.nav_groups

    @property
    def sidebar_builder(self) -> SidebarBuilder | None:
        return self.config.nav.sidebar_builder

    @property
    def require_tags(self) -> bool:
        return self.config.nav.require_tags

    # ------------------------------------------------------------------
    # Setup (async)
    # ------------------------------------------------------------------

    async def setup(self, app: FastAPI | None = None) -> None:
        """Run all startup wiring: create tables, seed roles, mount assets.

        This must be called once during application lifespan, typically via
        the :meth:`lifespan` context manager.
        """
        if app is not None:
            self._app = app

        if self._app is None:
            raise ConfigError(
                "Admin requires a FastAPI app instance. Pass app= or call setup(app=)."
            )

        if self.database.engine is None:
            raise ConfigError(
                "Admin requires a SQLAlchemy engine. Pass engine= to Admin()."
            )

        app = self._app

        # Add CSRF middleware if not already added in __init__
        if not getattr(self, "_csrf_middleware_added", False):
            from fastapi_admin_kit.auth.csrf import (
                CSRFMiddleware,
                auth_redirect_handler,
            )

            try:
                app.add_exception_handler(401, auth_redirect_handler)
                app.add_middleware(CSRFMiddleware)
            except RuntimeError:
                pass  # Already started — middleware was added in __init__

        # Add per-request session middleware
        if not getattr(self, "_session_middleware_added", False):
            from fastapi_admin_kit.db import SessionMiddleware

            try:
                app.add_middleware(SessionMiddleware)
                self._session_middleware_added = True
            except RuntimeError:
                pass

        # Add audit context middleware
        if not getattr(self, "_audit_middleware_added", False):
            from fastapi_admin_kit.audit.middleware import (
                AuditContextMiddleware,
            )

            try:
                app.add_middleware(AuditContextMiddleware)
                self._audit_middleware_added = True
            except RuntimeError:
                pass

        # 0. Validate secret_key strength
        if not self.router.secret_key:
            raise ConfigError(
                "Admin secret_key is required. Pass a strong secret (≥32 chars) "
                "via Admin(secret_key=...) or the SECRET_KEY environment variable."
            )
        if len(self.router.secret_key) < 32:
            raise ConfigError(
                f"Admin secret_key is too short ({len(self.router.secret_key)} chars). "
                "Must be at least 32 characters for secure signing."
            )

        # 1. Validate auth_model satisfies AdminUserProtocol
        self.config.auth.validate_auth_model()

        # 2. Database tables should be created via Alembic migrations
        skip_create_tables = (
            os.environ.get("SKIP_CREATE_TABLES", "true").lower() == "true"
        )
        if not skip_create_tables:
            await self.database._create_tables()

        # 3. Seed default roles
        await self.database._seed_roles(
            self.seed_roles, self.seed_roles_overwrite
        )

        # 4. Create and store session backend
        self._session_backend = self.database._init_session_backend(
            secret_key=self.router.secret_key,
            session_ttl=self.config.auth.session_ttl,
            cookie_name=self.config.auth.session_cookie_name,
            secure=self.config.auth.session_secure,
        )

        # 5. Store backends and config on app.state
        self._wire_app_state(app)

        # 6. Mount static files
        self._mount_static(app)

        # 7. Initialise Jinja2
        self._init_jinja(app)

        # 8. Auto-register built-in admin models (before auto_discover)
        self._register_builtin_models()

        # 8.1 Auto-discover user models
        if self.config.behavior.auto_discover:
            self.registry.auto_discover()

        # 8.2 Attach audit event listeners (after registry is populated)
        from fastapi_admin_kit.audit.listener import attach_audit_listener

        engine = self.database.engine
        if engine is not None:
            from sqlalchemy.ext.asyncio import AsyncEngine

            if isinstance(engine, AsyncEngine):
                from fastapi_admin_kit.db import create_session_factory

                session_factory = create_session_factory(engine)
                attach_audit_listener(session_factory, self.registry)

        # 9. Validate require_tags
        if self.config.nav.require_tags:
            self._validate_tags()

        # 10. Build sidebar structure (once at startup)
        self._nav_groups_built = self._build_sidebar()
        self.template._nav_groups_built = self._nav_groups_built
        if self._jinja_env:
            self._jinja_env.env.globals["nav_groups"] = self._nav_groups_built

        # 11. Build and mount routers
        self._build_router(app)

    # ------------------------------------------------------------------
    # Register
    # ------------------------------------------------------------------

    def register(
        self,
        model: type,
        admin_class: type[ModelAdmin] | None = None,
    ) -> _RegistrationProxy | RegisteredModel:
        """Register a model with the admin.

        Usage::

            admin.register(Product)

            @admin.register(Product)
            class ProductAdmin(ModelAdmin):
                list_display = ["name", "price"]
        """
        if admin_class is not None:
            registered = self.registry.register(model, admin_class)
        else:
            registered = self.registry.register(model)
        if self._jinja_env:
            self._jinja_env.env.globals["registered_models"] = (
                self.registry.all()
            )
            if self._nav_groups_built:
                self._nav_groups_built = self._build_sidebar()
                self.template._nav_groups_built = self._nav_groups_built
                self._jinja_env.env.globals["nav_groups"] = (
                    self._nav_groups_built
                )
        if admin_class is not None:
            return registered
        return _RegistrationProxy(self, registered)

    # ------------------------------------------------------------------
    # Lifespan
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        """FastAPI lifespan context manager.

        Usage::

            app = FastAPI(lifespan=admin.lifespan)
        """
        await self.setup(app)
        yield

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_registered(self, table_name: str) -> RegisteredModel | None:
        """Get a registered model by table name."""
        return self.registry.get(table_name)

    def all_registered(self) -> list[RegisteredModel]:
        """Get all registered models."""
        return self.registry.all()

    def unregister(self, model: type) -> None:
        """Unregister a model so it can be re-registered with a custom admin class.

        Useful for overriding built-in admin models::

            from fastapi_admin_kit.auth.models import AdminUser
            from fastapi_admin_kit.admin.builtin_models import AdminUserAdmin

            class MyAdminUserAdmin(AdminUserAdmin):
                list_display = ["id", "email", "full_name"]

            admin.unregister(AdminUser)
            admin.register(AdminUser, MyAdminUserAdmin)
        """
        table_name = model.__tablename__
        self.registry._models.pop(table_name, None)

    # ------------------------------------------------------------------
    # Internal wiring
    # ------------------------------------------------------------------

    def _validate_auth_model(self) -> None:
        """Validate that auth_model satisfies AdminUserProtocol."""
        self.config.auth.validate_auth_model()

    def _wire_app_state(self, app: FastAPI) -> None:
        """Store backends and configuration on app.state as typed AdminState."""
        from fastapi_admin_kit.admin.state import AdminState

        admin_config = {
            "title": self.config.ui.title,
            "logo_url": self.config.ui.logo_url,
            "favicon_url": self.config.ui.favicon_url,
            "primary_color": self.config.ui.primary_color,
            "primary_color_dark": self.config.ui.primary_color_dark,
            "dark_mode_default": self.config.ui.dark_mode_default,
            "per_page_default": self.config.ui.per_page_default,
            "session_ttl": self.config.auth.session_ttl,
            "audit_retention_days": self.config.audit.audit_retention_days,
            "dashboard_stats": self.config.behavior.dashboard_stats,
            "dashboard_charts": self.config.behavior.dashboard_charts,
            "admin_path": self.router.admin_path,
            "superuser_emails": self.config.auth.superuser_emails,
            "ui_config": self.config.ui.apply_to_template_context(),
        }
        if self.config.ui.theme:
            admin_config.update(self.config.ui.theme.to_context())

        # Create session factory if engine is available
        db_session = None
        session_factory = None
        engine = self.database.engine
        if engine is not None:
            from sqlalchemy.ext.asyncio import AsyncEngine

            if isinstance(engine, AsyncEngine):
                from fastapi_admin_kit.db import create_session_factory

                session_factory = create_session_factory(engine)
                # Legacy fallback — a single session for backward compat
                db_session = session_factory()
            else:
                from sqlalchemy.orm import sessionmaker as sync_sessionmaker

                session_factory = sync_sessionmaker(bind=engine, expire_on_commit=False)
                db_session = session_factory()

        state = AdminState(
            engine=engine,
            session_backend=self._session_backend,
            auth_backend=self.config.auth.auth_backend,
            storage=self.config.storage.storage,
            registry=self.registry,
            db_session=db_session,
            config=admin_config,
            jinja_env=self._jinja_env,
            admin_instance=self,
            secret_key=self.router.secret_key,
            session_samesite=self.config.auth.session_samesite,
        )

        # Store typed state as single attribute
        app.state.admin_state = state

        # Also store individual attributes for backward compatibility
        app.state.admin = self  # Admin instance (backward compat)
        app.state.admin_engine = state.engine
        app.state.admin_session_backend = state.session_backend
        app.state.admin_auth_backend = state.auth_backend
        app.state.admin_storage = state.storage
        app.state.admin_registry = state.registry
        app.state.admin_db_session = state.db_session
        app.state.admin_session_factory = session_factory
        app.state.admin_config = state.config
        app.state.admin_jinja_env = state.jinja_env
        # Unified signing-key source for sessions, CSRF, and JWT (see AdminState).
        app.state.admin_secret_key = state.secret_key

    def _mount_static(self, app: FastAPI) -> None:
        """Mount the static files directory and uploads directory."""
        static_dir = Path(__file__).parent.parent / "static"
        if static_dir.is_dir():
            app.mount(
                "/static",
                StaticFiles(directory=str(static_dir)),
                name="admin_static",
            )

        # Mount uploads directory if using LocalStorageBackend
        from fastapi_admin_kit.storage.local import LocalStorageBackend

        if isinstance(self.config.storage.storage, LocalStorageBackend):
            self.config.storage.storage.ensure_dir()
            app.mount(
                self.config.storage.uploads_url,
                StaticFiles(
                    directory=str(self.config.storage.storage.upload_dir)
                ),
                name="admin_uploads",
            )

    def _init_jinja(self, app: FastAPI) -> None:
        """Initialise the Jinja2 template environment."""
        from starlette.templating import Jinja2Templates

        templates_dir = Path(__file__).parent.parent / "templates"
        self._jinja_env = Jinja2Templates(directory=str(templates_dir))

        # Disable autoescape — templates are server-controlled, no user XSS risk
        self._jinja_env.env.autoescape = False

        def slugify(s: str) -> str:
            return re.sub(r"[^\w]", "-", s, flags=re.A).strip("-").lower()

        def _attr(obj: Any, name: str) -> Any:
            return getattr(obj, name, "")

        self._jinja_env.env.filters["slugify"] = slugify
        self._jinja_env.env.globals["attr"] = _attr
        from fastapi_admin_kit.inspection import model_display_name

        self._jinja_env.env.globals["model_display_name"] = model_display_name
        self._jinja_env.env.globals["registered_models"] = self.registry.all()
        self._jinja_env.env.globals["admin_path"] = self.router.admin_path
        self._jinja_env.env.globals["nav_groups"] = self._nav_groups_built

        # CSRF token helper — reads from request.state (set by CSRFMiddleware)
        def _get_csrf_token(request) -> str:
            return getattr(request.state, "csrf_token", "")

        self._jinja_env.env.globals["get_csrf_token"] = _get_csrf_token

        # Flash messages helper (reads from session cookie directly)
        def _get_flash_messages(request) -> list[dict[str, str]]:
            try:
                session_backend = request.app.state.admin_session_backend
                cookie_name = getattr(
                    session_backend, "cookie_name", "admin_session"
                )
                raw = request.cookies.get(cookie_name)
                if not raw or not hasattr(session_backend, "load"):
                    return []
                data = session_backend.load(raw)
                if not isinstance(data, dict):
                    return []
                return (
                    data.pop("admin_flash", []) if "admin_flash" in data else []
                )
            except Exception:
                return []

        self._jinja_env.env.globals["get_flash_messages"] = _get_flash_messages

        # Material Symbols icon helper
        _icon_map = {
            "home": "home",
            "chart-bar": "bar_chart",
            "clock": "schedule",
            "shield-check": "verified_user",
            "users": "group",
            "folder": "folder",
            "cube": "inventory_2",
            "shopping-cart": "shopping_cart",
            "magnifying-glass": "search",
            "chevron-right": "chevron_right",
            "chevron-left": "chevron_left",
            "chevron-up": "expand_less",
            "chevron-down": "expand_more",
            "ellipsis-vertical": "more_vert",
            "pencil": "edit",
            "trash": "delete",
            "x-mark": "close",
            "x-circle": "cancel",
            "check-circle": "check_circle",
            "check": "check",
            "plus": "add",
            "eye": "visibility",
            "bell": "notifications",
            "sun": "light_mode",
            "moon": "dark_mode",
            "bars-": "menu",
            "bars-3": "menu",
            "arrow-down-tray": "download",
            "arrow-path": "refresh",
            "paper-airplane": "send",
            "exclamation-triangle": "warning",
            "information-circle": "info",
            "document-text": "description",
            "arrow-down": "arrow_downward",
            "arrow-up": "arrow_upward",
            "bolt": "bolt",
            "cog-": "settings",
            "cog-6-tooth": "settings",
        }

        def _icon(name: str, size: str = "", **kwargs) -> str:
            ms_name = _icon_map.get(name, name)
            css_class = kwargs.get("class", kwargs.get("css_class", ""))
            size_style = f' style="font-size: {size};"' if size else ""
            cls = f"material-symbols-outlined {css_class}".strip()
            return f'<span class="{cls}"{size_style}>{ms_name}</span>'

        self._jinja_env.env.globals["icon"] = _icon

        # Admin config global (used by templates for branding, dark mode, etc.)
        admin_cfg = {
            "title": self.config.ui.title,
            "logo_url": self.config.ui.logo_url,
            "favicon_url": self.config.ui.favicon_url,
            "primary_color": self.config.ui.primary_color,
            "primary_color_dark": self.config.ui.primary_color_dark,
            "dark_mode_default": self.config.ui.dark_mode_default,
            "admin_path": self.router.admin_path,
        }
        self._jinja_env.env.globals["admin_config"] = admin_cfg

        # Static file cache-busting version hash
        import hashlib
        from pathlib import Path as _Path

        _static_dir = _Path(__file__).parent.parent / "static"
        _hash_data = b""
        for _f in (
            "css/tokens.css",
            "css/presets.css",
            "css/admin.css",
            "js/admin.js",
        ):
            _fp = _static_dir / _f
            if _fp.is_file():
                _hash_data += _fp.read_bytes()
        _static_version = (
            hashlib.md5(_hash_data).hexdigest()[:12] if _hash_data else "dev"
        )
        self._jinja_env.env.globals["static_version"] = _static_version

        # Theme config globals
        self._jinja_env.env.globals["theme_preset"] = "editorial"
        if self.config.ui.theme:
            self._jinja_env.env.globals["theme_css"] = (
                self.config.ui.theme.to_css_variables()
            )
            self._jinja_env.env.globals["theme_font_import_url"] = (
                self.config.ui.theme.font_import_url
            )
            self._jinja_env.env.globals["theme_preset"] = (
                self.config.ui.theme.preset
            )
        self._jinja_env.env.globals["ui_config"] = (
            self.config.ui.apply_to_template_context()
        )

        app.state.admin_jinja_env = self._jinja_env

    def _build_router(self, app: FastAPI) -> None:
        """Build and mount routers for all registered models."""
        if self._router_built:
            return

        from fastapi_admin_kit.auth.router import router as auth_router
        from fastapi_admin_kit.router import build_model_router
        from fastapi_admin_kit.views.audit import router as audit_router
        from fastapi_admin_kit.views.profile import router as profile_router
        from fastapi_admin_kit.views.roles import router as roles_router
        from fastapi_admin_kit.views.settings import router as settings_router
        from fastapi_admin_kit.views.totp import router as totp_router
        from fastapi_admin_kit.views.users import router as users_router

        for registered in self.registry.all():
            if getattr(registered.admin, "skip_auto_routes", False):
                continue
            model_router = build_model_router(registered)
            app.include_router(model_router, prefix=self.router.admin_path)

        # Auth routes (login/logout)
        app.include_router(auth_router, prefix=self.router.admin_path)

        # Global search API
        from fastapi_admin_kit.api.search import router as search_api_router

        app.include_router(search_api_router, prefix=self.router.admin_path)

        # Audit, role management, settings, user management, profile, and 2FA routes
        app.include_router(audit_router, prefix=self.router.admin_path)
        app.include_router(roles_router, prefix=self.router.admin_path)
        app.include_router(settings_router, prefix=self.router.admin_path)
        app.include_router(users_router, prefix=self.router.admin_path)
        app.include_router(profile_router, prefix=self.router.admin_path)
        app.include_router(totp_router, prefix=self.router.admin_path)

        # Dashboard route
        from fastapi_admin_kit.views.dashboard import dashboard_view_factory

        dashboard_view = dashboard_view_factory(self)
        app.add_api_route(
            self.router.admin_path,
            dashboard_view,
            methods=["GET"],
            tags=["admin"],
        )

        # JSON API for external frontend apps
        from fastapi_admin_kit.api import AdminAPIRouter

        api_router = AdminAPIRouter(registry=self.registry)
        app.include_router(api_router.build_router())

        self._router_built = True

    # ------------------------------------------------------------------
    # Built-in model registration
    # ------------------------------------------------------------------

    def _register_builtin_models(self) -> None:
        """Auto-register built-in admin models with default admin classes."""
        from fastapi_admin_kit.admin.builtin_models import (
            AdminLoginAttemptAdmin,
            AdminPermissionAdmin,
            AdminRefreshTokenAdmin,
            AdminRoleAdmin,
            AdminUserAdmin,
            AdminUserPermissionAdmin,
            AdminUserTOTPAdmin,
            AuditLogAdmin,
        )
        from fastapi_admin_kit.audit.models import AuditLog
        from fastapi_admin_kit.auth.models import (
            AdminLoginAttempt,
            AdminPermission,
            AdminRefreshToken,
            AdminRole,
            AdminUser,
            AdminUserPermission,
            AdminUserTOTP,
        )

        builtin_models = [
            (AdminUser, AdminUserAdmin),
            (AdminRole, AdminRoleAdmin),
            (AdminRefreshToken, AdminRefreshTokenAdmin),
            (AdminPermission, AdminPermissionAdmin),
            (AdminUserPermission, AdminUserPermissionAdmin),
            (AdminUserTOTP, AdminUserTOTPAdmin),
            (AdminLoginAttempt, AdminLoginAttemptAdmin),
            (AuditLog, AuditLogAdmin),
        ]

        for model, admin_class in builtin_models:
            if model.__tablename__ not in self.registry._models:
                self.registry.register(model, admin_class)

    # ------------------------------------------------------------------
    # Tags validation
    # ------------------------------------------------------------------

    def _validate_tags(self) -> None:
        """Raise ConfigError if any registered model has no tag (when require_tags=True)."""
        untagged: list[str] = []
        for registered in self.registry.all():
            admin = registered.admin
            tags = getattr(admin, "tags", None)
            tag = getattr(admin, "tag", None)
            if not tags and not tag:
                untagged.append(registered.table_name)
        if untagged:
            raise ConfigError(
                "require_tags=True but the following models have no tag: "
                + ", ".join(sorted(untagged))
            )

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------

    def _build_sidebar(self) -> list:
        """Build the sidebar group structure once at startup."""
        from fastapi_admin_kit.nav import DefaultSidebarBuilder

        builder = self.config.nav.sidebar_builder or DefaultSidebarBuilder()
        return builder.build(
            self.registry.all(),
            self.config.nav.nav_groups,
            admin_path=self.router.admin_path,
        )

    def build_sidebar_context(
        self,
        request: Any,
        user: Any = None,
        permissions_map: dict | None = None,
    ) -> dict:
        """Build per-request sidebar context (RBAC filter + permissions map)."""
        return self.template.build_sidebar_context(
            request, user=user, permissions_map=permissions_map
        )

    def sidebar_template_kwargs(self, request: Any) -> dict[str, Any]:
        """Thin wrapper — returns sidebar kwargs for TemplateResponse contexts."""
        return self.template.sidebar_template_kwargs(request)

    def apply_sidebar_context(
        self, request: Any, user: Any, context: dict
    ) -> dict:
        """Inject nav_groups + permissions_map into a template context dict."""
        return self.template.apply_sidebar_context(request, user, context)
