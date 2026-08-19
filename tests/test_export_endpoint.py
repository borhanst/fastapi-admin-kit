"""Tests for per-model endpoint export control (export_endpoint) and standalone router export."""

from __future__ import annotations

import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit import Admin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.migrations.models import User
from fastapi_admin_kit.modeladmin import ModelAdmin
from fastapi_admin_kit.models.base import Base as AdminBase
from tests.conftest import SECRET_KEY, run_async
from tests.test_registry import Product


@pytest.fixture(autouse=True)
def _clear_registry():
    from fastapi_admin_kit.registry import AdminRegistry

    AdminRegistry().clear()
    yield
    AdminRegistry().clear()


@pytest.fixture
def engine():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    sync_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    AdminBase.metadata.create_all(sync_engine)
    Product.metadata.create_all(sync_engine)
    sync_engine.dispose()
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield async_engine
    run_async(async_engine.dispose())
    os.unlink(path)


def _build_app(engine, admin_class):
    """Build a fully-setup FastAPI app with *admin_class* registered for Product."""
    admin = Admin(
        engine=engine,
        auth_model=User,
        auth_backend=BuiltinAuthBackend(),
        secret_key=SECRET_KEY,
        auto_discover=False,
        session_secure=False,
    )
    admin.register(Product, admin_class)
    app = FastAPI()
    run_async(admin.setup(app))
    return TestClient(app)


def _openapi_paths(client) -> dict:
    return client.get("/openapi.json").json()["paths"]


class TestDefaultExportEndpoint:
    def test_none_builds_both_routers_but_only_api_in_schema(self, engine):
        class ProductAdmin(ModelAdmin):
            pass

        client = _build_app(engine, ProductAdmin)
        paths = _openapi_paths(client)

        # JSON API routes are present in the schema.
        assert "/api/products" in paths
        assert "/api/products/{item_id}" in paths

        # Admin HTML model routes exist at runtime…
        resp = client.get("/admin/products/")
        assert resp.status_code != 404

        # …but never leak into the OpenAPI schema.
        assert not any(p.startswith("/admin/products") for p in paths)


class TestApiOnlyExportEndpoint:
    def test_api_excludes_admin_routes(self, engine):
        class ProductAdmin(ModelAdmin):
            export_endpoint = "api"

        client = _build_app(engine, ProductAdmin)
        paths = _openapi_paths(client)

        # JSON API routes are present.
        assert "/api/products" in paths
        assert "/api/products/{item_id}" in paths

        # No admin HTML routes for the model — neither mounted nor in schema.
        assert not any(p.startswith("/admin/products") for p in paths)
        assert client.get("/admin/products/").status_code == 404


class TestHtmlOnlyExportEndpoint:
    def test_html_excludes_api_routes(self, engine):
        class ProductAdmin(ModelAdmin):
            export_endpoint = "html"

        client = _build_app(engine, ProductAdmin)
        paths = _openapi_paths(client)

        # No JSON API routes for the model.
        assert not any(p.startswith("/api/products") for p in paths)

        # Admin HTML model routes are mounted…
        assert client.get("/admin/products/").status_code != 404

        # …but hidden from the OpenAPI schema.
        assert not any(p.startswith("/admin/products") for p in paths)


class TestStandaloneExport:
    def test_export_api_route_works_without_register(self):
        class ProductAdmin(ModelAdmin):
            export_endpoint = "api"

        router = ProductAdmin().export_api_route(Product)
        assert router is not None

        app = FastAPI()
        app.include_router(router)
        paths = app.openapi()["paths"]
        assert "/products" in paths
        assert "/products/{item_id}" in paths

    def test_export_api_route_with_prefix(self):
        class ProductAdmin(ModelAdmin):
            pass

        router = ProductAdmin().export_api_route(Product, prefix="/api")
        app = FastAPI()
        app.include_router(router)
        paths = app.openapi()["paths"]
        assert "/api/products" in paths

    def test_export_admin_route_works_without_register(self):
        class ProductAdmin(ModelAdmin):
            export_endpoint = "api"

        router = ProductAdmin().export_admin_route(Product, prefix="/admin")
        assert router is not None

        app = FastAPI()
        app.include_router(router)
        # Admin HTML routes are mounted but hidden from the schema entirely.
        assert app.openapi()["paths"] == {}

    def test_standalone_export_does_not_write_to_registry(self):
        from fastapi_admin_kit.registry import AdminRegistry

        class ProductAdmin(ModelAdmin):
            export_endpoint = "api"

        ProductAdmin().export_api_route(Product)
        ProductAdmin().export_admin_route(Product)
        assert AdminRegistry().get("products") is None
