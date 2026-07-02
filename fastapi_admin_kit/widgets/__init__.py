"""Widgets module — base class, all built-in widgets, WidgetRegistry, WidgetResolver."""

from __future__ import annotations

from fastapi_admin_kit.widgets.base import Widget
from fastapi_admin_kit.widgets.inputs import (
    DatePickerWidget,
    DateTimePickerWidget,
    FileUploadWidget,
    HiddenWidget,
    ImageUploadWidget,
    JsonEditorWidget,
    NumberInputWidget,
    PasswordWidget,
    ReadOnlyWidget,
    SelectWidget,
    TextareaWidget,
    TextInputWidget,
    ToggleWidget,
)
from fastapi_admin_kit.widgets.registry import WidgetRegistry
from fastapi_admin_kit.widgets.relation import MultiRelationWidget, RelationPickerWidget
from fastapi_admin_kit.widgets.resolver import WidgetResolver

__all__ = [
    "Widget",
    "WidgetRegistry",
    "WidgetResolver",
    "TextInputWidget",
    "TextareaWidget",
    "NumberInputWidget",
    "ToggleWidget",
    "DatePickerWidget",
    "DateTimePickerWidget",
    "SelectWidget",
    "JsonEditorWidget",
    "PasswordWidget",
    "ReadOnlyWidget",
    "HiddenWidget",
    "FileUploadWidget",
    "ImageUploadWidget",
    "RelationPickerWidget",
    "MultiRelationWidget",
]
