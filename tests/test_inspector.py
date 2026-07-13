"""Tests for ModelInspector class."""

import pytest
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "inspector_users"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class Post(Base):
    __tablename__ = "inspector_posts"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    content = Column(Text)
    author_id = Column(Integer, ForeignKey("inspector_users.id"), nullable=False)

    author = relationship("User", back_populates="posts")


User.posts = relationship("Post", back_populates="author")


class AbstractModel(Base):
    __abstract__ = True
    id = Column(Integer, primary_key=True)


class CompositeKeyModel(Base):
    __tablename__ = "inspector_composite_keys"

    tenant_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, primary_key=True)
    value = Column(String(100))


class ModelWithServerDefault(Base):
    __tablename__ = "inspector_model_with_defaults"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), server_default="default-slug")


class TestModelInspectorInspectModel:
    def test_returns_columns_and_relationships(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        columns, relationships = inspector.inspect_model(User)
        assert len(columns) == 5
        assert len(relationships) == 1

    def test_column_metadata(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        columns, _ = inspector.inspect_model(User)
        name_col = next(c for c in columns if c.name == "name")
        assert name_col.nullable is False
        assert name_col.primary_key is False
        assert not name_col.unique

    def test_primary_key_detection(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        columns, _ = inspector.inspect_model(User)
        pk_col = next(c for c in columns if c.name == "id")
        assert pk_col.primary_key is True

    def test_foreign_key_detection(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        columns, _ = inspector.inspect_model(Post)
        author_id_col = next(c for c in columns if c.name == "author_id")
        assert author_id_col.is_foreign_key is True
        assert len(author_id_col.foreign_keys) == 1

    def test_relationships(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        _, relationships = inspector.inspect_model(Post)
        assert len(relationships) == 1
        author_rel = relationships[0]
        assert author_rel.name == "author"
        assert author_rel.direction == "MANYTOONE"
        assert author_rel.target_model is User

    def test_server_default_captured(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        columns, _ = inspector.inspect_model(User)
        created_at_col = next(c for c in columns if c.name == "created_at")
        assert created_at_col.server_default is not None


class TestModelInspectorValidateModel:
    def test_valid_model_passes(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        # Should not raise
        inspector.validate_model(User)

    def test_invalid_model_raises(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        with pytest.raises(ValueError, match="not a SQLAlchemy model"):
            inspector.validate_model(str)


class TestModelInspectorExtractMetadata:
    def test_extracts_metadata(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        columns, relationships = inspector.inspect_model(User)
        metadata = inspector.extract_metadata(User, columns, relationships)
        assert metadata["table_name"] == "inspector_users"
        assert metadata["pk_field"] == "id"
        assert len(metadata["columns"]) == 5
        assert len(metadata["relationships"]) == 1


class TestModelInspectorIsAbstract:
    def test_abstract_model(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        assert inspector.is_abstract(AbstractModel) is True

    def test_concrete_model(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        assert inspector.is_abstract(User) is False

    def test_no_abstract_attribute(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()

        class SimpleModel:
            pass

        assert inspector.is_abstract(SimpleModel) is False


class TestModelInspectorGetPkField:
    def test_single_primary_key(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        assert inspector.get_pk_field(User) == "id"

    def test_composite_primary_key(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        result = inspector.get_pk_field(CompositeKeyModel)
        assert result == ("tenant_id", "user_id")

    def test_different_single_pk(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        assert inspector.get_pk_field(Post) == "id"


class TestModelInspectorAutoLabel:
    def test_strips_id_suffix(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        assert inspector.auto_label("category_id") == "Category"

    def test_underscore_to_space(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        assert inspector.auto_label("is_active") == "Is Active"

    def test_camel_case_split(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        assert inspector.auto_label("skuCode") == "Sku Code"

    def test_simple_name(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        assert inspector.auto_label("name") == "Name"

    def test_created_at(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        assert inspector.auto_label("created_at") == "Created At"

    def test_email_field(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        assert inspector.auto_label("user_email") == "User Email"


class TestModelInspectorIsRequired:
    def test_required_column(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        columns, _ = inspector.inspect_model(User)
        name_col = next(c for c in columns if c.name == "name")
        assert inspector.is_required(name_col) is True

    def test_nullable_column(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        columns, _ = inspector.inspect_model(User)
        is_active_col = next(c for c in columns if c.name == "is_active")
        assert inspector.is_required(is_active_col) is False

    def test_column_with_default(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        columns, _ = inspector.inspect_model(User)
        is_active_col = next(c for c in columns if c.name == "is_active")
        assert inspector.is_required(is_active_col) is False

    def test_primary_key_not_required(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        columns, _ = inspector.inspect_model(User)
        id_col = next(c for c in columns if c.name == "id")
        assert inspector.is_required(id_col) is False

    def test_column_with_server_default(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        columns, _ = inspector.inspect_model(ModelWithServerDefault)
        slug_col = next(c for c in columns if c.name == "slug")
        assert inspector.is_required(slug_col) is False

    def test_text_column_nullable(self):
        from fastapi_admin_kit.inspection.registry import ModelInspector

        inspector = ModelInspector()
        columns, _ = inspector.inspect_model(Post)
        content_col = next(c for c in columns if c.name == "content")
        assert inspector.is_required(content_col) is False
