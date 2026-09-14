"""API schema forms: enum dropdowns and multipart file upload in Swagger.

- Enum columns map to real ``Enum`` types in the create/update schemas, so
  Swagger renders them as dropdowns (both Python-enum and plain string enums).
- Models with file/image fields expose POST/PUT/PATCH as multipart forms so
  files can be picked in Swagger; uploads run through the same storage-backed
  save used by the HTML form.
"""

from __future__ import annotations

import base64
import enum
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, Enum, Integer, LargeBinary, String, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit import Admin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.migrations.models import Role, User
from fastapi_admin_kit.modeladmin import ModelAdmin
from fastapi_admin_kit.models.base import Base as AdminBase
from fastapi_admin_kit.widgets.inputs import ImageUploadWidget
from tests.conftest import SECRET_KEY, run_async


class Base(DeclarativeBase):
    pass


class TicketStatus(enum.StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    status = Column(Enum(TicketStatus), nullable=True)


class Survey(Base):
    __tablename__ = "surveys"
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    mood = Column(Enum("happy", "sad", name="survey_mood"), nullable=True)


class Photo(Base):
    __tablename__ = "photos"
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    image_url = Column(String(500), nullable=True)
    raw = Column(LargeBinary, nullable=True)


@pytest.fixture(autouse=True)
def _clear_registry():
    from fastapi_admin_kit.registry import AdminRegistry

    AdminRegistry().clear()
    yield
    AdminRegistry().clear()


def _make_client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    sync_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    AdminBase.metadata.create_all(sync_engine)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def _seed():
        async with AsyncSession(async_engine) as session:
            role = Role(name="SuperAdmin")
            session.add(role)
            await session.flush()
            user = User(
                email="test@example.com",
                password="$2b$12$DOXzSwSZYp0Y1pTzEvWjO.KOLQg3wA/Ez1RkN4RHMiLqngoLM2lMG",
                full_name="Test User",
                is_superuser=True,
                is_active=True,
            )
            user.roles.append(role)
            session.add(user)
            await session.commit()

    run_async(_seed())

    from fastapi_admin_kit.storage.local import LocalStorageBackend

    class PhotoAdmin(ModelAdmin):
        formfield_overrides = {"image_url": ImageUploadWidget()}

    admin = Admin(
        engine=async_engine,
        auth_model=User,
        auth_backend=BuiltinAuthBackend(),
        secret_key=SECRET_KEY,
        auto_discover=False,
        session_secure=False,
        storage=LocalStorageBackend(upload_dir=str(tmp_path / "uploads")),
    )
    admin.register(Ticket, ModelAdmin)
    admin.register(Survey, ModelAdmin)
    admin.register(Photo, PhotoAdmin)
    app = FastAPI()
    run_async(admin.setup(app))
    client = TestClient(app)
    creds = base64.b64encode(b"test@example.com:secret").decode()
    token = client.post("/api/auth/token", headers={"Authorization": f"Basic {creds}"}).json()[
        "access_token"
    ]
    headers = {"Authorization": f"Bearer {token}"}

    def cleanup():
        run_async(async_engine.dispose())
        os.unlink(path)

    return client, headers, cleanup


@pytest.fixture
def client_env(tmp_path):
    client, headers, cleanup = _make_client(tmp_path)
    yield client, headers
    cleanup()


def _resolve_ref(openapi, ref):
    node = openapi
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


def _deref(openapi, schema):
    """Follow $ref (incl. nullable anyOf wrappers) to the concrete schema."""
    while True:
        if "$ref" in schema:
            schema = _resolve_ref(openapi, schema["$ref"])
        elif "anyOf" in schema:
            non_null = [s for s in schema["anyOf"] if s.get("type") != "null"]
            if len(non_null) != 1:
                return schema
            schema = non_null[0]
        else:
            return schema


def _is_file_picker(prop):
    """True when the OpenAPI property renders as a Swagger file picker."""
    variants = prop.get("anyOf", [prop])
    return any(
        v.get("format") == "binary" or v.get("contentMediaType") == "application/octet-stream"
        for v in variants
    )


def _post_body_props(openapi, path):
    op = openapi["paths"][path]["post"]
    ctype, media = next(iter(op["requestBody"]["content"].items()))
    schema = media["schema"]
    if "$ref" in schema:
        schema = _resolve_ref(openapi, schema["$ref"])
    return ctype, schema.get("properties", {})


# ===========================================================================
# Enum dropdowns
# ===========================================================================


class TestApiEnumDropdown:
    def test_python_enum_schema_is_real_enum(self, client_env):
        client, _ = client_env
        openapi = client.get("/openapi.json").json()
        ctype, props = _post_body_props(openapi, "/api/tickets")
        assert ctype == "application/json"
        status_schema = _deref(openapi, props["status"])
        assert set(status_schema["enum"]) == {"open", "closed"}

    def test_plain_string_enum_gets_dropdown(self, client_env):
        client, _ = client_env
        openapi = client.get("/openapi.json").json()
        ctype, props = _post_body_props(openapi, "/api/surveys")
        assert ctype == "application/json"
        mood_schema = _deref(openapi, props["mood"])
        assert set(mood_schema["enum"]) == {"happy", "sad"}

    def test_create_with_enum_value(self, client_env):
        client, headers = client_env
        resp = client.post(
            "/api/tickets", headers=headers, json={"title": "T1", "status": "open"}
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "open"

    def test_create_rejects_unknown_enum_value(self, client_env):
        client, headers = client_env
        resp = client.post(
            "/api/tickets", headers=headers, json={"title": "T1", "status": "bogus"}
        )
        assert resp.status_code == 422


# ===========================================================================
# Multipart file/image upload
# ===========================================================================


class TestApiMultipartUpload:
    def test_file_model_uses_multipart_with_file_picker(self, client_env):
        client, _ = client_env
        openapi = client.get("/openapi.json").json()
        ctype, props = _post_body_props(openapi, "/api/photos")
        assert ctype == "multipart/form-data"
        assert _is_file_picker(props["image_url"])
        assert _is_file_picker(props["raw"])
        assert "string" in str(props["title"])

    def test_non_file_model_keeps_json_body(self, client_env):
        client, _ = client_env
        openapi = client.get("/openapi.json").json()
        ctype, _ = _post_body_props(openapi, "/api/tickets")
        assert ctype == "application/json"

    def test_multipart_create_uploads_file(self, client_env):
        client, headers = client_env
        resp = client.post(
            "/api/photos",
            headers=headers,
            data={"title": "Sunset"},
            files={"image_url": ("sunset.png", b"PNGDATA", "image/png")},
        )
        assert resp.status_code == 201, resp.text
        photo_id = resp.json()["id"]
        body = client.get(f"/api/photos/{photo_id}", headers=headers).json()
        assert body["title"] == "Sunset"
        assert body["image_url"]  # saved path, not empty

    def test_multipart_patch_without_file_keeps_existing(self, client_env):
        client, headers = client_env
        created = client.post(
            "/api/photos",
            headers=headers,
            data={"title": "Before"},
            files={"image_url": ("a.png", b"PNGDATA", "image/png")},
        )
        assert created.status_code == 201, created.text
        photo_id = created.json()["id"]
        before = client.get(f"/api/photos/{photo_id}", headers=headers).json()["image_url"]

        patched = client.patch(
            f"/api/photos/{photo_id}",
            headers=headers,
            data={"title": "After"},
        )
        assert patched.status_code == 200, patched.text
        after = client.get(f"/api/photos/{photo_id}", headers=headers).json()
        assert after["title"] == "After"
        assert after["image_url"] == before
