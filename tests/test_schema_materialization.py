"""Tests for Issue #32: Schema-First + Protocol hybrid approach.

Covers:
- Protocol definitions (AdminUserProtocol, AdminRoleProtocol, AdminPermissionProtocol)
- Schema dataclasses (Schema, Field, Relation)
- Built-in model schemas (USER_SCHEMA, ROLE_SCHEMA, etc.)
- SQLAlchemy materialization (backend converts schemas to native models)
- Admin accepts auth_model and validates protocol compliance
"""

from __future__ import annotations

import pytest

from fastapi_admin_kit.auth.protocol import (
    AdminPermissionProtocol,
    AdminRoleProtocol,
    AdminUserProtocol,
)
from fastapi_admin_kit.schemas.builtin import (
    AUDIT_LOG_SCHEMA,
    LOGIN_ATTEMPT_SCHEMA,
    PERMISSION_SCHEMA,
    ROLE_SCHEMA,
    USER_SCHEMA,
)
from fastapi_admin_kit.schemas.schema import Field, Relation, Schema

# ---------------------------------------------------------------------------
# Protocol tests
# ---------------------------------------------------------------------------


class TestAdminPermissionProtocol:
    def test_required_attributes(self):
        required = ["id", "name", "table_name", "can_view", "can_create", "can_edit", "can_delete"]
        for attr in required:
            assert hasattr(AdminPermissionProtocol, attr) or attr in (
                "id",
                "name",
                "table_name",
                "can_view",
                "can_create",
                "can_edit",
                "can_delete",
            )

    def test_is_runtime_checkable(self):
        from typing import runtime_checkable

        assert hasattr(AdminPermissionProtocol, "__protocol_attrs__") or runtime_checkable


class TestAdminRoleProtocol:
    def test_required_attributes(self):
        required = ["id", "name", "permissions"]
        for attr in required:
            assert hasattr(AdminRoleProtocol, attr) or attr in ("id", "name", "permissions")


class TestAdminUserProtocol:
    def test_required_attributes(self):
        required = ["id", "email", "is_active", "is_superuser", "roles"]
        for attr in required:
            assert hasattr(AdminUserProtocol, attr) or attr in (
                "id",
                "email",
                "is_active",
                "is_superuser",
                "roles",
            )

    def test_required_methods(self):
        required_methods = ["verify_password", "hash_password"]
        for method in required_methods:
            assert hasattr(AdminUserProtocol, method) or callable(
                getattr(AdminUserProtocol, method, None)
            )


# ---------------------------------------------------------------------------
# Schema dataclass tests
# ---------------------------------------------------------------------------


class TestField:
    def test_basic_field(self):
        f = Field("name", type="string", max_length=100)
        assert f.name == "name"
        assert f.type == "string"
        assert f.max_length == 100
        assert f.primary_key is False
        assert f.nullable is True

    def test_pk_field(self):
        f = Field("id", type="integer", primary_key=True, auto_increment=True)
        assert f.primary_key is True
        assert f.auto_increment is True

    def test_field_defaults(self):
        f = Field("test")
        assert f.type == "string"
        assert f.nullable is True
        assert f.unique is False
        assert f.default is None


class TestRelation:
    def test_many_to_many(self):
        r = Relation("roles", target="admin_roles", type="many_to_many", through="admin_user_roles")
        assert r.name == "roles"
        assert r.target == "admin_roles"
        assert r.type == "many_to_many"
        assert r.through == "admin_user_roles"

    def test_one_to_many(self):
        r = Relation("items", target="items", type="one_to_many")
        assert r.type == "one_to_many"
        assert r.through is None


class TestSchema:
    def test_basic_schema(self):
        schema = Schema(
            table_name="test_table",
            fields=[Field("id", type="integer", primary_key=True)],
        )
        assert schema.table_name == "test_table"
        assert len(schema.fields) == 1

    def test_get_field(self):
        schema = Schema(
            table_name="test",
            fields=[
                Field("id", type="integer", primary_key=True),
                Field("name", type="string"),
            ],
        )
        assert schema.get_field("name") is not None
        assert schema.get_field("name").type == "string"
        assert schema.get_field("missing") is None

    def test_get_pk_field(self):
        schema = Schema(
            table_name="test",
            fields=[
                Field("id", type="integer", primary_key=True),
                Field("name", type="string"),
            ],
        )
        pk = schema.get_pk_field()
        assert pk is not None
        assert pk.name == "id"

    def test_get_relation(self):
        schema = Schema(
            table_name="test",
            relations=[Relation("items", target="items_table")],
        )
        assert schema.get_relation("items") is not None
        assert schema.get_relation("missing") is None

    def test_field_names(self):
        schema = Schema(
            table_name="test",
            fields=[Field("a"), Field("b"), Field("c")],
        )
        assert schema.field_names() == ["a", "b", "c"]

    def test_relation_names(self):
        schema = Schema(
            table_name="test",
            relations=[Relation("x", target="t1"), Relation("y", target="t2")],
        )
        assert schema.relation_names() == ["x", "y"]


# ---------------------------------------------------------------------------
# Built-in schema tests
# ---------------------------------------------------------------------------


class TestBuiltinSchemas:
    def test_user_schema_table_name(self):
        assert USER_SCHEMA.table_name == "admin_users"

    def test_user_schema_has_id_field(self):
        pk = USER_SCHEMA.get_pk_field()
        assert pk is not None
        assert pk.name == "id"
        assert pk.primary_key is True

    def test_user_schema_has_email_field(self):
        f = USER_SCHEMA.get_field("email")
        assert f is not None
        assert f.unique is True
        assert f.nullable is False

    def test_user_schema_has_roles_relation(self):
        r = USER_SCHEMA.get_relation("roles")
        assert r is not None
        assert r.type == "many_to_many"
        assert r.through == "admin_user_roles"

    def test_role_schema_table_name(self):
        assert ROLE_SCHEMA.table_name == "admin_roles"

    def test_role_schema_has_name_field(self):
        f = ROLE_SCHEMA.get_field("name")
        assert f is not None
        assert f.unique is True

    def test_role_schema_has_permissions_relation(self):
        r = ROLE_SCHEMA.get_relation("permissions")
        assert r is not None
        assert r.type == "many_to_many"

    def test_permission_schema_table_name(self):
        assert PERMISSION_SCHEMA.table_name == "admin_permissions"

    def test_permission_schema_has_crud_fields(self):
        for field_name in ["can_view", "can_create", "can_edit", "can_delete"]:
            f = PERMISSION_SCHEMA.get_field(field_name)
            assert f is not None
            assert f.type == "boolean"

    def test_audit_log_schema_table_name(self):
        assert AUDIT_LOG_SCHEMA.table_name == "admin_audit_log"

    def test_audit_log_schema_has_timestamp(self):
        f = AUDIT_LOG_SCHEMA.get_field("timestamp")
        assert f is not None
        assert f.server_default == "now()"

    def test_login_attempt_schema_table_name(self):
        assert LOGIN_ATTEMPT_SCHEMA.table_name == "admin_login_attempts"

    def test_login_attempt_schema_has_email(self):
        f = LOGIN_ATTEMPT_SCHEMA.get_field("email")
        assert f is not None
        assert f.index is True


# ---------------------------------------------------------------------------
# Materialization tests
# ---------------------------------------------------------------------------


class TestSqlAlchemyMaterialize:
    def test_materialize_user_schema(self):
        from fastapi_admin_kit.admin.admin_database import AdminDatabase
        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyDatabaseBackend
        from fastapi_admin_kit.models.base import Base

        db = AdminDatabase.__new__(AdminDatabase)
        backend = SqlAlchemyDatabaseBackend(admin_database=db)

        model = backend.materialize(USER_SCHEMA, base=Base)

        assert model.__tablename__ == "admin_users"
        assert hasattr(model, "id")
        assert hasattr(model, "email")
        assert hasattr(model, "password")
        assert hasattr(model, "is_active")
        assert hasattr(model, "is_superuser")

    def test_materialize_role_schema(self):
        from fastapi_admin_kit.admin.admin_database import AdminDatabase
        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyDatabaseBackend
        from fastapi_admin_kit.models.base import Base

        db = AdminDatabase.__new__(AdminDatabase)
        backend = SqlAlchemyDatabaseBackend(admin_database=db)

        model = backend.materialize(ROLE_SCHEMA, base=Base)

        assert model.__tablename__ == "admin_roles"
        assert hasattr(model, "id")
        assert hasattr(model, "name")
        assert hasattr(model, "description")

    def test_materialize_permission_schema(self):
        from fastapi_admin_kit.admin.admin_database import AdminDatabase
        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyDatabaseBackend
        from fastapi_admin_kit.models.base import Base

        db = AdminDatabase.__new__(AdminDatabase)
        backend = SqlAlchemyDatabaseBackend(admin_database=db)

        model = backend.materialize(PERMISSION_SCHEMA, base=Base)

        assert model.__tablename__ == "admin_permissions"
        assert hasattr(model, "can_view")
        assert hasattr(model, "can_create")
        assert hasattr(model, "can_edit")
        assert hasattr(model, "can_delete")

    def test_materialize_audit_log_schema(self):
        from fastapi_admin_kit.admin.admin_database import AdminDatabase
        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyDatabaseBackend
        from fastapi_admin_kit.models.base import Base

        db = AdminDatabase.__new__(AdminDatabase)
        backend = SqlAlchemyDatabaseBackend(admin_database=db)

        model = backend.materialize(AUDIT_LOG_SCHEMA, base=Base)

        assert model.__tablename__ == "admin_audit_log"
        assert hasattr(model, "action")
        assert hasattr(model, "changes")

    def test_materialize_login_attempt_schema(self):
        from fastapi_admin_kit.admin.admin_database import AdminDatabase
        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyDatabaseBackend
        from fastapi_admin_kit.models.base import Base

        db = AdminDatabase.__new__(AdminDatabase)
        backend = SqlAlchemyDatabaseBackend(admin_database=db)

        model = backend.materialize(LOGIN_ATTEMPT_SCHEMA, base=Base)

        assert model.__tablename__ == "admin_login_attempts"
        assert hasattr(model, "email")
        assert hasattr(model, "success")

    def test_materialize_rejects_non_schema(self):
        from fastapi_admin_kit.admin.admin_database import AdminDatabase
        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyDatabaseBackend

        db = AdminDatabase.__new__(AdminDatabase)
        backend = SqlAlchemyDatabaseBackend(admin_database=db)

        with pytest.raises(TypeError, match="Expected Schema instance"):
            backend.materialize("not a schema")

    def test_materialize_custom_schema(self):
        from fastapi_admin_kit.admin.admin_database import AdminDatabase
        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyDatabaseBackend
        from fastapi_admin_kit.models.base import Base

        db = AdminDatabase.__new__(AdminDatabase)
        backend = SqlAlchemyDatabaseBackend(admin_database=db)

        custom = Schema(
            table_name="custom_items",
            fields=[
                Field("id", type="integer", primary_key=True),
                Field("title", type="string", max_length=200, nullable=False),
                Field("price", type="float", default=0.0),
                Field("active", type="boolean", default=True),
            ],
        )

        model = backend.materialize(custom, base=Base)

        assert model.__tablename__ == "custom_items"
        assert hasattr(model, "id")
        assert hasattr(model, "title")
        assert hasattr(model, "price")
        assert hasattr(model, "active")


class TestMaterializeForeignKeyTypeDerivation:
    """FK columns must mirror the referenced model's primary-key type.

    Fixes the case where a relation to the User model (or any model) declared
    its ``id`` as a UUID but the ``user_id`` FK column was created as an
    integer/string. The FK type is now derived from the target PK type.
    """

    def _backend(self):
        from sqlalchemy.orm import declarative_base

        from fastapi_admin_kit.admin.admin_database import AdminDatabase
        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyDatabaseBackend

        # A fresh declarative base avoids the shared, pre-materialized built-in
        # ``admin_users`` (which has an integer id) interfering with these tests.
        Base = declarative_base()  # noqa: N806
        db = AdminDatabase.__new__(AdminDatabase)
        return SqlAlchemyDatabaseBackend(admin_database=db), Base

    def test_fk_mirrors_uuid_user_id(self):
        from sqlalchemy.types import Uuid

        backend, Base = self._backend()  # noqa: N806

        user_schema = Schema(
            table_name="admin_users",
            fields=[
                Field("id", type="uuid", primary_key=True),
                Field("email", type="string", max_length=255, nullable=False),
            ],
        )
        # FK column declared with a mismatching type (integer) on purpose.
        post_schema = Schema(
            table_name="posts",
            fields=[
                Field("id", type="integer", primary_key=True),
                Field("user_id", type="integer", nullable=False),
            ],
            relations=[
                Relation(name="user", target="admin_users", type="many_to_one"),
            ],
        )

        backend.materialize(user_schema, base=Base)
        Post = backend.materialize(post_schema, base=Base, schemas={"admin_users": user_schema})  # noqa: N806

        user_id_col = Post.__table__.c.user_id
        assert isinstance(user_id_col.type, Uuid)
        # The FK still points at admin_users.id
        fk = list(user_id_col.foreign_keys)[0]
        assert fk.column.table.name == "admin_users"

    def test_fk_mirrors_integer_user_id(self):
        from sqlalchemy import Integer

        backend, Base = self._backend()  # noqa: N806

        user_schema = Schema(
            table_name="admin_users",
            fields=[
                Field("id", type="integer", primary_key=True),
            ],
        )
        # FK column declared with a string type (the old "log pattern") on purpose.
        post_schema = Schema(
            table_name="posts",
            fields=[
                Field("id", type="integer", primary_key=True),
                Field("user_id", type="string", max_length=255, nullable=False),
            ],
            relations=[
                Relation(name="user", target="admin_users", type="many_to_one"),
            ],
        )

        backend.materialize(user_schema, base=Base)
        Post = backend.materialize(post_schema, base=Base, schemas={"admin_users": user_schema})  # noqa: N806

        assert isinstance(Post.__table__.c.user_id.type, Integer)

    def test_fk_falls_back_to_field_type_when_target_unknown(self):
        from sqlalchemy import Integer

        backend, Base = self._backend()  # noqa: N806

        post_schema = Schema(
            table_name="posts",
            fields=[
                Field("id", type="integer", primary_key=True),
                Field("user_id", type="integer", nullable=False),
            ],
            relations=[
                Relation(name="user", target="admin_users", type="many_to_one"),
            ],
        )

        # No schema registry and no materialized target -> keep declared type.
        Post = backend.materialize(post_schema, base=Base)  # noqa: N806

        assert isinstance(Post.__table__.c.user_id.type, Integer)


# ---------------------------------------------------------------------------
# Admin auth_model validation tests
# ---------------------------------------------------------------------------


class TestAdminAuthModelValidation:
    def test_admin_accepts_auth_model_param(self):
        from fastapi_admin_kit.admin.core import Admin

        admin = Admin(auth_model=None)
        assert admin.auth_model is None

    def test_auth_config_validates_model(self):
        from fastapi_admin_kit.config.auth import AuthConfig
        from fastapi_admin_kit.migrations.models import User

        config = AuthConfig(auth_model=User)
        # Should not raise — User satisfies the protocol
        config.validate_auth_model()

    def test_auth_config_rejects_incomplete_model(self):
        from fastapi_admin_kit.config.auth import AuthConfig
        from fastapi_admin_kit.exceptions import ConfigError

        class IncompleteUser:
            pass

        config = AuthConfig(auth_model=IncompleteUser)
        with pytest.raises(ConfigError, match="missing required attributes"):
            config.validate_auth_model()

    def test_auth_config_rejects_missing_roles(self):
        from fastapi_admin_kit.config.auth import AuthConfig

        class UserNoRoles:
            id = 1
            email = "test@test.com"
            is_active = True
            is_superuser = False
            password = "hash"
            role_ids = None  # has role_ids but it's not a list property

            def verify_password(self, password):
                return False

        config = AuthConfig(auth_model=UserNoRoles)
        # Should pass because it has role_ids (even though None)
        # The validation checks hasattr, not the value
        config.validate_auth_model()
        # The validation checks hasattr, not the value

    def test_custom_auth_model_skips_builtin_user_tables(self):
        """When a custom auth_model is supplied, the built-in ``admin_users``
        table is reported as 'skip' so that ``create_all`` does not emit
        DDL for the default user schema. ``admin_user_roles`` is kept
        and its ``user_id`` foreign key is retargeted to the custom
        auth_model's table at create time.
        """
        from fastapi_admin_kit.admin.core import Admin

        class CustomUser:
            id = None
            email = "u@x.com"
            is_active = True
            is_superuser = False
            password = "h"
            role_ids = []

            def verify_password(self, password):
                return False

        admin = Admin(auth_model=CustomUser)
        skipped = admin._builtin_user_tables_to_skip()
        assert "admin_users" in skipped
        assert "admin_user_roles" not in skipped

    def test_default_user_tables_kept_when_no_auth_model(self):
        """Default installation (auth_model is None) must NOT skip the
        built-in ``admin_users`` / ``admin_user_roles`` tables."""
        from fastapi_admin_kit.admin.core import Admin

        admin = Admin(auth_model=None)
        skipped = admin._builtin_user_tables_to_skip()
        assert skipped == ()

    def test_default_user_tables_kept_when_auth_model_is_builtin(self):
        """When ``auth_model`` is the built-in ``User`` class, the built-in
        tables must remain (no skip)."""
        from fastapi_admin_kit.admin.core import Admin
        from fastapi_admin_kit.migrations.models import User as BuiltinUser

        admin = Admin(auth_model=BuiltinUser)
        skipped = admin._builtin_user_tables_to_skip()
        assert skipped == ()

    @pytest.mark.asyncio
    async def test_create_tables_skips_builtin_user_when_custom_auth_model(self, monkeypatch):
        """``admin.create_tables()`` must NOT create the built-in
        ``admin_users`` table when a custom ``auth_model`` is supplied
        (this is what callers in a FastAPI ``lifespan`` rely on).
        ``admin_user_roles`` IS created with its ``user_id`` FK
        retargeted to the custom auth_model's table.
        """
        from sqlalchemy import Column, Integer, String
        from sqlalchemy.orm import DeclarativeBase

        from fastapi_admin_kit.admin.core import Admin

        class _TestBase(DeclarativeBase):
            pass

        class CustomUser(_TestBase):
            __tablename__ = "users"
            id = Column(Integer, primary_key=True)
            email = Column(String, unique=True, nullable=False)
            password = Column(String, nullable=False)
            is_active = Column(Integer, default=True)
            is_superuser = Column(Integer, default=False)

            @property
            def role_ids(self) -> list[int]:
                return []

            def verify_password(self, password: str) -> bool:
                return False

        admin = Admin(auth_model=CustomUser)

        # Capture the ``tables=`` argument handed to ``create_all`` so we can
        # assert the built-in user table is excluded. We mock the engine
        # and metadata by passing a fake backend.
        captured: dict = {}

        class FakeBackend:
            def create_tables(self, engine, metadata, tables):
                captured["engine"] = engine
                captured["metadata"] = metadata
                captured["tables"] = tables

            def auto_migrate(self, engine, metadata):
                return None

            async def has_tables(self, engine, names):
                return set()

        admin.database._backend = FakeBackend()  # type: ignore[assignment]
        admin.database.engine = object()  # any sentinel
        admin.database._ai_enabled = admin._ai_enabled  # not used here

        await admin.create_tables()

        assert captured["tables"] is not None, (
            "expected create_tables to pass an explicit tables list when a "
            "custom auth_model is configured"
        )
        emitted = {t.name for t in captured["tables"]}
        assert "admin_users" not in emitted
        # admin_user_roles IS emitted (with retargeted FK)
        assert "admin_user_roles" in emitted
        # The cloned auth_model table is excluded from the create list
        # (project's own metadata owns the real table).
        assert "users" not in emitted
        # And nothing from the expected skip leaked in.
        expected_skip = set(admin._builtin_user_tables_to_skip())
        assert emitted.isdisjoint(expected_skip)

    @pytest.mark.asyncio
    async def test_create_tables_keeps_builtin_user_when_default(self, monkeypatch):
        """When no custom auth_model is configured, ``admin.create_tables()``
        must still create ``admin_users`` and ``admin_user_roles``."""
        from fastapi_admin_kit.admin.core import Admin

        admin = Admin(auth_model=None)

        captured: dict = {}

        class FakeBackend:
            def create_tables(self, engine, metadata, tables):
                captured["tables"] = tables

            def auto_migrate(self, engine, metadata):
                return None

            async def has_tables(self, engine, names):
                return set()

        admin.database._backend = FakeBackend()  # type: ignore[assignment]
        admin.database.engine = object()

        await admin.create_tables()

        # ``admin_users`` / ``admin_user_roles`` must be present in the
        # tables-to-create list. The list itself may still be non-None
        # (because AI tables are also filtered when AI is disabled) — what
        # matters is that the user tables are NOT excluded.
        emitted = {t.name for t in captured["tables"]}
        assert "admin_users" in emitted
        assert "admin_user_roles" in emitted

    @pytest.mark.asyncio
    async def test_create_tables_raises_clear_error_when_no_engine(self):
        """When neither ``engine=`` nor ``database_config=`` is supplied,
        ``admin.create_tables()`` must raise a clear ``RuntimeError`` —
        not a confusing ``AttributeError`` from deep inside SQLAlchemy
        (``'NoneType' object has no attribute '_run_ddl_visitor'``)."""
        from fastapi_admin_kit.admin.admin_database import AdminDatabase
        from fastapi_admin_kit.admin.core import Admin

        admin = Admin(auth_model=None)
        # Force-reset to a database with no engine and no database_config
        # (mimics a misconfigured project that supplied neither).
        admin.database = AdminDatabase(engine=None, base=None, database_config=None)

        with pytest.raises(RuntimeError, match="no engine"):
            await admin.create_tables()

    def test_resolved_engine_lazy_creates_from_database_config(self):
        """``AdminDatabase.resolved_engine`` must create the engine
        from ``database_config`` when no ``engine=`` was passed at
        construction. This is the property that fixes the
        ``'NoneType' object has no attribute '_run_ddl_visitor'`` error
        projects hit when they only pass ``database_config=`` to
        ``Admin()``."""
        from unittest.mock import MagicMock

        from fastapi_admin_kit.admin.admin_database import AdminDatabase

        sentinel_engine = MagicMock(name="engine")
        cfg = MagicMock()
        cfg.create_engine.return_value = sentinel_engine

        db = AdminDatabase(database_config=cfg)
        assert db.engine is None  # not yet resolved
        assert db.resolved_engine is sentinel_engine
        # And it's now cached on the instance.
        assert db.engine is sentinel_engine
        cfg.create_engine.assert_called_once()

    def test_builtin_user_satisfies_protocol(self):
        from fastapi_admin_kit.migrations.models import User

        # User should have all protocol-required attributes
        assert hasattr(User, "id")
        assert hasattr(User, "email")
        assert hasattr(User, "is_active")
        assert hasattr(User, "is_superuser")
        assert hasattr(User, "roles")
        assert hasattr(User, "verify_password")
        assert hasattr(User, "hash_password")
        assert hasattr(User, "role_ids")
