"""Built-in widget classes — all standard form widgets per spec."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from fastapi_admin_kit.types import FieldMeta
from fastapi_admin_kit.widgets.base import Widget


class TextInputWidget(Widget):
    macro_name = "text_input"

    def __init__(self, maxlength: int | None = None):
        self.maxlength = maxlength

    def render_context(self, field: FieldMeta, value: Any) -> dict:
        ctx = super().render_context(field, value)
        ctx["maxlength"] = self.maxlength
        return ctx

    def validate(self, value: Any, field: FieldMeta) -> list[str]:
        errors = super().validate(value, field)
        if value and self.maxlength and len(value) > self.maxlength:
            errors.append(f"{field.label} must be {self.maxlength} characters or fewer.")
        return errors


class TextareaWidget(Widget):
    macro_name = "textarea"

    def __init__(self, rows: int = 5):
        self.rows = rows

    def render_context(self, field: FieldMeta, value: Any) -> dict:
        ctx = super().render_context(field, value)
        ctx["rows"] = self.rows
        return ctx


class NumberInputWidget(Widget):
    macro_name = "number_input"

    def __init__(self, step: str = "1", min: str | None = None, max: str | None = None):
        self.step = step
        self.min = min
        self.max = max

    def render_context(self, field: FieldMeta, value: Any) -> dict:
        ctx = super().render_context(field, value)
        ctx.update({"step": self.step, "min": self.min, "max": self.max})
        return ctx

    def parse(self, raw: str | None) -> int | float | None:
        if raw is None or raw == "":
            return None
        try:
            return int(raw) if "." not in str(raw) else float(raw)
        except ValueError:
            return raw

    def validate(self, value: Any, field: FieldMeta) -> list[str]:
        errors = super().validate(value, field)
        if value is not None:
            try:
                float(value)
            except (TypeError, ValueError):
                errors.append(f"{field.label} must be a number.")
        return errors


class ToggleWidget(Widget):
    macro_name = "toggle"

    def parse(self, raw: str | None) -> bool:
        if raw is None:
            return False
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("on", "true", "1", "yes")

    def validate(self, value: Any, field: FieldMeta) -> list[str]:
        return []


class SelectWidget(Widget):
    macro_name = "select"

    def __init__(self, choices: list[tuple[str, str]] | None = None):
        self.choices = choices or []

    def render_context(self, field: FieldMeta, value: Any) -> dict:
        ctx = super().render_context(field, value)
        ctx["choices"] = self.choices
        return ctx

    def validate(self, value: Any, field: FieldMeta) -> list[str]:
        errors = super().validate(value, field)
        if value and self.choices:
            valid = {c[0] for c in self.choices}
            if value not in valid:
                errors.append(f"'{value}' is not a valid choice for {field.label}.")
        return errors


class DatePickerWidget(Widget):
    macro_name = "date_picker"

    def render_context(self, field: FieldMeta, value: Any) -> dict:
        ctx = super().render_context(field, value)
        if isinstance(value, date) and not isinstance(value, datetime):
            ctx["value"] = value.isoformat()
        elif isinstance(value, datetime):
            ctx["value"] = value.date().isoformat()
        return ctx

    def parse(self, raw: str | None) -> date | str | None:
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return raw

    def validate(self, value: Any, field: FieldMeta) -> list[str]:
        errors = super().validate(value, field)
        if value is not None and not isinstance(value, date):
            errors.append(f"{field.label} must be a valid date.")
        return errors


class DateTimePickerWidget(Widget):
    macro_name = "datetime_picker"

    def render_context(self, field: FieldMeta, value: Any) -> dict:
        ctx = super().render_context(field, value)
        if isinstance(value, datetime):
            ctx["value"] = value.replace(tzinfo=None).isoformat(timespec="minutes")
        elif isinstance(value, date):
            combined = datetime.combine(value, datetime.min.time())
            ctx["value"] = combined.isoformat(timespec="minutes")
        return ctx

    def parse(self, raw: str | None) -> datetime | str | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return raw

    def validate(self, value: Any, field: FieldMeta) -> list[str]:
        errors = super().validate(value, field)
        if value is not None and not isinstance(value, datetime):
            errors.append(f"{field.label} must be a valid date and time.")
        return errors


class JsonEditorWidget(Widget):
    macro_name = "json_editor"

    def parse(self, raw: str | None) -> Any:
        if not raw:
            return None
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return None
        return raw

    def validate(self, value: Any, field: FieldMeta) -> list[str]:
        errors = super().validate(value, field)
        if isinstance(value, str):
            try:
                json.loads(value)
            except json.JSONDecodeError as e:
                errors.append(f"{field.label} contains invalid JSON: {e}")
        return errors


class AutocompleteWidget(Widget):
    """Text input with datalist autocomplete suggestions."""

    macro_name = "autocomplete"

    def __init__(
        self,
        suggestions: list[str] | None = None,
        suggestions_fn: Any = None,
    ):
        self.suggestions = suggestions
        self.suggestions_fn = suggestions_fn

    def _get_suggestions(self) -> list[str]:
        if self.suggestions_fn is not None:
            return self.suggestions_fn()
        return self.suggestions or []

    def render_context(self, field: FieldMeta, value: Any) -> dict:
        ctx = super().render_context(field, value)
        ctx["suggestions"] = self._get_suggestions()
        return ctx


class PasswordWidget(Widget):
    macro_name = "password_input"

    def render_context(self, field: FieldMeta, value: Any) -> dict:
        ctx = super().render_context(field, value)
        ctx["value"] = ""  # NEVER pre-fill passwords
        return ctx

    def parse(self, raw: str | None) -> str | None:
        if not raw:
            return None
        return raw


class ReadOnlyWidget(Widget):
    macro_name = "readonly"

    def parse(self, raw: str | None) -> None:
        return None

    def validate(self, value: Any, field: FieldMeta) -> list[str]:
        return []


class HiddenWidget(Widget):
    macro_name = "hidden"


class FileUploadWidget(Widget):
    """File upload widget — stores file via StorageBackend, saves path string."""

    macro_name = "file_upload"

    def __init__(
        self,
        max_size_mb: float | None = None,
        accept: str | None = None,
    ) -> None:
        self.max_size_mb = max_size_mb
        self.accept = accept  # e.g. ".pdf,.docx" or "application/pdf"

    def render_context(self, field: FieldMeta, value: Any) -> dict:
        ctx = super().render_context(field, value)
        ctx["max_size_mb"] = self.max_size_mb
        ctx["accept"] = self.accept
        ctx["current_file"] = value if value else ""
        return ctx

    def parse(self, raw: Any) -> Any:
        """Raw form data — the actual UploadFile handling happens in the
        form submit factory because ``UploadFile`` objects need async read."""
        if raw is None or raw == "":
            return None
        return raw

    def validate(self, value: Any, field: FieldMeta) -> list[str]:
        errors = super().validate(value, field)
        # Size validation happens at save time in the form submit factory
        # because reading the file requires async I/O.
        return errors


class ImageUploadWidget(Widget):
    """Image upload widget — like FileUploadWidget but restricted to images."""

    macro_name = "image_upload"

    def __init__(
        self,
        max_size_mb: float | None = None,
        accept: str = "image/*",
    ) -> None:
        self.max_size_mb = max_size_mb
        self.accept = accept

    def render_context(self, field: FieldMeta, value: Any) -> dict:
        ctx = super().render_context(field, value)
        ctx["max_size_mb"] = self.max_size_mb
        ctx["accept"] = self.accept
        ctx["current_file"] = value if value else ""
        return ctx

    def parse(self, raw: Any) -> Any:
        if raw is None or raw == "":
            return None
        return raw

    def validate(self, value: Any, field: FieldMeta) -> list[str]:
        errors = super().validate(value, field)
        return errors


class WysiwygWidget(Widget):
    """Wysiwyg rich text editor widget (contenteditable-based)."""

    macro_name = "wysiwyg"

    def __init__(self, height: int = 200):
        self.height = height

    def render_context(self, field: FieldMeta, value: Any) -> dict:
        ctx = super().render_context(field, value)
        ctx["height"] = self.height
        return ctx

    def parse(self, raw: str | None) -> str | None:
        if not raw:
            return None
        return raw

    def validate(self, value: Any, field: FieldMeta) -> list[str]:
        return []


class ArrayWidget(Widget):
    """Array/list input widget — dynamic add/remove items."""

    macro_name = "array_input"

    def __init__(self, min_items: int = 0, max_items: int | None = None):
        self.min_items = min_items
        self.max_items = max_items

    def render_context(self, field: FieldMeta, value: Any) -> dict:
        ctx = super().render_context(field, value)
        if isinstance(value, str):
            try:
                import json
                ctx["value"] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                ctx["value"] = []
        ctx["min_items"] = self.min_items
        ctx["max_items"] = self.max_items
        return ctx

    def parse(self, raw: str | list | None) -> list:
        if raw is None:
            return []
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str):
            try:
                import json
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return [raw] if raw else []
        return []

    def validate(self, value: Any, field: FieldMeta) -> list[str]:
        errors = super().validate(value, field)
        if isinstance(value, list):
            if self.min_items and len(value) < self.min_items:
                errors.append(f"{field.label} requires at least {self.min_items} items.")
            if self.max_items and len(value) > self.max_items:
                errors.append(f"{field.label} allows at most {self.max_items} items.")
        return errors
