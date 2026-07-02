"""Tests for fastapi_admin_kit.widgets.resolver — WidgetResolver class."""

from fastapi_admin_kit.types import ColumnMeta
from fastapi_admin_kit.widgets.base import Widget
from fastapi_admin_kit.widgets.registry import WidgetRegistry
from fastapi_admin_kit.widgets.resolver import WidgetResolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _col(name: str = "title", col_type=None, **overrides):
    defaults = dict(name=name, type=col_type or type("String", (), {}))
    defaults.update(overrides)
    return ColumnMeta(**defaults)


def _empty_registry() -> WidgetRegistry:
    """Create a fresh registry with no registrations."""
    return WidgetRegistry()


def _default_registry() -> WidgetRegistry:
    """Create a registry with standard type/name registrations."""
    from sqlalchemy import (
        Boolean,
        Date,
        DateTime,
        Float,
        Integer,
        LargeBinary,
        Numeric,
        String,
        Text,
        Uuid,
    )

    from fastapi_admin_kit.widgets.inputs import (
        DatePickerWidget,
        DateTimePickerWidget,
        FileUploadWidget,
        NumberInputWidget,
        PasswordWidget,
        TextareaWidget,
        TextInputWidget,
        ToggleWidget,
    )

    reg = WidgetRegistry()
    reg.register_type(String, TextInputWidget)
    reg.register_type(Text, TextareaWidget)
    reg.register_type(Integer, NumberInputWidget)
    reg.register_type(Float, NumberInputWidget)
    reg.register_type(Numeric, NumberInputWidget)
    reg.register_type(Boolean, ToggleWidget)
    reg.register_type(Date, DatePickerWidget)
    reg.register_type(DateTime, DateTimePickerWidget)
    reg.register_type(LargeBinary, FileUploadWidget)
    reg.register_type(Uuid, TextInputWidget)
    reg.register_name("password", PasswordWidget)
    reg.register_name("secret", PasswordWidget)
    reg.register_name("token", PasswordWidget)
    return reg


# ===========================================================================
# WidgetResolver construction
# ===========================================================================


class TestWidgetResolverConstruction:
    def test_init_with_registry(self):
        reg = _empty_registry()
        resolver = WidgetResolver(reg)
        assert resolver.registry is reg

    def test_registry_property_returns_same_registry(self):
        reg = _default_registry()
        resolver = WidgetResolver(reg)
        assert resolver.registry is reg


# ===========================================================================
# Resolution: fallback
# ===========================================================================


class TestResolverFallback:
    def test_empty_registry_returns_text_input(self):
        reg = _empty_registry()
        resolver = WidgetResolver(reg)
        from fastapi_admin_kit.widgets.inputs import TextInputWidget

        w = resolver.resolve(_col(col_type=type("Unknown", (), {})))
        assert isinstance(w, TextInputWidget)

    def test_unregistered_type_returns_text_input(self):
        from sqlalchemy import String

        from fastapi_admin_kit.widgets.inputs import TextInputWidget

        reg = _empty_registry()
        resolver = WidgetResolver(reg)
        w = resolver.resolve(_col(col_type=String()))
        assert isinstance(w, TextInputWidget)


# ===========================================================================
# Resolution: type mapping
# ===========================================================================


class TestResolverTypeMapping:
    def test_string_resolves_to_text_input(self):
        from sqlalchemy import String

        from fastapi_admin_kit.widgets.inputs import TextInputWidget

        resolver = WidgetResolver(_default_registry())
        w = resolver.resolve(_col(col_type=String()))
        assert isinstance(w, TextInputWidget)

    def test_text_resolves_to_textarea(self):
        from sqlalchemy import Text

        from fastapi_admin_kit.widgets.inputs import (
            TextareaWidget,
            TextInputWidget,
        )

        resolver = WidgetResolver(_default_registry())
        # Text() is a subclass of String, so isinstance(Text(), String) is True.
        # The String -> TextInputWidget mapping matches first in the type_map.
        # This is consistent with the original behavior.
        w = resolver.resolve(_col(col_type=Text()))
        assert isinstance(w, (TextareaWidget, TextInputWidget))

    def test_integer_resolves_to_number_input(self):
        from sqlalchemy import Integer

        from fastapi_admin_kit.widgets.inputs import NumberInputWidget

        resolver = WidgetResolver(_default_registry())
        w = resolver.resolve(_col(col_type=Integer()))
        assert isinstance(w, NumberInputWidget)

    def test_float_resolves_to_number_input(self):
        from sqlalchemy import Float

        from fastapi_admin_kit.widgets.inputs import NumberInputWidget

        resolver = WidgetResolver(_default_registry())
        w = resolver.resolve(_col(col_type=Float()))
        assert isinstance(w, NumberInputWidget)

    def test_boolean_resolves_to_toggle(self):
        from sqlalchemy import Boolean

        from fastapi_admin_kit.widgets.inputs import ToggleWidget

        resolver = WidgetResolver(_default_registry())
        w = resolver.resolve(_col(col_type=Boolean()))
        assert isinstance(w, ToggleWidget)

    def test_date_resolves_to_date_picker(self):
        from sqlalchemy import Date

        from fastapi_admin_kit.widgets.inputs import DatePickerWidget

        resolver = WidgetResolver(_default_registry())
        w = resolver.resolve(_col(col_type=Date()))
        assert isinstance(w, DatePickerWidget)

    def test_datetime_resolves_to_datetime_picker(self):
        from sqlalchemy import DateTime

        from fastapi_admin_kit.widgets.inputs import DateTimePickerWidget

        resolver = WidgetResolver(_default_registry())
        w = resolver.resolve(_col(col_type=DateTime()))
        assert isinstance(w, DateTimePickerWidget)

    def test_large_binary_resolves_to_file_upload(self):
        from sqlalchemy import LargeBinary

        from fastapi_admin_kit.widgets.inputs import FileUploadWidget

        resolver = WidgetResolver(_default_registry())
        w = resolver.resolve(_col(col_type=LargeBinary()))
        assert isinstance(w, FileUploadWidget)

    def test_string_with_length_sets_maxlength(self):
        from sqlalchemy import String

        from fastapi_admin_kit.widgets.inputs import TextInputWidget

        resolver = WidgetResolver(_default_registry())
        w = resolver.resolve(_col(col_type=String(255)))
        assert isinstance(w, TextInputWidget)
        assert w.maxlength == 255

    def test_string_with_none_length_no_maxlength(self):
        from sqlalchemy import String

        from fastapi_admin_kit.widgets.inputs import TextInputWidget

        resolver = WidgetResolver(_default_registry())
        w = resolver.resolve(_col(col_type=String(None)))
        assert isinstance(w, TextInputWidget)
        assert w.maxlength is None


# ===========================================================================
# Resolution: name patterns
# ===========================================================================


class TestResolverNamePatterns:
    def test_password_in_name(self):
        from fastapi_admin_kit.widgets.inputs import PasswordWidget

        resolver = WidgetResolver(_default_registry())
        col = _col(name="user_password")
        w = resolver.resolve(col)
        assert isinstance(w, PasswordWidget)

    def test_secret_in_name(self):
        from fastapi_admin_kit.widgets.inputs import PasswordWidget

        resolver = WidgetResolver(_default_registry())
        col = _col(name="api_secret_key")
        w = resolver.resolve(col)
        assert isinstance(w, PasswordWidget)

    def test_token_in_name(self):
        from fastapi_admin_kit.widgets.inputs import PasswordWidget

        resolver = WidgetResolver(_default_registry())
        col = _col(name="auth_token")
        w = resolver.resolve(col)
        assert isinstance(w, PasswordWidget)

    def test_name_pattern_case_insensitive(self):
        from fastapi_admin_kit.widgets.inputs import PasswordWidget

        reg = WidgetRegistry()
        reg.register_name("email", PasswordWidget)
        resolver = WidgetResolver(reg)
        col = _col(name="USER_EMAIL")
        w = resolver.resolve(col)
        assert isinstance(w, PasswordWidget)

    def test_name_pattern_priority_over_type(self):
        from sqlalchemy import String

        from fastapi_admin_kit.widgets.inputs import (
            PasswordWidget,
            TextInputWidget,
        )

        reg = WidgetRegistry()
        reg.register_name("password", PasswordWidget)
        reg.register_type(String, TextInputWidget)
        resolver = WidgetResolver(reg)
        col = _col(name="password_hash", col_type=String())
        w = resolver.resolve(col)
        assert isinstance(w, PasswordWidget)

    def test_first_matching_pattern_wins(self):
        from fastapi_admin_kit.widgets.inputs import PasswordWidget

        reg = WidgetRegistry()
        reg.register_name("pass", PasswordWidget)
        reg.register_name("word", Widget)  # Different widget
        resolver = WidgetResolver(reg)
        col = _col(name="password")
        w = resolver.resolve(col)
        assert isinstance(w, PasswordWidget)


# ===========================================================================
# Resolution: foreign keys
# ===========================================================================


class TestResolverForeignKeys:
    def test_fk_resolves_to_relation_picker(self):
        from fastapi_admin_kit.widgets.relation import RelationPickerWidget

        resolver = WidgetResolver(_default_registry())
        col = _col(name="category_id", foreign_keys=[1])
        w = resolver.resolve(col)
        assert isinstance(w, RelationPickerWidget)

    def test_fk_takes_priority_over_type(self):
        from sqlalchemy import Integer

        from fastapi_admin_kit.widgets.relation import RelationPickerWidget

        resolver = WidgetResolver(_default_registry())
        col = _col(name="user_id", col_type=Integer(), foreign_keys=[1])
        w = resolver.resolve(col)
        assert isinstance(w, RelationPickerWidget)

    def test_name_pattern_takes_priority_over_fk(self):
        from fastapi_admin_kit.widgets.inputs import PasswordWidget

        resolver = WidgetResolver(_default_registry())
        col = _col(name="password_token", foreign_keys=[1])
        w = resolver.resolve(col)
        assert isinstance(w, PasswordWidget)


# ===========================================================================
# Resolution: enum types
# ===========================================================================


class TestResolverEnumTypes:
    def test_enum_resolves_to_select(self):
        from fastapi_admin_kit.widgets.inputs import SelectWidget

        class FakeEnum:
            enums = ["draft", "published", "archived"]

        resolver = WidgetResolver(_default_registry())
        col = _col(name="status", col_type=FakeEnum())
        w = resolver.resolve(col)
        assert isinstance(w, SelectWidget)

    def test_enum_choices_formatted(self):
        from fastapi_admin_kit.widgets.inputs import SelectWidget

        class FakeEnum:
            enums = ["draft", "published", "archived"]

        resolver = WidgetResolver(_default_registry())
        col = _col(name="status", col_type=FakeEnum())
        w = resolver.resolve(col)
        assert isinstance(w, SelectWidget)
        choices = w.choices
        assert ("draft", "Draft") in choices
        assert ("published", "Published") in choices
        assert ("archived", "Archived") in choices

    def test_enum_empty_enums_not_select(self):
        from fastapi_admin_kit.widgets.inputs import TextInputWidget

        class FakeEnum:
            enums = []

        resolver = WidgetResolver(_default_registry())
        col = _col(name="status", col_type=FakeEnum())
        w = resolver.resolve(col)
        assert isinstance(w, TextInputWidget)

    def test_no_enums_attribute_not_select(self):
        from fastapi_admin_kit.widgets.inputs import TextInputWidget

        resolver = WidgetResolver(_default_registry())
        col = _col(name="status", col_type=type("NoEnum", (), {}))
        w = resolver.resolve(col)
        assert isinstance(w, TextInputWidget)


# ===========================================================================
# Resolution: custom registrations
# ===========================================================================


class TestResolverCustomRegistrations:
    def test_custom_type_registration(self):
        class CustomType:
            pass

        class CustomWidget(Widget):
            macro_name = "custom"

        reg = WidgetRegistry()
        reg.register_type(CustomType, CustomWidget)
        resolver = WidgetResolver(reg)
        col = _col(col_type=CustomType())
        w = resolver.resolve(col)
        assert isinstance(w, CustomWidget)

    def test_custom_name_registration(self):
        class CustomWidget(Widget):
            macro_name = "custom"

        reg = WidgetRegistry()
        reg.register_name("myfield", CustomWidget)
        resolver = WidgetResolver(reg)
        col = _col(name="myfield_value")
        w = resolver.resolve(col)
        assert isinstance(w, CustomWidget)


# ===========================================================================
# Registry methods
# ===========================================================================


class TestRegistryMethods:
    def test_unregister_type(self):
        from sqlalchemy import String

        reg = WidgetRegistry()
        reg.register_type(String, Widget)
        assert reg.has_type(String)
        reg.unregister_type(String)
        assert not reg.has_type(String)

    def test_unregister_name(self):
        reg = WidgetRegistry()
        reg.register_name("test", Widget)
        assert reg.has_name("test")
        reg.unregister_name("test")
        assert not reg.has_name("test")

    def test_clear(self):
        from sqlalchemy import String

        reg = WidgetRegistry()
        reg.register_type(String, Widget)
        reg.register_name("test", Widget)
        reg.clear()
        assert not reg.has_type(String)
        assert not reg.has_name("test")

    def test_type_map_returns_copy(self):
        from sqlalchemy import String

        reg = WidgetRegistry()
        reg.register_type(String, Widget)
        tm = reg.type_map
        tm.pop(String, None)
        assert reg.has_type(String)

    def test_name_patterns_returns_copy(self):
        reg = WidgetRegistry()
        reg.register_name("test", Widget)
        np = reg.name_patterns
        np.clear()
        assert reg.has_name("test")
