"""Tests for ModelValidator class."""

import pytest
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Category(Base):
    __tablename__ = "validator_categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)


class Product(Base):
    __tablename__ = "validator_products"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    price = Column(Integer)


class TestModelValidatorValidateModelRegistration:
    def test_valid_model_passes(self):
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.registry.validation import ModelValidator

        registry = AdminRegistry()
        registry.clear()
        validator = ModelValidator(registry)
        # Should not raise
        validator.validate_model_registration(Product)

    def test_invalid_model_raises(self):
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.registry.validation import ModelValidator

        registry = AdminRegistry()
        registry.clear()
        validator = ModelValidator(registry)
        with pytest.raises(ValueError, match="not a SQLAlchemy model"):
            validator.validate_model_registration(str)

    def test_duplicate_table_name_raises(self):
        from unittest.mock import MagicMock

        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.registry.core import RegisteredModel
        from fastapi_admin_kit.registry.validation import ModelValidator

        registry = AdminRegistry()
        registry.clear()
        validator = ModelValidator(registry)
        # Register the model first
        registry.register(Product)
        # Manually insert a mock registration with a different model class
        # to simulate a table name conflict
        mock_model = MagicMock()
        mock_model.__name__ = "MockProduct"
        mock_model.__tablename__ = "validator_products"
        mock_admin = MagicMock()
        mock_admin.verbose_name = None
        mock_admin.verbose_name_plural = None
        mock_registered = RegisteredModel(
            model=mock_model,
            admin=mock_admin,
            table_name="validator_products",
            verbose_name="Mock Products",
            verbose_name_plural="Mock Products",
        )
        registry._models["validator_products"] = mock_registered
        # Try to validate registration of Product (different model, same table)
        with pytest.raises(ValueError, match="already registered"):
            validator.validate_model_registration(Product)

    def test_same_model_reregistration_passes(self):
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.registry.validation import ModelValidator

        registry = AdminRegistry()
        registry.clear()
        validator = ModelValidator(registry)
        # Register the model first
        registry.register(Product)
        # Re-registering the same model should not raise
        validator.validate_model_registration(Product)


class TestModelValidatorCheckTableNameConflicts:
    def test_returns_false_for_unknown_table(self):
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.registry.validation import ModelValidator

        registry = AdminRegistry()
        registry.clear()
        validator = ModelValidator(registry)
        assert validator.check_table_name_conflicts("nonexistent") is False

    def test_returns_true_for_registered_table(self):
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.registry.validation import ModelValidator

        registry = AdminRegistry()
        registry.clear()
        validator = ModelValidator(registry)
        registry.register(Product)
        assert validator.check_table_name_conflicts("validator_products") is True

    def test_returns_false_for_different_table(self):
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.registry.validation import ModelValidator

        registry = AdminRegistry()
        registry.clear()
        validator = ModelValidator(registry)
        registry.register(Product)
        assert validator.check_table_name_conflicts("validator_categories") is False
