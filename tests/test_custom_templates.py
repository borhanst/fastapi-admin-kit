"""Tests for custom template support (per-model and global overrides)."""

from __future__ import annotations

import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit import Admin
from fastapi_admin_kit.admin.admin_config import AdminConfig
from fastapi_admin_kit.migrations.models import User
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
            user = User(
                email="admin@test.com",
                password=User.hash_password("admin123"),
                full_name="Admin",
                is_superuser=True,
                is_active=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return run_async(_create())


def _make_client(engine, template_dir):
    app = FastAPI()
    admin = Admin(
        app=app,
        engine=engine,
        secret_key=SECRET_KEY,
        auto_discover=False,
        config=AdminConfig(template_dirs=[template_dir]),
    )
    admin.register(Product)
    run_async(admin.setup(app))
    return TestClient(app), admin


def test_custom_per_model_template_renders(engine, admin_user):
    """A per-model list.html override renders instead of the built-in default."""
    tmpdir = tempfile.mkdtemp()
    model_dir = os.path.join(tmpdir, "admin", "products")
    os.makedirs(model_dir)
    with open(os.path.join(model_dir, "list.html"), "w") as f:
        f.write(
            '{% extends "admin/base_list.html" %}'
            "{% block list_header %}<h1>CUSTOM-PRODUCT-LIST</h1>{% endblock %}"
        )

    client, _ = _make_client(engine, tmpdir)
    cookie = create_session_cookie(admin_user.id)
    resp = client.get("/admin/products/", cookies={"admin_session": cookie})
    assert resp.status_code == 200
    assert "CUSTOM-PRODUCT-LIST" in resp.text


def test_global_template_override_renders(engine, admin_user):
    """A global admin/form.html override is used when no per-model form exists."""
    tmpdir = tempfile.mkdtemp()
    admin_dir = os.path.join(tmpdir, "admin")
    os.makedirs(admin_dir)
    with open(os.path.join(admin_dir, "form.html"), "w") as f:
        f.write(
            '{% extends "admin/base_form.html" %}'
            "{% block form_submit_line %}<button>CUSTOM-GLOBAL-FORM</button>{% endblock %}"
        )

    client, _ = _make_client(engine, tmpdir)
    cookie = create_session_cookie(admin_user.id)
    resp = client.get("/admin/products/create", cookies={"admin_session": cookie})
    assert resp.status_code == 200
    assert "CUSTOM-GLOBAL-FORM" in resp.text


def test_builtin_default_used_when_no_custom_templates(engine, admin_user):
    """Without custom templates, the built-in defaults render fine."""
    tmpdir = tempfile.mkdtemp()
    client, _ = _make_client(engine, tmpdir)
    cookie = create_session_cookie(admin_user.id)
    resp = client.get("/admin/products/", cookies={"admin_session": cookie})
    assert resp.status_code == 200
    assert "<html" in resp.text


def test_resolve_template_precedence():
    """Explicit > per-model > global > built-in default."""
    from fastapi_admin_kit.views.renderers import resolve_template

    class _Loader:
        def __init__(self, existing):
            self._existing = set(existing)

        def get_source(self, env, name):
            if name in self._existing:
                return ("", name, None)
            raise RuntimeError("not found")

    class _Env:
        def __init__(self, existing):
            self.loader = _Loader(existing)

    class _Jinja:
        def __init__(self, existing):
            self.env = _Env(existing)

    class _State:
        admin_jinja_env = None

    class _App:
        state = _State()

    class _Req:
        app = None

    existing = {"admin/products/list.html", "admin/list.html"}
    req = _Req()
    req.app = _App()
    req.app.state.admin_jinja_env = _Jinja(existing)

    candidates = [
        "custom/products/list.html",
        "admin/products/list.html",
        "admin/list.html",
        "pages/list.html",
    ]
    assert resolve_template(req, candidates) == "admin/products/list.html"


def test_resolve_template_falls_back_to_default():
    """When nothing custom exists, the built-in default is returned."""
    from fastapi_admin_kit.views.renderers import resolve_template

    class _Loader:
        def get_source(self, env, name):
            raise RuntimeError("not found")

    class _Env:
        loader = _Loader()

    class _Jinja:
        env = _Env()

    class _State:
        admin_jinja_env = None

    class _App:
        state = _State()

    class _Req:
        app = None

    req = _Req()
    req.app = _App()
    req.app.state.admin_jinja_env = _Jinja()

    candidates = ["admin/products/list.html", "admin/list.html", "pages/list.html"]
    assert resolve_template(req, candidates) == "pages/list.html"
