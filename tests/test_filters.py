"""Tests for the Django-style filtering system (issue #52).

Covers the shared lookup parsing, per-filter clause building, registry
auto-detection, the JSON API end-to-end, and the in-memory backend.
"""

from __future__ import annotations

import base64
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit import Admin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.migrations.models import Role, User
from fastapi_admin_kit.models.base import Base as AdminBase
from tests.conftest import SECRET_KEY, create_session_cookie, run_async
from tests.test_registry import Category, Product


@pytest.fixture(autouse=True)
def _clear_registry():
    from fastapi_admin_kit.registry import AdminRegistry

    AdminRegistry().clear()
    yield
    AdminRegistry().clear()


# ===========================================================================
# Unit: shared lookup parsing
# ===========================================================================


class TestParseFilterParams:
    def test_exact_match(self):
        from fastapi_admin_kit.filters.lookups import parse_filter_params

        value, active = parse_filter_params({"filter_name": "widget"}, "name")
        assert value == "widget"
        assert active == {"name": "widget"}

    def test_icontains(self):
        from fastapi_admin_kit.filters.lookups import parse_filter_params

        value, active = parse_filter_params({"filter_name__icontains": "wid"}, "name")
        assert value == {"icontains": "wid"}
        assert active == {"name__icontains": "wid"}

    def test_startswith_and_endswith(self):
        from fastapi_admin_kit.filters.lookups import parse_filter_params

        value, _ = parse_filter_params(
            {"filter_name__startswith": "Jo", "filter_name__endswith": "hn"}, "name"
        )
        assert value == {"startswith": "Jo", "endswith": "hn"}

    def test_numeric_lookups(self):
        from fastapi_admin_kit.filters.lookups import parse_filter_params

        value, active = parse_filter_params(
            {
                "filter_price__gt": "100",
                "filter_price__gte": "10",
                "filter_price__lt": "50",
                "filter_price__lte": "200",
            },
            "price",
        )
        assert value == {"gt": "100", "gte": "10", "lt": "50", "lte": "200"}
        assert active["price__gt"] == "100"
        assert active["price__lte"] == "200"

    def test_range_and_in(self):
        from fastapi_admin_kit.filters.lookups import parse_filter_params

        value, _ = parse_filter_params(
            {"filter_price__range": "10,200", "filter_id__in": "1,2,3"}, "price"
        )
        assert value == {"range": "10,200"}

        value, _ = parse_filter_params({"filter_id__in": "1,2,3"}, "id")
        assert value == {"in": "1,2,3"}

    def test_no_params(self):
        from fastapi_admin_kit.filters.lookups import parse_filter_params

        value, active = parse_filter_params({"q": "search"}, "name")
        assert value is None
        assert active == {}


# ===========================================================================
# Unit: Filter.apply() clause building
# ===========================================================================


class TestFilterClauses:
    def setup_method(self):
        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyQueryAdapter

        self.adapter = SqlAlchemyQueryAdapter()

    def test_text_icontains(self):
        from fastapi_admin_kit.filters import TextFilter

        clause = TextFilter("name").apply(self.adapter, None, Product, {"icontains": "wid"})
        assert clause is not None
        assert str(clause).startswith("lower(products.name) LIKE lower")

    def test_text_startswith_endswith(self):
        from fastapi_admin_kit.filters import TextFilter

        start = TextFilter("name").apply(self.adapter, None, Product, {"startswith": "Jo"})
        end = TextFilter("name").apply(self.adapter, None, Product, {"endswith": "hn"})
        assert str(start).startswith("lower(products.name) LIKE")
        assert str(end).startswith("lower(products.name) LIKE")

    def test_numeric_gt_lt_combined(self):
        from fastapi_admin_kit.filters import NumericFilter

        clause = NumericFilter("price").apply(
            self.adapter, None, Product, {"gt": "100", "lt": "200"}
        )
        assert "products.price > :" in str(clause)
        assert "products.price < :" in str(clause)

    def test_numeric_range(self):
        from fastapi_admin_kit.filters import NumericFilter

        clause = NumericFilter("price").apply(self.adapter, None, Product, {"range": "10,200"})
        assert "products.price >=" in str(clause)
        assert "products.price <=" in str(clause)

    def test_numeric_in(self):
        from fastapi_admin_kit.filters import NumericFilter

        clause = NumericFilter("price").apply(self.adapter, None, Product, {"in": "1,2,3"})
        assert "products.price IN" in str(clause)

    def test_boolean_exact(self):
        from fastapi_admin_kit.filters import BooleanFilter

        clause = BooleanFilter("is_active").apply(self.adapter, None, Product, "1")
        assert "products.is_active" in str(clause)

    def test_choice_filter_resolved_column(self):
        from fastapi_admin_kit.filters import ChoiceFilter

        f = ChoiceFilter("category", resolved_column="category_id")
        clause = f.apply(self.adapter, None, Product, {"in": "1,2"})
        assert "products.category_id IN" in str(clause)

    def test_invalid_value_skipped(self):
        from fastapi_admin_kit.filters import NumericFilter

        assert NumericFilter("price").apply(self.adapter, None, Product, "abc") is None
        assert NumericFilter("price").apply(self.adapter, None, Product, {"gte": "abc"}) is None


# ===========================================================================
# Unit: FilterRegistry auto-detection
# ===========================================================================


class TestFilterRegistry:
    def test_auto_generate_types(self):
        from fastapi_admin_kit.filters import (
            BooleanFilter,
            ChoiceFilter,
            FilterRegistry,
            NumericFilter,
            TextFilter,
        )
        from fastapi_admin_kit.registry import AdminRegistry

        reg = AdminRegistry()
        reg.clear()
        registered = reg.register(Product)
        filters = FilterRegistry().auto_generate(Product, registered.columns)

        assert isinstance(filters["name"], TextFilter)
        assert isinstance(filters["price"], NumericFilter)
        assert isinstance(filters["is_active"], BooleanFilter)
        # FK column and relationship both auto-generate ChoiceFilter
        assert isinstance(filters["category_id"], ChoiceFilter)
        assert isinstance(filters["category"], ChoiceFilter)

    def test_auto_generate_memory_backend(self):
        from fastapi_admin_kit.backends import InMemoryBackend
        from fastapi_admin_kit.filters import (
            BooleanFilter,
            DatetimeRangeFilter,
            FilterRegistry,
            NumericFilter,
            TextFilter,
        )
        from fastapi_admin_kit.schemas.schema import Field, Schema

        schema = Schema(
            table_name="products",
            fields=[
                Field(name="id", type="integer", primary_key=True),
                Field(name="name", type="string"),
                Field(name="price", type="float"),
                Field(name="is_active", type="boolean"),
                Field(name="created_at", type="datetime"),
            ],
        )
        backend = InMemoryBackend()
        product = backend.database.materialize(schema)
        columns, _ = backend.introspection.inspect_model(product)
        filters = FilterRegistry().auto_generate(product, columns, backend.introspection)

        assert isinstance(filters["name"], TextFilter)
        assert isinstance(filters["price"], NumericFilter)
        assert isinstance(filters["is_active"], BooleanFilter)
        assert isinstance(filters["created_at"], DatetimeRangeFilter)

    def test_register_custom_filter(self):
        from fastapi_admin_kit.filters import Filter, FilterRegistry

        class CustomFilter(Filter):
            def apply(self, query_adapter, query, model, value):
                return None

        registry = FilterRegistry()
        registry.register("product", CustomFilter("price"))
        assert "price" in registry.get_filters("product")
        assert isinstance(registry.get_filters("product")["price"], CustomFilter)


# ===========================================================================
# Integration: JSON API end-to-end
# ===========================================================================


def _make_client(list_filter):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    sync_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    AdminBase.metadata.create_all(sync_engine)
    Product.metadata.create_all(sync_engine)
    Category.metadata.create_all(sync_engine)
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
                hashed_password="$2b$12$DOXzSwSZYp0Y1pTzEvWjO.KOLQg3wA/Ez1RkN4RHMiLqngoLM2lMG",
                full_name="Test User",
                is_superuser=True,
                is_active=True,
            )
            user.roles.append(role)
            session.add(user)

            gadgets = Category(name="Gadgets")
            books = Category(name="Books")
            session.add_all([gadgets, books])
            await session.flush()

            session.add_all(
                [
                    Product(name="Widget", price=10, is_active=True, category_id=gadgets.id),
                    Product(name="Widglet", price=25, is_active=True, category_id=gadgets.id),
                    Product(name="Novel", price=5, is_active=False, category_id=books.id),
                    Product(name="Textbook", price=40, is_active=True, category_id=books.id),
                ]
            )
            await session.commit()

    run_async(_seed())

    from fastapi_admin_kit.modeladmin import ModelAdmin

    admin_cls = type(
        "ProductAdmin",
        (ModelAdmin,),
        {"list_filter": list_filter},
    )

    admin = Admin(
        engine=async_engine,
        auth_model=User,
        auth_backend=BuiltinAuthBackend(),
        secret_key=SECRET_KEY,
        auto_discover=False,
        session_secure=False,
    )
    admin.register(Product, admin_cls)
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
def api():
    client, headers, cleanup = _make_client(
        ["name", "price", "is_active", "category_id", "category"]
    )
    yield client, headers
    cleanup()


def _names(body):
    return {item["name"] for item in body["items"]}


class TestApiFilters:
    def test_exact_match(self, api):
        client, headers = api
        body = client.get("/api/products/?filter_name=Widget", headers=headers).json()
        assert _names(body) == {"Widget"}

    def test_icontains(self, api):
        client, headers = api
        body = client.get("/api/products/?filter_name__icontains=wid", headers=headers).json()
        assert _names(body) == {"Widget", "Widglet"}

    def test_startswith(self, api):
        client, headers = api
        body = client.get("/api/products/?filter_name__startswith=Text", headers=headers).json()
        assert _names(body) == {"Textbook"}

    def test_endswith(self, api):
        client, headers = api
        body = client.get("/api/products/?filter_name__endswith=glet", headers=headers).json()
        assert _names(body) == {"Widglet"}

    def test_numeric_gt(self, api):
        client, headers = api
        body = client.get("/api/products/?filter_price__gt=10", headers=headers).json()
        assert _names(body) == {"Widglet", "Textbook"}

    def test_numeric_gte(self, api):
        client, headers = api
        body = client.get("/api/products/?filter_price__gte=10", headers=headers).json()
        assert _names(body) == {"Widget", "Widglet", "Textbook"}

    def test_numeric_lt(self, api):
        client, headers = api
        body = client.get("/api/products/?filter_price__lt=10", headers=headers).json()
        assert _names(body) == {"Novel"}

    def test_numeric_lte(self, api):
        client, headers = api
        body = client.get("/api/products/?filter_price__lte=10", headers=headers).json()
        assert _names(body) == {"Widget", "Novel"}

    def test_numeric_range(self, api):
        client, headers = api
        body = client.get("/api/products/?filter_price__range=5,25", headers=headers).json()
        assert _names(body) == {"Widget", "Widglet", "Novel"}

    def test_in_list(self, api):
        client, headers = api
        body = client.get("/api/products/?filter_price__in=5,40", headers=headers).json()
        assert _names(body) == {"Novel", "Textbook"}

    def test_boolean_filter(self, api):
        client, headers = api
        body = client.get("/api/products/?filter_is_active=1", headers=headers).json()
        assert _names(body) == {"Widget", "Widglet", "Textbook"}

    def test_relation_choice_filter(self, api):
        client, headers = api
        body = client.get("/api/products/?filter_category=1", headers=headers).json()
        # Category id 1 == Gadgets
        assert _names(body) == {"Widget", "Widglet"}

    def test_combined_filters(self, api):
        client, headers = api
        body = client.get(
            "/api/products/?filter_name__icontains=wid&filter_price__gte=10", headers=headers
        ).json()
        assert _names(body) == {"Widget", "Widglet"}


class TestAdminUiListFilters:
    def test_icontains_in_list_view(self, api):
        client, _headers = api
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/products/?filter_name__icontains=wid",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        assert "Widget" in resp.text
        assert "Widglet" in resp.text
        assert "Novel" not in resp.text

    def test_numeric_range_in_list_view(self, api):
        client, _headers = api
        cookie = create_session_cookie(1)
        resp = client.get(
            "/admin/products/?filter_price__range=5,10",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        assert "Widget" in resp.text
        assert "Novel" in resp.text
        assert "Textbook" not in resp.text


# ===========================================================================
# Integration: in-memory backend
# ===========================================================================


class TestInMemoryLookups:
    def test_text_and_numeric_lookups(self):
        from fastapi_admin_kit.backends import InMemoryBackend
        from fastapi_admin_kit.backends.memory import MemoryQueryAdapter
        from fastapi_admin_kit.filters import NumericFilter, TextFilter
        from fastapi_admin_kit.schemas.schema import Field, Schema

        schema = Schema(
            table_name="products",
            fields=[
                Field(name="id", type="integer", primary_key=True),
                Field(name="name", type="string"),
                Field(name="price", type="float"),
            ],
        )
        backend = InMemoryBackend()
        conn = backend.database.create_connection()
        session = backend.database.create_session_factory(conn)()
        product = backend.database.materialize(schema)

        for name, price in [("alpha", 10.0), ("Beta", 20.0), ("gamma", 30.0)]:
            obj = product()
            obj.name = name
            obj.price = price
            session.add(obj)
        session.commit()

        qa = MemoryQueryAdapter()

        def run(clause):
            q = qa.where(qa.select(product), clause)
            return {o.name for o in session.all(q)}

        assert run(TextFilter("name").apply(qa, None, product, {"icontains": "a"})) == {
            "alpha",
            "Beta",
            "gamma",
        }
        assert run(TextFilter("name").apply(qa, None, product, {"startswith": "Be"})) == {"Beta"}
        assert run(TextFilter("name").apply(qa, None, product, {"endswith": "ta"})) == {"Beta"}
        assert run(NumericFilter("price").apply(qa, None, product, {"gt": "15"})) == {
            "Beta",
            "gamma",
        }
        assert run(NumericFilter("price").apply(qa, None, product, {"range": "10,20"})) == {
            "alpha",
            "Beta",
        }
        assert run(NumericFilter("price").apply(qa, None, product, {"in": "10,30"})) == {
            "alpha",
            "gamma",
        }
