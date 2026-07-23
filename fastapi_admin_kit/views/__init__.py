"""Views package — re-exports ModelAdmin and view classes."""

from fastapi_admin_kit.modeladmin import ModelAdmin
from fastapi_admin_kit.views.class_views import (
    BaseView,
    BulkView,
    CreateView,
    DeleteView,
    EditView,
    ListView,
    SearchView,
    _resolve_view_class,
)
from fastapi_admin_kit.views.context import DisplayColumn, ViewContextBuilder
from fastapi_admin_kit.views.extra import AdminExtra
from fastapi_admin_kit.views.list_context import ListContextBuilder
from fastapi_admin_kit.views.sidebar import inject_sidebar_context


def create_model_router(registered):
    """Create a model router - backward compatible wrapper around build_model_router."""
    from fastapi_admin_kit.router import build_model_router

    return build_model_router(registered)


__all__ = [
    "ModelAdmin",
    "ViewContextBuilder",
    "ListContextBuilder",
    "DisplayColumn",
    "inject_sidebar_context",
    "_resolve_view_class",
    # View classes (OCP: extend without modifying)
    "BaseView",
    "ListView",
    "CreateView",
    "EditView",
    "DeleteView",
    "BulkView",
    "SearchView",
    # Per-model assets
    "AdminExtra",
    # Backward-compatible factory wrappers
    "create_model_router",
]


def __getattr__(name: str):
    """Lazy deprecation warnings for removed factory symbols."""
    _deprecated = {
        "ViewFactory": "fastapi_admin_kit.views.class_views",
        "list_view_factory": "fastapi_admin_kit.views.list",
        "create_form_factory": "fastapi_admin_kit.views.form",
        "create_submit_factory": "fastapi_admin_kit.views.form",
        "edit_form_factory": "fastapi_admin_kit.views.form",
        "edit_submit_factory": "fastapi_admin_kit.views.form",
        "delete_factory": "fastapi_admin_kit.views.delete",
        "bulk_factory": "fastapi_admin_kit.views.bulk",
        "search_factory": "fastapi_admin_kit.views.search",
    }
    if name in _deprecated:
        import warnings

        new_module = _deprecated[name]
        warnings.warn(
            f"{name} is deprecated. Import from {new_module} or use class-based views.",
            DeprecationWarning,
            stacklevel=2,
        )
        if name == "ViewFactory":
            raise ImportError(
                f"ViewFactory has been removed. Use class-based views from {new_module}."
            )
        # Re-import the wrapper function for backward compat
        import importlib

        module = importlib.import_module(new_module)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
