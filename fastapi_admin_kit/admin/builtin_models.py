"""Default ModelAdmin classes for built-in admin models."""

from fastapi_admin_kit.modeladmin import ModelAdmin
from fastapi_admin_kit.types import ExtraField
from fastapi_admin_kit.widgets.inputs import AutocompleteWidget, PasswordWidget
from fastapi_admin_kit.widgets.relation import MultiRelationWidget


async def flush_pending_perm_ops(request):
    """Flush pending direct-permission writes for the user on the request."""
    from sqlalchemy import delete

    from fastapi_admin_kit.auth.models import UserPermission
    from fastapi_admin_kit.db import get_db_session

    perm_ids = getattr(request.state, "_admin_perm_perm_ids", None)
    if not perm_ids or not isinstance(perm_ids, list):
        return

    # Get the user object from request state
    user_obj = getattr(request.state, "_admin_perm_user_obj", None)
    if user_obj is None:
        return

    request.state._admin_perm_perm_ids = None
    session = get_db_session(request)
    if session is None:
        return

    # Delete existing direct permissions
    await session.execute(delete(UserPermission).where(UserPermission.user_id == user_obj.id))

    # Insert new permissions
    for perm_id in perm_ids:
        up = UserPermission(user_id=user_obj.id, permission_id=perm_id)
        session.add(up)


def _get_table_names() -> list[str]:
    from fastapi_admin_kit.registry.core import AdminRegistry

    registry = AdminRegistry()
    return sorted({m.table_name for m in registry.all()})


class UserAdmin(ModelAdmin):
    tag = "admin"
    icon = "group"
    verbose_name = "Admin User"
    verbose_name_plural = "Admin Users"
    list_display = ["id", "email", "full_name", "is_superuser", "is_active"]
    search_fields = ["email", "full_name"]
    inline_edit = True
    exclude = ["hashed_password", "password_changed_at"]
    extra_fields = [
        ExtraField(
            name="password",
            label="Password",
            required=False,
            required_on_create=True,
            widget=PasswordWidget(),
        ),
    ]
    formfield_overrides = {
        "roles": MultiRelationWidget(
            related_table="admin_roles",
            search_url="/admin/users/roles/search",
        ),
    }

    def prepare_create_data(self, data, request=None):
        from fastapi_admin_kit.auth.models import User

        password = data.pop("password", None)
        if password:
            data["hashed_password"] = User.hash_password(password)
        else:
            data["hashed_password"] = ""
        return data

    def validate_create(self, data, request=None):
        """Validate user creation data — require password and validate strength."""
        from fastapi_admin_kit.auth.password import validate_password_strength
        from fastapi_admin_kit.types import FieldError

        password = data.get("password", "")
        if not password:
            raise FieldError({"password": ["Password is required for new users."]})
        errors = validate_password_strength(password)
        if errors:
            raise FieldError({"password": errors})
        return data

    def on_create(self, obj, request=None):
        pass

    def validate_update(self, obj, data, request=None):
        """Validate user update data — validate password strength if changed."""
        from fastapi_admin_kit.auth.password import validate_password_strength
        from fastapi_admin_kit.types import FieldError

        password = data.get("password", "")
        if password:
            errors = validate_password_strength(password)
            if errors:
                raise FieldError({"password": errors})
        return data

    def on_update(self, obj, data, request=None):
        pass

    def after_create(self, obj, request=None):
        if request is None:
            return
        perm_data = getattr(request.state, "_admin_perm_data", None)
        if perm_data:
            request.state._admin_perm_perm_ids = perm_data
            request.state._admin_perm_user_obj = obj

    def after_update(self, obj, request=None):
        if request is None:
            return
        perm_data = getattr(request.state, "_admin_perm_data", None)
        if perm_data:
            request.state._admin_perm_perm_ids = perm_data
            request.state._admin_perm_user_obj = obj

    async def get_form_context(self, context, obj=None, request=None):
        """Load direct permissions for the user being edited."""
        from sqlalchemy import select

        from fastapi_admin_kit.auth.models import Permission, UserPermission
        from fastapi_admin_kit.db import get_db_session

        perm_data = []
        if obj is not None and request is not None:
            try:
                session = get_db_session(request)
                result = await session.execute(
                    select(UserPermission, Permission)
                    .join(Permission, UserPermission.permission_id == Permission.id)
                    .where(UserPermission.user_id == obj.id)
                )
                for up, perm in result:
                    perm_data.append(
                        {
                            "id": perm.id,
                            "name": perm.name,
                            "table_name": perm.table_name,
                        }
                    )
            except Exception as exc:
                import logging

                logging.getLogger(__name__).debug("Permission load failed: %s", exc)

        context["perm_data"] = perm_data
        context["search_url"] = "/admin/permissions/search"
        return context

    def process_form_data(self, data, request=None):
        """Extract perm_data from request state and store for after_create/after_update.

        perm_data should already be extracted by the view and stored on
        request.state._admin_perm_data before this is called.
        """
        return data


class RoleAdmin(ModelAdmin):
    tag = "admin"
    icon = "shield-check"
    list_display = ["id", "name", "description"]
    search_fields = ["name"]
    exclude = ["users"]


class RefreshTokenAdmin(ModelAdmin):
    tag = "admin"
    icon = "key"
    verbose_name = "Refresh Token"
    verbose_name_plural = "Refresh Tokens"
    exclude = ["user"]


class PermissionAdmin(ModelAdmin):
    tag = "admin"
    icon = "lock"
    verbose_name = "Permission"
    verbose_name_plural = "Permissions"
    exclude = ["roles"]
    list_display = [
        "id",
        "name",
        "table_name",
        "can_view",
        "can_create",
        "can_edit",
        "can_delete",
    ]
    formfield_overrides = {
        "table_name": AutocompleteWidget(suggestions_fn=_get_table_names),
    }
    search_fields = ("name", "table_name")


class AuditLogAdmin(ModelAdmin):
    tag = "admin"
    icon = "clock"
    verbose_name = "Audit Log"
    verbose_name_plural = "Audit Logs"
    list_display = [
        "id",
        "user_email",
        "action",
        "model_name",
        "object_id",
        "timestamp",
    ]
    search_fields = ["user_email", "model_name"]
    readonly_fields = [
        "user_id",
        "user_email",
        "action",
        "model_name",
        "table_name",
        "object_id",
        "object_repr",
        "changes",
        "full_snapshot",
        "ip_address",
        "user_agent",
        "timestamp",
    ]


class UserTOTPAdmin(ModelAdmin):
    tag = "admin"
    icon = "lock"
    verbose_name = "2FA Token"
    verbose_name_plural = "2FA Tokens"
    list_display = ["id", "user_id", "enabled", "created_at"]
    exclude = ["secret_key", "backup_codes"]


class UserPermissionAdmin(ModelAdmin):
    tag = "admin"
    icon = "lock"
    verbose_name = "User Permission"
    verbose_name_plural = "User Permissions"
    list_display = [
        "id",
        "user",
        "table_name",
        "can_view",
        "can_create",
        "can_edit",
        "can_delete",
    ]
    formfield_overrides = {
        "table_name": AutocompleteWidget(suggestions_fn=_get_table_names),
    }


class LoginAttemptAdmin(ModelAdmin):
    tag = "admin"
    icon = "clock"
    verbose_name = "Login Attempt"
    verbose_name_plural = "Login Attempts"
    list_display = ["id", "email", "ip_address", "success", "note", "timestamp"]
    search_fields = ["email", "ip_address"]
