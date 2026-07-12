"""Default ModelAdmin classes for built-in admin models."""

from fastapi_admin_kit.modeladmin import ModelAdmin
from fastapi_admin_kit.types import ExtraField
from fastapi_admin_kit.widgets.inputs import AutocompleteWidget, PasswordWidget
from fastapi_admin_kit.widgets.relation import MultiRelationWidget


async def flush_pending_perm_ops(request):
    """Execute any pending direct-permission writes on the request's session.

    Called after ``after_create`` / ``after_update`` so the ops run on the
    same session (and thus the same SQLite connection) as the main request.
    """
    from sqlalchemy import text

    from fastapi_admin_kit.db import get_db_session

    ops = getattr(request.state, "_admin_perm_pending_ops", None)
    if not ops:
        return
    request.state._admin_perm_pending_ops = []
    session = get_db_session(request)
    if session is None:
        return
    for sql_str, params in ops:
        await session.execute(text(sql_str), params)


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
    inline_edit=True
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

    def on_create(self, obj, request=None):
        pass

    def on_update(self, obj, data, request=None):
        pass

    def after_create(self, obj, request=None):
        if request is None:
            return
        perm_data = getattr(request.state, "_admin_perm_data", None)
        if perm_data:
            self._save_direct_permissions_after_commit(obj, perm_data, request)

    def after_update(self, obj, request=None):
        if request is None:
            return
        perm_data = getattr(request.state, "_admin_perm_data", None)
        if perm_data:
            self._save_direct_permissions_after_commit(obj, perm_data, request)

    def _save_direct_permissions_after_commit(self, obj, perm_data, request):
        delete_sql = "DELETE FROM admin_user_permissions WHERE user_id = :uid"
        insert_sql = (
            "INSERT INTO admin_user_permissions"
            " (user_id, table_name, can_view, can_create, can_edit, can_delete)"
            " VALUES (:uid, :tn, :cv, :cc, :ce, :cd)"
        )

        ops = []
        ops.append((delete_sql, {"uid": obj.id}))

        for table_name, perms in perm_data.items():
            if not any(perms.get(a) for a in ["view", "create", "edit", "delete"]):
                continue
            ops.append(
                (
                    insert_sql,
                    {
                        "uid": obj.id,
                        "tn": table_name,
                        "cv": 1 if perms.get("view") else 0,
                        "cc": 1 if perms.get("create") else 0,
                        "ce": 1 if perms.get("edit") else 0,
                        "cd": 1 if perms.get("delete") else 0,
                    },
                )
            )

        if not hasattr(request.state, "_admin_perm_pending_ops"):
            request.state._admin_perm_pending_ops = []
        request.state._admin_perm_pending_ops.extend(ops)

    def get_form_context(self, context, obj=None, request=None):
        from sqlalchemy import select

        from fastapi_admin_kit.auth.models import UserPermission
        from fastapi_admin_kit.db import get_db_session

        perm_data = {}
        if obj is not None and request is not None:
            try:
                session = get_db_session(request)
                import asyncio

                async def _load_perms():
                    result = await session.execute(
                        select(UserPermission).where(
                            UserPermission.user_id == obj.id
                        )
                    )
                    return result.scalars().all()

                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        perms = pool.submit(asyncio.run, _load_perms()).result()
                else:
                    perms = loop.run_until_complete(_load_perms())

                for p in perms:
                    perm_data[p.table_name] = {
                        "_label": p.table_name,
                        "view": p.can_view,
                        "create": p.can_create,
                        "edit": p.can_edit,
                        "delete": p.can_delete,
                    }
            except Exception:
                pass

        context["perm_data"] = perm_data
        context["search_url"] = "/admin/tables/search"
        return context

    def process_form_data(self, data, request=None):
        if request is not None:
            import asyncio

            async def _get_perm_data():
                form = await request.form()
                return form.get("perm_data", "{}")

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    perm_data_raw = pool.submit(asyncio.run, _get_perm_data()).result()
            elif loop:
                perm_data_raw = loop.run_until_complete(_get_perm_data())
            else:
                perm_data_raw = asyncio.run(_get_perm_data())
        else:
            perm_data_raw = "{}"

        import json

        try:
            perm_data = json.loads(perm_data_raw)
        except (json.JSONDecodeError, TypeError):
            perm_data = {}

        if request is not None and perm_data:
            request.state._admin_perm_data = perm_data

        return data


class RoleAdmin(ModelAdmin):
    tag = "admin"
    icon = "shield-check"
    list_display = ["id", "name", "description"]
    search_fields = ["name"]
    skip_auto_routes = True
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
    list_display = [
        "id",
        "table_name",
        "can_view",
        "can_create",
        "can_edit",
        "can_delete",
    ]
    formfield_overrides = {
        "table_name": AutocompleteWidget(suggestions_fn=_get_table_names),
    }


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
    list_display = ["id", "user_id", "enabled", "secret_key", "created_at"]


class UserPermissionAdmin(ModelAdmin):
    tag = "admin"
    icon = "lock"
    verbose_name = "User Permission---"
    verbose_name_plural = "User Permissions---"
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
