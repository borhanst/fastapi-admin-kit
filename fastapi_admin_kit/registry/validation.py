"""ModelValidator — validates model registration in AdminRegistry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi_admin_kit.registry.core import AdminRegistry


class ModelValidator:
    """Validates model registration in AdminRegistry.

    This class centralizes all validation logic, making it testable
    and separable from the registry's storage and inspection concerns.
    """

    def __init__(self, registry: AdminRegistry) -> None:
        """Initialize the validator with a reference to the registry.

        Args:
            registry: The AdminRegistry instance to validate against.
        """
        self._registry = registry

    def validate_model_registration(
        self,
        model: type,
        admin_class: type | None = None,
    ) -> None:
        """Validate that a model can be registered with the admin.

        Args:
            model: A SQLAlchemy declarative model class.
            admin_class: Optional ModelAdmin subclass for the model.

        Raises:
            ValueError: If the model is not a valid SQLAlchemy model.
            ValueError: If the model's table name conflicts with an existing registration.
        """
        self._validate_is_sqlalchemy_model(model)
        self._check_table_name_conflicts(model)

    def validate_admin_fields(
        self,
        model: type,
        admin_class: type | None,
        columns: list[Any],
        relationships: list[Any],
    ) -> None:
        """Validate that all field names referenced in the admin class actually
        exist on the model.

        Checked attributes: ``list_display``, ``exclude``, ``readonly_fields``,
        and ``formfield_overrides``.

        Args:
            model: The registered model class.
            admin_class: The ModelAdmin subclass (or ``None`` for the default).
            columns: Inspected column descriptors (each has a ``.name``).
            relationships: Inspected relationship descriptors (each has a ``.name``).

        Raises:
            ValueError: With a descriptive message listing every unknown field.
        """
        if admin_class is None:
            return  # default ModelAdmin has no user-supplied field lists

        # Build the set of all valid field names for this model
        valid_fields: set[str] = {c.name for c in columns} | {r.name for r in relationships}

        model_name = getattr(model, "__name__", str(model))
        admin_name = admin_class.__name__

        # Also allow the admin class's own methods / @column-decorated attributes
        # as valid "fields" so that display-only computed columns don't raise.
        admin_methods: set[str] = {
            name
            for name in dir(admin_class)
            if not name.startswith("_") and callable(getattr(admin_class, name, None))
        }

        def _check(field_list: list[str] | None, attr_name: str) -> list[str]:
            if not field_list:
                return []
            return [f for f in field_list if f not in valid_fields and f not in admin_methods]

        errors: list[str] = []

        bad = _check(getattr(admin_class, "list_display", None), "list_display")
        if bad:
            errors.append(
                f"  list_display: unknown field(s) {bad!r}\n"
                f"    Valid fields: {sorted(valid_fields)!r}"
            )

        bad = _check(getattr(admin_class, "exclude", None), "exclude")
        if bad:
            errors.append(
                f"  exclude: unknown field(s) {bad!r}\n    Valid fields: {sorted(valid_fields)!r}"
            )

        bad = _check(getattr(admin_class, "readonly_fields", None), "readonly_fields")
        if bad:
            errors.append(
                f"  readonly_fields: unknown field(s) {bad!r}\n"
                f"    Valid fields: {sorted(valid_fields)!r}"
            )

        fo = getattr(admin_class, "formfield_overrides", None)
        if fo:
            bad_fo = [f for f in fo if f not in valid_fields]
            if bad_fo:
                errors.append(
                    f"  formfield_overrides: unknown field(s) {bad_fo!r}\n"
                    f"    Valid fields: {sorted(valid_fields)!r}"
                )

        if errors:
            raise ValueError(
                f"{admin_name} for model '{model_name}' references field(s) that "
                f"do not exist on the model:\n" + "\n".join(errors)
            )

    def _validate_is_sqlalchemy_model(self, model: type) -> None:
        """Validate that the model is a SQLAlchemy or SQLModel model.

        Args:
            model: A class to validate.

        Raises:
            ValueError: If the model is not a valid ORM model.
        """
        # SQLAlchemy models always have __tablename__
        if hasattr(model, "__tablename__"):
            return

        # SQLModel with table=True always has __tablename__ via metaclass
        # SQLModel without table=True won't have it
        try:
            from sqlmodel import SQLModel

            if isinstance(model, type) and issubclass(model, SQLModel):
                # Check if it's a table model (has registry = table is created)
                has_table = getattr(model, "table", False) or hasattr(model, "metadata")
                if not has_table:
                    raise ValueError(
                        f"{model.__name__} is a SQLModel but has no table. "
                        f"Use SQLModel(table=True) to create a table model."
                    )
        except ImportError:
            pass

        if not hasattr(model, "__tablename__"):
            raise ValueError(f"{model.__name__} is not a SQLAlchemy model (no __tablename__)")

    def _check_table_name_conflicts(self, model: type) -> None:
        """Check for table name conflicts with existing registrations.

        Args:
            model: A SQLAlchemy declarative model class.

        Raises:
            ValueError: If the table name is already registered.
        """
        table_name = model.__tablename__
        existing = self._registry.get(table_name)
        if existing is not None and existing.model is not model:
            raise ValueError(
                f"Table name '{table_name}' is already registered for "
                f"model {existing.model.__name__}. "
                f"Cannot register {model.__name__} with the same table name."
            )

    def check_table_name_conflicts(self, table_name: str) -> bool:
        """Check if a table name is already registered.

        Args:
            table_name: The table name to check.

        Returns:
            True if the table name is already registered, False otherwise.
        """
        return self._registry.get(table_name) is not None
