"""Tests for the @endpoint decorator — custom ModelAdmin FastAPI routes."""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit import Admin, ModelAdmin, endpoint
from fastapi_admin_kit.admin.decorators import EndpointOptions
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.migrations.models import Role, User
from fastapi_admin_kit.models.base import Base as AdminBase
from tests.conftest import SECRET_KEY, create_session_cookie, run_async
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


@pytest.fixture
def admin_user(engine):
    async def _create():
        async with AsyncSession(engine) as session:
            role = Role(name="SuperAdmin")
            session.add(role)
            await session.flush()
            user = User(
                email="admin@test.com",
                password="$2b$12$HQlaDF1uaZvpsppxtnwD5uXp1VxiNXsiS5OCEkXRn7G0xNjUEo8cG",
                full_name="Admin",
                is_superuser=True,
                is_active=True,
            )
            user.roles.append(role)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return run_async(_create())


class HealthResponse(BaseModel):
    status: str


class ProductEndpointAdmin(ModelAdmin):
    @endpoint(
        path="/health-check",
        methods=["GET"],
        tags=["monitoring"],
        description="Health check endpoint",
        summary="Health summary",
        response_description="Healthy status",
        permission="view",
    )
    async def health_check(self, request):
        return {"status": "healthy"}

    @endpoint(
        path="/typed",
        methods=["GET"],
        response_model=HealthResponse,
        status_code=201,
    )
    async def typed(self, request: Request, limit: int = 3):
        assert request is not None
        return HealthResponse(status=f"ok-{limit}")

    @endpoint(path="/submit", methods=["POST"])
    async def submit(self, request):
        return {"submitted": True}


@pytest.fixture
def client(engine, admin_user):
    app = FastAPI()
    admin = Admin(
        app=app,
        engine=engine,
        secret_key=SECRET_KEY,
        auth_backend=BuiltinAuthBackend(),
        auto_discover=False,
    )
    admin.register(Product, ProductEndpointAdmin)
    asyncio.run(admin.setup(app))
    return TestClient(app), admin, engine


# ===========================================================================
# Decorator metadata
# ===========================================================================


class TestEndpointDecoratorMetadata:
    def test_sets_admin_endpoint_attribute(self):
        opts = ProductEndpointAdmin.__dict__["health_check"]._admin_endpoint
        assert isinstance(opts, EndpointOptions)
        assert opts.path == "/health-check"
        assert opts.methods == ["GET"]
        assert opts.tags == ["monitoring"]
        assert opts.description == "Health check endpoint"
        assert opts.summary == "Health summary"
        assert opts.response_description == "Healthy status"
        assert opts.permission == "view"

    def test_defaults(self):
        class DefaultAdmin(ModelAdmin):
            @endpoint(path="/foo")
            async def foo(self, request):
                return {}

        opts = DefaultAdmin.__dict__["foo"]._admin_endpoint
        assert opts.methods == ["GET"]
        assert opts.tags == []
        assert opts.description == ""
        assert opts.name == ""
        assert opts.dependencies == []
        assert opts.status_code == 200
        assert opts.response_model is None
        assert opts.permission is None
        assert opts.include_in_schema is True

    def test_auto_name(self):
        class AutoAdmin(ModelAdmin):
            @endpoint(path="/auto")
            async def my_endpoint(self, request):
                return {}

        assert AutoAdmin.__dict__["my_endpoint"]._admin_endpoint.name == ""

    def test_exported_from_package(self):
        from fastapi_admin_kit import endpoint as pkg_endpoint

        assert pkg_endpoint is endpoint


# ===========================================================================
# Router registration
# ===========================================================================


class TestEndpointRouterRegistration:
    def test_routes_registered(self, client):
        _, _, _ = client
        from fastapi_admin_kit.registry import AdminRegistry

        registered = AdminRegistry().get("products")
        from fastapi_admin_kit.router import build_model_router

        router = build_model_router(registered)
        paths = {r.path: r.methods for r in router.routes}
        assert "/products/health-check" in paths
        assert "/products/typed" in paths
        assert "/products/submit" in paths
        assert "GET" in paths["/products/health-check"]
        assert "POST" in paths["/products/submit"]

    def test_name_generated(self, client):
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.router import build_model_router

        registered = AdminRegistry().get("products")
        router = build_model_router(registered)
        named = {r.name for r in router.routes}
        assert "products_health_check" in named

    def test_existing_routes_unchanged(self, client):
        from fastapi_admin_kit.registry import AdminRegistry
        from fastapi_admin_kit.router import build_model_router

        registered = AdminRegistry().get("products")
        router = build_model_router(registered)
        paths = {r.path for r in router.routes}
        assert "/products/" in paths
        assert "/products/create" in paths
        assert "/products/bulk" in paths
        assert "/products/export/" in paths


# ===========================================================================
# End-to-end HTTP behaviour
# ===========================================================================


class TestEndpointHTTP:
    def test_health_check_requires_auth(self, client):
        test_client, _, _ = client
        resp = test_client.get("/admin/products/health-check")
        assert resp.status_code in {401, 403}

    def test_health_check_authenticated(self, client, admin_user):
        test_client, _, _ = client
        cookie = create_session_cookie(admin_user.id)
        resp = test_client.get("/admin/products/health-check", cookies={"admin_session": cookie})
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy"}

    def test_untyped_request_injected(self, client, admin_user):
        test_client, _, _ = client
        cookie = create_session_cookie(admin_user.id)
        resp = test_client.get("/admin/products/health-check", cookies={"admin_session": cookie})
        assert resp.json() == {"status": "healthy"}

    def test_typed_request_and_query_param(self, client, admin_user):
        test_client, _, _ = client
        cookie = create_session_cookie(admin_user.id)
        resp = test_client.get("/admin/products/typed?limit=7", cookies={"admin_session": cookie})
        assert resp.status_code == 201
        assert resp.json() == {"status": "ok-7"}

    def test_default_query_param(self, client, admin_user):
        test_client, _, _ = client
        cookie = create_session_cookie(admin_user.id)
        resp = test_client.get("/admin/products/typed", cookies={"admin_session": cookie})
        assert resp.status_code == 201
        assert resp.json() == {"status": "ok-3"}

    def test_post_method(self, client, admin_user):
        test_client, _, _ = client
        cookie = create_session_cookie(admin_user.id)
        resp = test_client.post("/admin/products/submit", cookies={"admin_session": cookie})
        assert resp.status_code == 200
        assert resp.json() == {"submitted": True}

    def test_rbac_permission_denied_for_regular_user(self, client):
        """A non-superuser without the view permission gets 403."""
        test_client, _, engine = client

        async def _create_user():
            async with AsyncSession(engine) as session:
                role = Role(name="Viewer")
                session.add(role)
                await session.flush()
                user = User(
                    email="viewer@test.com",
                    password="$2b$12$HQlaDF1uaZvpsppxtnwD5uXp1VxiNXsiS5OCEkXRn7G0xNjUEo8cG",
                    full_name="Viewer",
                    is_superuser=False,
                    is_active=True,
                )
                user.roles.append(role)
                session.add(user)
                await session.commit()
                await session.refresh(user)
                return user

        user = run_async(_create_user())
        cookie = create_session_cookie(user.id)
        resp = test_client.get("/admin/products/health-check", cookies={"admin_session": cookie})
        assert resp.status_code == 403

    def test_openapi_includes_endpoint(self, client, admin_user):
        test_client, _, _ = client
        schema = test_client.get("/openapi.json").json()
        assert "/admin/products/health-check" in schema["paths"]
        get_op = schema["paths"]["/admin/products/health-check"]["get"]
        assert get_op["tags"] == ["Product", "monitoring"]
        assert get_op["summary"] == "Health summary"
        assert get_op["description"] == "Health check endpoint"
        assert get_op["responses"]["200"]["description"] == "Healthy status"

    def test_response_model_documented(self, client, admin_user):
        test_client, _, _ = client
        schema = test_client.get("/openapi.json").json()
        path = "/admin/products/typed"
        assert "201" in schema["paths"][path]["get"]["responses"]
        assert schema["paths"][path]["get"]["responses"]["201"]["content"]
