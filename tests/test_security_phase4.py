"""Regression tests for Phase 4 — S12, S13, S14, S16, S18 batch.

* S12 — backup codes hashed with bcrypt (legacy SHA256 verify kept)
* S13 — ``needs_rehash`` parses the bcrypt cost from ``parts[2]``
* S14 — export cells starting with formula characters are neutralised
* S16 — export/import single gate; search_view proper status codes;
        validate-field requires create-or-edit
* S18 — ordering allow-list, import field allow-list, session hardening
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import io
import os
import tempfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit import Admin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.csrf import generate_csrf_token
from fastapi_admin_kit.migrations.models import Permission, Role, User
from fastapi_admin_kit.models.base import Base as AdminBase
from tests.conftest import SECRET_KEY, create_session_cookie, run_async
from tests.test_registry import Product

# bcrypt hash of "secret"
SECRET_HASH = "$2b$12$DOXzSwSZYp0Y1pTzEvWjO.KOLQg3wA/Ez1RkN4RHMiLqngoLM2lMG"


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


async def _seed(engine):
    async with AsyncSession(engine) as session:
        super_role = Role(name="SuperAdmin")
        viewer_role = Role(name="Viewer")  # view only
        exporter_role = Role(name="Exporter")  # export only, no view
        importer_role = Role(name="Importer")  # import only, no create

        perm_view = Permission(name="View products", table_name="products", can_view=True)
        perm_export = Permission(name="Export products", table_name="products", can_export=True)
        perm_import = Permission(name="Import products", table_name="products", can_import=True)

        viewer_role.permissions.append(perm_view)
        exporter_role.permissions.append(perm_export)
        importer_role.permissions.append(perm_import)

        def _user(email, role, superuser=False):
            u = User(
                email=email,
                password=SECRET_HASH,
                full_name=email,
                is_superuser=superuser,
                is_active=True,
            )
            u.roles.append(role)
            return u

        users = [
            _user("super@test.com", super_role, superuser=True),
            _user("viewer@test.com", viewer_role),
            _user("exporter@test.com", exporter_role),
            _user("importer@test.com", importer_role),
        ]
        session.add_all(
            [
                super_role,
                viewer_role,
                exporter_role,
                importer_role,
                perm_view,
                perm_export,
                perm_import,
                *users,
            ]
        )
        await session.commit()
        for u in users:
            await session.refresh(u)
        return {u.email: u.id for u in users}


@pytest.fixture
def env(engine):
    ids = run_async(_seed(engine))

    app = FastAPI()
    admin = Admin(
        app=app,
        engine=engine,
        secret_key=SECRET_KEY,
        auth_backend=BuiltinAuthBackend(),
        auto_discover=False,
        session_secure=False,
    )
    admin.register(Product)
    asyncio.run(admin.setup(app))
    return TestClient(app), engine, ids


def _cookie(user_id: int) -> dict[str, str]:
    return {"admin_session": create_session_cookie(user_id)}


def _csrf_headers(token: str | None = None) -> dict[str, str]:
    token = token or generate_csrf_token(SECRET_KEY)
    return {"X-CSRF-Token": token}


# ===========================================================================
# S12 — backup codes hashed with bcrypt
# ===========================================================================


class TestBackupCodeHashing:
    def test_hash_is_bcrypt(self):
        from fastapi_admin_kit.auth.totp import hash_backup_code

        hashed = hash_backup_code("ABCD1234")
        assert hashed.startswith("$2")
        assert len(hashed) == 60

    def test_verify_bcrypt_and_single_use(self):
        from fastapi_admin_kit.auth.totp import (
            generate_backup_codes,
            hash_backup_code,
            verify_backup_code,
        )

        codes = generate_backup_codes(3)
        hashed = [hash_backup_code(c) for c in codes]
        assert verify_backup_code(codes[0], hashed)
        assert len(hashed) == 2
        assert not verify_backup_code(codes[0], hashed)  # consumed

    def test_verify_legacy_sha256_still_works(self):
        from fastapi_admin_kit.auth.totp import verify_backup_code

        code = "LEGACYCODE"
        legacy = [hashlib.sha256(code.encode()).hexdigest()]
        assert verify_backup_code(code, legacy)
        assert legacy == []

    def test_verify_skips_corrupt_hashes(self):
        from fastapi_admin_kit.auth.totp import hash_backup_code, verify_backup_code

        hashed = ["not-a-hash", "$2b$12$corruptcorruptcorruptcorruptcorruptcorruptcorruptcorrupt"]
        hashed.append(hash_backup_code("GOODCODE1"))
        assert verify_backup_code("GOODCODE1", hashed)


# ===========================================================================
# S13 — needs_rehash cost parsing
# ===========================================================================


class TestNeedsRehash:
    def test_current_cost_not_flagged(self):
        from fastapi_admin_kit.auth.password import password_manager

        hashed = password_manager.hash("MyStr0ng!Pass")
        assert not password_manager.needs_rehash(hashed)

    def test_lower_cost_flagged(self):
        from fastapi_admin_kit.auth.password import password_manager

        # $2b$<cost>$<53 chars> — cost lives in parts[2] (S13)
        low_cost = "$2b$10$" + "a" * 53
        assert password_manager.needs_rehash(low_cost)

    def test_higher_cost_not_flagged(self):
        from fastapi_admin_kit.auth.password import password_manager

        high_cost = "$2b$14$" + "a" * 53
        assert not password_manager.needs_rehash(high_cost)

    def test_garbage_flagged(self):
        from fastapi_admin_kit.auth.password import password_manager

        assert password_manager.needs_rehash("")
        assert password_manager.needs_rehash("not-a-bcrypt-hash")

    def test_old_bug_would_have_misread(self):
        """parts[3] is the hash body — never a valid cost."""
        from fastapi_admin_kit.auth.password import password_manager

        body = "a" * 53
        assert not body.isdigit()
        low_cost = f"$2b$10${body}"
        # With the old parts[3] read this returned False (never rehash).
        assert password_manager.needs_rehash(low_cost)


# ===========================================================================
# S14 — CSV/Excel formula injection
# ===========================================================================


class TestFormulaInjection:
    def test_dangerous_prefixes_neutralised(self):
        from fastapi_admin_kit.export_import.base import sanitize_export_cell

        for payload in ["=cmd|' /C calc'!A0", "+1", "-1", "@SUM(1)", "|cmd", "%x"]:
            assert sanitize_export_cell(payload).startswith("'")

    def test_safe_values_untouched(self):
        from fastapi_admin_kit.export_import.base import sanitize_export_cell

        assert sanitize_export_cell("hello") == "hello"
        assert sanitize_export_cell(42) == 42
        assert sanitize_export_cell(None) is None
        assert sanitize_export_cell("") == ""
        assert sanitize_export_cell("a=b") == "a=b"

    def test_csv_export_sanitises_cells(self):
        from fastapi_admin_kit.export_import.csv import CSVExport

        class _Col:
            primary_key = False

            def __init__(self, name):
                self.name = name

        registered = SimpleNamespace(
            columns=[_Col("name")],
            admin=SimpleNamespace(get_queryset=lambda *a, **k: None),
            verbose_name_plural="products",
        )
        exporter = CSVExport(registered)
        exporter.include_serial = False
        rows = [SimpleNamespace(name='=HYPERLINK("http://evil","click")')]
        out = exporter.export(rows)
        content = out.getvalue().decode()
        assert "'=HYPERLINK" in content
        assert "\n=HYPERLINK" not in content

    @pytest.mark.skipif(
        importlib.util.find_spec("openpyxl") is None, reason="openpyxl not installed"
    )
    def test_excel_export_sanitises_cells(self):
        openpyxl = pytest.importorskip("openpyxl")

        from fastapi_admin_kit.export_import.excel import ExcelExport

        class _Col:
            primary_key = False

            def __init__(self, name):
                self.name = name

        registered = SimpleNamespace(
            columns=[_Col("name")],
            admin=SimpleNamespace(get_queryset=lambda *a, **k: None),
            verbose_name_plural="products",
        )
        exporter = ExcelExport(registered)
        exporter.include_serial = False
        rows = [SimpleNamespace(name="=cmd|' /C calc'!A0")]
        out = exporter.export(rows)
        wb = openpyxl.load_workbook(io.BytesIO(out.getvalue()))
        ws = wb.active
        # Row 1 is the header; data starts at row 2.
        assert ws.cell(row=2, column=1).value == "'=cmd|' /C calc'!A0"


# ===========================================================================
# S16 — gating fixes
# ===========================================================================


class TestSearchStatusCodes:
    def test_unauthenticated_gets_401(self, env):
        client, _engine, _ids = env
        resp = client.get("/admin/products/search", params={"q": "a"})
        assert resp.status_code == 401

    def test_user_without_view_permission_gets_403(self, env):
        client, _engine, ids = env
        # exporter@test.com has export-only — no view permission.
        resp = client.get(
            "/admin/products/search",
            params={"q": "a"},
            cookies=_cookie(ids["exporter@test.com"]),
        )
        assert resp.status_code == 403

    def test_view_only_user_gets_200(self, env):
        client, _engine, ids = env
        resp = client.get(
            "/admin/products/search",
            params={"q": ""},
            cookies=_cookie(ids["viewer@test.com"]),
        )
        assert resp.status_code == 200


class TestExportImportGating:
    def test_unauthenticated_export_401(self, env):
        client, _engine, _ids = env
        assert client.get("/admin/products/export/?format=csv").status_code == 401

    def test_view_only_user_cannot_export(self, env):
        client, _engine, ids = env
        resp = client.get(
            "/admin/products/export/?format=csv", cookies=_cookie(ids["viewer@test.com"])
        )
        assert resp.status_code == 403

    def test_export_only_user_can_export(self, env):
        """S16: outer gate now equals the inner gate — an ``export``-granted
        user is no longer blocked by the stale ``view`` outer dependency."""
        client, _engine, ids = env
        resp = client.get(
            "/admin/products/export/?format=csv", cookies=_cookie(ids["exporter@test.com"])
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]

    def test_import_only_user_can_import(self, env):
        """S16: outer gate now equals the inner gate — multipart form field
        CSRF also exercised here (S18f): no X-CSRF-Token header, token comes
        from the multipart body."""
        client, engine, ids = env
        token = generate_csrf_token(SECRET_KEY)
        client.cookies.set("admin_csrf_token", token)
        csv_content = b"name,price\nImported Widget,42\n"
        resp = client.post(
            "/admin/products/import/",
            files={"file": ("products.csv", csv_content, "text/csv")},
            data={"csrf_token": token, "format": "csv"},
            cookies=_cookie(ids["importer@test.com"]),
        )
        assert resp.status_code == 200, resp.text

        async def _count():
            async with AsyncSession(engine) as session:
                result = await session.execute(
                    select(Product).where(Product.name == "Imported Widget")
                )
                return len(result.scalars().all())

        assert run_async(_count()) == 1

    def test_create_only_user_cannot_import(self, env):
        client, _engine, _ids = env

        async def _make_creator():
            async with AsyncSession(_engine) as session:
                role = Role(name="CreatorOnly")
                perm = Permission(name="Create products", table_name="products", can_create=True)
                role.permissions.append(perm)
                user = User(
                    email="creator@test.com",
                    password=SECRET_HASH,
                    full_name="c",
                    is_superuser=False,
                    is_active=True,
                )
                user.roles.append(role)
                session.add_all([role, perm, user])
                await session.commit()
                await session.refresh(user)
                return user.id

        creator_id = run_async(_make_creator())
        token = generate_csrf_token(SECRET_KEY)
        client.cookies.set("admin_csrf_token", token)
        resp = client.post(
            "/admin/products/import/",
            files={"file": ("p.csv", b"name,price\nX,1\n", "text/csv")},
            data={"csrf_token": token, "format": "csv"},
            cookies=_cookie(creator_id),
        )
        assert resp.status_code == 403


class TestValidateFieldPermission:
    def test_view_only_user_gets_403(self, env):
        client, _engine, ids = env
        token = generate_csrf_token(SECRET_KEY)
        client.cookies.set("admin_csrf_token", token)
        resp = client.post(
            "/admin/products/validate-field",
            data={"field_name": "name", "name": "x", "csrf_token": token},
            cookies=_cookie(ids["viewer@test.com"]),
        )
        assert resp.status_code == 403

    def test_superuser_gets_200(self, env):
        client, _engine, ids = env
        token = generate_csrf_token(SECRET_KEY)
        client.cookies.set("admin_csrf_token", token)
        resp = client.post(
            "/admin/products/validate-field",
            data={"field_name": "name", "name": "x", "csrf_token": token},
            cookies=_cookie(ids["super@test.com"]),
        )
        assert resp.status_code == 200


# ===========================================================================
# S18 — ordering allow-list
# ===========================================================================


class TestOrderingAllowList:
    def test_sanitize_keeps_real_columns(self):
        from fastapi_admin_kit.modeladmin import sanitize_ordering

        assert sanitize_ordering(Product, ["name", "-price"]) == ["name", "-price"]

    def test_sanitize_drops_non_attributes(self):
        from fastapi_admin_kit.modeladmin import sanitize_ordering

        for bad in ["metadata", "__table__", "registry", "does_not_exist"]:
            assert sanitize_ordering(Product, [bad]) == []
        assert sanitize_ordering(Product, ["-metadata"]) == []

    def test_sanitize_keeps_relationships(self):
        from fastapi_admin_kit.modeladmin import sanitize_ordering

        assert sanitize_ordering(Product, ["category"]) == ["category"]

    def test_get_ordering_filters_query_param(self):
        from fastapi_admin_kit.modeladmin import ModelAdmin

        assert ModelAdmin.get_ordering({"ordering": "metadata"}, None, Product) == []
        assert ModelAdmin.get_ordering({"ordering": "name"}, None, Product) == ["name"]
        # Without a model, behaviour unchanged (backward compatible).
        assert ModelAdmin.get_ordering({"ordering": "anything"}, None) == ["anything"]
        # Admin-configured ordering still honoured when query param absent.
        assert ModelAdmin.get_ordering({}, ["-id"], Product) == ["-id"]

    def test_list_endpoint_survives_malicious_ordering(self, env):
        client, _engine, ids = env
        resp = client.get(
            "/admin/products/",
            params={"ordering": "__table__"},
            cookies=_cookie(ids["super@test.com"]),
        )
        assert resp.status_code == 200


# ===========================================================================
# S18 — import field allow-list
# ===========================================================================


def _fake_registered(model, column_names):
    from fastapi_admin_kit.inspection.types import ColumnMeta

    cols = [ColumnMeta(name=n, type=None) for n in column_names]
    return SimpleNamespace(
        columns=cols,
        model=model,
        admin=SimpleNamespace(on_create=lambda *a, **k: None, on_update=lambda *a, **k: None),
    )


class TestImportFieldAllowList:
    def test_user_model_privileged_fields_blocked(self):
        from fastapi_admin_kit.export_import.csv import CSVImport

        registered = _fake_registered(
            User, ["email", "full_name", "password", "is_superuser", "is_active"]
        )
        allowed = CSVImport(registered).allowed_import_fields()
        assert "email" in allowed and "full_name" in allowed
        assert "password" not in allowed
        assert "is_superuser" not in allowed
        assert "is_active" not in allowed

    def test_plain_model_keeps_regular_flags(self):
        from fastapi_admin_kit.export_import.csv import CSVImport

        registered = _fake_registered(Product, ["name", "price", "is_active"])
        allowed = CSVImport(registered).allowed_import_fields()
        assert {"name", "price", "is_active"} <= allowed

    def test_default_field_map_excludes_sensitive(self):
        from fastapi_admin_kit.export_import.csv import CSVImport

        registered = _fake_registered(User, ["email", "password"])
        field_map = CSVImport(registered).get_field_map()
        assert "Email" in field_map
        assert all(target != "password" for target in field_map.values())

    def test_import_rows_cannot_set_blocked_fields(self):
        """Blocked headers are dropped before validation/transform/write."""
        from fastapi_admin_kit.export_import.csv import CSVImport

        registered = _fake_registered(User, ["email", "password", "is_superuser", "is_active"])
        importer = CSVImport(registered)

        class _FakeSession:
            def __init__(self):
                self.added = []
                self.autoflush = True

            def add(self, obj):
                self.added.append(obj)

            async def flush(self):
                return None

            async def rollback(self):
                return None

        fake_session = _FakeSession()
        request = SimpleNamespace(
            scope=SimpleNamespace(
                app=SimpleNamespace(state=SimpleNamespace(admin_session_backend_class=None))
            ),
            state=SimpleNamespace(admin_db_session=fake_session),
        )
        rows = [
            {
                "Email": "evil@test.com",
                "Hashed Password": "$2b$12$attackercontrolled",
                "Is Superuser": "true",
                "Is Active": "true",
            }
        ]
        result = run_async(importer.import_data(rows, request=request))
        assert result["created"] == 1, result["error_messages"]
        assert len(fake_session.added) == 1
        obj = fake_session.added[0]
        assert obj.email == "evil@test.com"
        # Blocked fields never reached the model.
        assert not getattr(obj, "password", None)
        assert not getattr(obj, "is_superuser", False)
        assert not getattr(obj, "is_active", False)


# ===========================================================================
# S18 — session hardening (iat required, rotation on login)
# ===========================================================================


class TestSessionHardening:
    def test_decode_rejects_token_without_iat(self):
        from itsdangerous import URLSafeTimedSerializer

        from fastapi_admin_kit.auth.session import SignedCookieSessionBackend

        backend = SignedCookieSessionBackend(secret_key=SECRET_KEY)
        raw = URLSafeTimedSerializer(SECRET_KEY, salt="admin-session").dumps({"user_id": 1})
        assert backend.decode(raw) is None  # no iat → rejected
        assert backend.decode(backend.encode({"user_id": 1})) is not None

    def test_dependency_rejects_missing_iat(self):
        from fastapi import HTTPException

        from fastapi_admin_kit.auth.dependencies import get_current_admin_user

        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(admin_session_backend=None)),
            cookies={},
        )

        async def _run():
            await get_current_admin_user(request, session_payload={"user_id": 1})

        try:
            run_async(_run())
            raised = False
        except HTTPException as exc:
            raised = exc.status_code == 401
        assert raised

    def test_login_rotates_session_value(self, env):
        """Two logins must produce different cookie values even within the
        same second (random sid in the payload)."""
        client, _engine, ids = env
        csrf = generate_csrf_token(SECRET_KEY)
        client.cookies.set("admin_csrf_token", csrf)

        def _login():
            return client.post(
                "/admin/login",
                data={
                    "username": "super@test.com",
                    "password": "secret",
                    "csrf_token": csrf,
                },
                follow_redirects=False,
            )

        r1, r2 = _login(), _login()
        assert r1.status_code == 302 and r2.status_code == 302
        c1 = r1.cookies.get("admin_session")
        c2 = r2.cookies.get("admin_session")
        assert c1 and c2 and c1 != c2
