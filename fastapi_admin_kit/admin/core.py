"""Admin class — public API, wires everything at init."""

from __future__ import annotations

import logging
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
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.config import (
    AIChatConfig,
    AuditConfig,
    AuthConfig,
    BehaviorConfig,
    CacheConfig,
    DatabaseConfig,
    NavConfig,
    StorageConfig,
    ThemeConfig,
    UIConfig,
)
from fastapi_admin_kit.exceptions import ConfigError
from fastapi_admin_kit.registry import AdminRegistry, RegisteredModel
from fastapi_admin_kit.schemas.builtin import (
    AI_TABLE_NAMES,
    INTERNAL_TABLE_NAMES,
    NOTIFICATION_TABLE_NAMES,
)
from fastapi_admin_kit.types import SeedRole

if TYPE_CHECKING:
    from fastapi_admin_kit.auth.backend import AuthBackend
    from fastapi_admin_kit.nav import NavGroupConfig, SidebarBuilder
    from fastapi_admin_kit.storage.base import StorageBackend
    from fastapi_admin_kit.views import ModelAdmin

logger = logging.getLogger(__name__)


def _merge_legacy_kwargs_into_config(
    config: AdminConfig,
    *,
    ui: dict[str, Any],
    auth: dict[str, Any],
    audit: dict[str, Any],
    behavior: dict[str, Any],
    storage: dict[str, Any],
    nav: dict[str, Any],
    cache: dict[str, Any] | None = None,
) -> AdminConfig:
    """Merge explicitly-provided legacy Admin() kwargs into a user-supplied config.

    When the caller passes both a full ``AdminConfig`` *and* legacy keyword
    arguments (e.g. ``title=``, ``auth_backend=``), the legacy kwargs must not be
    silently dropped. Each value is applied to the config only when the config's
    corresponding field is still at its own default — so an explicitly
    configured ``config.ui`` / ``config.auth`` always wins over a legacy default.
    """
    import inspect

    # Helper: apply legacy values for a sub-config, skipping anything that
    # matches the sub-config's own default.
    def _merge(sub_config: Any, legacy_values: dict[str, Any]) -> None:
        try:
            defaults = {
                name: param.default
                for name, param in inspect.signature(sub_config.__class__).parameters.items()
                if param.default is not inspect.Parameter.empty
            }
        except Exception:
            defaults = {}
        for key, value in legacy_values.items():
            if key not in defaults:
                continue
            current = getattr(sub_config, key, None)
            if current == defaults[key]:
                setattr(sub_config, key, value)

    _merge(config.ui, ui)
    _merge(config.auth, auth)
    _merge(config.audit, audit)
    _merge(config.behavior, behavior)
    _merge(config.storage, storage)
    _merge(config.nav, nav)
    if cache is not None:
        _merge(config.cache, cache)
    return config


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
        engine: Any | None = None,
        database_config: DatabaseConfig | None = None,
        *,
        # Component instances (new API)
        config: AdminConfig | None = None,
        database: AdminDatabase | None = None,
        router: AdminRouter | None = None,
        template: AdminTemplate | None = None,
        backend: Any | None = None,
        # Legacy kwargs for backward compatibility
        base: type | None = None,
        title: str = "FastAPI Admin Kit",
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
        auth_backend: AuthBackend | None = BuiltinAuthBackend(),
        session_cookie_name: str = "admin_session",
        session_secure: bool = True,
        session_samesite: str = "strict",
        access_token_ttl: int = 600,
        api_token_middleware: bool = True,
        api_token_strict: bool = False,
        trusted_proxies: list[str] | None = None,
        seed_roles: list[SeedRole] | None = None,
        seed_roles_overwrite: bool = False,
        superuser_emails: list[str] | None = None,
        storage: StorageBackend | None = None,
        uploads_url: str = "/uploads",
        auto_discover: bool = True,
        skip_models: list[str] | None = None,
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
        # AI
        ai: Any = None,
        ai_enabled: bool = False,
        is_development: bool = False,
        sidebar_bottom_links: list[dict[str, str]] | None = None,
        # Notifications
        enable_notification: bool = True,
        notification_service: Any | None = None,
        notifications_api_path: str | None = None,
        notifications_list_path: str | None = None,
        # AI chat file attachments
        ai_chat_max_file_size_mb: int = 10,
        ai_chat_allowed_extensions: list[str] | None = None,
        # Optional Redis-backed caching (opt-in)
        cache_enabled: bool | None = None,
        cache_ttl: int | None = None,
    ):
        self.registry = AdminRegistry()
        self._app: FastAPI | None = app

        # Expose the instance on app.state immediately so plugins (e.g.
        # configure_notifications) can reach the admin before admin.setup()
        # runs — _wire_app_state() overwrites the same slot at setup time.
        if app is not None:
            app.state.admin = self

        # Add CSRF middleware early (must be before app starts)
        if app is not None:
            from fastapi_admin_kit.auth.csrf import (
                CSRFMiddleware,
                auth_redirect_handler,
                forbidden_handler,
            )

            app.add_exception_handler(401, auth_redirect_handler)
            app.add_exception_handler(403, forbidden_handler)
            app.add_middleware(CSRFMiddleware)
            self._csrf_middleware_added = True

            # API bearer-token pre-validation. Added BEFORE SessionMiddleware
            # so it runs inside it (Starlette: last added = outermost) and can
            # use the per-request DB session to resolve the live user.
            from fastapi_admin_kit.api.middleware import AccessTokenMiddleware

            app.add_middleware(AccessTokenMiddleware)
            self._api_token_middleware_added = True

            # Register the per-request session + audit-context middlewares here
            # (at construction time) rather than in ``setup()``. Starlette builds
            # ``app.middleware_stack`` on the *first* scope it receives — which is
            # the lifespan startup event that fires *before* ``setup()`` runs. If
            # these middlewares were only added in ``setup()``, the stack would
            # already be frozen and ``add_middleware`` would raise ``RuntimeError``
            # (silently swallowed), leaving the session middleware out of the live
            # stack. Without it, DB writes are flushed but never committed.
            from fastapi_admin_kit.audit.middleware import (
                AuditContextMiddleware,
            )
            from fastapi_admin_kit.db import SessionMiddleware

            app.add_middleware(SessionMiddleware)
            self._session_middleware_added = True
            app.add_middleware(AuditContextMiddleware)
            self._audit_middleware_added = True
        else:
            self._csrf_middleware_added = False
            self._api_token_middleware_added = False
            self._session_middleware_added = False
            self._audit_middleware_added = False

        # Default auth backend if none provided
        if auth_backend is None:
            from fastapi_admin_kit.auth.backend import BuiltinAuthBackend

            auth_backend = BuiltinAuthBackend()

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
                    access_token_ttl=access_token_ttl,
                    api_token_middleware=api_token_middleware,
                    api_token_strict=api_token_strict,
                    trusted_proxies=trusted_proxies,
                ),
                audit=AuditConfig(audit_retention_days=audit_retention_days),
                behavior=BehaviorConfig(
                    auto_discover=auto_discover,
                    skip_models=skip_models,
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
                    sidebar_bottom_links=sidebar_bottom_links,
                ),
                ai_chat=AIChatConfig(
                    max_file_size_mb=ai_chat_max_file_size_mb,
                    allowed_extensions=ai_chat_allowed_extensions
                    or [
                        ".pdf",
                        ".xlsx",
                        ".xls",
                        ".docx",
                        ".doc",
                        ".csv",
                        ".png",
                        ".jpg",
                        ".jpeg",
                        ".gif",
                        ".webp",
                    ],
                ),
                cache=CacheConfig(enabled=cache_enabled, ttl=cache_ttl),
            )
        else:
            config = _merge_legacy_kwargs_into_config(
                config,
                ui=dict(
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
                auth=dict(
                    auth_model=auth_model,
                    auth_backend=auth_backend,
                    session_ttl=session_ttl,
                    session_cookie_name=session_cookie_name,
                    session_secure=session_secure,
                    superuser_emails=superuser_emails,
                    session_samesite=session_samesite,
                    access_token_ttl=access_token_ttl,
                    api_token_middleware=api_token_middleware,
                    api_token_strict=api_token_strict,
                    trusted_proxies=trusted_proxies,
                ),
                audit=dict(audit_retention_days=audit_retention_days),
                behavior=dict(
                    auto_discover=auto_discover,
                    skip_models=skip_models,
                    dashboard_stats=dashboard_stats or [],
                    dashboard_charts=dashboard_charts,
                ),
                storage=dict(storage=storage, uploads_url=uploads_url),
                nav=dict(
                    nav_groups=nav_groups or [],
                    sidebar_builder=sidebar_builder,
                    require_tags=require_tags,
                    dashboard_permission=dashboard_permission,
                    settings_permission=settings_permission,
                    sidebar_bottom_links=sidebar_bottom_links,
                ),
                cache=dict(enabled=cache_enabled, ttl=cache_ttl),
            )
            # The merge helper compares against CacheConfig's *constructor*
            # defaults, but the default instance already resolved the env
            # flag at construction — so apply explicit enabled/ttl overrides.
            if cache_enabled is not None:
                config.cache.enabled = cache_enabled
            if cache_ttl is not None:
                config.cache.ttl = cache_ttl

        if database is None:
            database = AdminDatabase(
                engine=engine,
                base=base,
                database_config=database_config,
                use_alembic=config.behavior.use_alembic,
            )

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
                sidebar_bottom_links=config.nav.sidebar_bottom_links,
                template_dirs=config.template_dirs,
            )

        self.config = config
        self.database = database
        self.router = router
        self.template = template
        self.cache_config = config.cache

        # Redis availability flags (populated by _setup_redis).
        self.redis_enabled = False
        self.redis_configured = False
        self._redis_wired = False

        # Store notification paths on config for template access
        default_notifications_path = f"{self.router.admin_path}/notifications"
        default_notifications_list = f"{self.router.admin_path}/admin_notifications/"
        self.config.notifications_api_path = notifications_api_path or default_notifications_path
        self.config.notifications_list_path = notifications_list_path or default_notifications_list

        # Notifications: auto-wire a service in setup() unless the user has
        # configured one already (e.g. via configure_notifications).
        self._enable_notification = enable_notification
        self._notification_service = notification_service

        # Backend: defaults to composed SqlAlchemyBackend
        if backend is None:
            from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyBackend

            backend = SqlAlchemyBackend.from_admin_database(database)
        self.backend = backend

        # Wire the AdminDatabase (engine/base/config) into the backend's
        # DatabaseBackend adapter.  When a backend is supplied standalone
        # (e.g. ``backend=SqlAlchemyBackend()``) its ``database`` adapter has no
        # engine reference, so ``create_connection()``/``create_session_factory()``
        # would fail.  ``from_admin_database`` already sets this; we only fill it
        # in when it is missing so a user-provided backend still works.
        backend_database = getattr(self.backend, "database", None)
        if (
            backend_database is not None
            and getattr(backend_database, "_admin_database", None) is None
        ):
            backend_database._admin_database = database

        # Inject backend into the auth backend so BuiltinAuthBackend can build
        # queries via QueryBackend instead of importing sqlalchemy directly.
        _auth_backend = getattr(getattr(self, "config", None), "auth", None)
        _auth_backend = getattr(_auth_backend, "auth_backend", None) if _auth_backend else None
        if _auth_backend is not None:
            for attr, value in (
                ("_backend", self.backend),
                ("backend", self.backend),
                ("_query_backend", getattr(self.backend, "query", None)),
                ("query_backend", getattr(self.backend, "query", None)),
            ):
                try:
                    setattr(_auth_backend, attr, value)
                except Exception:
                    pass

        # Inject backend's introspection adapter into the registry's ModelInspector
        self.registry.inspector._adapter = self.backend.introspection

        # RBAC
        self.seed_roles = seed_roles if seed_roles is not None else DEFAULT_SEED_ROLES
        self.seed_roles_overwrite = seed_roles_overwrite

        # Built sidebar (populated during setup)
        self._nav_groups_built: list[Any] = []

        # AI
        if ai_enabled and ai is None:
            from fastapi_admin_kit.ai.config import AIConfig

            ai = AIConfig()
        self._ai_config = ai
        self._ai_enabled = ai_enabled
        self.is_development = is_development

        # Internal state (populated during setup)
        self._session_backend: Any = None
        self._jinja_env: Environment | None = None
        self._router_built: bool = False

        # Wire Redis now (before startup) so the SDK can wrap the lifespan
        # before it begins. Degrades gracefully when Redis is unavailable.
        if app is not None:
            self._setup_redis(app)

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
    def engine(self) -> Any | None:
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

        self.database._ensure_engine()

        if self.database.engine is None:
            raise ConfigError(
                "Admin requires a SQLAlchemy engine. Pass engine= or database_config= to Admin()."
            )

        app = self._app

        # Wire Redis when the app was supplied after construction (e.g. via
        # ``await admin.setup(app)`` inside a manual lifespan).
        if not getattr(self, "_redis_wired", False):
            self._setup_redis(app)

        # Add CSRF middleware if not already added in __init__
        if not getattr(self, "_csrf_middleware_added", False):
            from fastapi_admin_kit.auth.csrf import (
                CSRFMiddleware,
                auth_redirect_handler,
                forbidden_handler,
            )

            try:
                app.add_exception_handler(401, auth_redirect_handler)
                app.add_exception_handler(403, forbidden_handler)
                app.add_middleware(CSRFMiddleware)
            except RuntimeError:
                pass  # Already started — middleware was added in __init__

        # Add API bearer-token middleware if not already added in __init__
        if not getattr(self, "_api_token_middleware_added", False):
            from fastapi_admin_kit.api.middleware import AccessTokenMiddleware

            try:
                app.add_middleware(AccessTokenMiddleware)
                self._api_token_middleware_added = True
            except RuntimeError:
                app.middleware_stack = None
                app.add_middleware(AccessTokenMiddleware)
                self._api_token_middleware_added = True

        # Add per-request session middleware
        if app is not None and not getattr(self, "_session_middleware_added", False):
            from fastapi_admin_kit.db import SessionMiddleware

            try:
                app.add_middleware(SessionMiddleware)
                self._session_middleware_added = True
            except RuntimeError:
                # Stack already built (e.g. the lifespan startup scope). Force a
                # rebuild on the next request so the middleware is included.
                app.middleware_stack = None
                app.add_middleware(SessionMiddleware)
                self._session_middleware_added = True

        # Add audit context middleware
        if app is not None and not getattr(self, "_audit_middleware_added", False):
            from fastapi_admin_kit.audit.middleware import (
                AuditContextMiddleware,
            )

            try:
                app.add_middleware(AuditContextMiddleware)
                self._audit_middleware_added = True
            except RuntimeError:
                app.middleware_stack = None
                app.add_middleware(AuditContextMiddleware)
                self._audit_middleware_added = True

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
        #    ``create_tables()`` is the public entry point that projects can
        #    also call from their lifespan before ``admin.setup(app)`` —
        #    using it here keeps both code paths in sync (and is the only
        #    way the custom-auth_model skip is applied).
        await self.create_tables()

        # 2.1 Preflight: if AI is enabled but the tables are genuinely missing
        # (Alembic / SKIP_CREATE_TABLES mode), warn loudly but never block boot.
        if self._ai_enabled:
            try:
                missing = await self.database._missing_tables(
                    self._ai_enabled, list(AI_TABLE_NAMES)
                )
            except Exception:  # pragma: no cover - inspector failures must not block boot
                missing = set()
            if missing:
                logger.warning(
                    "ai_enabled=True but these tables are missing: %s. "
                    "AI chat/usage tracking will fail until the schema is migrated — run "
                    "`alembic revision --autogenerate && alembic upgrade head` "
                    "(or `fak migrate admin_ai_conversations` in dev mode).",
                    ", ".join(sorted(missing)),
                )

        # 3. Seed default roles
        await self.database._seed_roles(self.seed_roles, self.seed_roles_overwrite)

        # 4. Create and store session backend
        self._session_backend = self.database._init_session_backend(
            secret_key=self.router.secret_key,
            session_ttl=self.config.auth.session_ttl,
            cookie_name=self.config.auth.session_cookie_name,
            secure=self.config.auth.session_secure,
        )

        # 5. Store backends and config on app.state
        self._wire_app_state(app)

        # 5.1 Auto-wire the notification system (mount router + service on
        # app.state) unless the user configured it manually already.
        self._setup_notifications(app)

        # 6. Mount static files
        self._mount_static(app)

        # 7. Initialise Jinja2
        self._init_jinja(app)

        # 8. Auto-register built-in admin models (before auto_discover)
        self._register_builtin_models()

        # 8.1 Auto-discover user models
        if self.config.behavior.auto_discover:
            self.registry.auto_discover(exclude_tables=self._excluded_builtin_tables())

        # 8.2 Apply skip_models — mark listed models to hide from admin
        skip_models = self.config.behavior.skip_models
        # Built-in internal models are always hidden from admin
        # Note: model class names match table names (e.g., admin_refresh_tokens)
        default_skip = {"admin_refresh_tokens", "admin_user_permissions", "admin_user_totp"}
        all_skip = default_skip | skip_models | self._excluded_builtin_tables()
        skip_lower = {s.lower() for s in all_skip}
        for registered in self.registry.all():
            model_name = getattr(registered.model, "__name__", "").lower()
            if model_name in skip_lower:
                registered.admin.skip_auto_routes = True

        # 8.3 Attach audit event listeners (after registry is populated)
        session_factory = getattr(app.state, "admin_session_factory", None)
        if session_factory is not None:
            self.backend.audit.attach_listeners(session_factory, self.registry)

        # 9. Validate require_tags
        if self.config.nav.require_tags:
            self._validate_tags()

        # 9.1 Add AI nav group before building sidebar
        if self._ai_enabled:
            self._add_ai_nav_group()

        # 10. Build sidebar structure (once at startup)
        self._nav_groups_built = self._build_sidebar()
        self.template._nav_groups_built = self._nav_groups_built
        if self._jinja_env:
            self._jinja_env.env.globals["nav_groups"] = self._nav_groups_built

        # 11. Build and mount routers
        self._build_router(app)

        # 12. Setup AI routes if enabled
        if self._ai_enabled:
            self._setup_ai_routes(app)

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
            self._jinja_env.env.globals["registered_models"] = self.registry.all()
            if self._nav_groups_built:
                self._nav_groups_built = self._build_sidebar()
                self.template._nav_groups_built = self._nav_groups_built
                self._jinja_env.env.globals["nav_groups"] = self._nav_groups_built
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

            from fastapi_admin_kit.auth.models import User
            from fastapi_admin_kit.admin.builtin_models import UserAdmin

            class MyUserAdmin(UserAdmin):
                list_display = ["id", "email", "full_name"]

            admin.unregister(User)
            admin.register(User, MyUserAdmin)
        """
        table_name = model.__tablename__
        self.registry._models.pop(table_name, None)

    # ------------------------------------------------------------------
    # Internal wiring
    # ------------------------------------------------------------------

    def _setup_redis(self, app: FastAPI) -> None:
        """Wire the optional Redis-backed caching/rate-limiting integration.

        Checks ``REDIS_URL`` at startup: when present (and the
        ``fastapi-redis-sdk`` is installed) the SDK's lifespan wrapper plus
        caching/rate-limiting support are registered on the app. Otherwise the
        admin falls back to the existing in-memory rate limiter and no cache
        middleware — full backward compatibility.
        """
        if self._redis_wired:
            return
        self._redis_wired = True

        from fastapi_admin_kit.redis import (
            redis_configured,
            redis_enabled,
            setup_redis,
        )

        self.redis_configured = redis_configured()
        self.redis_enabled = redis_enabled()

        if not self.redis_enabled:
            return

        setup_redis(
            app,
            cache_enabled=self.cache_config.enabled,
            cache_ttl=self.cache_config.ttl,
            rate_limiting=True,
        )

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
            "access_token_ttl": self.config.auth.access_token_ttl,
            "api_token_middleware": self.config.auth.api_token_middleware,
            "api_token_strict": self.config.auth.api_token_strict,
            "trusted_proxies": self.config.auth.trusted_proxies,
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
        connection = None
        engine = self.database.engine
        if engine is not None:
            connection = self.backend.database.create_connection()
            session_factory = self.backend.database.create_session_factory(connection)
            # Legacy fallback — a single session for backward compat. It is a
            # backend-agnostic SessionBackend, exactly like the per-request one.
            db_session = session_factory()

        # Inject auth_model and backend into the auth backend for ORM-agnostic queries.
        # BuiltinAuthBackend uses the QueryBackend (select/where/options) and the
        # DatabaseBackend's session_adapter_class via as_session_backend, so it
        # must not import sqlalchemy directly.
        if self.config.auth.auth_backend is not None:
            if self.config.auth.auth_model is not None:
                try:
                    self.config.auth.auth_backend._auth_model = self.config.auth.auth_model
                except AttributeError:
                    pass
            # Wire the composite backend and its query adapter — supports both
            # BuiltinAuthBackend (stores _backend/_query_backend) and any
            # custom backend that exposes the same attributes.
            for attr, value in (
                ("_backend", self.backend),
                ("backend", self.backend),
                ("_query_backend", getattr(self.backend, "query", None)),
                ("query_backend", getattr(self.backend, "query", None)),
            ):
                try:
                    setattr(self.config.auth.auth_backend, attr, value)
                except Exception:
                    pass

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
            backend=self.backend,
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
        # Multi-ORM backend: store composed backend and derive individual adapters
        app.state.admin_backend = self.backend
        app.state.admin_connection = connection
        app.state.admin_session_backend_class = self.backend.database.session_adapter_class
        app.state.admin_query_adapter = self.backend.query
        app.state.admin_introspection_adapter = self.backend.introspection
        app.state.admin_audit_backend = self.backend.audit

        # Wire the password hasher to the User model
        from fastapi_admin_kit.auth.models import User

        User.set_hasher(self.config.auth.get_hasher())

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
                StaticFiles(directory=str(self.config.storage.storage.upload_dir)),
                name="admin_uploads",
            )

    def _init_jinja(self, app: FastAPI) -> None:
        """Initialise the Jinja2 template environment.

        User-provided template dirs (from AdminConfig.template_dirs) are
        prepended so custom templates override built-in ones.
        """
        from starlette.templating import Jinja2Templates

        templates_dir = Path(__file__).parent.parent / "templates"
        user_dirs = list(getattr(self.template, "template_dirs", None) or [])
        all_dirs = [str(d) for d in user_dirs] + [str(templates_dir)]
        self._jinja_env = Jinja2Templates(directory=all_dirs)

        # Enable autoescape for XSS protection
        self._jinja_env.env.autoescape = True

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
        self._jinja_env.env.globals["notifications_api_path"] = getattr(
            self.config, "notifications_api_path", f"{self.router.admin_path}/notifications"
        )
        self._jinja_env.env.globals["notifications_list_path"] = getattr(
            self.config, "notifications_list_path", f"{self.router.admin_path}/admin_notifications/"
        )
        self._jinja_env.env.globals["notifications_enabled"] = self._enable_notification
        self._jinja_env.env.globals["nav_groups"] = self._nav_groups_built

        # CSRF token helper — reads from request.state (set by CSRFMiddleware)
        def _get_csrf_token(request) -> str:
            return getattr(request.state, "csrf_token", "")

        self._jinja_env.env.globals["get_csrf_token"] = _get_csrf_token

        # Flash messages helper (reads from session cookie directly)
        def _get_flash_messages(request) -> list[dict[str, str]]:
            try:
                session_backend = request.app.state.admin_session_backend
                cookie_name = getattr(session_backend, "cookie_name", "admin_session")
                raw = request.cookies.get(cookie_name)
                if not raw or not hasattr(session_backend, "load"):
                    return []
                data = session_backend.load(raw)
                if not isinstance(data, dict):
                    return []
                return data.pop("admin_flash", []) if "admin_flash" in data else []
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
            "arrow-up-tray": "upload",
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
            "smart_toy": "smart_toy",
            "monitoring": "monitoring",
            "build": "build",
            "sparkles": "auto_awesome",
            "robot": "smart_toy",
        }

        def _icon(name: str, size: str = "", **kwargs) -> str:
            from markupsafe import Markup

            ms_name = _icon_map.get(name, name)
            css_class = kwargs.get("class", kwargs.get("css_class", ""))
            size_style = f' style="font-size: {size};"' if size else ""
            cls = f"material-symbols-outlined {css_class}".strip()
            return Markup(f'<span class="{cls}"{size_style}>{ms_name}</span>')

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
            "ai_enabled": self._ai_enabled,
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
        _static_version = hashlib.md5(_hash_data).hexdigest()[:12] if _hash_data else "dev"
        self._jinja_env.env.globals["static_version"] = _static_version

        # Theme config globals
        self._jinja_env.env.globals["theme_preset"] = "editorial"
        if self.config.ui.theme:
            self._jinja_env.env.globals["theme_css"] = self.config.ui.theme.to_css_variables()
            self._jinja_env.env.globals["theme_font_import_url"] = (
                self.config.ui.theme.font_import_url
            )
            self._jinja_env.env.globals["theme_preset"] = self.config.ui.theme.preset
        self._jinja_env.env.globals["ui_config"] = self.config.ui.apply_to_template_context()

        app.state.admin_jinja_env = self._jinja_env

    def _setup_notifications(self, app: FastAPI) -> None:
        """Auto-wire the notification system into the admin.

        When ``enable_notification=True`` (the default) the admin creates a
        default :class:`NotificationService`, registers it on ``app.state``
        and mounts the notification router at the configured API path — so
        users do **not** need to call ``configure_notifications`` themselves.

        A service already configured by the user (via
        ``configure_notifications()`` or ``Admin(notification_service=...)``)
        is respected and never double-mounted.
        """
        if not self._enable_notification:
            return
        if getattr(app.state, "notification_service", None) is not None:
            return

        from fastapi_admin_kit.notifications.plugin import configure_notifications
        from fastapi_admin_kit.notifications.service import NotificationService

        service = self._notification_service
        if service is None:
            session_factory = getattr(app.state, "admin_session_factory", None)
            service = NotificationService(session_factory=session_factory)
            self._notification_service = service

        configure_notifications(app, service, prefix=self.config.notifications_api_path)

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
            # API-only models (export_endpoint="api") get no admin HTML router.
            if getattr(registered.admin, "export_endpoint", None) == "api":
                continue
            model_router = build_model_router(registered, cache_config=self.cache_config)
            if model_router is None:
                continue
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
            include_in_schema=False,
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
            # UserPermissionAdmin,
            # UserTOTPAdmin,
            AuditLogAdmin,
            LoginAttemptAdmin,
            NotificationAdmin,
            NotificationLogAdmin,
            NotificationPreferenceAdmin,
            PermissionAdmin,
            RoleAdmin,
            UserAdmin,
        )
        from fastapi_admin_kit.migrations.models import (
            AuditLog,
            LoginAttempt,
            Notification,
            NotificationLog,
            NotificationPreference,
            Permission,
            Role,
            User,
        )

        if self._ai_enabled:
            from fastapi_admin_kit.admin.builtin_models import (
                AIConversationAdmin,
                AIMessageAdmin,
                AIUsageLogAdmin,
            )
            from fastapi_admin_kit.migrations.models import (
                AIConversation,
                AIMessage,
                AIUsageLog,
            )

        builtin_models = [
            (Role, RoleAdmin),
            # (RefreshToken, RefreshTokenAdmin),
            (Permission, PermissionAdmin),
            # (UserPermission, UserPermissionAdmin),
            # (UserTOTP, UserTOTPAdmin),
            (LoginAttempt, LoginAttemptAdmin),
            (AuditLog, AuditLogAdmin),
        ]

        # When a custom auth_model is provided, the built-in ``User`` model is
        # not registered: the project supplies its own user model and
        # ``UserAdmin`` (the built-in CRUD) does not match it. Skipping here
        # also keeps the registry consistent with the migration metadata, from
        # which the built-in ``admin_users`` table is removed in
        # ``_adapt_builtin_user_id_columns`` when a custom auth_model is set.
        from fastapi_admin_kit.migrations.models import User as BuiltinUser

        if self.config.auth.auth_model is None or self.config.auth.auth_model is BuiltinUser:
            builtin_models.insert(0, (User, UserAdmin))

        # Notification models are exposed under the "notifications" sidebar
        # group. Register them only when notifications are enabled so the
        # group never appears when enable_notification=False.
        if self._enable_notification:
            builtin_models += [
                (Notification, NotificationAdmin),
                (NotificationPreference, NotificationPreferenceAdmin),
                (NotificationLog, NotificationLogAdmin),
            ]

        for model, admin_class in builtin_models:
            if model.__tablename__ not in self.registry._models:
                self.registry.register(model, admin_class)

        if self._ai_enabled:
            ai_builtin_models = [
                (AIConversation, AIConversationAdmin),
                (AIMessage, AIMessageAdmin),
                (AIUsageLog, AIUsageLogAdmin),
            ]
            for model, admin_class in ai_builtin_models:
                if model.__tablename__ not in self.registry._models:
                    self.registry.register(model, admin_class)

    def _builtin_user_tables_to_skip(self) -> tuple[str, ...]:
        """Return the names of built-in tables that should NOT be created when
        a custom ``auth_model`` is configured.

        When the project supplies its own user model (``auth_model=``), the
        built-in ``admin_users`` table is skipped — the custom auth_model
        is the source of truth for user identity. ``admin_user_roles`` is
        kept and its ``user_id`` foreign key is retargeted to the custom
        auth_model's table at create time (see
        ``SqlAlchemyDatabaseBackend.adapt_auth_model``) so the junction
        links roles to the project's own user rows.

        The role/permission system (``admin_roles``,
        ``admin_role_permissions``, ``admin_permissions``) is kept so the
        admin can still manage granular per-table access.

        Returns an empty tuple when the built-in ``User`` is in use (default
        installation) or when no ``auth_model`` is configured.
        """
        from fastapi_admin_kit.migrations.models import User as BuiltinUser

        auth_model = self.config.auth.auth_model
        if auth_model is None or auth_model is BuiltinUser:
            return ()
        return ("admin_users",)

    async def create_tables(self) -> None:
        """Create all admin database tables, correctly handling a custom
        ``auth_model``.

        This is the public API projects should use in their ``lifespan`` (or
        startup hook) instead of calling
        ``AdminBase.metadata.create_all`` directly. Calling
        ``AdminBase.metadata.create_all`` directly bypasses the
        custom-auth_model logic and will create the default
        ``admin_users`` / ``admin_user_roles`` tables even when a project
        supplies its own user model.

        What this method does, in order:

        1. Validate the configured ``auth_model`` (raises ``ConfigError`` if
           it does not satisfy :class:`AdminUserProtocol`).
        2. Mirror the auth model's primary-key type onto the built-in
           log-pattern ``user_id`` columns (e.g. a UUID PK becomes a UUID
           ``user_id`` so the column type matches across tables).
        3. Call ``AdminDatabase._create_tables(extra_exclude_tables=...)``
           with the built-in user tables filtered out when a custom
           ``auth_model`` is configured. Honors ``SKIP_CREATE_TABLES=true``
           and the AI / notification feature flags exactly like
           ``Admin.setup()`` does.
        """
        self.config.auth.validate_auth_model()
        skip_create_tables = os.environ.get("SKIP_CREATE_TABLES", "false").lower() == "true"
        if skip_create_tables:
            logger.info("SKIP_CREATE_TABLES=true: skipping admin table creation")
            return
        self._adapt_builtin_user_id_columns()
        # Ask the configured backend to retarget the built-in user
        # relations (admin_user_roles FK, Role.users M2M, etc.) at the
        # custom auth_model. Each backend implements this against its own
        # ORM primitives; non-SQLA backends may no-op.
        #
        # Use ``self.database._backend`` (the backend that actually performs
        # DDL in ``_create_tables`` below) rather than the composite
        # ``self.backend.database`` so tests that swap
        # ``admin.database._backend`` with a fake do not mutate the global
        # SQLAlchemy mapper state. A backend without ``adapt_auth_model``
        # (e.g. a test fake or memory backend) is treated as no-op.
        database_backend = getattr(self.database, "_backend", None)
        adapt = getattr(database_backend, "adapt_auth_model", None)
        if adapt is not None and self.config.auth.auth_model is not None:
            try:
                from fastapi_admin_kit.migrations.models import User as BuiltinUser

                if self.config.auth.auth_model is not BuiltinUser:
                    adapt(self.config.auth.auth_model)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("adapt_auth_model failed: %s", exc)
        extra_exclude = list(self._builtin_user_tables_to_skip())
        if extra_exclude:
            logger.info(
                "Custom auth_model=%s configured: skipping built-in admin "
                "tables %s at create_all (project supplies its own user "
                "table).",
                self.config.auth.auth_model,
                extra_exclude,
            )
        await self.database._create_tables(
            include_ai_tables=self._ai_enabled,
            extra_exclude_tables=extra_exclude or None,
        )

    def _adapt_builtin_user_id_columns(self) -> None:
        """
        Adapt the built-in log-pattern ``user_id`` columns in ``AdminBase.metadata``
        to match the primary-key type of the configured ``auth_model`` (see
        ``schemas/builtin.py``). When a project supplies a custom
        ``auth_model`` whose primary key differs from the built-in ``User``
        (e.g. a ``UUID`` PK), these columns are retyped to match so that
        ``metadata.create_all`` emits the correct DDL.

        This is a no-op for the default installation (``auth_model is None``
        or the built-in ``User``), which preserves backward compatibility
        and never alters existing schemas/migrations.

        When a custom ``auth_model`` is provided, the built-in ``admin_users``
        table is also removed from ``AdminBase.metadata`` (and the
        ``admin_user_roles`` junction) so that ``create_all`` does not emit
        DDL for the default schema. The custom user model — which must
        already be registered on a ``Base`` and present in the project's
        metadata — becomes the sole source of truth for the user table.
        """
        from fastapi_admin_kit.migrations.models import User as BuiltinUser

        auth_model = self.config.auth.auth_model
        if auth_model is None:
            return
        if auth_model is BuiltinUser:
            return

        metadata = BuiltinUser.__table__.metadata

        from sqlalchemy import inspect as sa_inspect

        pk_cols = sa_inspect(auth_model).primary_key
        if not pk_cols:
            return
        pk_col = pk_cols[0]
        new_type = pk_col.type
        logger.debug(
            "Adapting builtin user_id columns: auth_model=%s pk_col=%s pk_type=%r",
            auth_model,
            pk_col.name,
            new_type,
        )

        # user_email columns intentionally stay string (they store emails).
        log_tables = [
            "admin_audit_log",
            "admin_user_permissions",
            "admin_refresh_tokens",
            "admin_user_totp",
            "admin_notifications",
            "admin_notification_preferences",
            "admin_notification_logs",
            "admin_ai_usage_log",
            "admin_ai_conversations",
        ]
        for table_name in log_tables:
            table = metadata.tables.get(table_name)
            if table is None or "user_id" not in table.c:
                continue
            col = table.c["user_id"]
            logger.debug(
                "  %s.user_id: %r (%s) -> %r (%s)",
                table_name,
                col.type,
                type(col.type).__name__,
                new_type,
                type(new_type).__name__,
            )
            col.type = new_type

        # Note: the built-in ``admin_users`` table is excluded from
        # ``create_all`` at the call site in ``setup()`` via
        # ``AdminDatabase._create_tables(extra_exclude_tables=...)`` — we do
        # NOT remove it from ``AdminBase.metadata`` here because the
        # ``FacadeDict`` exposed by ``Base.metadata`` is immutable.
        #
        # FK retargeting on ``admin_user_roles`` and the ``Role.users`` M2M
        # re-binding are delegated to the configured backend via
        # ``backend.adapt_auth_model(auth_model)`` — this keeps ``core.py``
        # ORM-agnostic. Backends (SQLAlchemy) implement the actual column
        # and relationship mutations; memory/no-op backends can ignore.

        # Note: the built-in ``admin_users`` and ``admin_user_roles`` tables
        # are excluded from ``create_all`` at the call site in ``setup()`` via
        # ``AdminDatabase._create_tables(extra_exclude_tables=...)`` — we do
        # NOT remove them from ``AdminBase.metadata`` here because the
        # ``FacadeDict`` exposed by ``Base.metadata`` is immutable.

    # ------------------------------------------------------------------
    # AI Setup
    # ------------------------------------------------------------------

    def _excluded_builtin_tables(self) -> frozenset[str]:
        """Tables to hide from auto-discovery / default-skip lists.

        Always excludes internal tables (refresh tokens, user permissions,
        TOTP secrets, AI attachments). When AI is disabled, also excludes the
        three user-facing AI tables so they never leak into the sidebar/routes.
        When notifications are disabled, also excludes the notification tables
        so the "notifications" sidebar group never appears.

        When a custom ``auth_model`` is configured, also excludes the built-in
        ``admin_users`` model from auto-discovery (it is never created when a
        custom auth_model is set — see ``_builtin_user_tables_to_skip``). The
        ``admin_user_roles`` junction table is NOT excluded: it is kept and its
        ``user_id`` foreign key is retargeted to the custom auth_model's table
        so role relationships still work end-to-end.
        """
        excluded = set(INTERNAL_TABLE_NAMES)  # incl. admin_ai_attachments
        if not self._ai_enabled:
            excluded |= AI_TABLE_NAMES
        if not self._enable_notification:
            excluded |= NOTIFICATION_TABLE_NAMES
        if self._builtin_user_tables_to_skip():
            excluded |= {"admin_users"}
        return frozenset(excluded)

    def _add_ai_nav_group(self) -> None:
        """Add the AI nav group to nav_groups before sidebar build.

        Idempotent: skips if an ``ai`` group already exists (setup can run
        more than once, e.g. across tests).
        """
        from fastapi_admin_kit.nav import NavGroupConfig, NavItemConfig

        if any(g.tag == "ai" for g in self.config.nav.nav_groups):
            return

        ai_nav = NavGroupConfig(
            tag="ai",
            label="AI",
            icon="smart_toy",
            order=900,
            collapsed_by_default=False,
            extra_items=[
                NavItemConfig(
                    label="Chat",
                    url="/admin/ai/chat",
                    icon="chat",
                    order=1,
                ),
                NavItemConfig(
                    label="Dashboard",
                    url="/admin/ai/dashboard",
                    icon="monitoring",
                    order=2,
                ),
                NavItemConfig(
                    label="Logs",
                    url="/admin/ai/logs",
                    icon="description",
                    order=3,
                ),
                NavItemConfig(
                    label="Tools",
                    url="/admin/ai/tools",
                    icon="build",
                    order=4,
                ),
                NavItemConfig(
                    label="Agents",
                    url="/admin/ai/agents",
                    icon="smart_toy",
                    order=5,
                ),
            ],
        )
        self.config.nav.nav_groups.append(ai_nav)

    def _setup_ai_routes(self, app: FastAPI) -> None:
        """Initialize AI agents and mount AI routes."""
        from fastapi_admin_kit.ai.plugin import AIPlugin

        plugin = AIPlugin(agents=self._ai_config.agents if self._ai_config else [])
        plugin.on_startup(self)

        if self._ai_config and self._ai_config.dashboard_enabled:
            app.include_router(plugin.get_routes(), prefix=self.router.admin_path)

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

    async def build_sidebar_context(
        self,
        request: Any,
        user: Any = None,
        permissions_map: dict | None = None,
    ) -> dict:
        """Build per-request sidebar context (RBAC filter + permissions map)."""
        return await self.template.build_sidebar_context(
            request, user=user, permissions_map=permissions_map
        )

    async def sidebar_template_kwargs(self, request: Any) -> dict[str, Any]:
        """Thin wrapper — returns sidebar kwargs for TemplateResponse contexts."""
        return await self.template.sidebar_template_kwargs(request)

    async def apply_sidebar_context(self, request: Any, user: Any, context: dict) -> dict:
        """Inject nav_groups + permissions_map into a template context dict."""
        return await self.template.apply_sidebar_context(request, user, context)
