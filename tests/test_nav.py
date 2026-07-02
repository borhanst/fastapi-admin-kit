"""Tests for the nav/sidebar tag & group system."""

from __future__ import annotations

import pytest

from fastapi_admin_kit.nav import (
    BuiltNavGroup,
    BuiltNavItem,
    DefaultSidebarBuilder,
    NavGroupConfig,
    NavItemConfig,
    SidebarBuilder,
)
from fastapi_admin_kit.registry import AdminRegistry, RegisteredModel, RegisteredModel
from fastapi_admin_kit.views import ModelAdmin
from fastapi_admin_kit.exceptions import ConfigError


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_registered(name, tag, *, nav_order=999, tags=None, icon=None, nav_children=None):
    class M:
        __tablename__ = name.lower()
        id = None

    attrs: dict = {}
    if nav_order != 999:
        attrs["nav_order"] = nav_order
    if icon:
        attrs["icon"] = icon
    if nav_children is not None:
        attrs["nav_children"] = nav_children
    if tags:
        attrs["tags"] = tags
    elif tag is not None:
        attrs["tag"] = tag

    admin_cls = type("AdminCfg_" + name, (ModelAdmin,), attrs)
    return RegisteredModel(
        model=M,
        admin=admin_cls(),
        table_name=name.lower(),
        verbose_name=name,
        verbose_name_plural=name + "s",
        columns=[],
        relationships=[],
    )


# ── tag extraction ────────────────────────────────────────────────────────────

class TestGetTags:

    def test_single_tag(self):
        r = _make_registered("Product", "Catalogue")
        assert DefaultSidebarBuilder()._get_tags(r) == ["Catalogue"]

    def test_tags_list_wins(self):
        r = _make_registered("X", None, tags=["A", "B"])
        assert DefaultSidebarBuilder()._get_tags(r) == ["A", "B"]

    def test_tag_attribute(self):
        r = _make_registered("Product", "Orders")
        assert DefaultSidebarBuilder()._get_tags(r) == ["Orders"]

    def test_no_tag_falls_back_other(self):
        r = _make_registered("Thing", None)
        assert DefaultSidebarBuilder()._get_tags(r) == ["Other"]


# ── ordering ──────────────────────────────────────────────────────────────────

class TestOrdering:

    def test_groups_sorted_by_order(self):
        configs = [
            NavGroupConfig(tag="Catalogue", order=2),
            NavGroupConfig(tag="Orders", order=1),
            NavGroupConfig(tag="Other", order=3),
        ]
        registry = [
            _make_registered("Product", "Catalogue"),
            _make_registered("Order", "Orders"),
            _make_registered("Thing", None),
        ]
        groups = DefaultSidebarBuilder().build(registry, configs, admin_path="/admin")
        assert [g.tag for g in groups] == ["Orders", "Catalogue", "Other"]

    def test_items_sorted_by_nav_order(self):
        class OrderA(ModelAdmin):
            tag = "Orders"
            nav_order = 1

        class OrderB(ModelAdmin):
            tag = "Orders"
            nav_order = 2

        class OrderC(ModelAdmin):
            tag = "Orders"

        m_a = type("M_A", (), {"__tablename__": "a"})
        m_b = type("M_B", (), {"__tablename__": "b"})
        m_c = type("M_C", (), {"__tablename__": "c"})
        registry = [
            RegisteredModel(m_c, OrderC(), "c", "C", "Cs", [], []),
            RegisteredModel(m_a, OrderA(), "a", "A", "As", [], []),
            RegisteredModel(m_b, OrderB(), "b", "B", "Bs", [], []),
        ]
        groups = DefaultSidebarBuilder().build(registry, [NavGroupConfig(tag="Orders", order=1)], admin_path="/admin")
        assert [i.label for i in groups[0].items] == ["As", "Bs", "Cs"]


# ── require_tags flag ─────────────────────────────────────────────────────────

class TestRequireTags:
    def test_untagged_raises(self):
        import fastapi_admin_kit as fpa

        class M:
            __tablename__ = "m"

        admin = fpa.Admin(engine=None)
        admin.registry._models["m"] = RegisteredModel(
            model=M,
            admin=ModelAdmin(),
            table_name="m",
            verbose_name="M",
            verbose_name_plural="Ms",
        )
        with pytest.raises(ConfigError, match="m"):
            admin._validate_tags()
