"""FormValidator — three-level validation runner."""

from __future__ import annotations

from typing import Any


class FormValidator:
    def run(
        self,
        registered: Any,
        parsed: dict[str, Any],
        obj: Any = None,
    ) -> dict[str, list[str]]:
        errors: dict[str, list[str]] = {}

        for field_meta in registered.form_fields:
            if field_meta.readonly:
                continue
            widget = registered.get_widget(field_meta.name)
            value = parsed.get(field_meta.name)

            widget_errors = widget.validate(value, field_meta)
            if widget_errors:
                errors[field_meta.name] = widget_errors
                continue

            validator_fn = getattr(
                registered.admin, f"validate_{field_meta.name}", None
            )
            if validator_fn:
                result = validator_fn(value, obj=obj)
                if result:
                    errors[field_meta.name] = (
                        [result] if isinstance(result, str) else list(result)
                    )

        if not errors and hasattr(registered.admin, "validate"):
            obj_errors = registered.admin.validate(parsed, obj=obj)
            for fname, err in obj_errors.items():
                errors[fname] = [err] if isinstance(err, str) else list(err)

        return errors
