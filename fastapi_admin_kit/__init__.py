"""FastAPI Admin Kit — Drop-in admin panel for FastAPI + SQLAlchemy apps."""

from fastapi_admin_kit.admin import Admin
from fastapi_admin_kit.admin.decorators import column, endpoint
from fastapi_admin_kit.auth.mixins import AuthModelMixin
from fastapi_admin_kit.config import DatabaseConfig, DatabaseType
from fastapi_admin_kit.exceptions import ConfigError
from fastapi_admin_kit.export_import import CSVExport, CSVImport, ExportBase, ImportBase
from fastapi_admin_kit.inline import InlineModelAdmin, StackedInline, TabularInline
from fastapi_admin_kit.nav import (
    BuiltNavGroup,
    BuiltNavItem,
    DefaultSidebarBuilder,
    NavGroupConfig,
    NavItemConfig,
    SidebarBuilder,
)
from fastapi_admin_kit.notifications import (
    ChannelResult,
    EmailDeliveryError,
    EmailProvider,
    EmailResult,
    Notification,
    NotificationConfig,
    NotificationLog,
    NotificationPreference,
    NotificationResult,
    NotificationService,
    NotificationTemplate,
    RealtimeNotificationHub,
    SMSDeliveryError,
    SMSProvider,
    SMSResult,
    SMSStatus,
    SMTPEmailProvider,
    TemplateRegistry,
    TwilioSMSProvider,
    configure_notifications,
    notifications_router,
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
    InlineFormsetData,
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
    "AuthModelMixin",
    "ConfigError",
    "DatabaseConfig",
    "DatabaseType",
    "RegisteredModel",
    "ModelAdmin",
    "column",
    "endpoint",
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
    "InlineFormsetData",
    # Inline admin
    "InlineModelAdmin",
    "StackedInline",
    "TabularInline",
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
    # Export/Import
    "ExportBase",
    "ImportBase",
    "CSVExport",
    "CSVImport",
    # Notification system
    "ChannelResult",
    "EmailDeliveryError",
    "EmailProvider",
    "EmailResult",
    "Notification",
    "NotificationConfig",
    "NotificationLog",
    "NotificationPreference",
    "NotificationResult",
    "NotificationService",
    "NotificationTemplate",
    "RealtimeNotificationHub",
    "SMTPEmailProvider",
    "SMSDeliveryError",
    "SMSProvider",
    "SMSResult",
    "SMSStatus",
    "TemplateRegistry",
    "TwilioSMSProvider",
    "configure_notifications",
    "notifications_router",
]
__version__ = "0.5.0"
