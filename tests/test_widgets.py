"""Tests for fastapi_admin_kit.widgets — base, inputs, relation, registry."""

import json
from datetime import date, datetime, time

import pytest

from fastapi_admin_kit.types import ColumnMeta, FieldMeta
from fastapi_admin_kit.widgets.base import Widget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _field(name: str = "title", **overrides) -> FieldMeta:
    defaults = dict(name=name, label=name.replace("_", " ").title(), required=False)
    defaults.update(overrides)
    return FieldMeta(**defaults)


def _col(name: str = "title", col_type=None, **overrides):
    defaults = dict(name=name, type=col_type or type("String", (), {}))
    defaults.update(overrides)
    return ColumnMeta(**defaults)


# ===========================================================================
# 4.1 Widget ABC
# ===========================================================================


class TestWidgetBase:
    def test_has_macro_name(self):
        assert hasattr(Widget, "macro_name")

    def test_render_context_returns_dict_with_field_meta_and_value(self):
        w = Widget()
        field = _field()
        ctx = w.render_context(field, "hello")
        assert ctx["field"] is field
        assert ctx["value"] == "hello"
        assert ctx["name"] == "title"
        assert ctx["id"] == "field-title"

    def test_parse_returns_none_for_none(self):
        w = Widget()
        assert w.parse(None) is None

    def test_parse_returns_none_for_empty_string(self):
        w = Widget()
        assert w.parse("") is None

    def test_parse_passthrough(self):
        w = Widget()
        assert w.parse("abc") == "abc"

    def test_validate_required_returns_error(self):
        w = Widget()
        field = _field(required=True)
        errors = w.validate(None, field)
        assert any("required" in e.lower() for e in errors)

    def test_validate_not_required_returns_empty(self):
        w = Widget()
        field = _field(required=False)
        errors = w.validate(None, field)
        assert errors == []


# ===========================================================================
# 4.2 Built-in widgets
# ===========================================================================


class TestTextInputWidget:
    def test_parse_string(self):
        from fastapi_admin_kit.widgets.inputs import TextInputWidget
        w = TextInputWidget()
        assert w.parse("hello") == "hello"

    def test_parse_none(self):
        from fastapi_admin_kit.widgets.inputs import TextInputWidget
        w = TextInputWidget()
        assert w.parse(None) is None

    def test_validate_maxlength(self):
        from fastapi_admin_kit.widgets.inputs import TextInputWidget
        w = TextInputWidget(maxlength=5)
        field = _field()
        errors = w.validate("toolong", field)
        assert any("5 characters" in e for e in errors)

    def test_validate_maxlength_ok(self):
        from fastapi_admin_kit.widgets.inputs import TextInputWidget
        w = TextInputWidget(maxlength=10)
        field = _field()
        errors = w.validate("short", field)
        assert errors == []

    def test_render_context_includes_maxlength(self):
        from fastapi_admin_kit.widgets.inputs import TextInputWidget
        w = TextInputWidget(maxlength=100)
        field = _field()
        ctx = w.render_context(field, "val")
        assert ctx["maxlength"] == 100


class TestTextareaWidget:
    def test_parse(self):
        from fastapi_admin_kit.widgets.inputs import TextareaWidget
        w = TextareaWidget()
        assert w.parse("multiline") == "multiline"

    def test_render_context_rows(self):
        from fastapi_admin_kit.widgets.inputs import TextareaWidget
        w = TextareaWidget(rows=10)
        field = _field()
        ctx = w.render_context(field, "")
        assert ctx["rows"] == 10


class TestNumberInputWidget:
    def test_parse_int(self):
        from fastapi_admin_kit.widgets.inputs import NumberInputWidget
        w = NumberInputWidget()
        assert w.parse("42") == 42

    def test_parse_float(self):
        from fastapi_admin_kit.widgets.inputs import NumberInputWidget
        w = NumberInputWidget()
        assert w.parse("3.14") == pytest.approx(3.14)

    def test_parse_none(self):
        from fastapi_admin_kit.widgets.inputs import NumberInputWidget
        w = NumberInputWidget()
        assert w.parse(None) is None

    def test_validate_non_numeric(self):
        from fastapi_admin_kit.widgets.inputs import NumberInputWidget
        w = NumberInputWidget()
        field = _field()
        errors = w.validate("abc", field)
        assert any("number" in e.lower() for e in errors)

    def test_render_context_step(self):
        from fastapi_admin_kit.widgets.inputs import NumberInputWidget
        w = NumberInputWidget(step="0.01", min="0", max="100")
        field = _field()
        ctx = w.render_context(field, 0)
        assert ctx["step"] == "0.01"
        assert ctx["min"] == "0"
        assert ctx["max"] == "100"


class TestToggleWidget:
    def test_parse_on(self):
        from fastapi_admin_kit.widgets.inputs import ToggleWidget
        w = ToggleWidget()
        assert w.parse("on") is True

    def test_parse_off(self):
        from fastapi_admin_kit.widgets.inputs import ToggleWidget
        w = ToggleWidget()
        assert w.parse(None) is False

    def test_parse_true_string(self):
        from fastapi_admin_kit.widgets.inputs import ToggleWidget
        w = ToggleWidget()
        assert w.parse("true") is True

    def test_always_valid(self):
        from fastapi_admin_kit.widgets.inputs import ToggleWidget
        w = ToggleWidget()
        field = _field()
        assert w.validate(True, field) == []
        assert w.validate(False, field) == []


class TestSelectWidget:
    def test_parse(self):
        from fastapi_admin_kit.widgets.inputs import SelectWidget
        w = SelectWidget(choices=[("a", "A"), ("b", "B")])
        assert w.parse("a") == "a"

    def test_validate_invalid_choice(self):
        from fastapi_admin_kit.widgets.inputs import SelectWidget
        w = SelectWidget(choices=[("a", "A"), ("b", "B")])
        field = _field()
        errors = w.validate("z", field)
        assert any("not a valid choice" in e.lower() for e in errors)

    def test_validate_valid_choice(self):
        from fastapi_admin_kit.widgets.inputs import SelectWidget
        w = SelectWidget(choices=[("a", "A")])
        field = _field()
        assert w.validate("a", field) == []

    def test_render_context_choices(self):
        from fastapi_admin_kit.widgets.inputs import SelectWidget
        choices = [("x", "X")]
        w = SelectWidget(choices=choices)
        field = _field()
        ctx = w.render_context(field, "x")
        assert ctx["choices"] is choices


class TestDatePickerWidget:
    def test_parse_valid_date(self):
        from fastapi_admin_kit.widgets.inputs import DatePickerWidget
        w = DatePickerWidget()
        result = w.parse("2024-01-15")
        assert isinstance(result, date)
        assert result.year == 2024

    def test_parse_none(self):
        from fastapi_admin_kit.widgets.inputs import DatePickerWidget
        w = DatePickerWidget()
        assert w.parse(None) is None

    def test_parse_invalid(self):
        from fastapi_admin_kit.widgets.inputs import DatePickerWidget
        w = DatePickerWidget()
        result = w.parse("not-a-date")
        assert result == "not-a-date"

    def test_validate_non_date(self):
        from fastapi_admin_kit.widgets.inputs import DatePickerWidget
        w = DatePickerWidget()
        field = _field()
        errors = w.validate("not-a-date", field)
        assert any("valid date" in e.lower() for e in errors)


class TestDateTimePickerWidget:
    def test_parse_valid(self):
        from fastapi_admin_kit.widgets.inputs import DateTimePickerWidget
        w = DateTimePickerWidget()
        result = w.parse("2024-01-15T14:30")
        assert isinstance(result, datetime)

    def test_parse_none(self):
        from fastapi_admin_kit.widgets.inputs import DateTimePickerWidget
        w = DateTimePickerWidget()
        assert w.parse(None) is None

    def test_validate_non_datetime(self):
        from fastapi_admin_kit.widgets.inputs import DateTimePickerWidget
        w = DateTimePickerWidget()
        field = _field()
        errors = w.validate("bad", field)
        assert any("date and time" in e.lower() for e in errors)


class TestJsonEditorWidget:
    def test_parse_valid_json(self):
        from fastapi_admin_kit.widgets.inputs import JsonEditorWidget
        w = JsonEditorWidget()
        result = w.parse('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_none(self):
        from fastapi_admin_kit.widgets.inputs import JsonEditorWidget
        w = JsonEditorWidget()
        assert w.parse(None) is None

    def test_parse_invalid_json(self):
        from fastapi_admin_kit.widgets.inputs import JsonEditorWidget
        w = JsonEditorWidget()
        result = w.parse("{invalid}")
        assert result is None

    def test_validate_invalid_json_string(self):
        from fastapi_admin_kit.widgets.inputs import JsonEditorWidget
        w = JsonEditorWidget()
        field = _field()
        errors = w.validate("{bad json}", field)
        assert any("json" in e.lower() for e in errors)


class TestPasswordWidget:
    def test_parse_returns_raw_value(self):
        from fastapi_admin_kit.widgets.inputs import PasswordWidget
        w = PasswordWidget()
        result = w.parse("secret123")
        assert result == "secret123"

    def test_parse_none(self):
        from fastapi_admin_kit.widgets.inputs import PasswordWidget
        w = PasswordWidget()
        assert w.parse(None) is None

    def test_render_context_never_prefills(self):
        from fastapi_admin_kit.widgets.inputs import PasswordWidget
        w = PasswordWidget()
        field = _field()
        ctx = w.render_context(field, "existing-hash")
        assert ctx["value"] == ""


class TestReadOnlyWidget:
    def test_parse_returns_none(self):
        from fastapi_admin_kit.widgets.inputs import ReadOnlyWidget
        w = ReadOnlyWidget()
        assert w.parse("anything") is None

    def test_always_valid(self):
        from fastapi_admin_kit.widgets.inputs import ReadOnlyWidget
        w = ReadOnlyWidget()
        field = _field()
        assert w.validate("x", field) == []


class TestHiddenWidget:
    def test_macro_name(self):
        from fastapi_admin_kit.widgets.inputs import HiddenWidget
        w = HiddenWidget()
        assert w.macro_name == "hidden"


# ===========================================================================
# 4.3 Relation widgets
# ===========================================================================


class TestRelationPickerWidget:
    def test_parse_int_fk(self):
        from fastapi_admin_kit.widgets.relation import RelationPickerWidget
        w = RelationPickerWidget(related_table="categories", related_verbose="Category")
        assert w.parse("42") == 42

    def test_parse_none(self):
        from fastapi_admin_kit.widgets.relation import RelationPickerWidget
        w = RelationPickerWidget(related_table="categories", related_verbose="Category")
        assert w.parse(None) is None

    def test_parse_uuid_fk(self):
        from fastapi_admin_kit.widgets.relation import RelationPickerWidget
        w = RelationPickerWidget(related_table="categories", related_verbose="Category")
        result = w.parse("550e8400-e29b-41d4-a716-446655440000")
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_render_context(self):
        from fastapi_admin_kit.widgets.relation import RelationPickerWidget
        w = RelationPickerWidget(related_table="categories", related_verbose="Category")
        field = _field("category_id")
        ctx = w.render_context(field, 3)
        assert ctx["related_table"] == "categories"
        assert ctx["related_verbose"] == "Category"
        assert ctx["value"] == 3


class TestMultiRelationWidget:
    def test_parse_list(self):
        from fastapi_admin_kit.widgets.relation import MultiRelationWidget
        w = MultiRelationWidget()
        result = w.parse(["1", "2", "3"])
        assert result == ["1", "2", "3"]

    def test_parse_none(self):
        from fastapi_admin_kit.widgets.relation import MultiRelationWidget
        w = MultiRelationWidget()
        assert w.parse(None) == []

    def test_parse_single(self):
        from fastapi_admin_kit.widgets.relation import MultiRelationWidget
        w = MultiRelationWidget()
        assert w.parse("5") == ["5"]

    def test_always_valid(self):
        from fastapi_admin_kit.widgets.relation import MultiRelationWidget
        w = MultiRelationWidget()
        field = _field()
        assert w.validate(["1", "2"], field) == []


# ===========================================================================
# 4.4 WidgetRegistry
# ===========================================================================


class TestWidgetRegistry:
    def test_register_and_get(self):
        from fastapi_admin_kit.widgets.registry import WidgetRegistry
        from fastapi_admin_kit.widgets.resolver import WidgetResolver
        from fastapi_admin_kit.widgets.inputs import TextInputWidget
        reg = WidgetRegistry()
        reg.register_type(str, TextInputWidget)
        resolver = WidgetResolver(reg)
        w = resolver.resolve(_col(col_type=str))
        assert isinstance(w, TextInputWidget)

    def test_fallback_to_text_input(self):
        from fastapi_admin_kit.widgets.registry import WidgetRegistry
        from fastapi_admin_kit.widgets.resolver import WidgetResolver
        from fastapi_admin_kit.widgets.inputs import TextInputWidget
        reg = WidgetRegistry()
        resolver = WidgetResolver(reg)
        w = resolver.resolve(_col(col_type=type("Unknown", (), {})))
        assert isinstance(w, TextInputWidget)

    def test_fk_resolves_to_relation_picker(self):
        from fastapi_admin_kit.widgets.registry import WidgetRegistry
        from fastapi_admin_kit.widgets.resolver import WidgetResolver
        from fastapi_admin_kit.widgets.relation import RelationPickerWidget
        reg = WidgetRegistry()
        resolver = WidgetResolver(reg)
        col = _col(name="category_id", foreign_keys=[1])
        w = resolver.resolve(col)
        assert isinstance(w, RelationPickerWidget)

    def test_name_pattern_password(self):
        from fastapi_admin_kit.widgets.registry import WidgetRegistry
        from fastapi_admin_kit.widgets.resolver import WidgetResolver
        from fastapi_admin_kit.widgets.inputs import PasswordWidget
        reg = WidgetRegistry()
        reg.register_name("password", PasswordWidget)
        resolver = WidgetResolver(reg)
        col = _col(name="user_password")
        w = resolver.resolve(col)
        assert isinstance(w, PasswordWidget)

    def test_name_pattern_takes_priority_over_type(self):
        from fastapi_admin_kit.widgets.registry import WidgetRegistry
        from fastapi_admin_kit.widgets.resolver import WidgetResolver
        from fastapi_admin_kit.widgets.inputs import PasswordWidget, TextInputWidget
        reg = WidgetRegistry()
        reg.register_name("password", PasswordWidget)
        reg.register_type(str, TextInputWidget)
        resolver = WidgetResolver(reg)
        col = _col(name="password_hash", col_type=str)
        w = resolver.resolve(col)
        assert isinstance(w, PasswordWidget)
