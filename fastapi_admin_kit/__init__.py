"""FastAPI Admin Kit — Drop-in admin panel for FastAPI + SQLAlchemy apps."""

from fastapi_admin_kit.admin import Admin
from fastapi_admin_kit.admin.decorators import column
from fastapi_admin_kit.config import DatabaseConfig, DatabaseType
from fastapi_admin_kit.exceptions import ConfigError
from fastapi_admin_kit.nav import (
    BuiltNavGroup,
    BuiltNavItem,
    DefaultSidebarBuilder,
    NavGroupConfig,
    NavItemConfig,
    SidebarBuilder,
)
from fastapi_admin_kit.registry import AdminRegistry, RegisteredModel
from fastapi_admin_kit.types import (
    ColumnMeta,
    ExtraField,
    FieldMeta,
    FieldRenderContext,
    FieldsetContext,
    FieldsetSpec,
    FormContext,
    PermissionSet,
    RelationMeta,
    SeedRole,
)
from fastapi_admin_kit.views import (
    AdminExtra,
    BaseView,
    BulkView,
    CreateView,
    DeleteView,
    EditView,
    ListView,
    ModelAdmin,
    SearchView,
)

__all__ = [
    "Admin",
    "AdminRegistry",
    "ConfigError",
    "DatabaseConfig",
    "DatabaseType",
    "RegisteredModel",
    "ModelAdmin",
    "column",
    "BuiltNavGroup",
    "BuiltNavItem",
    "DefaultSidebarBuilder",
    "NavGroupConfig",
    "NavItemConfig",
    "SidebarBuilder",
    "ColumnMeta",
    "RelationMeta",
    "FieldMeta",
    "PermissionSet",
    "SeedRole",
    "ExtraField",
    "FieldRenderContext",
    "FieldsetContext",
    "FieldsetSpec",
    "FormContext",
    # View classes
    "BaseView",
    "ListView",
    "CreateView",
    "EditView",
    "DeleteView",
    "BulkView",
    "SearchView",
    # Per-model assets
    "AdminExtra",
]
__version__ = "0.1.0"
