"""ModelAdmin base class — configuration + lifecycle hooks + validation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi_admin_kit.admin.decorators import column
from fastapi_admin_kit.form.types import ExtraField, FieldMeta

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from fastapi_admin_kit.nav import NavItemConfig


class ModelAdmin:
    """Base class for model admin configuration.

    Subclass this to customise how a model is displayed, filtered, and edited.
    All fields are optional — unset fields fall back to auto-detected values.
    """

    # List view config
    list_display: list[str] | None = None
    list_filter: list[str | Any] | None = None
    search_fields: list[str] | None = None
    ordering: list[str] | None = None
    per_page: int = 20
    pagination: Any = None  # OffsetPagination | CursorPagination | DynamicPagination
    list_filter_options: dict[str, dict[str, Any]] = {}
    list_filter_horizontal: bool = False

    # Inline editing config
    inline_edit: bool = False
    inline_edit_fields: list[str] | None = None
    inline_exclude_fields: list[str] | None = None

    # Actions config
    actions_list: list[str] = []
    actions_row: list[str] = []
    actions_detail: list[str] = []
    actions_submit_line: list[str] = []
    actions_list_hide_default: bool = False

    # Form config
    fields: list[str] | None = None
    exclude: list[str] | None = None
    readonly_fields: list[str] | None = None
    formfield_overrides: dict[str, Any] = {}
    extra_fields: list[ExtraField] = []
    fieldsets: list[Any] = []  # FieldsetSpec accepted but not strictly enforced here
    field_placeholders: dict[str, str] = {}  # {field_name: placeholder_text}

    # Inline admin config
    inlines: list[Any] = []  # list of InlineModelAdmin subclasses

    # Conditional fields
    conditional_fields: dict[str, dict[str, Any]] = {}

    # Form UX config
    warn_unsaved_form: bool = True
    compressed_fields: bool = True
    change_form_show_cancel_button: bool = True

    # Labels and display
    verbose_name: str | None = None
    verbose_name_plural: str | None = None
    icon: str | None = None
    tag: str | None = None
    tags: list[str] | None = None
    nav_order: int = 999
    nav_children: list[NavItemConfig] | None = None

    # Route generation
    skip_auto_routes: bool = False

    # Custom display functions (dict-based fallback)
    display_functions: dict[str, Any] | None = None

    # Decorator for custom column display
    column = staticmethod(column)

    # Badge hook — return str e.g. "12" or None
    def get_nav_badge(self, request: Any = None) -> str | None:
        return None

    # Object display
    def __str__(self, obj: Any) -> str:
        """How to display an object in dropdowns/links."""
        return str(
            getattr(obj, "name", None)
            or getattr(obj, "title", None)
            or f"#{getattr(obj, 'id', '?')}"
        )

    def get_model(self) -> Any:
        return self.model

    # ── Query hooks ──────────────────────────────────────────────────

    def get_queryset(self, session: Session, request: Any = None) -> Any:
        """Override to filter records globally (e.g. soft-delete filter).

        Returns a SQLAlchemy ``select`` statement for the model.
        Override and call ``super().get_queryset(session, request)`` to
        chain additional ``.where()`` conditions.
        """
        from sqlalchemy import select

        return select(self.model)  # type: ignore[attr-defined]

    def get_object(self, session: Session, id: Any) -> Any:
        """Override for custom PK lookup."""
        return session.get(self.model, id)  # type: ignore[attr-defined]

    # ── Lifecycle hooks (stubs) ─────────────────────────────────────

    def prepare_create_data(self, data: dict[str, Any], request: Any = None) -> dict[str, Any]:
        """Strip extra fields and return only model-column data for INSERT."""
        extra_names = {f.name for f in self.extra_fields}
        return {k: v for k, v in data.items() if k not in extra_names}

    def prepare_update_data(self, data: dict[str, Any], request: Any = None) -> dict[str, Any]:
        """Strip extra fields and return only model-column data for UPDATE."""
        extra_names = {f.name for f in self.extra_fields}
        return {k: v for k, v in data.items() if k not in extra_names}

    def on_create(self, obj: Any, request: Any = None) -> None:
        """Called before INSERT. Mutate *obj* as needed."""

    def after_create(self, obj: Any, request: Any = None) -> None:
        """Called after INSERT commit."""

    def on_update(self, obj: Any, data: dict[str, Any], request: Any = None) -> None:
        """Called before UPDATE. *data* contains the incoming form values."""

    def after_update(self, obj: Any, request: Any = None) -> None:
        """Called after UPDATE commit."""

    def on_delete(self, obj: Any, request: Any = None) -> None:
        """Called before DELETE."""

    def after_delete(self, obj: Any, request: Any = None) -> None:
        """Called after DELETE commit."""

    # ── Validation hooks (stubs) ────────────────────────────────────

    def validate_create(self, data: dict[str, Any], request: Any = None) -> dict[str, Any]:
        """Validate and/or transform form data before create.

        Return the (possibly modified) data dict.  Raise ``ValueError``
        with a user-facing message to abort the operation.
        """
        return data

    def validate_update(
        self, obj: Any, data: dict[str, Any], request: Any = None
    ) -> dict[str, Any]:
        """Validate and/or transform form data before update.

        Return the (possibly modified) data dict.  Raise ``ValueError``
        with a user-facing message to abort the operation.
        """
        return data

    # ── Form data processing hooks ──────────────────────────────────

    def process_form_data(self, data: dict[str, Any], request: Any = None) -> dict[str, Any]:
        """Process form data before save. Override for custom processing.

        Called after form parsing and validation. Use this to transform
        form data, extract special fields, or prepare data for saving.
        """
        return data

    def save_model(
        self, obj: Any, data: dict[str, Any], request: Any = None, is_create: bool = False
    ) -> None:
        """Custom save logic. Override for full control over save flow.

        When overridden, this method is called instead of the default
        save logic. The object is already added to the session but not
        committed yet. Call session.commit() yourself if needed.
        """
        pass

    # ── Form context hooks ──────────────────────────────────────────

    async def get_form_context(
        self, context: dict[str, Any], obj: Any = None, request: Any = None
    ) -> dict[str, Any]:
        """Customize form template context. Return modified context.

        Called when building the form context for create/edit views.
        Override to add custom template variables.
        """
        return context

    # ── Dynamic field hooks ─────────────────────────────────────────

    def get_readonly_fields(self, obj: Any = None, request: Any = None) -> list[str]:
        """Return list of readonly field names. Override for dynamic readonly.

        Called during form field generation. Fields returned here are
        in addition to the static readonly_fields list.
        """
        return self.readonly_fields or []

    def get_hidden_fields(self, obj: Any = None, request: Any = None) -> list[str]:
        """Return list of hidden field names. Override for dynamic hidden.

        Called during form field generation. Hidden fields are excluded
        from the form entirely.
        """
        return []

    # ── Form field helper ───────────────────────────────────────────

    def get_form_fields(
        self,
        obj: Any = None,
        request: Any = None,
        columns: list[Any] | None = None,
        relationships: list[Any] | None = None,
    ) -> list[FieldMeta]:
        """Return ordered list of FieldMeta objects for the create/edit form."""
        from fastapi_admin_kit.inspection import auto_label, is_required

        columns = columns or []
        relationships = relationships or []
        form_fields: list[FieldMeta] = []

        raw = []
        if self.fields is not None:
            names = set(self.fields)
            raw = [c for c in columns if c.name in names and not c.primary_key] + [
                r
                for r in relationships
                if r.name in names and r.direction in ("MANYTOONE", "MANYTOMANY")
            ]
        else:
            raw = [c for c in columns if not c.primary_key] + [
                r for r in relationships if r.direction in ("MANYTOONE", "MANYTOMANY")
            ]
            if self.exclude:
                raw = [x for x in raw if x.name not in self.exclude]

            # Exclude FK columns that have a corresponding relationship
            # to avoid duplicate fields (e.g., user_id + user both showing)
            from sqlalchemy import inspect as sa_inspect

            rel_fk_cols: set[str] = set()
            try:
                mapper = sa_inspect(self.model)
                for r in relationships:
                    if r.direction in ("MANYTOONE", "MANYTOMANY"):
                        rel_prop = mapper.relationships.get(r.name)
                        if rel_prop is not None:
                            for local_col in rel_prop.local_columns:
                                rel_fk_cols.add(local_col.key)
            except Exception:
                pass
            raw = [x for x in raw if not (hasattr(x, "foreign_keys") and x.name in rel_fk_cols)]

        dynamic_readonly = set(self.get_readonly_fields())
        dynamic_hidden = set(self.get_hidden_fields())

        for item in raw:
            name = item.name
            if name in dynamic_hidden:
                continue
            readonly = name in (self.readonly_fields or []) or name in dynamic_readonly
            required = is_required(item) if hasattr(item, "nullable") else False
            label = auto_label(name)
            placeholder = self.field_placeholders.get(name, f"Enter {label.lower()}...")
            form_fields.append(
                FieldMeta(
                    name=name,
                    label=label,
                    required=required,
                    readonly=readonly,
                    placeholder=placeholder,
                )
            )

        for extra in self.extra_fields:
            form_fields.append(
                FieldMeta(
                    name=extra.name,
                    label=extra.label or auto_label(extra.name),
                    required=extra.required,
                    readonly=False,
                    extra={
                        "extra_field": True,
                        "widget": extra.widget,
                        "required_on_create": extra.required_on_create,
                    },
                )
            )

        # Respect fieldsets ordering if defined
        if self.fieldsets:
            ordered: list[FieldMeta] = []
            seen: set[str] = set()
            for fs in self.fieldsets:
                for fname in fs.fields:
                    for fm in form_fields:
                        if fm.name == fname and fname not in seen:
                            ordered.append(fm)
                            seen.add(fname)
                            break
            for fm in form_fields:
                if fm.name not in seen:
                    ordered.append(fm)
            return ordered

        return form_fields

    # ── Action helpers ─────────────────────────────────────────────

    def get_actions_for_location(self, location: str) -> list[Any]:
        """Get resolved Action instances for a given location (list/row/detail/submit_line)."""
        from fastapi_admin_kit.actions.base import Action

        action_names = getattr(self, f"actions_{location}", [])
        resolved = []
        for name in action_names:
            action_fn = getattr(self, name, None)
            if not action_fn:
                continue
            if hasattr(action_fn, "_admin_action"):
                resolved.append(action_fn._admin_action())
            elif callable(action_fn):
                label = name.replace("_", " ").title()
                _fn = action_fn
                _admin = self

                class _FallbackAction(Action):
                    def __init__(self):
                        super().__init__(name=name, label=label)

                    async def execute(self, objects, request):
                        import inspect

                        if inspect.iscoroutinefunction(_fn):
                            await _fn(_admin, objects, request)
                        else:
                            _fn(_admin, objects, request)

                resolved.append(_FallbackAction())
        return resolved

    def get_list_actions(self) -> list[Any]:
        return self.get_actions_for_location("list")

    def get_row_actions(self) -> list[Any]:
        return self.get_actions_for_location("row")

    def get_detail_actions(self) -> list[Any]:
        return self.get_actions_for_location("detail")

    def get_submit_line_actions(self) -> list[Any]:
        return self.get_actions_for_location("submit_line")

    # ── Inline edit helpers ────────────────────────────────────────

    def get_inline_edit_fields(
        self,
        obj: Any = None,
        request: Any = None,
        columns: list[Any] | None = None,
        relationships: list[Any] | None = None,
    ) -> list[FieldMeta]:
        """Return FieldMeta list for the inline edit form."""
        all_fields = self.get_form_fields(
            obj=obj, request=request, columns=columns, relationships=relationships
        )
        if self.inline_edit_fields is not None:
            allowed = set(self.inline_edit_fields)
            return [f for f in all_fields if f.name in allowed]
        if self.inline_exclude_fields is not None:
            excluded = set(self.inline_exclude_fields)
            return [f for f in all_fields if f.name not in excluded]
        return all_fields

    # ── Permission helpers ───────────────────────────────────────────

    def has_view_permission(self, request: Any = None) -> bool:
        return True

    def has_create_permission(self, request: Any = None) -> bool:
        return True

    def has_edit_permission(self, request: Any = None) -> bool:
        return True

    def has_delete_permission(self, request: Any = None) -> bool:
        return True
