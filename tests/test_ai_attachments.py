"""Tests for AI Chat File Attachments."""

from __future__ import annotations

import io

import pytest

from fastapi_admin_kit.ai.attachments import (
    detect_mime,
    validate_extension,
    validate_mime,
)
from tests.conftest import create_session_cookie

# ===========================================================================
# Attachment validation helpers
# ===========================================================================


class TestValidateExtension:
    def test_allows_pdf(self):
        assert validate_extension("report.pdf") == ".pdf"

    def test_allows_image(self):
        assert validate_extension("photo.jpg") == ".jpg"
        assert validate_extension("photo.jpeg") == ".jpeg"
        assert validate_extension("photo.png") == ".png"
        assert validate_extension("photo.webp") == ".webp"
        assert validate_extension("photo.gif") == ".gif"

    def test_allows_doc(self):
        assert validate_extension("doc.docx") == ".docx"
        assert validate_extension("doc.doc") == ".doc"

    def test_allows_excel(self):
        assert validate_extension("sheet.xlsx") == ".xlsx"
        assert validate_extension("sheet.xls") == ".xls"

    def test_allows_csv(self):
        assert validate_extension("data.csv") == ".csv"

    def test_extension_case_insensitive(self):
        assert validate_extension("report.PDF") == ".pdf"
        assert validate_extension("photo.JPG") == ".jpg"

    def test_rejects_no_extension(self):
        with pytest.raises(ValueError, match="no extension"):
            validate_extension("noextension")

    def test_rejects_disallowed_extension(self):
        with pytest.raises(ValueError, match="not allowed"):
            validate_extension("script.exe")

    def test_rejects_empty_filename(self):
        with pytest.raises(ValueError, match="Filename is required"):
            validate_extension("")

    def test_rejects_none_filename(self):
        with pytest.raises(ValueError, match="Filename is required"):
            validate_extension(None)

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError, match="not allowed"):
            validate_extension("../../../etc/passwd.exe")


class TestDetectMime:
    def test_pdf_magic_bytes(self):
        assert detect_mime("report.pdf", b"%PDF-1.4") == "application/pdf"

    def test_png_magic_bytes(self):
        assert detect_mime("image.png", b"\x89PNG\r\n\x1a\n") == "image/png"

    def test_jpeg_magic_bytes(self):
        assert detect_mime("image.jpg", b"\xff\xd8\xff") == "image/jpeg"

    def test_gif_magic_bytes(self):
        assert detect_mime("image.gif", b"GIF89a") == "image/gif"
        assert detect_mime("image.gif", b"GIF87a") == "image/gif"

    def test_webp_magic_bytes(self):
        data = b"RIFF\x00\x00\x00\x00WEBP"
        assert detect_mime("image.webp", data) == "image/webp"

    def test_fallback_to_extension(self):
        assert detect_mime("report.pdf", b"not pdf data") == "application/pdf"

    def test_fallback_to_mimetypes(self):
        assert detect_mime("report.pdf", b"some data") == "application/pdf"

    def test_unknown_returns_octet_stream(self):
        assert detect_mime("unknown.unknownext", b"some data") == "application/octet-stream"


class TestValidateMime:
    def test_pdf_matches(self):
        validate_mime(".pdf", "application/pdf")

    def test_image_matches(self):
        validate_mime(".png", "image/png")
        validate_mime(".jpg", "image/jpeg")

    def test_mismatch_raises(self):
        with pytest.raises(ValueError, match="does not match"):
            validate_mime(".pdf", "image/png")

    def test_unknown_extension_skips(self):
        validate_mime(".xyz", "application/octet-stream")


# ===========================================================================
# Upload endpoint integration tests
# ===========================================================================


class TestUploadEndpoint:
    @pytest.fixture
    def client(self, admin_app):
        from fastapi.testclient import TestClient

        return TestClient(admin_app)

    @pytest.fixture
    def auth_headers(self, admin_user):
        return {"Cookie": f"admin_session={create_session_cookie(admin_user.id)}"}

    def test_upload_pdf_returns_url(self, client, auth_headers):
        content = b"%PDF-1.4 fake pdf content"
        files = {"files": ("report.pdf", io.BytesIO(content), "application/pdf")}
        resp = client.post("/admin/ai/chat/upload", files=files, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["filename"] == "report.pdf"
        assert data[0]["mime_type"] == "application/pdf"
        assert data[0]["size"] == len(content)
        assert "url" in data[0]
        assert data[0]["id"] is not None

    def test_upload_image_returns_url(self, client, auth_headers):
        content = b"\x89PNG\r\n\x1a\nfake png"
        files = {"files": ("photo.png", io.BytesIO(content), "image/png")}
        resp = client.post("/admin/ai/chat/upload", files=files, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["mime_type"] == "image/png"

    def test_upload_rejects_disallowed_extension(self, client, auth_headers):
        files = {"files": ("script.exe", io.BytesIO(b"binary"), "application/octet-stream")}
        resp = client.post("/admin/ai/chat/upload", files=files, headers=auth_headers)
        assert resp.status_code == 400

    def test_upload_rejects_oversized_file(self, client, auth_headers):
        from fastapi_admin_kit.config.ai_chat import AIChatConfig

        original_max = AIChatConfig.max_file_size_mb
        try:
            AIChatConfig.max_file_size_mb = 0
            content = b"x" * 1024
            files = {"files": ("big.pdf", io.BytesIO(content), "application/pdf")}
            resp = client.post("/admin/ai/chat/upload", files=files, headers=auth_headers)
            assert resp.status_code == 400
        finally:
            AIChatConfig.max_file_size_mb = original_max

    def test_upload_multiple_files(self, client, auth_headers):
        files = [
            ("files", ("a.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")),
            ("files", ("b.png", io.BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")),
        ]
        resp = client.post("/admin/ai/chat/upload", files=files, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
