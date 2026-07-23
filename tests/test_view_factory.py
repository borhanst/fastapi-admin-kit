"""Tests for ViewContextBuilder and backward-compatible factory wrappers."""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class TestCategory(Base):
    __tablename__ = "test_categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)


class TestProduct(Base):
    __tablename__ = "test_products"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    price = Column(Integer)
    is_active = Column(Boolean, default=True)
    category_id = Column(Integer, ForeignKey("test_categories.id"))

    category = relationship("TestCategory")


# ===========================================================================
# ViewContextBuilder Tests
# ===========================================================================


class TestViewContextBuilder:
    def setup_method(self):
        from fastapi_admin_kit.registry import AdminRegistry

        AdminRegistry().clear()

    def test_init_default(self):
        from fastapi_admin_kit.views.context import ViewContextBuilder

        builder = ViewContextBuilder()
        assert builder.registry is None
        assert builder.permission_checker is None
        assert builder.widget_resolver is None

    def test_init_with_dependencies(self):
        from fastapi_admin_kit.views.context import ViewContextBuilder

        registry = MagicMock()
        checker = MagicMock()
        resolver = MagicMock()
        builder = ViewContextBuilder(
            registry=registry,
            permission_checker=checker,
            widget_resolver=resolver,
        )
        assert builder.registry is registry
        assert builder.permission_checker is checker
        assert builder.widget_resolver is resolver

    def test_get_field_type_relation(self):
        from fastapi_admin_kit.views.context import ViewContextBuilder

        builder = ViewContextBuilder()
        field_type = builder._get_field_type(TestProduct, "category")
        assert field_type == "relation"

    def test_get_field_type_boolean(self):
        from fastapi_admin_kit.views.context import ViewContextBuilder

        builder = ViewContextBuilder()
        field_type = builder._get_field_type(TestProduct, "is_active")
        assert field_type == "boolean"

    def test_get_field_type_text(self):
        from fastapi_admin_kit.views.context import ViewContextBuilder

        builder = ViewContextBuilder()
        field_type = builder._get_field_type(TestProduct, "name")
        assert field_type == "text"

    def test_get_eager_loads(self):
        from fastapi_admin_kit.views.context import ViewContextBuilder

        builder = ViewContextBuilder()
        loads = builder._get_eager_loads(TestProduct, ["name", "category"])
        assert len(loads) == 1

    def test_get_eager_loads_no_relations(self):
        from fastapi_admin_kit.views.context import ViewContextBuilder

        builder = ViewContextBuilder()
        loads = builder._get_eager_loads(TestProduct, ["name", "price"])
        assert len(loads) == 0


# ===========================================================================
# Backward Compatibility Tests
# ===========================================================================


class TestBackwardCompatibility:
    def setup_method(self):
        from fastapi_admin_kit.registry import AdminRegistry

        AdminRegistry().clear()

    def test_list_view_factory_import(self):
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.views.list import list_view_factory

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(TestProduct)

        view = list_view_factory(registered)
        assert callable(view)
        assert view.__name__ == "list_test_products"

    def test_create_form_factory_import(self):
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.views.form import create_form_factory

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(TestProduct)

        view = create_form_factory(registered)
        assert callable(view)
        assert view.__name__ == "create_form_test_products"

    def test_edit_form_factory_import(self):
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.views.form import edit_form_factory

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(TestProduct)

        view = edit_form_factory(registered)
        assert callable(view)
        assert view.__name__ == "edit_form_test_products"

    def test_delete_factory_import(self):
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.views.delete import delete_factory

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(TestProduct)

        view = delete_factory(registered)
        assert callable(view)
        assert view.__name__ == "delete_test_products"

    def test_bulk_factory_import(self):
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.views.bulk import bulk_factory

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(TestProduct)

        view = bulk_factory(registered)
        assert callable(view)
        assert view.__name__ == "bulk_test_products"


# ===========================================================================
# Views Package Exports Tests
# ===========================================================================


class TestViewsPackageExports:
    def test_imports_class_views(self):
        from fastapi_admin_kit.views import (
            BaseView,
            BulkView,
            CreateView,
            DeleteView,
            DisplayColumn,
            EditView,
            ListView,
            SearchView,
            ViewContextBuilder,
        )

        assert BaseView is not None
        assert ListView is not None
        assert CreateView is not None
        assert EditView is not None
        assert DeleteView is not None
        assert BulkView is not None
        assert SearchView is not None
        assert ViewContextBuilder is not None
        assert DisplayColumn is not None

    def test_imports_backward_compatible_factories(self):
        from fastapi_admin_kit.views import (
            bulk_factory,
            create_form_factory,
            create_submit_factory,
            delete_factory,
            edit_form_factory,
            edit_submit_factory,
            list_view_factory,
        )

        assert callable(list_view_factory)
        assert callable(create_form_factory)
        assert callable(create_submit_factory)
        assert callable(edit_form_factory)
        assert callable(edit_submit_factory)
        assert callable(delete_factory)
        assert callable(bulk_factory)


# ===========================================================================
# DisplayColumn Tests
# ===========================================================================


class TestDisplayColumn:
    def test_init(self):
        from fastapi_admin_kit.views.context import DisplayColumn

        col = DisplayColumn("name", "Name", is_relation=False)
        assert col.name == "name"
        assert col.label == "Name"
        assert col.is_relation is False

    def test_value(self):
        from fastapi_admin_kit.views.context import DisplayColumn

        col = DisplayColumn("name", "Name")
        obj = type("Obj", (), {"name": "Test"})()
        assert col.value(obj) == "Test"

    def test_value_default(self):
        from fastapi_admin_kit.views.context import DisplayColumn

        col = DisplayColumn("missing", "Missing")
        obj = type("Obj", (), {})()
        assert col.value(obj) == ""
