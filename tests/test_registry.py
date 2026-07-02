"""Tests for ModelAdmin base class, AdminRegistry, and @admin.register."""

import pytest
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    price = Column(Integer)
    is_active = Column(Boolean, default=True)
    category_id = Column(Integer, ForeignKey("categories.id"))

    category = relationship("Category")


class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    body = Column(String(5000))


# ===========================================================================
# 5.1-5.3 ModelAdmin base class
# ===========================================================================


class TestModelAdminDefaults:
    def test_list_display_none(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        assert admin.list_display is None

    def test_list_filter_none(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        assert admin.list_filter is None

    def test_search_fields_none(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        assert admin.search_fields is None

    def test_ordering_none(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        assert admin.ordering is None

    def test_per_page_default(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        assert admin.per_page == 20

    def test_fields_none(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        assert admin.fields is None

    def test_exclude_none(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        assert admin.exclude is None

    def test_readonly_fields_none(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        assert admin.readonly_fields is None

    def test_verbose_name_none(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        assert admin.verbose_name is None

    def test_verbose_name_plural_none(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        assert admin.verbose_name_plural is None

    def test_icon_none(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        assert admin.icon is None


class TestModelAdminStr:
    def test_str_prefers_name(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        obj = type("Obj", (), {"name": "Widget", "id": 1})()
        assert admin.__str__(obj) == "Widget"

    def test_str_falls_back_to_title(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        obj = type("Obj", (), {"title": "My Article", "id": 5})()
        assert admin.__str__(obj) == "My Article"

    def test_str_falls_back_to_id(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        obj = type("Obj", (), {"id": 42})()
        assert admin.__str__(obj) == "#42"

    def test_str_fallback_question_mark(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        obj = type("Obj", (), {})()
        assert admin.__str__(obj) == "#?"


class TestModelAdminCustomConfig:
    def test_subclass_override(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        class ProductAdmin(ModelAdmin):
            list_display = ["name", "price"]
            search_fields = ["name"]
            per_page = 50

        admin = ProductAdmin()
        assert admin.list_display == ["name", "price"]
        assert admin.search_fields == ["name"]
        assert admin.per_page == 50


class TestModelAdminLifecycleHooks:
    def test_on_create_is_noop(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        obj = object()
        # Should not raise
        admin.on_create(obj)
        admin.on_create(obj, request=None)

    def test_after_create_is_noop(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        admin.after_create(object())

    def test_on_update_is_noop(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        admin.on_update(object(), {"name": "new"})

    def test_after_update_is_noop(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        admin.after_update(object())

    def test_on_delete_is_noop(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        admin.on_delete(object())

    def test_after_delete_is_noop(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        admin.after_delete(object())


class TestModelAdminValidation:
    def test_validate_create_returns_data(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        data = {"name": "Test"}
        assert admin.validate_create(data) is data

    def test_validate_update_returns_data(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        obj = object()
        data = {"name": "Updated"}
        assert admin.validate_update(obj, data) is data


class TestModelAdminPermissions:
    def test_all_permissions_true_by_default(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = ModelAdmin()
        assert admin.has_view_permission() is True
        assert admin.has_create_permission() is True
        assert admin.has_edit_permission() is True
        assert admin.has_delete_permission() is True


class TestModelAdminCustomHooks:
    def test_subclass_can_override_hooks(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        calls = []

        class AuditedAdmin(ModelAdmin):
            def on_create(self, obj, request=None):
                calls.append(("on_create", obj))

            def validate_create(self, data, request=None):
                data["validated"] = True
                return data

        admin = AuditedAdmin()
        admin.on_create("myobj")
        assert calls == [("on_create", "myobj")]

        result = admin.validate_create({"name": "x"})
        assert result["validated"] is True


# ===========================================================================
# 5.4-5.6 AdminRegistry
# ===========================================================================


class TestAdminRegistry:
    def setup_method(self):
        from fastapi_admin_kit.registry import AdminRegistry

        self.registry = AdminRegistry()
        self.registry.clear()

    def test_singleton(self):
        from fastapi_admin_kit.registry import AdminRegistry

        r1 = AdminRegistry()
        r2 = AdminRegistry()
        assert r1 is r2

    def test_register_model(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(Product)
        assert registered.model is Product
        assert registered.table_name == "products"
        assert registered.verbose_name == "Products"
        assert registered.verbose_name_plural == "Productss"
        assert len(registered.columns) == 5
        assert registered.pk_field == "id"

    def test_register_with_admin_class(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin
        from fastapi_admin_kit.registry import AdminRegistry

        class ProductAdmin(ModelAdmin):
            list_display = ["name", "price"]
            verbose_name = "Item"

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(Product, ProductAdmin)
        assert registered.admin.list_display == ["name", "price"]
        assert registered.verbose_name == "Item"
        assert registered.verbose_name_plural == "Items"

    def test_register_generates_verbose_name_from_table(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(Category)
        assert registered.verbose_name == "Categories"
        assert registered.verbose_name_plural == "Categoriess"

    def test_register_strips_id_from_foreign_key(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(Product)
        cat_col = next(c for c in registered.columns if c.name == "category_id")
        assert cat_col.is_foreign_key is True

    def test_get_returns_registered(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        reg.register(Product)
        result = reg.get("products")
        assert result is not None
        assert result.table_name == "products"

    def test_get_returns_none_for_unknown(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        assert reg.get("nonexistent") is None

    def test_all_returns_list(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        reg.register(Product)
        reg.register(Category)
        all_models = reg.all()
        assert len(all_models) == 2
        table_names = {m.table_name for m in all_models}
        assert table_names == {"products", "categories"}

    def test_clear(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.register(Product)
        assert len(reg.all()) == 1
        reg.clear()
        assert len(reg.all()) == 0

    def test_register_rejects_non_model(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        with pytest.raises(ValueError, match="not a SQLAlchemy model"):
            reg.register(str)

    def test_pk_field_detected(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(Product)
        assert registered.pk_field == "id"

    def test_relationships_detected(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(Product)
        assert len(registered.relationships) == 1
        assert registered.relationships[0].name == "category"


# ===========================================================================
# 5.6 @admin.register decorator pattern
# ===========================================================================


class TestAdminRegisterDecorator:
    def setup_method(self):
        from fastapi_admin_kit.registry import AdminRegistry

        AdminRegistry().clear()

    def test_function_call_pattern(self):
        from fastapi_admin_kit.admin import Admin

        admin = Admin()
        registered = admin.register(Product)
        assert registered.model is Product
        assert registered.table_name == "products"

    def test_decorator_pattern(self):
        from fastapi_admin_kit.admin import Admin
        from fastapi_admin_kit.modeladmin import ModelAdmin

        admin = Admin()

        @admin.register(Article)
        class ArticleAdmin(ModelAdmin):
            list_display = ["title"]
            per_page = 10

        registered = admin.get_registered("articles")
        assert registered is not None
        assert registered.model is Article
        assert registered.admin.list_display == ["title"]
        assert registered.admin.per_page == 10

    def test_decorator_returns_registered_model(self):
        from fastapi_admin_kit.admin import Admin
        from fastapi_admin_kit.modeladmin import ModelAdmin
        from fastapi_admin_kit.registry import RegisteredModel

        admin = Admin()

        @admin.register(Article)
        class ArticleAdmin(ModelAdmin):
            pass

        # The decorator (ArticleAdmin) is now the RegisteredModel returned by __call__
        assert isinstance(ArticleAdmin, RegisteredModel)
        assert ArticleAdmin.model is Article

    def test_get_registered(self):
        from fastapi_admin_kit.admin import Admin

        admin = Admin()
        admin.register(Product)
        result = admin.get_registered("products")
        assert result is not None
        assert result.model is Product

    def test_all_registered(self):
        from fastapi_admin_kit.admin import Admin

        admin = Admin()
        admin.register(Product)
        admin.register(Category)
        all_reg = admin.all_registered()
        assert len(all_reg) == 2


# ===========================================================================
# RegisteredModel dataclass
# ===========================================================================


class TestRegisteredModel:
    def test_dataclass_fields(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(Product)
        assert registered.model is Product
        assert isinstance(registered.columns, list)
        assert isinstance(registered.relationships, list)
        assert registered.table_name == "products"

    def test_pk_field_from_columns(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(Category)
        assert registered.pk_field == "id"


# ===========================================================================
# views package
# ===========================================================================


class TestViewsPackage:
    def test_imports(self):
        from fastapi_admin_kit.views import ModelAdmin, create_model_router

        assert ModelAdmin is not None
        assert callable(create_model_router)

    def test_create_model_router(self):
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.views import create_model_router

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(Product)
        router = create_model_router(registered)
        assert router is not None


# ===========================================================================
# AdminRegistry with injected inspector/validator
# ===========================================================================


class TestAdminRegistryDependencyInjection:
    def setup_method(self):
        from fastapi_admin_kit.registry import AdminRegistry

        self.registry = AdminRegistry()
        self.registry.clear()

    def test_has_default_inspector(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        assert isinstance(reg.inspector, ModelInspector)

    def test_has_default_validator(self):
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.registry.validation import ModelValidator

        reg = AdminRegistry()
        assert isinstance(reg.validator, ModelValidator)

    def test_can_replace_inspector(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        custom_inspector = ModelInspector()
        reg.inspector = custom_inspector
        assert reg.inspector is custom_inspector

    def test_can_replace_validator(self):
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.registry.validation import ModelValidator

        reg = AdminRegistry()
        custom_validator = ModelValidator(reg)
        reg.validator = custom_validator
        assert reg.validator is custom_validator

    def test_register_uses_inspector(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(Product)
        assert len(registered.columns) == 5
        assert len(registered.relationships) == 1

    def test_register_uses_validator(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        # First registration should succeed
        reg.register(Product)
        # Second registration of same model should succeed (re-registration)
        reg.register(Product)
        assert len(reg.all()) == 1

    def test_validator_rejects_invalid_model(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        with pytest.raises(ValueError, match="not a SQLAlchemy model"):
            reg.register(str)

    def test_inspector_extracts_pk_field(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(Product)
        assert registered.pk_field == "id"

    def test_inspector_extracts_relationships(self):
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(Product)
        assert len(registered.relationships) == 1
        assert registered.relationships[0].name == "category"
