"""ModelValidator — validates model registration in AdminRegistry."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
