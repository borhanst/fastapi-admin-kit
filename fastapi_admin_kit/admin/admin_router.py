"""Admin router building and static file mounting."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class AdminRouter:
    """Builds and mounts routers for all registered models and admin routes."""

    def __init__(
        self,
        admin_path: str = "/admin",
        secret_key: str = "",
    ):
        self.admin_path = admin_path.rstrip("/")
        self.secret_key = secret_key or ""

    def _build_router(self, app: Any) -> None:
        """Build and mount routers for all registered models."""
        from fastapi_admin_kit.api.search import router as search_api_router
        from fastapi_admin_kit.auth.router import router as auth_router
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.router import build_model_router
        from fastapi_admin_kit.views.audit import router as audit_router
        from fastapi_admin_kit.views.roles import router as roles_router

        registry = AdminRegistry()

        for registered in registry.all():
            if getattr(registered.admin, "skip_auto_routes", False):
                continue
            model_router = build_model_router(registered)
            app.include_router(model_router, prefix=self.admin_path)

        # Auth routes (login/logout)
        app.include_router(auth_router, prefix=self.admin_path)

        # Global search API
        app.include_router(search_api_router, prefix=self.admin_path)

        # Audit & role management routes
        app.include_router(audit_router, prefix=self.admin_path)
        app.include_router(roles_router, prefix=self.admin_path)

    def _mount_static(self, app: Any) -> None:
        """Mount the static files directory and uploads directory."""
        from pathlib import Path

        from fastapi.staticfiles import StaticFiles

        static_dir = Path(__file__).parent.parent / "static"
        if static_dir.is_dir():
            # Primary mount — matches template references (/static/...)
            app.mount(
                "/static",
                StaticFiles(directory=str(static_dir)),
                name="admin_static",
            )

    def _init_jinja(self, app: Any) -> None:
        """Initialise the Jinja2 template environment."""
        import re
        from pathlib import Path

        from starlette.templating import Jinja2Templates

        templates_dir = Path(__file__).parent / "templates"
        jinja_env = Jinja2Templates(directory=str(templates_dir))

        def slugify(s: str) -> str:
            return re.sub(r"[^\w]", "-", s, flags=re.A).strip("-").lower()

        jinja_env.env.filters["slugify"] = slugify
        app.state.admin_jinja_env = jinja_env
