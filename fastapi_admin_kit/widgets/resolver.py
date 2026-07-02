"""WidgetResolver — dedicated class for resolving which widget to use for a column.

Resolution order (fixed, cannot be short-circuited):
  1. Exact field name pattern  ->  e.g. "password" -> PasswordWidget
  2. FK column present         ->  RelationPickerWidget
  3. Enum type                 ->  SelectWidget
  4. SQLAlchemy type match     ->  via type_registry
  5. Fallback                  ->  TextInputWidget

This class separates resolution logic from registration (WidgetRegistry),
creating a clear seam between "what widgets exist" and "which widget to use."
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi_admin_kit.types import ColumnMeta

if TYPE_CHECKING:
    from fastapi_admin_kit.widgets.base import Widget
    from fastapi_admin_kit.widgets.registry import WidgetRegistry


class WidgetResolver:
    """Resolves which widget instance to use for a given ColumnMeta.

    Uses dependency injection for the WidgetRegistry, making resolution
    testable and separable from registration concerns.

    Supports both SQLAlchemy types and Python built-in types (used by SQLModel).
    """

    # Python type to SQLAlchemy type name mapping for SQLModel support
    PYTHON_TYPE_MAP: dict[type, str] = {
        int: "Integer",
        str: "String",
        float: "Float",
        bool: "Boolean",
    }

    def __init__(self, registry: WidgetRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> WidgetRegistry:
        """Get the underlying widget registry."""
        return self._registry

    def resolve(self, col: ColumnMeta) -> Widget:
        """Resolve which widget instance to use for a given column.

        Resolution priority:
          1. Name pattern match (case-insensitive substring)
          2. Foreign key column -> RelationPickerWidget
          3. Enum type -> SelectWidget with choices
          4. SQLAlchemy type match via registry
          5. Python type match (for SQLModel)
          6. Fallback -> TextInputWidget
        """
        for pattern, widget_cls in self._registry.name_patterns:
            if pattern in col.name.lower():
                return widget_cls()

        if col.foreign_keys:
            from fastapi_admin_kit.widgets.relation import RelationPickerWidget

            return RelationPickerWidget()

        col_type = col.type
        if hasattr(col_type, "enums") and col_type.enums:
            choices = [(v, v.replace("_", " ").title()) for v in col_type.enums]
            from fastapi_admin_kit.widgets.inputs import SelectWidget

            return SelectWidget(choices=choices)

        # Try SQLAlchemy type match via registry
        for sa_type, widget_cls in self._registry.type_map.items():
            if isinstance(col_type, sa_type):
                from fastapi_admin_kit.widgets.inputs import TextInputWidget

                has_length = hasattr(col_type, "length") and col_type.length
                if widget_cls == TextInputWidget and has_length:
                    return TextInputWidget(maxlength=col_type.length)
                return widget_cls()

        # Handle Python built-in types (used by SQLModel)
        if col_type in self.PYTHON_TYPE_MAP:
            import sqlalchemy as sa

            sa_type_name = self.PYTHON_TYPE_MAP[col_type]
            sa_type = getattr(sa, sa_type_name, None)
            if sa_type is not None:
                for sa_registered_type, widget_cls in self._registry.type_map.items():
                    if sa_type is sa_registered_type or (
                        isinstance(sa_type, type) and isinstance(sa_type(), sa_registered_type)
                    ):
                        return widget_cls()

        from fastapi_admin_kit.widgets.inputs import TextInputWidget

        return TextInputWidget()
