"""WidgetRegistry — stores type-to-widget and name-to-widget mappings.

This class handles ONLY registration/storage of widget mappings.
Resolution logic lives in WidgetResolver (fastapi_admin_kit/widgets/resolver.py).

Resolution order (documented here for reference, implemented in WidgetResolver):
  1. Exact field name pattern  ->  e.g. "password" -> PasswordWidget
  2. FK column present         ->  RelationPickerWidget
  3. Enum type                 ->  SelectWidget
  4. SQLAlchemy type match     ->  via type_map dict
  5. Fallback                  ->  TextInputWidget
"""

from __future__ import annotations

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

from fastapi_admin_kit.widgets.base import Widget
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


class WidgetRegistry:
    """Stores SQLAlchemy column type and name pattern mappings to widget classes.

    This class is responsible ONLY for registration and storage.
    Use WidgetResolver to determine which widget to use for a column.
    """

    def __init__(self) -> None:
        self._type_map: dict[type, type[Widget]] = {}
        self._name_patterns: list[tuple[str, type[Widget]]] = []

    @property
    def type_map(self) -> dict[type, type[Widget]]:
        """Read-only access to the type-to-widget mapping."""
        return dict(self._type_map)

    @property
    def name_patterns(self) -> list[tuple[str, type[Widget]]]:
        """Read-only access to the name pattern list."""
        return list(self._name_patterns)

    def register_type(self, sa_type: type, widget_cls: type[Widget]) -> None:
        """Register a widget class for a SQLAlchemy column type."""
        self._type_map[sa_type] = widget_cls

    def unregister_type(self, sa_type: type) -> None:
        """Remove a registered type mapping."""
        self._type_map.pop(sa_type, None)

    def register_name(self, pattern: str, widget_cls: type[Widget]) -> None:
        """Register a widget class for a name pattern (case-insensitive substring)."""
        self._name_patterns.append((pattern.lower(), widget_cls))

    def unregister_name(self, pattern: str) -> None:
        """Remove all registrations for a name pattern."""
        self._name_patterns = [(p, w) for p, w in self._name_patterns if p != pattern.lower()]

    def clear(self) -> None:
        """Remove all registered mappings."""
        self._type_map.clear()
        self._name_patterns.clear()

    def has_type(self, sa_type: type) -> bool:
        """Check if a type is registered."""
        return sa_type in self._type_map

    def has_name(self, pattern: str) -> bool:
        """Check if a name pattern is registered."""
        return any(p == pattern.lower() for p, _ in self._name_patterns)


widget_registry = WidgetRegistry()

widget_registry.register_type(String, TextInputWidget)
widget_registry.register_type(Text, TextareaWidget)
widget_registry.register_type(Integer, NumberInputWidget)
widget_registry.register_type(Float, NumberInputWidget)
widget_registry.register_type(Numeric, NumberInputWidget)
widget_registry.register_type(Boolean, ToggleWidget)
widget_registry.register_type(Date, DatePickerWidget)
widget_registry.register_type(DateTime, DateTimePickerWidget)
widget_registry.register_type(LargeBinary, FileUploadWidget)
widget_registry.register_type(Uuid, TextInputWidget)

widget_registry.register_name("password", PasswordWidget)
widget_registry.register_name("secret", PasswordWidget)
widget_registry.register_name("token", PasswordWidget)
