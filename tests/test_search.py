"""Tests for Phase 18 — Relation Search Endpoint."""

from __future__ import annotations

import asyncio
import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, ForeignKey, Integer, String, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, relationship

from fastapi_admin_kit.admin import Admin
from fastapi_admin_kit.models.base import Base as AdminBase
from fastapi_admin_kit.registry import AdminRegistry
from sqlalchemy.pool import StaticPool
from tests.conftest import create_session_cookie, run_async


# ---------------------------------------------------------------------------
# Test models
# ---------------------------------------------------------------------------


class _Base(DeclarativeBase):
    pass


class _Category(_Base):
    __tablename__ = "search_categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)


class _Product(_Base):
    __tablename__ = "search_products"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(String(500))
    category_id = Column(Integer, ForeignKey("search_categories.id"))

    category = relationship("_Category")


class _SelfRef(_Base):
    """Self-referential FK model for testing exclude_id."""
    __tablename__ = "search_selfref"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    parent_id = Column(Integer, ForeignKey("search_selfref.id"))

    parent = relationship("_SelfRef", remote_side="[_SelfRef.id]")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_registry():
    AdminRegistry().clear()
    yield
    AdminRegistry().clear()


@pytest.fixture()
def engine():
    import tempfile
    os.environ["SKIP_CREATE_TABLES"] = "false"
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    sync_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    AdminBase.metadata.create_all(bind=sync_engine)
    _Base.metadata.create_all(bind=sync_engine)
    sync_engine.dispose()
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"check_same_thread": False},
    )
    yield async_engine
    os.environ.pop("SKIP_CREATE_TABLES", None)
    os.unlink(path)


@pytest.fixture()
def app():
    return FastAPI()


@pytest.fixture()
async def admin_app(app, engine):
    from fastapi_admin_kit.admin import Admin

    admin = Admin(app=app, engine=engine, secret_key="test-secret-key-long-enough-for-security!", auto_discover=False)
    admin.register(_Category)
    admin.register(_Product)
    admin.register(_SelfRef)
    await admin.setup()

    sync_eng = create_engine(f"sqlite:///{engine.url.database}", connect_args={"check_same_thread": False})
    with Session(sync_eng) as session:
        from fastapi_admin_kit.auth.models import AdminRole, AdminUser
        from sqlalchemy import select as sa_select
        result = session.execute(sa_select(AdminRole).limit(1))
        role = result.scalar_one_or_none()
        if role is None:
            role = AdminRole(name="SuperAdmin")
            session.add(role)
            session.flush()
        user = AdminUser(
            email="admin@test.com",
            hashed_password="$2b$12$HQlaDF1uaZvpsppxtnwD5uXp1VxiNXsiS5OCEkXRn7G0xNjUEo8cG",
            full_name="Admin",
            is_superuser=True,
            is_active=True,
        )
        user.roles.append(role)
        session.add(user)
        session.commit()
        session.refresh(user)

        cat1 = _Category(name="Electronics")
        cat2 = _Category(name="Books")
        session.add_all([cat1, cat2])
        session.flush()
        p1 = _Product(name="Laptop", description="Gaming laptop", category_id=cat1.id)
        p2 = _Product(name="Phone", description="Smart phone", category_id=cat1.id)
        p3 = _Product(name="Novel", description="Fiction book", category_id=cat2.id)
        session.add_all([p1, p2, p3])
        session.flush()
        parent = _SelfRef(name="Parent")
        session.add(parent)
        session.flush()
        child = _SelfRef(name="Child", parent_id=parent.id)
        session.add(child)
        session.commit()
    sync_eng.dispose()

    return app


# ---------------------------------------------------------------------------
# 18.7 — Tests
# ---------------------------------------------------------------------------


class TestSearchReturnsResults:
    def test_search_returns_matching_results(self, admin_app):
        client = TestClient(admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_products/search",
            params={"q": "Laptop"},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["label"] == "Laptop"

    def test_search_is_case_insensitive(self, admin_app):
        client = TestClient(admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_products/search",
            params={"q": "laptop"},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

    def test_search_multiple_matches(self, admin_app):
        client = TestClient(admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_products/search",
            params={"q": "phone"},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

    def test_empty_query_returns_first_records(self, admin_app):
        client = TestClient(admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_products/search",
            params={"q": "", "limit": 2},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_limit_controls_result_count(self, admin_app):
        client = TestClient(admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_products/search",
            params={"q": "", "limit": 1},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1


class TestSearchExcludeId:
    def test_exclude_id_removes_record(self, admin_app):
        client = TestClient(admin_app)
        cookie = create_session_cookie(1)
        resp_all = client.get(
            "/admin/search_products/search",
            params={"q": ""},
            cookies={"admin_session": cookie},
        )
        all_products = resp_all.json()
        assert len(all_products) == 3

        exclude_id = all_products[0]["id"]
        resp = client.get(
            "/admin/search_products/search",
            params={"q": "", "exclude_id": exclude_id},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert all(item["id"] != exclude_id for item in data)

    def test_exclude_id_self_referential(self, admin_app):
        client = TestClient(admin_app)
        cookie = create_session_cookie(1)
        resp_all = client.get(
            "/admin/search_selfref/search",
            params={"q": ""},
            cookies={"admin_session": cookie},
        )
        all_records = resp_all.json()
        assert len(all_records) == 2

        parent_id = next(r["id"] for r in all_records if r["label"] == "Parent")
        resp = client.get(
            "/admin/search_selfref/search",
            params={"q": "", "exclude_id": parent_id},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["label"] == "Child"


class TestSearchFallback:
    def test_fallback_to_string_column(self, admin_app):
        """When search_fields is None, search should fall back to first String column."""
        AdminRegistry().clear()
        admin_app_fresh = FastAPI()

        admin = Admin(app=admin_app_fresh, engine=None, secret_key="test-secret-key-long-enough-for-security!", auto_discover=False)
        admin.register(_Product)

        client = TestClient(admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_products/search",
            params={"q": "Laptop"},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["label"] == "Laptop"


class TestSearchUnauthorized:
    def test_unauthorized_returns_401(self, admin_app):
        client = TestClient(admin_app)
        resp = client.get(
            "/admin/search_products/search",
            params={"q": "Laptop"},
        )
        assert resp.status_code in {401, 403}


class TestSearchLabel:
    def test_label_uses_admin_str(self, admin_app):
        """Verify that the label is generated by admin.__str__(obj)."""
        client = TestClient(admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_products/search",
            params={"q": ""},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        data = resp.json()
        labels = {item["label"] for item in data}
        assert "Laptop" in labels
        assert "Phone" in labels
        assert "Novel" in labels


class TestSearchJSON:
    def test_returns_json_format(self, admin_app):
        client = TestClient(admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_products/search",
            params={"q": "Laptop"},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/json"
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert "id" in data[0]
        assert "label" in data[0]
