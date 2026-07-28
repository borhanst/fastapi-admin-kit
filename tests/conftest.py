import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit.models.base import Base as AdminBase
from tests.test_registry import Product

SECRET_KEY = "test-secret-key-long-enough-for-security!"


@pytest.fixture(autouse=True)
def _clear_registry():
    from fastapi_admin_kit.registry import AdminRegistry

    AdminRegistry().clear()
    yield
    AdminRegistry().clear()


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Product.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def app():
    from fastapi import FastAPI

    return FastAPI()


@pytest.fixture
def admin_user(engine):
    from sqlalchemy.orm import sessionmaker

    from fastapi_admin_kit.auth.models import Role, User

    AdminBase.metadata.create_all(engine)
    session_local = sessionmaker(engine)
    session = session_local()
    try:
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
        return user
    finally:
        session.close()


def create_session_cookie(user_id, secret_key=SECRET_KEY):
    from fastapi_admin_kit.auth.session import SignedCookieSessionBackend

    backend = SignedCookieSessionBackend(secret_key=secret_key)
    return backend.encode({"user_id": user_id})


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def admin_app(app, engine, admin_user):
    import asyncio
    import os

    from fastapi_admin_kit import Admin

    admin = Admin(app=app, engine=engine, secret_key=SECRET_KEY, auto_discover=False)
    os.environ["SKIP_CREATE_TABLES"] = "true"
    try:
        asyncio.run(admin.setup(app))
    finally:
        os.environ.pop("SKIP_CREATE_TABLES", None)
    return app
