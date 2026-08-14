"""End-to-end test of the dependency-free InMemoryBackend.

This proves the ``fastapi_admin_kit`` data-access seam is truly pluggable: the
whole protocol contract (connection → session factory → session read/write,
query building, introspection, audit, role seeding) is exercised without
importing SQLAlchemy anywhere in the backend under test.
"""

from __future__ import annotations

from typing import Any

from fastapi_admin_kit.auth.types import SeedRole
from fastapi_admin_kit.backends import InMemoryBackend
from fastapi_admin_kit.backends.memory import MemorySessionBackend
from fastapi_admin_kit.schemas.schema import Field, Schema


def _product_schema() -> Schema:
    return Schema(
        table_name="products",
        verbose_name="product",
        verbose_name_plural="products",
        fields=[
            Field(name="id", type="integer", primary_key=True, auto_increment=True),
            Field(name="name", type="string", nullable=False),
            Field(name="price", type="float", nullable=False, default=0.0),
        ],
    )


def test_backend_exposes_all_five_protocols():
    backend = InMemoryBackend()
    assert backend.database is not None
    assert backend.query is not None
    assert backend.introspection is not None
    assert backend.audit is not None
    assert backend.database.session_adapter_class is MemorySessionBackend


def test_connection_session_factory_and_materialize():
    backend = InMemoryBackend()
    connection = backend.database.create_connection()
    assert isinstance(connection, dict)

    factory = backend.database.create_session_factory(connection)
    session = factory()
    assert isinstance(session, MemorySessionBackend)

    product = backend.database.materialize(_product_schema())
    assert getattr(product, "__tablename__") == "products"
    # Column descriptors let us build conditions at the class level.
    assert (product.name == "x").name == "name"


def test_session_crud_and_query_methods():
    backend = InMemoryBackend()
    connection = backend.database.create_connection()
    session = backend.database.create_session_factory(connection)()
    product = backend.database.materialize(_product_schema())

    p1 = product()
    p1.name = "alpha"
    p1.price = 10.0
    p2 = product()
    p2.name = "beta"
    p2.price = 20.0
    p3 = product()
    p3.name = "gamma"
    p3.price = 30.0
    session.add(p1)
    session.add(p2)
    session.add(p3)
    session.commit()

    q = backend.query.select(product)
    assert len(session.all(q)) == 3

    assert session.get(product, 1).name == "alpha"
    assert session.get(product, 999) is None

    # WHERE + scalar_one_or_none
    found = session.scalar_one_or_none(
        backend.query.where(backend.query.select(product), product.name == "beta")
    )
    assert found is not None and found.price == 20.0

    # count query via the query adapter + session.count
    count_q = backend.query.count(backend.query.select(product))
    assert session.count(count_q) == 3

    # scalar returns the integer count as well
    assert session.scalar(count_q) == 3

    # first with ordering + limit/offset
    desc_q = backend.query.order_by(backend.query.select(product), product.price.desc())
    assert session.first(desc_q).name == "gamma"
    page_q = backend.query.limit(backend.query.offset(desc_q, 1), 1)
    assert session.first(page_q).name == "beta"

    # in_ / ilike / or_ combinators
    in_q = backend.query.where(backend.query.select(product), product.name.in_(["alpha", "gamma"]))
    assert {r.name for r in session.all(in_q)} == {"alpha", "gamma"}

    ilike_q = backend.query.where(
        backend.query.select(product), backend.query.ilike(product.name, "%am%")
    )
    assert {r.name for r in session.all(ilike_q)} == {"gamma"}

    or_q = backend.query.where(
        backend.query.select(product),
        backend.query.or_(product.price == 10.0, product.price == 30.0),
    )
    assert {r.name for r in session.all(or_q)} == {"alpha", "gamma"}

    # delete
    session.delete(found)
    session.commit()
    assert session.get(product, 2) is None
    assert session.count(backend.query.count(backend.query.select(product))) == 2


def test_introspection_reflects_schema():
    backend = InMemoryBackend()
    product = backend.database.materialize(_product_schema())
    columns, relations = backend.introspection.inspect_model(product)
    col_names = {c.name for c in columns}
    assert col_names == {"id", "name", "price"}
    assert next(c.primary_key for c in columns if c.name == "id") is True
    assert backend.introspection.get_pk_field(product) == "id"
    assert backend.introspection.get_column_type_name(product, "price") == "float"
    assert backend.introspection.is_abstract(product) is False
    assert backend.introspection.get_relationship_names(product) == set()
    assert backend.introspection.cast_pk_value(product, "1") == 1


def test_audit_snapshot_and_diff():
    backend = InMemoryBackend()
    before = {"name": "a", "price": 1.0}
    after = {"name": "b", "price": 1.0}
    diff = backend.audit.compute_diff(
        backend.audit.snapshot(_obj_with(**before)),
        backend.audit.snapshot(_obj_with(**after)),
    )
    assert diff == {"name": ("a", "b")}


def test_seed_roles_persists_role_permission_junction():
    backend = InMemoryBackend()
    connection = backend.database.create_connection()
    factory = backend.database.create_session_factory(connection)

    seed = [
        SeedRole(
            name="Admin",
            description="Full access",
            permissions={"products": {"view": True, "create": True, "edit": True, "delete": True}},
        ),
        SeedRole(name="Viewer", permissions={"products": {"view": True}}),
    ]
    backend.database.seed_roles(factory, seed)
    # Idempotent unless overwrite.
    backend.database.seed_roles(factory, seed)
    assert len(connection["admin_roles"]) == 2

    roles = {r["name"] for r in connection["admin_roles"]}
    assert roles == {"Admin", "Viewer"}
    perms = {p["table_name"] for p in connection["admin_permissions"]}
    assert perms == {"products"}
    assert len(connection["admin_role_permissions"]) == 2  # one junction per role

    # overwrite clears and reseeds
    backend.database.seed_roles(factory, seed, overwrite=True)
    assert len(connection["admin_roles"]) == 2


def _obj_with(**kwargs: Any) -> object:
    class _Tmp:
        pass

    obj = _Tmp()
    obj.__dict__.update(kwargs)
    return obj
