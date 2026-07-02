"""Tests for Phase 19 — File Upload & Storage."""

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

import pytest
from starlette.datastructures import UploadFile

from fastapi_admin_kit.storage.base import StorageBackend
from fastapi_admin_kit.storage.local import LocalStorageBackend
from fastapi_admin_kit.widgets.inputs import FileUploadWidget, ImageUploadWidget
from fastapi_admin_kit.types import FieldMeta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _field(name: str = "document", **overrides) -> FieldMeta:
    defaults = dict(name=name, label=name.replace("_", " ").title(), required=False)
    defaults.update(overrides)
    return FieldMeta(**defaults)


def _upload(filename: str, content: bytes = b"hello world") -> UploadFile:
    """Create an UploadFile for testing."""
    return UploadFile(filename=filename, file=io.BytesIO(content))


# ===========================================================================
# 19.1 — StorageBackend ABC
# ===========================================================================


class TestStorageBackendABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            StorageBackend()

    def test_sanitize_filename_available(self):
        assert hasattr(StorageBackend, "sanitize_filename")


# ===========================================================================
# 19.3 — sanitize_filename
# ===========================================================================


class TestSanitizeFilename:
    def test_prepends_uuid_prefix(self):
        backend = LocalStorageBackend()
        result = backend.sanitize_filename("photo.jpg")
        parts = result.split("_", 1)
        assert len(parts) == 2
        assert len(parts[0]) == 12  # UUID hex[:12]
        assert parts[1] == "photo.jpg"

    def test_strips_path_separators(self):
        backend = LocalStorageBackend()
        result = backend.sanitize_filename("../../../etc/passwd")
        assert "/" not in result
        assert "\\" not in result
        assert ".." not in result

    def test_strips_leading_slash(self):
        backend = LocalStorageBackend()
        result = backend.sanitize_filename("/etc/passwd")
        assert "/" not in result

    def test_handles_empty_filename(self):
        backend = LocalStorageBackend()
        result = backend.sanitize_filename("")
        assert result.startswith("unnamed") or "_" in result

    def test_strips_null_bytes(self):
        backend = LocalStorageBackend()
        result = backend.sanitize_filename("photo\x00.jpg")
        assert "\x00" not in result
        assert "photo.jpg" in result


# ===========================================================================
# 19.2 — LocalStorageBackend
# ===========================================================================


class TestLocalStorageBackend:
    @pytest.fixture()
    def tmp_upload_dir(self, tmp_path):
        return tmp_path / "uploads"

    @pytest.fixture()
    def backend(self, tmp_upload_dir):
        return LocalStorageBackend(upload_dir=tmp_upload_dir, base_url="/uploads")

    @pytest.mark.anyio
    async def test_save_returns_path(self, backend):
        f = _upload("test.txt")
        path = await backend.save(f)
        assert isinstance(path, str)
        assert path.endswith("test.txt")

    @pytest.mark.anyio
    async def test_save_creates_file(self, backend):
        f = _upload("test.txt", content=b"hello world")
        path = await backend.save(f)
        target = backend.upload_dir / path
        assert target.is_file()
        assert target.read_bytes() == b"hello world"

    @pytest.mark.anyio
    async def test_save_with_directory(self, backend):
        f = _upload("test.txt")
        path = await backend.save(f, directory="documents")
        assert path.startswith("documents/")
        target = backend.upload_dir / path
        assert target.is_file()

    def test_url_returns_correct_url(self, backend):
        url = backend.url("documents/test.txt")
        assert url == "/uploads/documents/test.txt"

    @pytest.mark.anyio
    async def test_delete_removes_file(self, backend):
        f = _upload("to_delete.txt")
        path = await backend.save(f)
        target = backend.upload_dir / path
        assert target.is_file()

        await backend.delete(path)
        assert not target.is_file()

    @pytest.mark.anyio
    async def test_delete_nonexistent_no_error(self, backend):
        # Should not raise
        await backend.delete("nonexistent/file.txt")

    @pytest.mark.anyio
    async def test_oversized_file_rejected(self, tmp_upload_dir):
        backend = LocalStorageBackend(upload_dir=tmp_upload_dir, max_size_mb=0.001)  # ~1KB
        # Create a file larger than 1KB
        big_content = b"x" * 2048
        f = _upload("big.txt", content=big_content)

        with pytest.raises(ValueError, match="exceeds maximum"):
            await backend.save(f)

    @pytest.mark.anyio
    async def test_file_within_size_limit_accepted(self, tmp_upload_dir):
        backend = LocalStorageBackend(upload_dir=tmp_upload_dir, max_size_mb=1.0)  # 1MB
        f = _upload("small.txt", content=b"small")
        path = await backend.save(f)
        assert path.endswith("small.txt")

    def test_ensure_dir_creates_directory(self, tmp_path):
        upload_dir = tmp_path / "new_dir"
        backend = LocalStorageBackend(upload_dir=upload_dir)
        assert not upload_dir.exists()
        backend.ensure_dir()
        assert upload_dir.is_dir()


# ===========================================================================
# 19.5 — FileUploadWidget
# ===========================================================================


class TestFileUploadWidget:
    def test_macro_name(self):
        w = FileUploadWidget()
        assert w.macro_name == "file_upload"

    def test_parse_none(self):
        w = FileUploadWidget()
        assert w.parse(None) is None

    def test_parse_empty(self):
        w = FileUploadWidget()
        assert w.parse("") is None

    def test_parse_passthrough(self):
        w = FileUploadWidget()
        assert w.parse("some_value") == "some_value"

    def test_validate_required(self):
        w = FileUploadWidget()
        field = _field(required=True)
        errors = w.validate(None, field)
        assert any("required" in e.lower() for e in errors)

    def test_validate_not_required(self):
        w = FileUploadWidget()
        field = _field(required=False)
        errors = w.validate(None, field)
        assert errors == []

    def test_render_context(self):
        w = FileUploadWidget(max_size_mb=10.0, accept=".pdf,.docx")
        field = _field()
        ctx = w.render_context(field, "docs/file.pdf")
        assert ctx["max_size_mb"] == 10.0
        assert ctx["accept"] == ".pdf,.docx"
        assert ctx["current_file"] == "docs/file.pdf"

    def test_render_context_no_value(self):
        w = FileUploadWidget()
        field = _field()
        ctx = w.render_context(field, None)
        assert ctx["current_file"] == ""


# ===========================================================================
# ImageUploadWidget
# ===========================================================================


class TestImageUploadWidget:
    def test_macro_name(self):
        w = ImageUploadWidget()
        assert w.macro_name == "image_upload"

    def test_default_accept_is_image(self):
        w = ImageUploadWidget()
        assert w.accept == "image/*"

    def test_render_context(self):
        w = ImageUploadWidget(max_size_mb=5.0)
        field = _field()
        ctx = w.render_context(field, "images/photo.jpg")
        assert ctx["max_size_mb"] == 5.0
        assert ctx["accept"] == "image/*"
        assert ctx["current_file"] == "images/photo.jpg"


# ===========================================================================
# Widget registry mapping
# ===========================================================================


class TestRegistryMapping:
    def test_large_binary_maps_to_file_upload(self):
        from fastapi_admin_kit.widgets.registry import widget_registry
        from fastapi_admin_kit.widgets.resolver import WidgetResolver
        from fastapi_admin_kit.types import ColumnMeta
        from sqlalchemy import LargeBinary

        col = ColumnMeta(name="avatar", type=LargeBinary())
        resolver = WidgetResolver(widget_registry)
        widget = resolver.resolve(col)
        assert isinstance(widget, FileUploadWidget)
