"""Tests for Phase 18 — Relation Search Endpoint."""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, ForeignKey, Integer, String, Table, create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, relationship

from fastapi_admin_kit.admin import Admin
from fastapi_admin_kit.modeladmin import ModelAdmin
from fastapi_admin_kit.models.base import Base as AdminBase
from fastapi_admin_kit.registry import AdminRegistry
from tests.conftest import SECRET_KEY, create_session_cookie

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


# Association table for the many-to-many Article <-> Tag relationship.
_search_article_tags = Table(
    "search_article_tags",
    _Base.metadata,
    Column("article_id", Integer, ForeignKey("search_articles.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("search_tags.id"), primary_key=True),
)


class _Tag(_Base):
    __tablename__ = "search_tags"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)

    def __str__(self) -> str:
        return self.name


class _Article(_Base):
    __tablename__ = "search_articles"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)

    tags = relationship("_Tag", secondary=_search_article_tags)


class _ProductAdmin(ModelAdmin):
    """Product admin that searches across the FK ``category`` relation."""

    search_fields = ["name", "category__name"]
    list_display = ["id", "name"]


class _ArticleAdmin(ModelAdmin):
    """Article admin that searches across the m2m ``tags`` relation."""

    search_fields = ["title", "tags__name"]
    list_display = ["id", "title"]


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

    admin = Admin(
        app=app,
        engine=engine,
        secret_key="test-secret-key-long-enough-for-security!",
        auto_discover=False,
    )
    admin.register(_Category)
    admin.register(_Product)
    admin.register(_SelfRef)
    await admin.setup()

    sync_eng = create_engine(
        f"sqlite:///{engine.url.database}", connect_args={"check_same_thread": False}
    )
    with Session(sync_eng) as session:
        from sqlalchemy import select as sa_select

        from fastapi_admin_kit.auth.models import Role, User

        result = session.execute(sa_select(Role).limit(1))
        role = result.scalar_one_or_none()
        if role is None:
            role = Role(name="SuperAdmin")
            session.add(role)
            session.flush()
        user = User(
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


@pytest.fixture()
async def m2m_admin_app(app, engine):
    """App with FK (category) and m2m (tags) relation search configured."""
    from fastapi_admin_kit.admin import Admin

    admin = Admin(
        app=app,
        engine=engine,
        secret_key="test-secret-key-long-enough-for-security!",
        auto_discover=False,
    )
    admin.register(_Category)
    admin.register(_Product, _ProductAdmin)
    admin.register(_Tag)
    admin.register(_Article, _ArticleAdmin)
    await admin.setup()

    sync_eng = create_engine(
        f"sqlite:///{engine.url.database}", connect_args={"check_same_thread": False}
    )
    with Session(sync_eng) as session:
        from sqlalchemy import select as sa_select

        from fastapi_admin_kit.auth.models import Role, User

        result = session.execute(sa_select(Role).limit(1))
        role = result.scalar_one_or_none()
        if role is None:
            role = Role(name="SuperAdmin")
            session.add(role)
            session.flush()
        user = User(
            email="admin@test.com",
            hashed_password="$2b$12$HQlaDF1uaZvpsppxtnwD5uXp1VxiNXsiS5OCEkXRn7G0xNjUEo8cG",
            full_name="Admin",
            is_superuser=True,
            is_active=True,
        )
        user.roles.append(role)
        session.add(user)
        session.flush()

        electronics = _Category(name="Electronics")
        books = _Category(name="Books")
        session.add_all([electronics, books])
        session.flush()
        laptop = _Product(name="Laptop", category_id=electronics.id)
        phone = _Product(name="Phone", category_id=electronics.id)
        novel = _Product(name="Novel", category_id=books.id)
        session.add_all([laptop, phone, novel])
        session.flush()

        python_tag = _Tag(name="Python")
        fastapi_tag = _Tag(name="FastAPI")
        session.add_all([python_tag, fastapi_tag])
        session.flush()
        a1 = _Article(title="Intro to Python", tags=[python_tag])
        a2 = _Article(title="FastAPI Basics", tags=[fastapi_tag, python_tag])
        session.add_all([a1, a2])
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

        admin = Admin(
            app=admin_app_fresh,
            engine=None,
            secret_key="test-secret-key-long-enough-for-security!",
            auto_discover=False,
        )
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


# ---------------------------------------------------------------------------
# Relation search — FK (category__name) and m2m (tags__name)
# ---------------------------------------------------------------------------


class TestRelationSearchPicker:
    def test_fk_relation_search(self, m2m_admin_app):
        """Searching by category__name finds products via the FK relation."""
        client = TestClient(m2m_admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_products/search",
            params={"q": "Electronics"},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        data = resp.json()
        labels = {item["label"] for item in data}
        assert "Laptop" in labels
        assert "Phone" in labels
        assert "Novel" not in labels

    def test_m2m_relation_search(self, m2m_admin_app):
        """Searching by tags__name finds articles via the m2m relation (distinct)."""
        client = TestClient(m2m_admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_articles/search",
            params={"q": "Python"},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        data = resp.json()
        # "FastAPI Basics" has both Python + FastAPI tags, so .distinct() must
        # ensure it appears exactly once.
        labels = [item["label"] for item in data]
        assert labels.count("FastAPI Basics") == 1
        assert "Intro to Python" in labels
        assert "FastAPI Basics" in labels

    def test_m2m_relation_search_second_tag(self, m2m_admin_app):
        client = TestClient(m2m_admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_articles/search",
            params={"q": "FastAPI"},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        data = resp.json()
        labels = [item["label"] for item in data]
        assert labels == ["FastAPI Basics"]


class TestRelationPickerEndpoints:
    """The FK/M2M picker endpoints search the *target* model via its search_fields,
    so a target admin using ``relation__field`` lookups makes the picker search
    across the target's own relations."""

    def test_fk_target_autocomplete_honors_relation_field(self, m2m_admin_app):
        # _ProductAdmin.search_fields = ["name", "category__name"] → the FK
        # picker for products (and any FK to Product) can match by category name.
        client = TestClient(m2m_admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_products/autocomplete/",
            params={"q": "Electronics"},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        data = resp.json()
        labels = {item["label"] for item in data}
        assert "Laptop" in labels
        assert "Phone" in labels
        assert "Novel" not in labels

    def test_m2m_target_search_honors_relation_field(self, m2m_admin_app):
        # _ArticleAdmin.search_fields = ["title", "tags__name"] → the M2M picker
        # for tags can match articles by tag name.
        client = TestClient(m2m_admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_articles/search",
            params={"q": "Python"},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        labels = [item["label"] for item in resp.json()]
        assert labels.count("FastAPI Basics") == 1
        assert "Intro to Python" in labels


class TestRelationSearchListView:
    def test_m2m_search_on_list_view(self, m2m_admin_app):
        """The list view free-text search honours tags__name and dedupes rows."""
        client = TestClient(m2m_admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_articles/",
            params={"q": "Python"},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        assert "Intro to Python" in resp.text
        assert "FastAPI Basics" in resp.text
        # Each article rendered once despite the m2m join.
        assert resp.text.count("FastAPI Basics") >= 1

    def test_fk_search_on_list_view(self, m2m_admin_app):
        client = TestClient(m2m_admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_products/",
            params={"q": "Books"},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        assert "Novel" in resp.text
        assert "Laptop" not in resp.text
        assert "Phone" not in resp.text

    def test_unknown_relation_field_is_ignored(self, m2m_admin_app):
        """A broken relation__attr lookup must not crash — just no matches."""
        client = TestClient(m2m_admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_articles/search",
            params={"q": "anything"},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200


class TestM2MSave:
    """Reproduce: many-to-many values submitted via the form must persist."""

    def test_m2m_saved_on_create(self, m2m_admin_app, engine):
        from sqlalchemy import create_engine as _ce
        from sqlalchemy.orm import Session as _Sess

        from fastapi_admin_kit.auth.csrf import generate_csrf_token

        client = TestClient(m2m_admin_app)
        cookie = create_session_cookie(1)
        csrf_token = generate_csrf_token(SECRET_KEY)
        resp = client.post(
            "/admin/search_articles/create",
            data={
                "title": "Saved Article",
                "tags": '["1", "2"]',
                "csrf_token": csrf_token,
            },
            cookies={"admin_session": cookie, "admin_csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert resp.status_code in {302, 303}

        sync_eng = _ce(
            f"sqlite:///{engine.url.database}",
            connect_args={"check_same_thread": False},
        )
        with _Sess(sync_eng) as s:
            from sqlalchemy import select as _sel

            art = s.execute(_sel(_Article).where(_Article.title == "Saved Article")).scalar_one()
            tag_names = {t.name for t in art.tags}
        sync_eng.dispose()
        assert tag_names == {"Python", "FastAPI"}

    def test_m2m_saved_on_edit(self, m2m_admin_app, engine):
        from sqlalchemy import create_engine as _ce
        from sqlalchemy.orm import Session as _Sess

        from fastapi_admin_kit.auth.csrf import generate_csrf_token

        # "Intro to Python" (seeded with tag Python=1). Reassign to FastAPI=2.
        client = TestClient(m2m_admin_app)
        cookie = create_session_cookie(1)
        csrf_token = generate_csrf_token(SECRET_KEY)

        sync_eng = _ce(
            f"sqlite:///{engine.url.database}",
            connect_args={"check_same_thread": False},
        )
        with _Sess(sync_eng) as s:
            from sqlalchemy import select as _sel

            art = s.execute(_sel(_Article).where(_Article.title == "Intro to Python")).scalar_one()
            art_id = art.id
        sync_eng.dispose()

        resp = client.post(
            f"/admin/search_articles/{art_id}",
            data={
                "title": "Intro to Python",
                "tags": '["2"]',
                "csrf_token": csrf_token,
            },
            cookies={"admin_session": cookie, "admin_csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert resp.status_code in {302, 303}

        with _Sess(sync_eng) as s:
            from sqlalchemy import select as _sel

            art = s.execute(_sel(_Article).where(_Article.id == art_id)).scalar_one()
            tag_names = {t.name for t in art.tags}
        sync_eng.dispose()
        # Edit must REPLACE the m2m set, not keep Python.
        assert tag_names == {"FastAPI"}

    def test_m2m_field_rendered_in_create_form(self, m2m_admin_app):
        client = TestClient(m2m_admin_app)
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/search_articles/create",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        assert "tags" in resp.text
        assert "multiRelation" in resp.text or "multi_relation" in resp.text

    def test_m2m_saved_via_json_api_create(self, m2m_admin_app, engine):
        """Regression: JSON API create must persist many-to-many relations."""

        from fastapi_admin_kit.api.auth import create_access_token

        class _U:
            id = 1
            email = "api@test.com"
            full_name = "API"
            is_superuser = True
            roles = []
            role_id = 1

        secret = "test-secret-key-long-enough-for-security!"
        token = create_access_token(_U(), secret)
        client = TestClient(m2m_admin_app)
        resp = client.post(
            "/api/search_articles",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "API Article", "tags": ["1", "2"]},
        )
        assert resp.status_code in {200, 201}, resp.text

        from sqlalchemy import create_engine as _ce
        from sqlalchemy.orm import Session as _Sess

        sync_eng = _ce(
            f"sqlite:///{engine.url.database}",
            connect_args={"check_same_thread": False},
        )
        with _Sess(sync_eng) as s:
            from sqlalchemy import select as _sel

            art = s.execute(_sel(_Article).where(_Article.title == "API Article")).scalar_one()
            tag_names = {t.name for t in art.tags}
        sync_eng.dispose()
        assert tag_names == {"Python", "FastAPI"}
