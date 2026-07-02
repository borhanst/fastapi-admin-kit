"""Widget base class — two-layer: Python class (parse + validate) + Jinja2 macro (HTML)."""

from __future__ import annotations

from typing import Any

from fastapi_admin_kit.types import FieldMeta


class Widget:
    """Base widget class.

    Stateless: receives FieldMeta + value at render/validate time.
    Override ``parse`` to transform raw form data.
    Override ``validate`` to add custom validation.
    Override ``render_context`` to customise template variables.
    """

    macro_name: str = "text_input"

    def render_context(self, field: FieldMeta, value: Any) -> dict:
        """Variables injected into the Jinja2 macro."""
        return {
            "field": field,
            "value": value if value is not None else "",
            "id": f"field-{field.name}",
            "name": field.name,
        }

    def parse(self, raw: str | list | None) -> Any:
        """Convert raw FormData string to typed Python value."""
        if raw is None or raw == "":
            return None
        return raw

    def validate(self, value: Any, field: FieldMeta) -> list[str]:
        """Return a list of error messages. Empty list means valid."""
        errors: list[str] = []
        if field.required and (value is None or value == ""):
            errors.append(f"{field.label} is required.")
        return errors

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} macro={self.macro_name!r}>"
