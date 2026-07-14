"""Core data structures for FastAPI Admin Kit — ColumnMeta, RelationMeta, FieldMeta, etc."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ColumnMeta:
    """Metadata for a single SQLAlchemy column."""

    name: str
    type: Any  # SQLAlchemy type instance
    nullable: bool = True
    primary_key: bool = False
    foreign_keys: list = field(default_factory=list)
    default: Any = None
    server_default: Any = None
    index: bool = False
    unique: bool = False

    @property
    def is_foreign_key(self) -> bool:
        return bool(self.foreign_keys)


@dataclass
class RelationMeta:
    """Metadata for a single SQLAlchemy relationship."""

    name: str
    direction: str  # MANYTOONE, ONETOMANY, MANYTOMANY
    target_model: type
    uselist: bool = True
    back_populates: str | None = None
    secondary: Any = None  # association table for many-to-many


@dataclass
class FieldMeta:
    """Metadata for a form field — drives widget rendering and validation."""

    name: str
    label: str
    required: bool
    readonly: bool = False
    help_text: str | None = None
    placeholder: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class PermissionSet:
    """Set of boolean permissions for a single model."""

    can_view: bool = False
    can_create: bool = False
    can_edit: bool = False
    can_delete: bool = False


@dataclass
class FieldsetSpec:
    """Defines a logical grouping of fields within a form."""

    title: str | None = None
    collapsed: bool = False
    fields: list[str] = field(default_factory=list)


@dataclass
class SeedRole:
    """Defines a role to be seeded on first startup."""

    name: str
    description: str = ""
    permissions: dict[str, dict[str, bool]] = field(default_factory=dict)


@dataclass
class FieldRenderContext:
    meta: FieldMeta
    widget_macro: str
    widget_context: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class FieldsetContext:
    title: str | None = None
    collapsed: bool = False
    fields: list[FieldRenderContext] = field(default_factory=list)


@dataclass
class InlineFormFieldMeta:
    """Metadata for a single field in an inline formset."""

    name: str
    label: str
    field_type: str = "text"  # text, number, boolean, select, relation, date, datetime
    required: bool = False
    readonly: bool = False
    choices: list[tuple[str, str]] | None = None  # for select fields
    related_table: str = ""  # for relation fields
    related_verbose: str = ""  # for relation fields
    search_url: str = ""  # for relation fields
    placeholder: str = ""


@dataclass
class InlineFormsetData:
    """Data for rendering an inline formset on the parent form."""

    prefix: str  # e.g., "orderitem_set"
    inline_type: str  # "stacked" or "tabular"
    fields: list[str]  # field names to display
    field_metas: list[InlineFormFieldMeta] = field(default_factory=list)  # field metadata
    field_labels: dict[str, str] = field(default_factory=dict)
    verbose_name: str = ""
    verbose_name_plural: str = ""
    can_delete: bool = True
    can_add: bool = True  # permission to add new inline objects
    can_change: bool = True  # permission to edit inline objects
    can_remove: bool = True  # permission to delete inline objects
    initial: list[dict[str, Any]] = field(default_factory=list)  # existing related objects
    initial_ids: list[str] = field(default_factory=list)  # PKs of existing objects
    extra_count: int = 1  # number of empty forms
    max_num: int | None = None
    min_num: int = 0
    errors: dict[int, dict[str, list[str]]] = field(
        default_factory=dict
    )  # {row_idx: {field: [errs]}}
    readonly_fields: list[str] = field(default_factory=list)
    formfield_overrides: dict[str, Any] = field(default_factory=dict)
    fk_field: str = ""  # FK column name on the related model
    boolean_fields: list[str] = field(default_factory=list)  # fields that are Boolean type


@dataclass
class FormContext:
    model_name: str
    verbose_name: str
    is_create: bool
    obj: Any = None
    fieldsets: list[FieldsetContext] = field(default_factory=list)
    errors: dict[str, list[str]] = field(default_factory=dict)
    values: dict[str, Any] = field(default_factory=dict)
    action_url: str = ""
    list_url: str = ""
    can_delete: bool = False
    permissions: PermissionSet = field(default_factory=PermissionSet)
    readonly: bool = False
    inline_formsets: list[InlineFormsetData] = field(default_factory=list)


@dataclass
class ExtraField:
    name: str
    label: str = ""
    widget: Any = None
    default: Any = None
    required: bool = False
    required_on_create: bool | None = None


@dataclass
class TabConfig:
    """Configuration for changelist tabs."""

    title: str
    url: str = ""
    permission: str | None = None
    is_active: bool = False


@dataclass
class TableSection:
    """Expandable section showing a related table."""

    title: str
    related_model: Any = None
    related_field: str = ""
    list_display: list[str] = field(default_factory=list)


@dataclass
class TemplateSection:
    """Expandable section rendering a custom template."""

    title: str
    template: str = ""
    context_fn: Any = None
