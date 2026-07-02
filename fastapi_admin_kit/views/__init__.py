"""Views package — re-exports ModelAdmin and route factories."""

from fastapi_admin_kit.modeladmin import ModelAdmin
from fastapi_admin_kit.views.bulk import bulk_factory
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
from fastapi_admin_kit.views.delete import delete_factory
from fastapi_admin_kit.views.extra import AdminExtra
from fastapi_admin_kit.views.factory import ViewFactory
from fastapi_admin_kit.views.form import (
    create_form_factory,
    create_submit_factory,
    edit_form_factory,
    edit_submit_factory,
)
from fastapi_admin_kit.views.list import list_view_factory
from fastapi_admin_kit.views.search import search_factory
from fastapi_admin_kit.views.sidebar import inject_sidebar_context


def create_model_router(registered):
    """Create a model router - backward compatible wrapper around build_model_router."""
    from fastapi_admin_kit.router import build_model_router

    return build_model_router(registered)


__all__ = [
    "ModelAdmin",
    "ViewContextBuilder",
    "ViewFactory",
    "DisplayColumn",
    "inject_sidebar_context",
    "_resolve_view_class",
    # Protocols (ISP: small focused interfaces)
    "QueryProvider",
    "FormParser",
    "HTMLRenderer",
    "APIRenderer",
    # Concrete implementations (SRP: each does one thing)
    "DefaultQueryProvider",
    "HTMLFormParser",
    "JSONBodyParser",
    "ListHTMLRenderer",
    "FormHTMLRenderer",
    "ListAPIRenderer",
    "ItemAPIRenderer",
    "DeleteAPIRenderer",
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
    # Backward-compatible factory functions
    "list_view_factory",
    "create_form_factory",
    "create_submit_factory",
    "edit_form_factory",
    "edit_submit_factory",
    "delete_factory",
    "bulk_factory",
    "search_factory",
    "create_model_router",
]
