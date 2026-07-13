"""AdminRegistry — singleton holding all registered models."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi_admin_kit.inspection.registry import ModelInspector
from fastapi_admin_kit.registry.validation import ModelValidator

if TYPE_CHECKING:
    from fastapi_admin_kit.views import ModelAdmin
    from fastapi_admin_kit.widgets.base import Widget
    from fastapi_admin_kit.widgets.resolver import WidgetResolver


@dataclass
class RegisteredModel:
    """Central dataclass holding a registered model and its admin config."""

    model: type
    admin: ModelAdmin
    table_name: str
    verbose_name: str
    verbose_name_plural: str
    columns: list = field(default_factory=list)
    relationships: list = field(default_factory=list)
    pk_field: str | tuple[str, ...] | None = "id"
    _schemas: dict | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        # Find primary key
        for col in self.columns:
            if col.primary_key:
                self.pk_field = col.name
                break
        # Ensure admin has reference to model for form field deduplication
        if not hasattr(self.admin, "model") or self.admin.model is None:
            self.admin.model = self.model

    @property
    def form_fields(self) -> list[Any]:
        return self.admin.get_form_fields(
            columns=self.columns,
            relationships=self.relationships,
        )

    @property
    def list_fields(self) -> list[str]:
        if self.admin.list_display:
            valid = {c.name for c in self.columns}
            return [f for f in self.admin.list_display if f in valid]
        return [c.name for c in self.columns if not c.primary_key]

    def get_widget(self, field_name: str, resolver: WidgetResolver | None = None) -> Widget:
        from fastapi_admin_kit.inspection import auto_label
        from fastapi_admin_kit.widgets.registry import widget_registry
        from fastapi_admin_kit.widgets.relation import (
            MultiRelationWidget,
            RelationPickerWidget,
        )
        from fastapi_admin_kit.widgets.resolver import WidgetResolver

        if resolver is None:
            resolver = WidgetResolver(widget_registry)

        overrides = getattr(self.admin, "formfield_overrides", {})
        if field_name in overrides:
            return overrides[field_name]

        col = next((c for c in self.columns if c.name == field_name), None)
        rel = next((r for r in self.relationships if r.name == field_name), None)
        if col is not None:
            widget = resolver.resolve(col)
            if (
                isinstance(widget, RelationPickerWidget)
                and not widget.related_table
                and col.foreign_keys
            ):
                fk = col.foreign_keys[0]
                widget.related_table = fk.column.table.name
            return widget
        if rel is not None:
            related_verbose = auto_label(rel.target_model.__tablename__)
            if rel.direction == "MANYTOONE" or not rel.uselist:
                return RelationPickerWidget(
                    related_table=rel.target_model.__tablename__,
                    related_verbose=related_verbose,
                )
            return MultiRelationWidget(
                related_table=rel.target_model.__tablename__,
                related_verbose=related_verbose,
            )
        return resolver.resolve(  # type: ignore[arg-type]
            type("_Col", (), {"type": type(None), "name": field_name})()
        )


class AdminRegistry:
    """Singleton registry for admin models.

    Uses dependency injection for ModelInspector and ModelValidator,
    making the registry testable and separable from inspection/validation concerns.
    """

    _instance: AdminRegistry | None = None
    _models: dict[str, RegisteredModel] = {}

    def __new__(cls) -> AdminRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._models = {}
        return cls._instance

    def __init__(self) -> None:
        """Initialize the registry with default inspector and validator."""
        if not hasattr(self, "_inspector"):
            self._inspector = ModelInspector()
        if not hasattr(self, "_validator"):
            self._validator = ModelValidator(self)

    @property
    def inspector(self) -> ModelInspector:
        """Get the model inspector."""
        return self._inspector

    @inspector.setter
    def inspector(self, value: ModelInspector) -> None:
        """Set the model inspector."""
        self._inspector = value

    @property
    def validator(self) -> ModelValidator:
        """Get the model validator."""
        return self._validator

    @validator.setter
    def validator(self, value: ModelValidator) -> None:
        """Set the model validator."""
        self._validator = value

    def register(
        self,
        model: type,
        admin_class: type[ModelAdmin] | None = None,
    ) -> RegisteredModel:
        """Register a model with the admin.

        Args:
            model: A SQLAlchemy declarative model class.
            admin_class: Optional ModelAdmin subclass for the model.

        Returns:
            The registered model configuration.

        Raises:
            ValueError: If the model is not a valid SQLAlchemy model.
        """
        from fastapi_admin_kit.views import ModelAdmin

        # Validate using the injected validator
        self._validator.validate_model_registration(model, admin_class)

        # Inspect using the injected inspector
        columns, relationships = self._inspector.inspect_model(model)

        admin = admin_class() if admin_class else ModelAdmin()
        table_name = model.__tablename__
        if admin.verbose_name:
            verbose_name = admin.verbose_name
        else:
            class_name = getattr(model, "__name__", None)
            if class_name and not class_name.startswith("_"):
                verbose_name = re.sub(r"([A-Z])", r" \1", class_name).strip().title()
            else:
                verbose_name = table_name.replace("_", " ").title()
        if admin.verbose_name_plural:
            verbose_name_plural = admin.verbose_name_plural
        elif (
            verbose_name.endswith("y")
            and len(verbose_name) > 1
            and verbose_name[-2].lower() not in "aeiou"
        ):
            verbose_name_plural = f"{verbose_name[:-1]}ies"
        else:
            verbose_name_plural = f"{verbose_name}s"

        registered = RegisteredModel(
            model=model,
            admin=admin,
            table_name=table_name,
            verbose_name=verbose_name,
            verbose_name_plural=verbose_name_plural,
            columns=columns,
            relationships=relationships,
        )

        self._models[table_name] = registered
        return registered

    def get(self, table_name: str) -> RegisteredModel | None:
        """Get a registered model by table name.

        Args:
            table_name: The table name to look up.

        Returns:
            The registered model, or None if not found.
        """
        return self._models.get(table_name)

    def all(self) -> list[RegisteredModel]:
        """Get all registered models.

        Returns:
            A list of all registered models.
        """
        return list(self._models.values())

    def auto_discover(self) -> list[RegisteredModel]:
        """Scan all subclasses of DeclarativeBase and register unregistered ones.

        Also discovers SQLModel subclasses if SQLModel is installed.

        Returns:
            A list of newly registered models.
        """
        from sqlalchemy.orm import DeclarativeBase

        discovered: list[RegisteredModel] = []
        seen: set[type] = set()

        # Discover SQLAlchemy DeclarativeBase subclasses
        for subclass in _all_declarative_subclasses(DeclarativeBase):
            if hasattr(subclass, "registry"):
                for mapper in subclass.registry.mappers:
                    cls = mapper.class_
                    if cls not in seen:
                        seen.add(cls)
                        if hasattr(cls, "__tablename__") and cls.__tablename__ not in self._models:
                            discovered.append(self.register(cls))

        # Discover SQLModel subclasses (if installed)
        try:
            from sqlmodel import SQLModel

            for subclass in _all_declarative_subclasses(SQLModel):
                if hasattr(subclass, "registry"):
                    for mapper in subclass.registry.mappers:
                        cls = mapper.class_
                        if cls not in seen:
                            seen.add(cls)
                            if (
                                hasattr(cls, "__tablename__")
                                and cls.__tablename__ not in self._models
                            ):
                                discovered.append(self.register(cls))
        except ImportError:
            pass

        return discovered

    def clear(self) -> None:
        """Clear all registrations (useful for testing)."""
        self._models.clear()


def _all_declarative_subclasses(base: type) -> set[type]:
    """Recursively collect all subclasses of *base*.

    Args:
        base: The base class to find subclasses of.

    Returns:
        A set of all subclasses.
    """
    result: set[type] = set()
    work = [base]
    while work:
        cls = work.pop()
        for sub in cls.__subclasses__():
            if sub not in result:
                result.add(sub)
                work.append(sub)
    return result
