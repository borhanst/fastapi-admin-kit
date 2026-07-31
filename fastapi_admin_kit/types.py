"""Core data structures — re-export barrel for backward compatibility.

Domain-specific types live in:
- fastapi_admin_kit.inspection.types  (ColumnMeta, RelationMeta)
- fastapi_admin_kit.form.types         (FieldMeta, FieldError, FormContext, …)
- fastapi_admin_kit.auth.types         (PermissionSet, SeedRole)
- fastapi_admin_kit.ui.types           (TabConfig, TableSection, TemplateSection)

New code should import from the domain module directly.
"""

from __future__ import annotations

from fastapi_admin_kit.auth.types import PermissionSet, SeedRole
from fastapi_admin_kit.form.types import (
    ExtraField,
    FieldError,
    FieldMeta,
    FieldRenderContext,
    FieldsetContext,
    FieldsetSpec,
    FormContext,
    InlineFormFieldMeta,
    InlineFormsetData,
)
from fastapi_admin_kit.inspection.types import ColumnMeta, RelationMeta
from fastapi_admin_kit.ui.types import TabConfig, TableSection, TemplateSection

__all__ = [
    "ColumnMeta",
    "ExtraField",
    "FieldError",
    "FieldMeta",
    "FieldRenderContext",
    "FieldsetContext",
    "FieldsetSpec",
    "FormContext",
    "InlineFormFieldMeta",
    "InlineFormsetData",
    "PermissionSet",
    "RelationMeta",
    "SeedRole",
    "TabConfig",
    "TableSection",
    "TemplateSection",
]
