"""Inline admin classes for editing related objects on the parent form.

Usage::

    from fastapi_admin_kit.inline import TabularInline, StackedInline

    class OrderItemInline(TabularInline):
        model = OrderItem
        fields = ["product", "quantity", "price"]
        extra = 1

    class OrderAdmin(ModelAdmin):
        inlines = [OrderItemInline]
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class InlineModelAdmin:
    """Base class for inline model admin configuration.

    Subclass this to define how related objects are displayed inline
    on the parent model's form.
    """

    # The related model class
    model: type | None = None

    # Fields to display in the inline form
    fields: list[str] | None = None

    # Fields to exclude from the inline form
    exclude: list[str] | None = None

    # Number of empty forms to display
    extra: int = 1

    # Maximum number of forms (None = unlimited)
    max_num: int | None = None

    # Minimum number of forms
    min_num: int = 0

    # Whether to show delete checkboxes
    can_delete: bool = True

    # Ordering for the related objects
    ordering: list[str] | None = None

    # Verbose names (auto-detected from model if not set)
    verbose_name: str | None = None
    verbose_name_plural: str | None = None

    # Fields displayed as read-only in the inline
    readonly_fields: list[str] | None = None

    # Widget overrides for specific fields
    formfield_overrides: dict[str, Any] = {}

    # Inline type: "stacked" or "tabular" — set by subclass
    inline_type: str = "stacked"

    # FK field name on the related model that points to the parent
    # Auto-detected from relationship if not set
    fk_name: str | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Auto-detect verbose_name from model if not set
        if cls.model is not None:
            if cls.verbose_name is None:
                cls.verbose_name = cls.model.__name__
            if cls.verbose_name_plural is None:
                name = cls.verbose_name
                if name.endswith("y") and len(name) > 1 and name[-2].lower() not in "aeiou":
                    cls.verbose_name_plural = f"{name[:-1]}ies"
                else:
                    cls.verbose_name_plural = f"{name}s"

    def get_form_fields(self, columns: list[Any] | None = None) -> list[str]:
        """Return the list of field names to display in the inline form."""
        if self.fields is not None:
            return self.fields
        if columns is not None:
            return [c.name for c in columns if not c.primary_key]
        return []

    def get_readonly_fields(self) -> list[str]:
        """Return list of readonly field names."""
        return self.readonly_fields or []

    def get_formfield_overrides(self) -> dict[str, Any]:
        """Return widget overrides for inline fields."""
        return self.formfield_overrides


class StackedInline(InlineModelAdmin):
    """Inline admin that displays related objects as stacked form blocks."""

    inline_type: str = "stacked"


class TabularInline(InlineModelAdmin):
    """Inline admin that displays related objects as compact table rows."""

    inline_type: str = "tabular"
