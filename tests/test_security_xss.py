"""Regression tests for S05/S06 — stored XSS via Alpine.js x-data attributes.

DB values (e.g. a tag named ``');alert(1);//``) were interpolated into
single-quoted JS strings inside double-quoted HTML attributes, letting
stored values break out and execute. All interpolations now use ``|tojson``
inside single-quoted attributes.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import relationship
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit import Admin, ModelAdmin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.migrations.models import Role, User
from fastapi_admin_kit.models.base import Base as AdminBase
from tests.conftest import SECRET_KEY, create_session_cookie, run_async

XSS_PAYLOAD = "');alert(1);//"


@pytest.fixture(autouse=True)
def _clear_registry():
    from fastapi_admin_kit.registry import AdminRegistry

    AdminRegistry().clear()
    yield
    AdminRegistry().clear()


class _XSSBase(AdminBase):
    __abstract__ = True


class _Tag(_XSSBase):
    __tablename__ = "xss_tags"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)

    def __str__(self) -> str:
        return self.name


class _Article(_XSSBase):
    __tablename__ = "xss_articles"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    tag_id = Column(Integer, ForeignKey("xss_tags.id"))
    tag = relationship("_Tag")


class _ArticleAdmin(ModelAdmin):
    list_display = ["id", "title"]


@pytest.fixture
def env():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    sync_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    AdminBase.metadata.create_all(sync_engine)
    _XSSBase.metadata.create_all(sync_engine)
    sync_engine.dispose()
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def _seed():
        async with AsyncSession(async_engine) as session:
            role = Role(name="SuperAdmin")
            user = User(
                email="admin@test.com",
                hashed_password="$2b$12$HQlaDF1uaZvpsppxtnwD5uXp1VxiNXsiS5OCEkXRn7G0xNjUEo8cG",
                full_name="Admin",
                is_superuser=True,
                is_active=True,
            )
            user.roles.append(role)
            session.add(user)

            malicious_tag = _Tag(name=XSS_PAYLOAD)
            session.add(malicious_tag)
            await session.flush()

            article = _Article(title="Target", tag=malicious_tag)
            session.add(article)
            await session.commit()
            await session.refresh(article)
            return article.id

    article_id = run_async(_seed())

    app = FastAPI()
    admin = Admin(
        app=app,
        engine=async_engine,
        secret_key=SECRET_KEY,
        auth_backend=BuiltinAuthBackend(),
        auto_discover=False,
        session_secure=False,
    )
    admin.register(_Article, _ArticleAdmin)
    asyncio.run(admin.setup(app))

    client = TestClient(app)
    client.cookies.set("admin_session", create_session_cookie(1, SECRET_KEY))
    return client, article_id


class TestStoredXssInEditForm:
    def test_relation_picker_payload_is_json_encoded(self, env):
        """FK label carrying a JS break-out must be JSON-encoded, not raw."""
        client, article_id = env
        resp = client.get(f"/admin/xss_articles/{article_id}")
        assert resp.status_code == 200
        # The raw payload must not appear unescaped inside a JS string context.
        assert "relationPicker('" + XSS_PAYLOAD not in resp.text
        assert "relationPicker('')" not in resp.text.replace(XSS_PAYLOAD, "")
        # JSON encoding escapes the single quote as \u0027 — no break-out.
        picker_ctx = resp.text.split("relationPicker")[1][:200]
        assert "\\u0027" in picker_ctx or XSS_PAYLOAD not in picker_ctx

    def test_payload_never_breaks_out_of_attribute(self, env):
        client, article_id = env
        resp = client.get(f"/admin/xss_articles/{article_id}")
        assert resp.status_code == 200
        for line in resp.text.splitlines():
            if "relationPicker(" in line and "x-data=" in line:
                # |tojson escapes ' as \u0027 so the single-quoted HTML
                # attribute cannot be terminated early by stored data.
                # Old vulnerable output: relationPicker('');alert(1);//', …)
                assert "\\u0027" in line or XSS_PAYLOAD not in line
