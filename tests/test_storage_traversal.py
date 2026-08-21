"""Regression tests for S09 (path traversal) and S15 (unbounded reads).

S09: ``LocalStorageBackend.delete()`` joined ``upload_dir / path`` without a
jail check, so an attacker-controlled DB value like ``../../.env`` deleted
files outside the upload directory. The ``directory`` argument to ``save()``
was also unvalidated.

S15: files were fully read into RAM before the size check and
``max_size_mb=None`` meant unlimited. Size is now checked from
``UploadFile.size`` *before* reading, and ``None`` defaults to 10 MB.
"""

from __future__ import annotations

import io

import pytest
from starlette.datastructures import UploadFile

from fastapi_admin_kit.storage.base import DEFAULT_MAX_SIZE_MB
from fastapi_admin_kit.storage.local import LocalStorageBackend
from fastapi_admin_kit.types import FieldMeta
from fastapi_admin_kit.views.file_handler import handle_file_field
from fastapi_admin_kit.widgets.inputs import FileUploadWidget


def _upload(filename: str, content: bytes = b"hello") -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(content))


class _NoReadBytesIO(io.BytesIO):
    """BytesIO that records whether its content was ever read."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.read_called = False

    def read(self, *args, **kwargs):
        self.read_called = True
        return super().read(*args, **kwargs)


class _State:
    def __init__(self, storage):
        self.admin_storage = storage


class _App:
    def __init__(self, storage):
        self.state = _State(storage)


class _StubRequest:
    """Minimal request stand-in for handle_file_field (only needs app.state)."""

    def __init__(self, storage):
        self.app = _App(storage)


@pytest.fixture
def backend(tmp_path):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    return LocalStorageBackend(upload_dir=upload_dir, base_url="/uploads")


# ===========================================================================
# S09 — delete() jail check
# ===========================================================================


class TestDeleteJailCheck:
    async def test_traversal_delete_rejected(self, backend, tmp_path):
        sentinel = tmp_path / ".env"
        sentinel.write_text("SECRET=1")
        with pytest.raises(ValueError):
            await backend.delete("../../.env")
        assert sentinel.exists()

    async def test_sibling_escape_rejected(self, backend, tmp_path):
        sibling = tmp_path / "sibling.txt"
        sibling.write_text("x")
        with pytest.raises(ValueError):
            await backend.delete("../sibling.txt")
        assert sibling.exists()

    async def test_nested_traversal_rejected(self, backend, tmp_path):
        sentinel = tmp_path / "escape.txt"
        sentinel.write_text("x")
        with pytest.raises(ValueError):
            await backend.delete("subdir/../../escape.txt")
        assert sentinel.exists()

    async def test_absolute_path_delete_rejected(self, backend, tmp_path):
        outside = tmp_path / "outside.txt"
        outside.write_text("x")
        with pytest.raises(ValueError):
            await backend.delete(str(outside))
        assert outside.exists()

    async def test_windows_style_traversal_rejected(self, backend):
        with pytest.raises(ValueError):
            await backend.delete("..\\..\\windows\\system32\\config")

    async def test_legitimate_delete_still_works(self, backend):
        path = await backend.save(_upload("legit.txt"))
        target = backend.upload_dir / path
        assert target.is_file()
        await backend.delete(path)
        assert not target.exists()

    async def test_delete_nonexistent_inside_jail_no_error(self, backend):
        await backend.delete("nonexistent/file.txt")


# ===========================================================================
# S09 — save() directory validation
# ===========================================================================


class TestSaveDirectoryValidation:
    async def test_parent_directory_rejected(self, backend, tmp_path):
        with pytest.raises(ValueError):
            await backend.save(_upload("evil.txt"), directory="..")
        assert not (tmp_path / "evil.txt").exists()

    async def test_traversal_directory_rejected(self, backend, tmp_path):
        with pytest.raises(ValueError):
            await backend.save(_upload("evil.txt"), directory="../../evil")
        assert not list(tmp_path.glob("evil"))

    async def test_slash_in_directory_rejected(self, backend):
        with pytest.raises(ValueError):
            await backend.save(_upload("f.txt"), directory="a/b")

    async def test_dotdot_only_directory_rejected(self, backend):
        with pytest.raises(ValueError):
            await backend.save(_upload("f.txt"), directory="..")

    async def test_valid_directory_accepted(self, backend):
        path = await backend.save(_upload("ok.txt"), directory="documents")
        assert path.startswith("documents/")
        assert (backend.upload_dir / path).is_file()


# ===========================================================================
# S15 — bounded reads
# ===========================================================================


class TestBoundedReads:
    def test_default_max_size_constant(self):
        assert DEFAULT_MAX_SIZE_MB == 10

    async def test_none_max_size_uses_default_limit(self, tmp_path):
        backend = LocalStorageBackend(upload_dir=tmp_path / "u", max_size_mb=None)
        payload = _NoReadBytesIO(b"x" * 64)
        big = UploadFile(file=payload, size=11 * 1024 * 1024, filename="big.bin")
        with pytest.raises(ValueError, match="exceeds maximum"):
            await backend.save(big)
        assert not payload.read_called, "file was read into RAM before size check"

    async def test_within_default_limit_saved(self, tmp_path):
        backend = LocalStorageBackend(upload_dir=tmp_path / "u", max_size_mb=None)
        small = UploadFile(file=io.BytesIO(b"data"), size=len(b"data"), filename="small.txt")
        path = await backend.save(small)
        assert (backend.upload_dir / path).is_file()

    async def test_explicit_limit_checked_before_read(self, tmp_path):
        backend = LocalStorageBackend(upload_dir=tmp_path / "u", max_size_mb=0.001)
        payload = _NoReadBytesIO(b"x" * 64)
        big = UploadFile(file=payload, size=2048, filename="big.txt")
        with pytest.raises(ValueError, match="exceeds maximum"):
            await backend.save(big)
        assert not payload.read_called


class TestHandleFileFieldBoundedReads:
    def _field_meta(self, name="document"):
        return FieldMeta(name=name, label=name.title(), required=False)

    async def test_widget_none_limit_uses_default(self, backend):
        payload = _NoReadBytesIO(b"x" * 64)
        big = UploadFile(file=payload, size=11 * 1024 * 1024, filename="big.bin")
        parsed: dict = {}
        errors: dict = {}
        widget = FileUploadWidget(max_size_mb=None)
        await handle_file_field(
            _StubRequest(backend),
            widget,
            self._field_meta(),
            {"document": big},
            obj=None,
            action=None,
            parsed=parsed,
            errors=errors,
        )
        assert "document" in errors
        assert not payload.read_called
        assert "document" not in parsed

    async def test_small_file_passes_through(self, backend):
        small = UploadFile(file=io.BytesIO(b"data"), filename="small.txt")
        parsed: dict = {}
        errors: dict = {}
        widget = FileUploadWidget(max_size_mb=None)
        await handle_file_field(
            _StubRequest(backend),
            widget,
            self._field_meta(),
            {"document": small},
            obj=None,
            action=None,
            parsed=parsed,
            errors=errors,
        )
        assert errors == {}
        assert "document" in parsed
